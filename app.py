import os
import json
import requests
from datetime import datetime
from flask import Flask, render_template, request, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
import uuid

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# create the app
app = Flask(__name__)
# setup a secret key, required by sessions
app.secret_key = os.environ.get("SESSION_SECRET") or os.environ.get("FLASK_SECRET_KEY") or "dev-secret-key-change-in-production"
# configure the database, relative to the app instance folder
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
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
TMDB_API_KEY = "a4747b23774690ec1831568f642ff364"
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Google Books API configuration
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_API_KEY")
GOOGLE_BOOKS_BASE_URL = "https://www.googleapis.com/books/v1"

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
    """Get user's watchlist"""
    try:
        user = get_or_create_user()
        watchlist_items = models.Watchlist.query.filter_by(user_id=user.id).order_by(models.Watchlist.added_at.desc()).all()
        
        watchlist = []
        for item in watchlist_items:
            watchlist.append({
                'tmdb_id': item.tmdb_id,
                'title': item.title,
                'release_date': item.release_date,
                'poster_path': item.poster_path,
                'overview': item.overview,
                'vote_average': item.vote_average,
                'genres': item.genres,
                'added_at': item.added_at.isoformat()
            })
        
        return jsonify({'watchlist': watchlist})
    except Exception as e:
        return jsonify({'error': f'Failed to get watchlist: {str(e)}'}), 500

@app.route('/api/remove-from-watchlist', methods=['POST'])
def remove_from_watchlist():
    """Remove movie from watchlist"""
    try:
        data = request.get_json()
        movie_id = data.get('movie_id')
        
        if not movie_id:
            return jsonify({'error': 'Movie ID is required'}), 400
        
        user = get_or_create_user()
        watchlist_item = models.Watchlist.query.filter_by(user_id=user.id, tmdb_id=movie_id).first()
        
        if not watchlist_item:
            return jsonify({'error': 'Movie not found in watchlist'}), 404
        
        db.session.delete(watchlist_item)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Movie removed from watchlist'})
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
        writer.writerow(['Title', 'Release Date', 'Rating', 'Added Date', 'Overview'])
        
        # Write data
        for item in watchlist_items:
            writer.writerow([
                item.title,
                item.release_date,
                item.vote_average,
                item.added_at.strftime('%Y-%m-%d'),
                item.overview[:100] + '...' if len(item.overview) > 100 else item.overview
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

@app.route('/api/reading-list')
def get_reading_list():
    """Get user's reading list (placeholder for now)"""
    try:
        # For now, return empty list since we don't have book watchlist implemented yet
        # This can be extended to support books in the future
        return jsonify({'books': []})
    except Exception as e:
        return jsonify({'error': f'Failed to get reading list: {str(e)}'}), 500

@app.route('/api/remove-from-reading-list', methods=['POST'])
def remove_from_reading_list():
    """Remove book from reading list (placeholder for now)"""
    try:
        return jsonify({'success': True, 'message': 'Book removed from reading list'})
    except Exception as e:
        return jsonify({'error': f'Failed to remove from reading list: {str(e)}'}), 500

@app.route('/add_to_watchlist', methods=['POST'])
def add_to_watchlist():
    """Add movie to user's watchlist"""
    try:
        data = request.get_json()
        movie_id = data.get('movie_id')
        title = data.get('title')
        
        if not movie_id or not title:
            return jsonify({'error': 'Movie ID and title are required'}), 400
        
        user = get_or_create_user()
        
        # Check if movie already in watchlist
        existing = models.Watchlist.query.filter_by(user_id=user.id, tmdb_id=movie_id).first()
        if existing:
            return jsonify({'error': 'Movie already in watchlist'}), 400
        
        # Add to watchlist
        watchlist_item = models.Watchlist(
            user_id=user.id,
            tmdb_id=movie_id,
            title=title,
            release_date=data.get('release_date', ''),
            poster_path=data.get('poster_path', ''),
            overview=data.get('overview', ''),
            vote_average=data.get('vote_average', 0),
            genres=data.get('genres', [])
        )
        
        db.session.add(watchlist_item)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Movie added to watchlist'})
        
    except Exception as e:
        return jsonify({'error': f'Failed to add to watchlist: {str(e)}'}), 500

@app.route('/search_movie')
def search_movie():
    """Search for a movie using TMDB API"""
    query = request.args.get('query', '')
    if not query:
        return jsonify([])
    
    try:
        url = f"{TMDB_BASE_URL}/search/movie"
        params = {
            'api_key': TMDB_API_KEY,
            'query': query
        }
        
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
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
        url = f"{TMDB_BASE_URL}/search/tv"
        params = {
            'api_key': TMDB_API_KEY,
            'query': query
        }
        
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
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
        url = f"{TMDB_BASE_URL}/search/movie"
        params = {
            'api_key': TMDB_API_KEY,
            'query': query
        }
        
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        suggestions = []
        for movie in data.get('results', [])[:5]:
            suggestions.append({
                'id': movie['id'],
                'title': movie['title'],
                'release_date': movie.get('release_date', ''),
                'poster_path': f"https://image.tmdb.org/t/p/w200{movie['poster_path']}" if movie.get('poster_path') else '',
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
        url = f"{TMDB_BASE_URL}/search/tv"
        params = {
            'api_key': TMDB_API_KEY,
            'query': query
        }
        
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        suggestions = []
        for tv in data.get('results', [])[:5]:
            suggestions.append({
                'id': tv['id'],
                'name': tv['name'],
                'first_air_date': tv.get('first_air_date', ''),
                'poster_path': f"https://image.tmdb.org/t/p/w200{tv['poster_path']}" if tv.get('poster_path') else '',
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
        return jsonify({'book': None})
    
    try:
        books = fetch_google_books(query, set(), max_results=5)
        if books:
            # Return the best match (first result)
            return jsonify({'book': books[0]})
        else:
            return jsonify({'book': None})
    except Exception as e:
        print(f"Error searching for book: {e}")
        return jsonify({'book': None})

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
        search_url = f"{GOOGLE_BOOKS_BASE_URL}/volumes"
        params = {
            'q': query,
            'maxResults': max_results,
            'key': GOOGLE_BOOKS_API_KEY
        }
        
        response = requests.get(search_url, params=params, timeout=3)
        response.raise_for_status()
        data = response.json()
        
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
        
        # Analyze user preferences
        user_categories = []
        user_authors = []
        excluded_ids = set()
        
        for book in user_books:
            user_categories.extend(book.get('categories', []))
            user_authors.extend(book.get('authors', []))
            excluded_ids.add(book.get('id'))
        
        # Get category preferences
        category_counts = {}
        for category in user_categories:
            category_counts[category] = category_counts.get(category, 0) + 1
        
        # Search for recommendations using top categories
        all_candidates = []
        top_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        
        for category, _ in top_categories:
            search_query = f"subject:{category}"
            candidates = fetch_google_books(search_query, excluded_ids, max_results=20)
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
        
        for book in unique_candidates:
            score = 0
            book_categories = book.get('categories', [])
            book_authors = book.get('authors', [])
            
            # Category matching with diminishing returns
            category_matches = 0
            for category in book_categories:
                if category in category_counts:
                    category_matches += 1
                    score += max(15 - (category_matches * 3), 5) * category_counts[category]
            
            # Author diversity bonus
            if not any(author in user_authors for author in book_authors):
                score += 8
            else:
                score += 3
            
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
                    if 2020 <= year <= 2024:
                        score += 3
                    elif 2010 <= year <= 2019:
                        score += 2
                    elif 1990 <= year <= 2009:
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
            
            if score > 0:
                scored_candidates.append((book, score))
        
        if not scored_candidates:
            recommendation = unique_candidates[0] if unique_candidates else None
            reasoning = "Discovered based on thematic connections to your reading preferences."
        else:
            # Weighted random selection
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            
            import random
            top_count = min(8, len(scored_candidates))
            weights = [max(1, score) for _, score in scored_candidates[:top_count]]
            recommendation, score = random.choices(scored_candidates[:top_count], weights=weights)[0]
            
            # Enhanced reasoning
            shared_categories = [cat for cat in recommendation.get('categories', []) if cat in category_counts]
            shared_authors = [author for author in recommendation.get('authors', []) if author in user_authors]
            
            reasoning_parts = []
            
            if shared_categories:
                reasoning_parts.append(f"Perfect match for your {', '.join(shared_categories[:2]).lower()} interests from {', '.join([book.get('title', '') for book in user_books[:2]])}.")
            elif shared_authors:
                reasoning_parts.append(f"Since you enjoyed {shared_authors[0]}, this explores similar storytelling mastery.")
            else:
                reasoning_parts.append(f"Thematically connected to your taste for {', '.join([book.get('title', '') for book in user_books[:2]])}.")
            
            pub_year = recommendation.get('published_date', '')[:4] if recommendation.get('published_date') else ''
            if pub_year and int(pub_year) >= 2020:
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
                tmdb_id=recommendation.get('id', ''),
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
        
        # Exclude previous recommendations for variety
        previous_recommendations = models.Recommendation.query.filter_by(user_id=user.id).all()
        for rec in previous_recommendations:
            excluded_ids.add(int(rec.tmdb_id))
        
        # Find most common genres
        genre_counts = {}
        for genre_id in all_genre_ids:
            genre_counts[genre_id] = genre_counts.get(genre_id, 0) + 1
        
        # Get top genres for searching
        top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        primary_genres = [str(genre_id) for genre_id, _ in top_genres]
        
        # Search for recommendations
        all_candidates = []
        
        # Discover movies by genre
        discover_url = f"{TMDB_BASE_URL}/discover/movie"
        params = {
            'api_key': TMDB_API_KEY,
            'with_genres': ','.join(primary_genres),
            'sort_by': 'vote_average.desc',
            'vote_count.gte': 100,
            'page': 1
        }
        
        response = requests.get(discover_url, params=params, timeout=10)
        if response.ok:
            data = response.json()
            all_candidates.extend(data.get('results', []))
        
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
                    current_year = 2024
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
            
            scored_candidates.append((movie, score))
        
        if not scored_candidates:
            return jsonify({'error': 'No suitable recommendations found'}), 404
        
        # Weighted selection for variety
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        
        import random
        top_count = min(12, len(scored_candidates))
        weights = [max(1, score) for _, score in scored_candidates[:top_count]]
        recommendation, score = random.choices(scored_candidates[:top_count], weights=weights)[0]
        
        # Enhanced reasoning generation
        shared_genres = []
        for genre_id in recommendation.get('genre_ids', []):
            if genre_id in genre_counts:
                genre_name = next((g['name'] for g in genre_mapping if g['id'] == genre_id), f'Genre {genre_id}')
                shared_genres.append(genre_name)
        
        reasoning_parts = []
        
        if shared_genres:
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
                if year >= 2022:
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
                tmdb_id=recommendation.get('id'),
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
        
        # Exclude previous recommendations for variety
        previous_recommendations = models.Recommendation.query.filter_by(user_id=user.id).all()
        for rec in previous_recommendations:
            excluded_ids.add(int(rec.tmdb_id))
        
        # Find most common genres
        genre_counts = {}
        for genre_id in all_genre_ids:
            genre_counts[genre_id] = genre_counts.get(genre_id, 0) + 1
        
        # Get top genres
        top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        primary_genres = [str(genre_id) for genre_id, _ in top_genres]
        
        # Search for recommendations
        all_candidates = []
        
        # Discover TV series by genre
        discover_url = f"{TMDB_BASE_URL}/discover/tv"
        params = {
            'api_key': TMDB_API_KEY,
            'with_genres': ','.join(primary_genres),
            'sort_by': 'vote_average.desc',
            'vote_count.gte': 50,
            'page': 1
        }
        
        response = requests.get(discover_url, params=params, timeout=10)
        if response.ok:
            data = response.json()
            all_candidates.extend(data.get('results', []))
        
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
                    current_year = 2024
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
            
            scored_candidates.append((tv_show, score))
        
        if not scored_candidates:
            return jsonify({'error': 'No suitable recommendations found'}), 404
        
        # Weighted random selection
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        
        import random
        top_count = min(10, len(scored_candidates))
        weights = [max(1, score) for _, score in scored_candidates[:top_count]]
        recommendation, score = random.choices(scored_candidates[:top_count], weights=weights)[0]
        
        # Enhanced reasoning for TV series
        shared_genres = []
        for genre_id in recommendation.get('genre_ids', []):
            if genre_id in genre_counts:
                genre_name = next((g['name'] for g in tv_genre_mapping if g['id'] == genre_id), f'Genre {genre_id}')
                shared_genres.append(genre_name)
        
        reasoning_parts = []
        
        if shared_genres:
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
                if year >= 2023:
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
                tmdb_id=recommendation.get('id'),
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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)