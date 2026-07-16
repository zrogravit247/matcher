# Matcher

A recommendation platform for movies, TV shows, and books, powered by the TMDB and Google Books APIs.

## Features

- **Movie & TV Recommendations**: TMDB-powered discovery with genre-weighted scoring
- **Book Recommendations**: Google Books API integration
- **Watchlist**: Save and manage movies you want to watch
- **In-process response caching**: repeated searches/suggestions and genre-based discovery results are cached briefly to cut down on outbound API calls

## Local setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set up environment variables:
   ```bash
   cp .env.example .env
   # then edit .env with your own values
   ```
   - `SESSION_SECRET`: a random string for signing Flask sessions
   - `TMDB_API_KEY`: get one free at https://www.themoviedb.org/settings/api
   - `GOOGLE_API_KEY`: a Google Books API key
   - `DATABASE_URL` (optional): defaults to a local SQLite file (`matcher.db`) if unset. Set this to a Postgres URL if you'd rather use Postgres.

3. Run the app:
   ```bash
   export $(cat .env | xargs)  # or use a tool like direnv
   python main.py
   ```
   Or with gunicorn (closer to production):
   ```bash
   gunicorn --bind 0.0.0.0:5000 main:app
   ```

4. Optional maintenance: anonymous user sessions are never deleted automatically. Periodically run:
   ```bash
   flask --app main cleanup-users
   ```
   to remove anonymous users (and their data) older than 90 days.

## Deploying (Fly.io, always-on)

This repo includes a `Dockerfile` and `fly.toml` set up for [Fly.io](https://fly.io), using SQLite on a persistent volume so there's no separate database service to run or pay for.

1. Install the Fly CLI and sign in: https://fly.io/docs/hands-on/install-flyctl/
2. From the repo root, launch (this reads `fly.toml`; pick a unique app name when prompted):
   ```bash
   fly launch --no-deploy
   ```
3. Create the persistent volume for the SQLite database (must match the `source` in `fly.toml`, and match your chosen region):
   ```bash
   fly volumes create matcher_data --size 1 --region iad
   ```
4. Set your secrets (never commit these):
   ```bash
   fly secrets set SESSION_SECRET=$(openssl rand -hex 32)
   fly secrets set TMDB_API_KEY=your-tmdb-api-key
   fly secrets set GOOGLE_API_KEY=your-google-books-api-key
   ```
5. Deploy:
   ```bash
   fly deploy
   ```

`min_machines_running = 1` in `fly.toml` keeps one instance always on rather than scaling to zero when idle. To attach a custom domain later, see `fly certs add`.

## Technologies

- **Backend**: Python Flask with SQLAlchemy ORM
- **Database**: SQLite by default (Postgres supported via `DATABASE_URL`)
- **APIs**: TMDB API, Google Books API
- **Deployment**: Docker + gunicorn, hosted on Fly.io

## License

MIT License
