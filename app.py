import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from flask import Flask, render_template, request, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
import uuid

class Base(DeclarativeBase):
    pass

# expire_on_commit=False: by default SQLAlchemy marks every loaded object
# stale after each commit, so the next attribute access silently re-SELECTs it.
# With a remote database (Neon) that is a full network round-trip per request;
# objects here never outlive one request, so the staleness guard buys nothing.
db = SQLAlchemy(model_class=Base, session_options={"expire_on_commit": False})

# create the app
app = Flask(__name__)
# setup a secret key, required by sessions
app.secret_key = os.environ.get("SESSION_SECRET") or os.environ.get("FLASK_SECRET_KEY") or "dev-secret-key-change-in-production"
# configure the database. Defaults to a local SQLite file so the app runs
# with zero external dependencies; set DATABASE_URL to point at Postgres
# (e.g. Neon) in production.
basedir = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(basedir, 'matcher.db')}"
# Normalize Postgres URL schemes to the psycopg3 dialect: providers hand out
# "postgres://" (legacy Heroku-style) or "postgresql://", both of which
# SQLAlchemy would otherwise route to the unmaintained psycopg2 driver.
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
# initialize the app with the extension, flask-sqlalchemy >= 3.0.x
db.init_app(app)

# Import models after db is created to avoid circular import
import models
import recommender

with app.app_context():
    db.create_all()

# TMDB API configuration
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
if not TMDB_API_KEY:
    print("WARNING: TMDB_API_KEY is not set. Movie/TV search and recommendations will fail.")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Google Books API configuration
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_API_KEY")
GOOGLE_BOOKS_BASE_URL = "https://www.googleapis.com/books/v1"

# Google Sign-In (OAuth Client ID). Sign-in endpoints are disabled if unset;
# the app still works fully for anonymous guests.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")

# Shared connection-pooled session for all outbound API calls (reuses TCP/TLS
# connections instead of opening a new one per request).
http = requests.Session()

# Simple in-process TTL cache for outbound API responses. Search/suggestion
# queries and genre-based discover results repeat a lot across users, so
# caching them cuts outbound API calls significantly. Not shared across
# processes/workers, which is fine at this app's scale.
_cache = {}
_CACHE_MAX_ENTRIES = 500

def cache_get(key):
    entry = _cache.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        del _cache[key]
        return None
    return value

def cache_set(key, value, ttl_seconds):
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[key] = (value, time.time() + ttl_seconds)

def fetch_json_cached(url, params, cache_key, ttl_seconds=900, timeout=5):
    """GET url (or return a cached response) as JSON, or None on failure.

    Used for batches of calls fetched concurrently via ThreadPoolExecutor, so
    the timeout is kept short - one slow/stuck call shouldn't drag the whole
    batch's wall-clock time up to a long timeout when the others finish fast.
    """
    data = cache_get(cache_key)
    if data is not None:
        return data
    try:
        response = http.get(url, params=params, timeout=timeout)
        if response.ok:
            data = response.json()
            cache_set(cache_key, data, ttl_seconds)
            return data
    except requests.RequestException:
        pass
    return None

def get_or_create_user():
    """Get or create a user based on session"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())

    # Try to find existing user by session ID
    user = models.User.query.filter_by(session_id=session['user_id']).first()

    if not user:
        # Create new user
        user = models.User(session_id=session['user_id'])
        db.session.add(user)
        db.session.commit()

    return user

def merge_users(source, target):
    """Move a guest user's data into a signed-in account, then delete the guest.

    Used when someone who built up a watchlist/history anonymously signs in
    to an account that already exists: nothing they did as a guest is lost.
    Watchlist rows that would collide with an item already on the account
    (same content_type + id) are dropped rather than duplicated.
    """
    existing_keys = {(item.content_type, item.tmdb_id) for item in target.watchlist}

    # Drop guest rows that duplicate something already on the account.
    for item in list(source.watchlist):
        if (item.content_type, item.tmdb_id) in existing_keys:
            db.session.delete(item)
    db.session.flush()

    # Re-parent the rest with bulk UPDATEs rather than by assigning to the ORM
    # relationship: the guest's children cascade delete-orphan, so they must be
    # detached at the SQL level and the stale in-memory collections expired
    # before deleting the guest row - otherwise the cascade takes the
    # re-parented rows down with it.
    models.Watchlist.query.filter_by(user_id=source.id).update({'user_id': target.id})
    models.Recommendation.query.filter_by(user_id=source.id).update({'user_id': target.id})
    db.session.flush()
    db.session.expire(source)

    db.session.delete(source)
    db.session.commit()

def build_taste_profile(user, content_type, local_feedback=None, history=None):
    """Combine a user's like/dislike history into signals the scorers can use.

    Signed-in users' feedback lives in the database; guests' feedback lives in
    their browser's localStorage and arrives with the request (we never store
    it server-side). Both are merged here so scoring works the same either way.

    `history` is the user's prefetched Recommendation rows for this content
    type; the recommendation routes already load them for exclusions, and
    passing them in avoids a second round-trip to the remote database.

    Returns liked/disliked genre weights plus the ids of liked titles, which
    callers use to pull "more like this" candidates.
    """
    entries = []

    if user.google_id:
        if history is not None:
            rows = sorted((r for r in history if r.was_liked is not None),
                          key=lambda r: r.recommended_at, reverse=True)[:30]
        else:
            rows = (models.Recommendation.query
                    .filter(models.Recommendation.user_id == user.id,
                            models.Recommendation.content_type == content_type,
                            models.Recommendation.was_liked.isnot(None))
                    .order_by(models.Recommendation.recommended_at.desc())
                    .limit(30).all())
        for row in rows:
            entries.append({
                'id': row.tmdb_id,
                'liked': row.was_liked,
                'genre_ids': row.genres if isinstance(row.genres, list) else []
            })

    for entry in (local_feedback or [])[-30:]:
        if not isinstance(entry, dict) or entry.get('liked') is None:
            continue
        entries.append({
            'id': str(entry.get('id', '')),
            'liked': bool(entry.get('liked')),
            'genre_ids': entry.get('genre_ids') or []
        })

    liked_genres = {}
    disliked_genres = {}
    liked_ids = []
    for entry in entries:
        bucket = liked_genres if entry['liked'] else disliked_genres
        for genre_id in entry['genre_ids']:
            # Book "genres" are category strings; movie/TV are numeric ids.
            bucket[genre_id] = bucket.get(genre_id, 0) + 1
        if entry['liked'] and entry['id']:
            liked_ids.append(entry['id'])

    return {
        'liked_genres': liked_genres,
        'disliked_genres': disliked_genres,
        'liked_ids': liked_ids
    }

@app.route('/api/recommendation_feedback', methods=['POST'])
def recommendation_feedback():
    """Record a like/dislike. Only persisted for signed-in users; guests keep
    their feedback in localStorage and send it with each request instead."""
    try:
        data = request.get_json() or {}
        item_id = data.get('id')
        liked = data.get('liked')
        content_type = data.get('content_type', 'movie')

        if item_id is None or liked is None:
            return jsonify({'error': 'id and liked are required'}), 400

        user = get_or_create_user()
        if not user.google_id:
            # Guest: acknowledged, but intentionally not stored server-side.
            return jsonify({'success': True, 'stored': False})

        rec = (models.Recommendation.query
               .filter_by(user_id=user.id, content_type=content_type, tmdb_id=str(item_id))
               .order_by(models.Recommendation.recommended_at.desc())
               .first())
        if not rec:
            return jsonify({'error': 'Recommendation not found'}), 404

        rec.was_liked = bool(liked)
        db.session.commit()
        return jsonify({'success': True, 'stored': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to record feedback: {str(e)}'}), 500

@app.route('/api/sync_feedback', methods=['POST'])
def sync_feedback():
    """Merge a guest's localStorage feedback into their account after sign-in."""
    try:
        user = get_or_create_user()
        if not user.google_id:
            return jsonify({'success': False, 'error': 'Not signed in'}), 401

        data = request.get_json() or {}
        entries = data.get('feedback') or []
        applied = 0
        for entry in entries:
            if not isinstance(entry, dict) or entry.get('liked') is None:
                continue
            rec = (models.Recommendation.query
                   .filter_by(user_id=user.id,
                              content_type=entry.get('content_type', 'movie'),
                              tmdb_id=str(entry.get('id', '')))
                   .order_by(models.Recommendation.recommended_at.desc())
                   .first())
            if rec and rec.was_liked is None:
                rec.was_liked = bool(entry['liked'])
                applied += 1
        db.session.commit()
        return jsonify({'success': True, 'applied': applied})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to sync feedback: {str(e)}'}), 500

@app.route('/api/me')
def api_me():
    """Current session's identity, plus the OAuth client id the frontend
    needs to render the Google Sign-In button."""
    try:
        user = get_or_create_user()
        return jsonify({
            'signed_in': bool(user.google_id),
            'name': user.display_name,
            'email': user.email,
            'avatar_url': user.avatar_url,
            'google_client_id': GOOGLE_CLIENT_ID
        })
    except Exception as e:
        return jsonify({'error': f'Failed to load profile: {str(e)}'}), 500

@app.route('/auth/google', methods=['POST'])
def auth_google():
    """Verify a Google ID token and sign the session in, merging any guest data."""
    if not GOOGLE_CLIENT_ID:
        return jsonify({'error': 'Google Sign-In is not configured'}), 503

    data = request.get_json()
    credential = data.get('credential') if data else None
    if not credential:
        return jsonify({'error': 'Missing credential'}), 400

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_auth_requests
        idinfo = google_id_token.verify_oauth2_token(
            credential, google_auth_requests.Request(), GOOGLE_CLIENT_ID)
    except ValueError:
        return jsonify({'error': 'Invalid credential'}), 401

    try:
        google_id = idinfo['sub']
        current = get_or_create_user()
        account = models.User.query.filter_by(google_id=google_id).first()

        if account is None:
            # First sign-in for this Google account: promote the current
            # session user (and everything they saved as a guest) in place.
            current.google_id = google_id
            account = current
        elif account.id != current.id:
            # Existing account: fold the guest session's data into it and
            # point this session at the account.
            merge_users(current, account)
            session['user_id'] = account.session_id

        account.email = idinfo.get('email')
        account.display_name = idinfo.get('name')
        account.avatar_url = idinfo.get('picture')
        db.session.commit()

        return jsonify({
            'success': True,
            'name': account.display_name,
            'email': account.email,
            'avatar_url': account.avatar_url
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Sign-in failed: {str(e)}'}), 500

@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    """Sign out: detach the session. The next request gets a fresh guest identity."""
    session.pop('user_id', None)
    return jsonify({'success': True})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/movies')
def movies():
    return render_template('movies.html')

@app.route('/tv')
def tv_series():
    return render_template('tv.html')

@app.route('/books')
def books():
    return render_template('books.html')

@app.route('/watchlist')
def watchlist_page():
    return render_template('watchlist.html')

@app.route('/api/watchlist')
def get_watchlist():
    """Get user's full watchlist across all content types"""
    try:
        user = get_or_create_user()
        watchlist_items = models.Watchlist.query.filter_by(user_id=user.id).order_by(models.Watchlist.added_at.desc()).all()

        watchlist = []
        for item in watchlist_items:
            watchlist.append({
                'tmdb_id': item.tmdb_id,
                'content_type': item.content_type,
                'title': item.title,
                'release_date': item.release_date,
                'poster_path': item.poster_path,
                'overview': item.overview,
                'vote_average': item.vote_average,
                'genres': item.genres,
                'authors': item.authors,
                'added_at': item.added_at.isoformat()
            })

        return jsonify({'watchlist': watchlist})
    except Exception as e:
        return jsonify({'error': f'Failed to get watchlist: {str(e)}'}), 500

@app.route('/api/remove-from-watchlist', methods=['POST'])
def remove_from_watchlist():
    """Remove an item from the watchlist"""
    try:
        data = request.get_json()
        item_id = data.get('id') or data.get('movie_id')
        content_type = data.get('content_type', 'movie')

        if not item_id:
            return jsonify({'error': 'Item ID is required'}), 400

        user = get_or_create_user()
        watchlist_item = models.Watchlist.query.filter_by(
            user_id=user.id, content_type=content_type, tmdb_id=str(item_id)).first()

        if not watchlist_item:
            return jsonify({'error': 'Item not found in watchlist'}), 404

        db.session.delete(watchlist_item)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Removed from watchlist'})
    except Exception as e:
        return jsonify({'error': f'Failed to remove from watchlist: {str(e)}'}), 500

@app.route('/api/download-watchlist-csv')
def download_watchlist_csv():
    """Download watchlist as CSV"""
    try:
        user = get_or_create_user()
        watchlist_items = models.Watchlist.query.filter_by(user_id=user.id).order_by(models.Watchlist.added_at.desc()).all()
        
        import io
        import csv
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Type', 'Title', 'Authors', 'Release Date', 'Rating', 'Added Date', 'Overview'])

        # Write data
        for item in watchlist_items:
            overview = item.overview or ''
            writer.writerow([
                item.content_type,
                item.title,
                ', '.join(item.authors) if item.authors else '',
                item.release_date,
                item.vote_average,
                item.added_at.strftime('%Y-%m-%d'),
                overview[:100] + '...' if len(overview) > 100 else overview
            ])
        
        output.seek(0)
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={"Content-disposition": "attachment; filename=my-watchlist.csv"}
        )
    except Exception as e:
        return jsonify({'error': f'Failed to download CSV: {str(e)}'}), 500

@app.route('/add_to_watchlist', methods=['POST'])
def add_to_watchlist():
    """Add a movie, TV show, or book to the user's watchlist"""
    try:
        data = request.get_json()
        item_id = data.get('id') or data.get('movie_id')
        title = data.get('title')
        content_type = data.get('content_type', 'movie')

        if content_type not in ('movie', 'tv', 'book'):
            return jsonify({'error': 'Invalid content type'}), 400
        if not item_id or not title:
            return jsonify({'error': 'Item ID and title are required'}), 400

        user = get_or_create_user()

        existing = models.Watchlist.query.filter_by(
            user_id=user.id, content_type=content_type, tmdb_id=str(item_id)).first()
        if existing:
            return jsonify({'error': 'Already in watchlist'}), 400

        watchlist_item = models.Watchlist(
            user_id=user.id,
            content_type=content_type,
            tmdb_id=str(item_id),
            title=title,
            release_date=data.get('release_date', ''),
            poster_path=data.get('poster_path', ''),
            overview=data.get('overview', ''),
            vote_average=data.get('vote_average', 0),
            genres=data.get('genres', []),
            authors=data.get('authors', [])
        )

        db.session.add(watchlist_item)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Added to watchlist'})

    except Exception as e:
        return jsonify({'error': f'Failed to add to watchlist: {str(e)}'}), 500

@app.route('/search_movie')
def search_movie():
    """Search for a movie using TMDB API"""
    query = request.args.get('query', '')
    if not query:
        return jsonify([])

    try:
        cache_key = ('search_movie', query)
        data = cache_get(cache_key)
        if data is None:
            url = f"{TMDB_BASE_URL}/search/movie"
            params = {
                'api_key': TMDB_API_KEY,
                'query': query
            }
            response = http.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            cache_set(cache_key, data, ttl_seconds=600)

        movies = []
        for movie in data.get('results', [])[:10]:
            if movie.get('poster_path'):
                movies.append({
                    'id': movie['id'],
                    'title': movie['title'],
                    'release_date': movie.get('release_date', ''),
                    'poster_path': f"https://image.tmdb.org/t/p/w500{movie['poster_path']}",
                    'overview': movie.get('overview', ''),
                    'vote_average': movie.get('vote_average', 0),
                    'genre_ids': movie.get('genre_ids', []),
                    'original_language': movie.get('original_language', '')
                })
        
        return jsonify(movies)
    except:
        return jsonify([])

@app.route('/search_tv')
def search_tv():
    """Search for a TV series using TMDB API"""
    query = request.args.get('query', '')
    if not query:
        return jsonify([])

    try:
        cache_key = ('search_tv', query)
        data = cache_get(cache_key)
        if data is None:
            url = f"{TMDB_BASE_URL}/search/tv"
            params = {
                'api_key': TMDB_API_KEY,
                'query': query
            }
            response = http.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            cache_set(cache_key, data, ttl_seconds=600)

        tv_series = []
        for tv in data.get('results', [])[:10]:
            if tv.get('poster_path'):
                tv_series.append({
                    'id': tv['id'],
                    'name': tv['name'],
                    'first_air_date': tv.get('first_air_date', ''),
                    'poster_path': f"https://image.tmdb.org/t/p/w500{tv['poster_path']}",
                    'overview': tv.get('overview', ''),
                    'vote_average': tv.get('vote_average', 0),
                    'genre_ids': tv.get('genre_ids', []),
                    'origin_country': tv.get('origin_country', []),
                    'original_language': tv.get('original_language', '')
                })
        
        return jsonify(tv_series)
    except:
        return jsonify([])

@app.route('/get_movie_suggestions')
def get_movie_suggestions():
    """Get movie suggestions for autocomplete using TMDB API"""
    query = request.args.get('query', '')
    if not query or len(query) < 2:
        return jsonify([])

    try:
        cache_key = ('search_movie', query)
        data = cache_get(cache_key)
        if data is None:
            url = f"{TMDB_BASE_URL}/search/movie"
            params = {
                'api_key': TMDB_API_KEY,
                'query': query
            }
            response = http.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            cache_set(cache_key, data, ttl_seconds=600)

        suggestions = []
        for movie in data.get('results', [])[:5]:
            suggestions.append({
                'id': movie['id'],
                'title': movie['title'],
                'release_date': movie.get('release_date', ''),
                'poster_path': f"https://image.tmdb.org/t/p/w92{movie['poster_path']}" if movie.get('poster_path') else '',
                'vote_average': movie.get('vote_average', 0),
                'genre_ids': movie.get('genre_ids', [])
            })
        
        return jsonify(suggestions)
    except:
        return jsonify([])

@app.route('/get_tv_suggestions')
def get_tv_suggestions():
    """Get TV suggestions for autocomplete using TMDB API"""
    query = request.args.get('query', '')
    if not query or len(query) < 2:
        return jsonify([])

    try:
        cache_key = ('search_tv', query)
        data = cache_get(cache_key)
        if data is None:
            url = f"{TMDB_BASE_URL}/search/tv"
            params = {
                'api_key': TMDB_API_KEY,
                'query': query
            }
            response = http.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            cache_set(cache_key, data, ttl_seconds=600)

        suggestions = []
        for tv in data.get('results', [])[:5]:
            suggestions.append({
                'id': tv['id'],
                'name': tv['name'],
                'first_air_date': tv.get('first_air_date', ''),
                'poster_path': f"https://image.tmdb.org/t/p/w92{tv['poster_path']}" if tv.get('poster_path') else '',
                'vote_average': tv.get('vote_average', 0),
                'genre_ids': tv.get('genre_ids', [])
            })
        
        return jsonify(suggestions)
    except:
        return jsonify([])

@app.route('/search_book', methods=['GET', 'POST'])
def search_book():
    """Search for a book using Google Books API"""
    if request.method == 'POST':
        data = request.get_json()
        query = data.get('title', '') if data else ''
    else:
        query = request.args.get('query', '')
    
    if not query:
        return jsonify([])

    try:
        books = fetch_google_books(query, set(), max_results=5)
        return jsonify(books)
    except Exception as e:
        print(f"Error searching for book: {e}")
        return jsonify([])

@app.route('/get_book_suggestions')
def get_book_suggestions():
    """Get book suggestions using Google Books API"""
    query = request.args.get('query', '')
    if not query or len(query) < 2:
        return jsonify([])
    
    try:
        books = fetch_google_books(query, set(), max_results=5)
        return jsonify(books)
    except:
        return jsonify([])

def fetch_google_books(query, excluded_ids, max_results=10, lang=None):
    """Fetch books from Google Books API, optionally restricted to a language"""
    try:
        cache_key = ('google_books', query, max_results, lang)
        data = cache_get(cache_key)
        if data is None:
            search_url = f"{GOOGLE_BOOKS_BASE_URL}/volumes"
            params = {
                'q': query,
                'maxResults': max_results,
                'key': GOOGLE_BOOKS_API_KEY
            }
            if lang:
                params['langRestrict'] = lang
            response = http.get(search_url, params=params, timeout=3)
            response.raise_for_status()
            data = response.json()
            cache_set(cache_key, data, ttl_seconds=600)

        books = []
        if 'items' in data:
            for item in data['items']:
                volume_info = item.get('volumeInfo', {})
                book_id = item.get('id', '')
                
                if book_id not in excluded_ids:
                    book = {
                        'id': book_id,
                        'title': volume_info.get('title', 'Unknown Title'),
                        'authors': volume_info.get('authors', ['Unknown Author']),
                        'published_date': volume_info.get('publishedDate', ''),
                        'overview': volume_info.get('description', '')[:500] if volume_info.get('description') else '',
                        'categories': volume_info.get('categories', []),
                        'poster_path': volume_info.get('imageLinks', {}).get('thumbnail', '').replace('http:', 'https:'),
                        'vote_average': float(volume_info.get('averageRating', 0) or 0),
                        'vote_count': int(volume_info.get('ratingsCount', 0) or 0),
                        'page_count': int(volume_info.get('pageCount', 0) or 0),
                        'language': volume_info.get('language', 'en'),
                        'publisher': volume_info.get('publisher', ''),
                        'subtitle': volume_info.get('subtitle', '')
                    }
                    books.append(book)
        
        return books
    except:
        return []

@app.route('/get_book_recommendation', methods=['POST'])
def get_book_recommendation():
    """Get a book recommendation"""
    try:
        data = request.get_json()
        user_books = data.get('books', [])
        if not user_books or len(user_books) < 3:
            return jsonify({'error': 'Please provide at least 3 books'}), 400

        user = get_or_create_user()
        previous_recommendations = models.Recommendation.query.filter_by(user_id=user.id, content_type='book').all()
        profile = build_taste_profile(user, 'book', data.get('feedback'), history=previous_recommendations)

        excluded_ids = {str(b.get('id')) for b in user_books if b.get('id')}
        excluded_ids.update(rec.tmdb_id for rec in previous_recommendations)

        recommendation = recommender.recommend_book(
            user_books, profile, excluded_ids, {'fetch_books': fetch_google_books})
        if not recommendation:
            return jsonify({'error': 'No suitable recommendations found'}), 404

        try:
            db.session.add(models.Recommendation(
                user_id=user.id, content_type='book', tmdb_id=str(recommendation.get('id', '')),
                title=recommendation.get('title', ''), release_date=recommendation.get('published_date', ''),
                poster_path=recommendation.get('poster_path', ''), overview=recommendation.get('overview', ''),
                vote_average=recommendation.get('vote_average', 0), genres=recommendation.get('categories', [])))
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({'recommendation': recommendation})
    except Exception as e:
        return jsonify({'error': f'Failed to get recommendation: {str(e)}'}), 500

@app.route('/get_movie_recommendation', methods=['POST'])
def get_movie_recommendation():
    """Get a movie recommendation"""
    try:
        data = request.get_json()
        user_movies = data.get('movies', [])
        if not user_movies or len(user_movies) < 3:
            return jsonify({'error': 'Please provide at least 3 movies'}), 400

        user = get_or_create_user()
        previous_recommendations = models.Recommendation.query.filter_by(user_id=user.id, content_type='movie').all()
        profile = build_taste_profile(user, 'movie', data.get('feedback'), history=previous_recommendations)

        excluded_ids = {m.get('id') for m in user_movies if m.get('id')}
        excluded_ids.update(int(rec.tmdb_id) for rec in previous_recommendations)

        recommendation = recommender.recommend_movie(
            user_movies, profile, excluded_ids,
            {'fetch': fetch_json_cached, 'tmdb_base': TMDB_BASE_URL, 'tmdb_key': TMDB_API_KEY})
        if not recommendation:
            return jsonify({'error': 'No suitable recommendations found'}), 404

        try:
            db.session.add(models.Recommendation(
                user_id=user.id, content_type='movie', tmdb_id=str(recommendation.get('id')),
                title=recommendation.get('title', ''), release_date=recommendation.get('release_date', ''),
                poster_path=recommendation.get('poster_path', ''), overview=recommendation.get('overview', ''),
                vote_average=recommendation.get('vote_average', 0), genres=recommendation.get('genre_ids', [])))
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({'recommendation': recommendation})
    except Exception as e:
        return jsonify({'error': f'Failed to get recommendation: {str(e)}'}), 500

@app.route('/get_tv_recommendation', methods=['POST'])
def get_tv_recommendation():
    """Get a TV series recommendation"""
    try:
        data = request.get_json()
        user_tv_series = data.get('tv_series', [])
        if not user_tv_series or len(user_tv_series) < 3:
            return jsonify({'error': 'Please provide at least 3 TV series'}), 400

        user = get_or_create_user()
        previous_recommendations = models.Recommendation.query.filter_by(user_id=user.id, content_type='tv').all()
        profile = build_taste_profile(user, 'tv', data.get('feedback'), history=previous_recommendations)

        excluded_ids = {s.get('id') for s in user_tv_series if s.get('id')}
        excluded_ids.update(int(rec.tmdb_id) for rec in previous_recommendations)

        recommendation = recommender.recommend_tv(
            user_tv_series, profile, excluded_ids,
            {'fetch': fetch_json_cached, 'tmdb_base': TMDB_BASE_URL, 'tmdb_key': TMDB_API_KEY})
        if not recommendation:
            return jsonify({'error': 'No suitable recommendations found'}), 404

        try:
            db.session.add(models.Recommendation(
                user_id=user.id, content_type='tv', tmdb_id=str(recommendation.get('id')),
                title=recommendation.get('name', ''), release_date=recommendation.get('first_air_date', ''),
                poster_path=recommendation.get('poster_path', ''), overview=recommendation.get('overview', ''),
                vote_average=recommendation.get('vote_average', 0), genres=recommendation.get('genre_ids', [])))
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({'recommendation': recommendation})
    except Exception as e:
        return jsonify({'error': f'Failed to get recommendation: {str(e)}'}), 500

@app.cli.command("cleanup-users")
def cleanup_users():
    """Delete anonymous users (and their cascaded data) created more than 90 days ago.

    Anonymous sessions are never explicitly deleted, so the User table grows
    forever without this. Run periodically (e.g. via a scheduled job on your
    host) to keep the database small.
    """
    cutoff = datetime.utcnow() - timedelta(days=90)
    stale_users = models.User.query.filter(models.User.created_at < cutoff).all()
    count = len(stale_users)
    for user in stale_users:
        db.session.delete(user)
    db.session.commit()
    print(f"Deleted {count} user(s) created before {cutoff.isoformat()}.")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)