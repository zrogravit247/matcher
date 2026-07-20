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

# TV crew roles that indicate real authorship of a series. TMDB's tv_credits
# rarely uses a literal "Creator" job, so the showrunner-ish roles stand in.
TV_AUTHORSHIP_JOBS = {'Creator', 'Executive Producer', 'Writer', 'Director', 'Producer'}

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

def score_feedback_adjustment(item_genre_ids, profile):
    """Genre-level score delta from a user's likes/dislikes.

    Positive signals outweigh negative ones so a single dislike can't wipe out
    a genre the user has repeatedly liked.
    """
    delta = 0
    for genre_id in item_genre_ids:
        delta += 12 * min(profile['liked_genres'].get(genre_id, 0), 3)
        delta -= 8 * min(profile['disliked_genres'].get(genre_id, 0), 3)
    return delta

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
                    'genre_ids': movie.get('genre_ids', [])
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
                    'genre_ids': tv.get('genre_ids', [])
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

def fetch_google_books(query, excluded_ids, max_results=10):
    """Fetch books from Google Books API"""
    try:
        cache_key = ('google_books', query, max_results)
        data = cache_get(cache_key)
        if data is None:
            search_url = f"{GOOGLE_BOOKS_BASE_URL}/volumes"
            params = {
                'q': query,
                'maxResults': max_results,
                'key': GOOGLE_BOOKS_API_KEY
            }
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
    """Get book recommendation using Google Books API"""
    try:
        data = request.get_json()
        user_books = data.get('books', [])
        
        if not user_books or len(user_books) < 3:
            return jsonify({'error': 'Please provide at least 3 books'}), 400

        user = get_or_create_user()
        # One query serves both the exclusion list and the taste profile;
        # every extra query is a network round-trip to the remote database.
        previous_recommendations = models.Recommendation.query.filter_by(user_id=user.id, content_type='book').all()
        profile = build_taste_profile(user, 'book', data.get('feedback'), history=previous_recommendations)

        # Analyze user preferences
        user_categories = []
        user_authors = []
        excluded_ids = set()
        
        for book in user_books:
            user_categories.extend(book.get('categories', []))
            user_authors.extend(book.get('authors', []))
            excluded_ids.add(book.get('id'))

        # Exclude previous book recommendations for variety. Scoped to
        # content_type='book' since movie/tv recommendations share this table
        # but use numeric TMDB ids rather than Google Books ids.
        for rec in previous_recommendations:
            excluded_ids.add(rec.tmdb_id)

        # Get category and author preferences
        category_counts = {}
        for category in user_categories:
            category_counts[category] = category_counts.get(category, 0) + 1

        author_counts = {}
        for author in user_authors:
            author_counts[author] = author_counts.get(author, 0) + 1

        # Search for recommendations using top categories (broad thematic
        # discovery) and top authors (precise "more like this author" - a
        # much stronger signal than category text, which Google Books tags
        # inconsistently).
        all_candidates = []
        top_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        top_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)[:2]

        for category, _ in top_categories:
            search_query = f"subject:{category}"
            candidates = fetch_google_books(search_query, excluded_ids, max_results=20)
            all_candidates.extend(candidates)

        for author, _ in top_authors:
            search_query = f'inauthor:"{author}"'
            candidates = fetch_google_books(search_query, excluded_ids, max_results=15)
            all_candidates.extend(candidates)

        # Remove duplicates
        seen_ids = set()
        unique_candidates = []
        for book in all_candidates:
            if book['id'] not in seen_ids:
                seen_ids.add(book['id'])
                unique_candidates.append(book)
        
        if not unique_candidates:
            return jsonify({'error': 'No suitable recommendations found'}), 404
        
        # Advanced scoring with diversity factors
        scored_candidates = []
        current_year = datetime.utcnow().year

        for book in unique_candidates:
            if not book.get('overview'):
                continue

            score = 0
            book_categories = book.get('categories', [])
            book_authors = book.get('authors', [])
            
            # Category matching with diminishing returns
            category_matches = 0
            for category in book_categories:
                if category in category_counts:
                    category_matches += 1
                    score += max(15 - (category_matches * 3), 5) * category_counts[category]
            
            # Author match, weighted by how many of the user's picks that
            # author wrote - the book equivalent of the director/creator
            # signal. Four books by one author is a deliberate request for
            # more of them; one is only a mild hint.
            author_affinity = max((author_counts.get(author, 0) for author in book_authors), default=0)
            if author_affinity:
                score += min(author_affinity, 4) * 12
            else:
                score += 6
            
            # Rating quality
            rating = book.get('vote_average', 0)
            if rating >= 4.5:
                score += 15
            elif rating >= 4.0:
                score += 10
            elif rating >= 3.5:
                score += 5
            
            # Publication era diversity
            pub_date = book.get('published_date', '')
            if pub_date:
                try:
                    year = int(pub_date[:4])
                    if year >= current_year - 5:
                        score += 3
                    elif year >= current_year - 15:
                        score += 2
                    elif year >= 1990:
                        score += 1
                    elif year < 1990:
                        score += 4
                except:
                    pass
            
            # Page count variety
            page_count = book.get('page_count', 0)
            if 200 <= page_count <= 400:
                score += 3
            elif 150 <= page_count <= 600:
                score += 1
            
            # Language diversity
            if book.get('language', 'en') != 'en':
                score += 5

            # Steer toward categories the user has liked and away from ones
            # they have rejected.
            score += score_feedback_adjustment(book_categories, profile)

            if score > 0:
                scored_candidates.append((book, score))
        
        if not scored_candidates:
            recommendation = unique_candidates[0] if unique_candidates else None
            reasoning = "Discovered based on thematic connections to your reading preferences."
        else:
            # Weighted random selection, biased toward the strongest matches
            scored_candidates.sort(key=lambda x: x[1], reverse=True)

            import random
            top_count = min(5, len(scored_candidates))
            weights = [max(1, score) for _, score in scored_candidates[:top_count]]
            recommendation, score = random.choices(scored_candidates[:top_count], weights=weights)[0]
            
            # Enhanced reasoning
            shared_categories = [cat for cat in recommendation.get('categories', []) if cat in category_counts]
            shared_authors = [author for author in recommendation.get('authors', []) if author in user_authors]
            
            reasoning_parts = []

            # Lead with the author when the pick is by one the user favours -
            # the most specific reason available, same as director for films.
            if shared_authors:
                author = shared_authors[0]
                picked = author_counts.get(author, 0)
                if picked > 1:
                    reasoning_parts.append(f"Another book from {author}, who wrote {picked} of your picks.")
                else:
                    reasoning_parts.append(f"Another book from {author}, whose work you already picked.")
            elif shared_categories:
                reasoning_parts.append(f"Perfect match for your {', '.join(shared_categories[:2]).lower()} interests from {', '.join([book.get('title', '') for book in user_books[:2]])}.")
            else:
                reasoning_parts.append(f"Thematically connected to your taste for {', '.join([book.get('title', '') for book in user_books[:2]])}.")
            
            pub_year = recommendation.get('published_date', '')[:4] if recommendation.get('published_date') else ''
            if pub_year and int(pub_year) >= current_year - 5:
                reasoning_parts.append("A highly acclaimed recent release.")
            elif pub_year and int(pub_year) < 1980:
                reasoning_parts.append("A timeless classic that shaped literature.")
            
            if recommendation.get('vote_average', 0) >= 4.3:
                reasoning_parts.append("Exceptional reader ratings and critical acclaim.")
            
            reasoning = " ".join(reasoning_parts)
        
        if not recommendation:
            # If no new recommendations found, suggest ending
            return jsonify({
                'recommendation': None,
                'message': "That's all the recommendations we have for now! We've explored the best matches for your preferences. Try different movies or check your watchlist for great films to watch."
            })
        
        recommendation['reasoning'] = reasoning
        
        # Save to database
        try:
            db_recommendation = models.Recommendation(
                user_id=user.id,
                content_type='book',
                tmdb_id=str(recommendation.get('id', '')),
                title=recommendation.get('title', ''),
                release_date=recommendation.get('published_date', ''),
                poster_path=recommendation.get('poster_path', ''),
                overview=recommendation.get('overview', ''),
                vote_average=recommendation.get('vote_average', 0),
                genres=recommendation.get('categories', [])
            )
            db.session.add(db_recommendation)
            db.session.commit()
        except:
            pass
        
        return jsonify({'recommendation': recommendation})
        
    except Exception as e:
        return jsonify({'error': f'Failed to get recommendation: {str(e)}'}), 500

@app.route('/get_movie_recommendation', methods=['POST'])
def get_movie_recommendation():
    """Get movie recommendation using TMDB API"""
    try:
        data = request.get_json()
        user_movies = data.get('movies', [])

        if not user_movies or len(user_movies) < 3:
            return jsonify({'error': 'Please provide at least 3 movies'}), 400

        user = get_or_create_user()
        # One query serves both the exclusion list and the taste profile;
        # every extra query is a network round-trip to the remote database.
        previous_recommendations = models.Recommendation.query.filter_by(user_id=user.id, content_type='movie').all()
        profile = build_taste_profile(user, 'movie', data.get('feedback'), history=previous_recommendations)

        # Enhanced preference analysis
        all_genre_ids = []
        excluded_ids = set()
        user_ratings = []

        for movie in user_movies:
            all_genre_ids.extend(movie.get('genre_ids', []))
            excluded_ids.add(movie.get('id'))
            user_ratings.append(movie.get('vote_average', 0))
        
        # Genre mapping for better reasoning
        genre_mapping = [
            {'id': 28, 'name': 'Action'}, {'id': 12, 'name': 'Adventure'}, {'id': 16, 'name': 'Animation'},
            {'id': 35, 'name': 'Comedy'}, {'id': 80, 'name': 'Crime'}, {'id': 99, 'name': 'Documentary'},
            {'id': 18, 'name': 'Drama'}, {'id': 10751, 'name': 'Family'}, {'id': 14, 'name': 'Fantasy'},
            {'id': 36, 'name': 'History'}, {'id': 27, 'name': 'Horror'}, {'id': 10402, 'name': 'Music'},
            {'id': 9648, 'name': 'Mystery'}, {'id': 10749, 'name': 'Romance'}, {'id': 878, 'name': 'Science Fiction'},
            {'id': 10770, 'name': 'TV Movie'}, {'id': 53, 'name': 'Thriller'}, {'id': 10752, 'name': 'War'},
            {'id': 37, 'name': 'Western'}
        ]
        
        # Exclude previous movie recommendations for variety. Scoped to
        # content_type='movie' since tv/book recommendations share this table
        # but use different id formats (book ids aren't numeric TMDB ids).
        for rec in previous_recommendations:
            excluded_ids.add(int(rec.tmdb_id))

        # Find most common genres
        genre_counts = {}
        for genre_id in all_genre_ids:
            genre_counts[genre_id] = genre_counts.get(genre_id, 0) + 1

        # Get top genres for searching
        top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        primary_genres = [str(genre_id) for genre_id, _ in top_genres]

        # Who directed the user's picks? Done first (and in parallel) because
        # the director ids feed the candidate search below.
        director_counts = {}
        director_names = {}
        credit_jobs = [(movie.get('id'), f"{TMDB_BASE_URL}/movie/{movie.get('id')}/credits",
                        {'api_key': TMDB_API_KEY}, ('movie_credits', movie.get('id')))
                       for movie in user_movies if movie.get('id')]
        if credit_jobs:
            with ThreadPoolExecutor(max_workers=len(credit_jobs)) as executor:
                futures = [executor.submit(fetch_json_cached, url, params, cache_key)
                           for _, url, params, cache_key in credit_jobs]
                for future in futures:
                    data = future.result()
                    if not data:
                        continue
                    for crew in data.get('crew', []):
                        if crew.get('job') == 'Director' and crew.get('id'):
                            director_counts[crew['id']] = director_counts.get(crew['id'], 0) + 1
                            director_names[crew['id']] = crew.get('name', '')

        # Directors the user picked more than once are a deliberate signal
        # (e.g. four Nolan films), so pull their filmographies in as candidates.
        top_directors = sorted(director_counts.items(), key=lambda x: x[1], reverse=True)[:2]

        # Gather candidates from three complementary sources, fetched in
        # parallel since they're independent HTTP calls:
        #  1. Genre-based discovery, OR'd across the user's top genres
        #     (pipe-separated = OR; comma-separated = AND, which was
        #     starving the candidate pool down to near-zero for less common
        #     genre combinations).
        #  2. TMDB's own "recommendations" endpoint for each movie the user
        #     picked - a stronger relevance signal than genre overlap alone,
        #     roughly TMDB's version of "people who liked this also liked".
        #  3. Other films by the directors behind the user's picks.
        discover_url = f"{TMDB_BASE_URL}/discover/movie"
        genre_filter = '|'.join(primary_genres)
        jobs = []
        for page in range(1, 4):
            jobs.append(('discover', None, discover_url, {
                'api_key': TMDB_API_KEY,
                'with_genres': genre_filter,
                'sort_by': 'vote_average.desc',
                'vote_count.gte': 100,
                'page': page
            }, ('discover_movie', genre_filter, page)))
        for movie in user_movies:
            movie_id = movie.get('id')
            if movie_id:
                jobs.append(('similar', movie_id, f"{TMDB_BASE_URL}/movie/{movie_id}/recommendations",
                             {'api_key': TMDB_API_KEY}, ('movie_recs', movie_id)))
        # Titles the user hit "Love It!" on pull in their own similar-titles
        # list, so a like visibly steers the very next recommendation.
        for liked_id in profile['liked_ids'][:4]:
            jobs.append(('similar', liked_id, f"{TMDB_BASE_URL}/movie/{liked_id}/recommendations",
                         {'api_key': TMDB_API_KEY}, ('movie_recs', liked_id)))
        for director_id, _ in top_directors:
            # Person credits rather than discover's with_crew filter: with_crew
            # matches any crew role, so a film the director merely produced
            # would be surfaced and then described as one they directed.
            jobs.append(('director', director_id, f"{TMDB_BASE_URL}/person/{director_id}/movie_credits",
                         {'api_key': TMDB_API_KEY}, ('director_films', director_id)))

        all_candidates = []
        similar_appearance_counts = {}
        candidate_directors = {}

        with ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as executor:
            futures = {
                executor.submit(fetch_json_cached, url, params, cache_key): (kind, source_id)
                for kind, source_id, url, params, cache_key in jobs
            }
            for future in futures:
                kind, source_id = futures[future]
                data = future.result()
                if not data:
                    continue
                if kind == 'director':
                    # Person credits are shaped differently to discover results:
                    # crew entries across every role, no 'results' key, and
                    # unfiltered for quality. Keep only films they actually
                    # directed, so the reasoning line stays truthful.
                    for candidate in data.get('crew', []):
                        if (candidate.get('job') == 'Director' and candidate.get('id')
                                and candidate.get('vote_count', 0) >= 100):
                            all_candidates.append(candidate)
                            candidate_directors[candidate['id']] = source_id
                    continue
                results = data.get('results', [])
                all_candidates.extend(results)
                if kind == 'similar':
                    for candidate in results:
                        candidate_id = candidate.get('id')
                        if candidate_id:
                            similar_appearance_counts[candidate_id] = similar_appearance_counts.get(candidate_id, 0) + 1

        # De-duplicate; the two sources above frequently overlap, and without
        # this the same movie could be scored (and weighted-selected) twice.
        seen_ids = set()
        unique_candidates = []
        for candidate in all_candidates:
            candidate_id = candidate.get('id')
            if candidate_id and candidate_id not in seen_ids:
                seen_ids.add(candidate_id)
                unique_candidates.append(candidate)
        all_candidates = unique_candidates

        current_year = datetime.utcnow().year

        # Advanced movie scoring system
        scored_candidates = []
        
        for movie in all_candidates:
            if (movie.get('id') in excluded_ids or
                movie.get('vote_average', 0) < 6.0 or
                not movie.get('overview') or
                not movie.get('release_date')):
                continue
                
            score = 0
            movie_genres = movie.get('genre_ids', [])
            
            # Genre matching with diminishing returns
            genre_matches = 0
            for genre_id in movie_genres:
                if genre_id in genre_counts:
                    genre_matches += 1
                    score += max(20 - (genre_matches * 4), 8) * genre_counts[genre_id]
            
            # Rating quality with nuanced scoring
            rating = movie.get('vote_average', 0)
            if rating >= 8.5:
                score += 25
            elif rating >= 8.0:
                score += 20
            elif rating >= 7.5:
                score += 15
            elif rating >= 7.0:
                score += 10
            elif rating >= 6.5:
                score += 5
            
            # Release year diversity bonus
            release_year = movie.get('release_date', '')[:4]
            if release_year:
                try:
                    year = int(release_year)
                    if current_year - year <= 2:
                        score += 8
                    elif current_year - year <= 5:
                        score += 5
                    elif current_year - year <= 10:
                        score += 3
                    elif current_year - year >= 30:
                        score += 10
                except:
                    pass
            
            # Popularity balance
            popularity = movie.get('popularity', 0)
            if 20 <= popularity <= 100:
                score += 5
            elif 10 <= popularity <= 200:
                score += 2
            
            # Language diversity bonus
            if movie.get('original_language', 'en') != 'en':
                score += 7

            # Appears in TMDB's own "recommendations" for one or more of the
            # user's input movies - a stronger signal than genre overlap.
            score += min(similar_appearance_counts.get(movie.get('id'), 0), 4) * 10

            # Steer toward genres the user has liked and away from ones they
            # have rejected.
            score += score_feedback_adjustment(movie_genres, profile)

            # Same director as the user's picks, weighted by how many of their
            # picks that director made: someone who chose four Nolan films is
            # asking for Nolan far more strongly than someone who chose one.
            candidate_director = candidate_directors.get(movie.get('id'))
            if candidate_director:
                score += min(director_counts.get(candidate_director, 0), 4) * 25

            scored_candidates.append((movie, score))

        if not scored_candidates:
            return jsonify({'error': 'No suitable recommendations found'}), 404

        # Weighted selection for variety, biased toward the strongest matches
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        import random
        top_count = min(5, len(scored_candidates))
        weights = [max(1, score) for _, score in scored_candidates[:top_count]]
        recommendation, score = random.choices(scored_candidates[:top_count], weights=weights)[0]
        
        # Resolve genre names for the frontend (TMDB discover results only
        # include genre_ids, not the {id, name} objects the UI needs to
        # render genre badges).
        recommendation['genres'] = [
            {'id': genre_id, 'name': next((g['name'] for g in genre_mapping if g['id'] == genre_id), f'Genre {genre_id}')}
            for genre_id in recommendation.get('genre_ids', [])
        ]

        # Enhanced reasoning generation
        shared_genres = []
        for genre_id in recommendation.get('genre_ids', []):
            if genre_id in genre_counts:
                genre_name = next((g['name'] for g in genre_mapping if g['id'] == genre_id), f'Genre {genre_id}')
                shared_genres.append(genre_name)

        reasoning_parts = []

        # Lead with the director when the pick is by one the user clearly
        # favours - it's the most specific reason we have.
        rec_director = candidate_directors.get(recommendation.get('id'))
        rec_director_name = director_names.get(rec_director) if rec_director else None
        if rec_director_name and director_counts.get(rec_director, 0) > 1:
            reasoning_parts.append(f"Another film from {rec_director_name}, who directed {director_counts[rec_director]} of your picks.")
        elif rec_director_name:
            reasoning_parts.append(f"Directed by {rec_director_name}, whose work you already picked.")
        elif shared_genres:
            reasoning_parts.append(f"Perfect match for your {', '.join(shared_genres[:2]).lower()} preferences from films like {user_movies[0].get('title', '')}.")
        else:
            reasoning_parts.append(f"Cinematically connected to your appreciation for {user_movies[0].get('title', '')} and {user_movies[1].get('title', '')}.")

        # Add unique characteristics
        rating = recommendation.get('vote_average', 0)
        release_year = recommendation.get('release_date', '')[:4]
        
        if rating >= 8.0:
            reasoning_parts.append(f"Exceptional {rating:.1f}/10 rating from critics and audiences.")
        
        if release_year:
            try:
                year = int(release_year)
                if year >= current_year - 2:
                    reasoning_parts.append("A standout recent release.")
                elif year <= 1990:
                    reasoning_parts.append("A cinematic masterpiece from film history.")
            except:
                pass

        if recommendation.get('original_language', 'en') != 'en':
            reasoning_parts.append("Expands your horizons with international cinema.")

        reasoning = " ".join(reasoning_parts)
        recommendation['reasoning'] = reasoning

        # Save to database
        try:
            db_recommendation = models.Recommendation(
                user_id=user.id,
                content_type='movie',
                tmdb_id=str(recommendation.get('id')),
                title=recommendation.get('title', ''),
                release_date=recommendation.get('release_date', ''),
                poster_path=recommendation.get('poster_path', ''),
                overview=recommendation.get('overview', ''),
                vote_average=recommendation.get('vote_average', 0),
                genres=recommendation.get('genre_ids', [])
            )
            db.session.add(db_recommendation)
            db.session.commit()
        except:
            pass
        
        return jsonify({'recommendation': recommendation})
        
    except Exception as e:
        return jsonify({'error': f'Failed to get recommendation: {str(e)}'}), 500

@app.route('/get_tv_recommendation', methods=['POST'])
def get_tv_recommendation():
    """Get TV series recommendation using TMDB API"""
    try:
        data = request.get_json()
        user_tv_series = data.get('tv_series', [])
        
        if not user_tv_series or len(user_tv_series) < 3:
            return jsonify({'error': 'Please provide at least 3 TV series'}), 400

        user = get_or_create_user()
        # One query serves both the exclusion list and the taste profile;
        # every extra query is a network round-trip to the remote database.
        previous_recommendations = models.Recommendation.query.filter_by(user_id=user.id, content_type='tv').all()
        profile = build_taste_profile(user, 'tv', data.get('feedback'), history=previous_recommendations)

        # Enhanced TV preference analysis
        all_genre_ids = []
        excluded_ids = set()
        user_ratings = []
        
        for tv_series in user_tv_series:
            all_genre_ids.extend(tv_series.get('genre_ids', []))
            excluded_ids.add(tv_series.get('id'))
            user_ratings.append(tv_series.get('vote_average', 0))
        
        # TV genre mapping for better reasoning
        tv_genre_mapping = [
            {'id': 10759, 'name': 'Action & Adventure'}, {'id': 16, 'name': 'Animation'}, {'id': 35, 'name': 'Comedy'},
            {'id': 80, 'name': 'Crime'}, {'id': 99, 'name': 'Documentary'}, {'id': 18, 'name': 'Drama'},
            {'id': 10751, 'name': 'Family'}, {'id': 10762, 'name': 'Kids'}, {'id': 9648, 'name': 'Mystery'},
            {'id': 10763, 'name': 'News'}, {'id': 10764, 'name': 'Reality'}, {'id': 10765, 'name': 'Sci-Fi & Fantasy'},
            {'id': 10766, 'name': 'Soap'}, {'id': 10767, 'name': 'Talk'}, {'id': 10768, 'name': 'War & Politics'},
            {'id': 37, 'name': 'Western'}
        ]
        
        # Exclude previous TV recommendations for variety. Scoped to
        # content_type='tv' since movie/book recommendations share this table
        # but use different id formats (book ids aren't numeric TMDB ids).
        for rec in previous_recommendations:
            excluded_ids.add(int(rec.tmdb_id))

        # Find most common genres
        genre_counts = {}
        for genre_id in all_genre_ids:
            genre_counts[genre_id] = genre_counts.get(genre_id, 0) + 1

        # Get top genres
        top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        primary_genres = [str(genre_id) for genre_id, _ in top_genres]

        # Who created the user's picks? For TV the creator is the meaningful
        # authorship signal - directors rotate episode to episode, so "created
        # by Vince Gilligan" says far more than who directed one episode.
        creator_counts = {}
        creator_names = {}
        detail_jobs = [(show.get('id'), f"{TMDB_BASE_URL}/tv/{show.get('id')}",
                        {'api_key': TMDB_API_KEY}, ('tv_details', show.get('id')))
                       for show in user_tv_series if show.get('id')]
        if detail_jobs:
            with ThreadPoolExecutor(max_workers=len(detail_jobs)) as executor:
                futures = [executor.submit(fetch_json_cached, url, params, cache_key)
                           for _, url, params, cache_key in detail_jobs]
                for future in futures:
                    data = future.result()
                    if not data:
                        continue
                    for creator in data.get('created_by', []):
                        if creator.get('id'):
                            creator_counts[creator['id']] = creator_counts.get(creator['id'], 0) + 1
                            creator_names[creator['id']] = creator.get('name', '')

        top_creators = sorted(creator_counts.items(), key=lambda x: x[1], reverse=True)[:2]

        # Gather candidates from three complementary sources, fetched in
        # parallel since they're independent HTTP calls:
        #  1. Genre-based discovery, OR'd across the user's top genres
        #     (pipe-separated = OR; comma-separated = AND, which was
        #     starving the candidate pool down to near-zero for less common
        #     genre combinations).
        #  2. TMDB's own "recommendations" endpoint for each show the user
        #     picked - a stronger relevance signal than genre overlap alone.
        #  3. Other shows from the creators behind the user's picks. This uses
        #     the person credits endpoint rather than discover's with_people
        #     filter, which does not actually constrain TV results (it returns
        #     thousands of unrelated shows).
        discover_url = f"{TMDB_BASE_URL}/discover/tv"
        genre_filter = '|'.join(primary_genres)
        jobs = []
        for page in range(1, 4):
            jobs.append(('discover', None, discover_url, {
                'api_key': TMDB_API_KEY,
                'with_genres': genre_filter,
                'sort_by': 'vote_average.desc',
                'vote_count.gte': 50,
                'page': page
            }, ('discover_tv', genre_filter, page)))
        for tv_series in user_tv_series:
            tv_id = tv_series.get('id')
            if tv_id:
                jobs.append(('similar', tv_id, f"{TMDB_BASE_URL}/tv/{tv_id}/recommendations",
                             {'api_key': TMDB_API_KEY}, ('tv_recs', tv_id)))
        # Shows the user hit "Love It!" on pull in their own similar-shows
        # list, so a like visibly steers the very next recommendation.
        for liked_id in profile['liked_ids'][:4]:
            jobs.append(('similar', liked_id, f"{TMDB_BASE_URL}/tv/{liked_id}/recommendations",
                         {'api_key': TMDB_API_KEY}, ('tv_recs', liked_id)))
        for creator_id, _ in top_creators:
            jobs.append(('creator', creator_id, f"{TMDB_BASE_URL}/person/{creator_id}/tv_credits",
                         {'api_key': TMDB_API_KEY}, ('tv_person_credits', creator_id)))

        all_candidates = []
        similar_appearance_counts = {}
        candidate_creators = {}

        with ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as executor:
            futures = {
                executor.submit(fetch_json_cached, url, params, cache_key): (kind, source_id)
                for kind, source_id, url, params, cache_key in jobs
            }
            for future in futures:
                kind, source_id = futures[future]
                data = future.result()
                if not data:
                    continue
                if kind == 'creator':
                    # Person credits are shaped differently to discover results:
                    # crew entries across every role, no 'results' key, and
                    # unfiltered for quality. Restrict to substantive creative
                    # roles so incidental credits ("Thanks") don't count as
                    # authorship.
                    for candidate in data.get('crew', []):
                        if (candidate.get('job') in TV_AUTHORSHIP_JOBS and candidate.get('id')
                                and candidate.get('vote_count', 0) >= 50):
                            all_candidates.append(candidate)
                            candidate_creators[candidate['id']] = source_id
                    continue
                results = data.get('results', [])
                all_candidates.extend(results)
                if kind == 'similar':
                    for candidate in results:
                        candidate_id = candidate.get('id')
                        if candidate_id:
                            similar_appearance_counts[candidate_id] = similar_appearance_counts.get(candidate_id, 0) + 1

        # De-duplicate; the two sources above frequently overlap, and without
        # this the same show could be scored (and weighted-selected) twice.
        seen_ids = set()
        unique_candidates = []
        for candidate in all_candidates:
            candidate_id = candidate.get('id')
            if candidate_id and candidate_id not in seen_ids:
                seen_ids.add(candidate_id)
                unique_candidates.append(candidate)
        all_candidates = unique_candidates

        current_year = datetime.utcnow().year

        # Advanced TV series scoring system
        scored_candidates = []
        
        for tv_show in all_candidates:
            if (tv_show.get('id') in excluded_ids or
                tv_show.get('vote_average', 0) < 6.0 or
                not tv_show.get('overview')):
                continue
            
            # Filter out reality TV shows if user input contains scripted shows
            user_genres = set(all_genre_ids)
            # Reality TV genre ID is 10764
            if 10764 not in user_genres and tv_show.get('genre_ids', []):
                if 10764 in tv_show.get('genre_ids', []):
                    continue  # Skip reality TV if user didn't input reality shows
                
            score = 0
            tv_genres = tv_show.get('genre_ids', [])
            
            # Genre matching with variety bonus
            genre_matches = 0
            for genre_id in tv_genres:
                if genre_id in genre_counts:
                    genre_matches += 1
                    score += max(18 - (genre_matches * 3), 6) * genre_counts[genre_id]
            
            # Rating excellence
            rating = tv_show.get('vote_average', 0)
            if rating >= 8.5:
                score += 22
            elif rating >= 8.0:
                score += 18
            elif rating >= 7.5:
                score += 14
            elif rating >= 7.0:
                score += 10
            elif rating >= 6.5:
                score += 6
            
            # Air date diversity
            first_air_date = tv_show.get('first_air_date', '')
            if first_air_date:
                try:
                    year = int(first_air_date[:4])
                    if current_year - year <= 1:
                        score += 10
                    elif current_year - year <= 3:
                        score += 6
                    elif current_year - year <= 7:
                        score += 4
                    elif current_year - year >= 20:
                        score += 8
                except:
                    pass
            
            # Popularity sweet spot
            popularity = tv_show.get('popularity', 0)
            if 15 <= popularity <= 80:
                score += 6
            elif 5 <= popularity <= 150:
                score += 3
            
            # International content bonus
            origin_countries = tv_show.get('origin_country', [])
            if origin_countries and 'US' not in origin_countries:
                score += 8

            # Appears in TMDB's own "recommendations" for one or more of the
            # user's input shows - a stronger signal than genre overlap.
            score += min(similar_appearance_counts.get(tv_show.get('id'), 0), 4) * 10

            # Steer toward genres the user has liked and away from ones they
            # have rejected.
            score += score_feedback_adjustment(tv_genres, profile)

            # Same creator as the user's picks, weighted by how many of their
            # picks that person created.
            candidate_creator = candidate_creators.get(tv_show.get('id'))
            if candidate_creator:
                score += min(creator_counts.get(candidate_creator, 0), 4) * 25

            scored_candidates.append((tv_show, score))

        if not scored_candidates:
            return jsonify({'error': 'No suitable recommendations found'}), 404

        # Weighted random selection, biased toward the strongest matches
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        import random
        top_count = min(5, len(scored_candidates))
        weights = [max(1, score) for _, score in scored_candidates[:top_count]]
        recommendation, score = random.choices(scored_candidates[:top_count], weights=weights)[0]
        
        # Resolve genre names for the frontend (TMDB discover results only
        # include genre_ids, not the {id, name} objects the UI needs to
        # render genre badges).
        recommendation['genres'] = [
            {'id': genre_id, 'name': next((g['name'] for g in tv_genre_mapping if g['id'] == genre_id), f'Genre {genre_id}')}
            for genre_id in recommendation.get('genre_ids', [])
        ]

        # Enhanced reasoning for TV series
        shared_genres = []
        for genre_id in recommendation.get('genre_ids', []):
            if genre_id in genre_counts:
                genre_name = next((g['name'] for g in tv_genre_mapping if g['id'] == genre_id), f'Genre {genre_id}')
                shared_genres.append(genre_name)

        reasoning_parts = []

        # Lead with the creator when the pick comes from one the user favours.
        rec_creator = candidate_creators.get(recommendation.get('id'))
        rec_creator_name = creator_names.get(rec_creator) if rec_creator else None
        if rec_creator_name and creator_counts.get(rec_creator, 0) > 1:
            reasoning_parts.append(f"From {rec_creator_name}, the creator behind {creator_counts[rec_creator]} of your picks.")
        elif rec_creator_name:
            reasoning_parts.append(f"From {rec_creator_name}, whose work you already picked.")
        elif shared_genres:
            reasoning_parts.append(f"Expertly crafted {', '.join(shared_genres[:2]).lower()} storytelling that builds on your love for {user_tv_series[0].get('name', '')}.")
        else:
            reasoning_parts.append(f"Narrative excellence that resonates with your appreciation for {user_tv_series[0].get('name', '')} and {user_tv_series[1].get('name', '')}.")

        # Add distinctive features
        rating = recommendation.get('vote_average', 0)
        air_year = recommendation.get('first_air_date', '')[:4]
        
        if rating >= 8.0:
            reasoning_parts.append(f"Outstanding {rating:.1f}/10 viewer and critic ratings.")
        
        if air_year:
            try:
                year = int(air_year)
                if year >= current_year - 1:
                    reasoning_parts.append("A compelling new series gaining critical acclaim.")
                elif year <= 2000:
                    reasoning_parts.append("A groundbreaking series that defined television.")
            except:
                pass

        origin_countries = recommendation.get('origin_country', [])
        if origin_countries and 'US' not in origin_countries:
            country = origin_countries[0]
            reasoning_parts.append(f"Acclaimed international production from {country}.")

        reasoning = " ".join(reasoning_parts)
        recommendation['reasoning'] = reasoning

        # Save to database
        try:
            db_recommendation = models.Recommendation(
                user_id=user.id,
                content_type='tv',
                tmdb_id=str(recommendation.get('id')),
                title=recommendation.get('name', ''),
                release_date=recommendation.get('first_air_date', ''),
                poster_path=recommendation.get('poster_path', ''),
                overview=recommendation.get('overview', ''),
                vote_average=recommendation.get('vote_average', 0),
                genres=recommendation.get('genre_ids', [])
            )
            db.session.add(db_recommendation)
            db.session.commit()
        except:
            pass
        
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