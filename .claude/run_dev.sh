#!/bin/bash
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
export SESSION_SECRET="${SESSION_SECRET:-dev-secret-key}"
export TMDB_API_KEY="${TMDB_API_KEY:-dummy-key}"
export GOOGLE_API_KEY="${GOOGLE_API_KEY:-dummy-key}"
exec .venv/bin/flask --app main run --host 0.0.0.0 --port 5050
