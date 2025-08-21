# Movie Recommendation Platform

A dynamic media recommendation platform that leverages advanced machine learning to curate personalized content across diverse literary and cinematic landscapes, with enhanced cross-media suggestion capabilities.

## Features

- **Movie Recommendations**: Powered by TMDB API with intelligent scoring algorithms
- **TV Show Discovery**: Advanced filtering and personalized suggestions
- **Book Recommendations**: Google Books API integration with cross-media suggestions
- **Watchlist Management**: Personal content curation and tracking
- **International Content**: Multi-language and global content exploration

## Technologies

- **Backend**: Python Flask with SQLAlchemy ORM
- **Database**: PostgreSQL with connection pooling
- **APIs**: TMDB API, Google Books API
- **Deployment**: Gunicorn WSGI server
- **Frontend**: Responsive HTML/CSS with JavaScript enhancements

## Setup

1. Install dependencies:
   ```bash
   pip install -e .
   ```

2. Set up environment variables:
   - `DATABASE_URL`: PostgreSQL connection string
   - `SESSION_SECRET`: Flask session secret key
   - `TMDB_API_KEY`: The Movie Database API key
   - `GOOGLE_API_KEY`: Google Books API key

3. Run the application:
   ```bash
   gunicorn --bind 0.0.0.0:5000 main:app
   ```

## License

MIT License