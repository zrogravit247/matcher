from app import db
from datetime import datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), unique=True, nullable=False)
    # Google account fields; all null for anonymous (guest) users. A guest
    # becomes a signed-in user when google_id is set, and their session data
    # is merged into any existing account with the same google_id.
    google_id = db.Column(db.String(64), unique=True, nullable=True)
    email = db.Column(db.String(255), nullable=True)
    display_name = db.Column(db.String(255), nullable=True)
    avatar_url = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    recommendations = db.relationship('Recommendation', backref='user', lazy=True, cascade='all, delete-orphan')
    watchlist = db.relationship('Watchlist', backref='user', lazy=True, cascade='all, delete-orphan')

class Recommendation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # 'movie' | 'tv' | 'book'. Movie/TV ids are numeric TMDB ids; book ids are
    # alphanumeric Google Books ids, so tmdb_id is a string and exclusion
    # queries must be scoped by content_type rather than assuming int(tmdb_id).
    content_type = db.Column(db.String(10), nullable=False, default='movie')
    tmdb_id = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    release_date = db.Column(db.String(20))
    poster_path = db.Column(db.String(255))
    overview = db.Column(db.Text)
    vote_average = db.Column(db.Float)
    genres = db.Column(db.JSON)  # Store detailed genre info as JSON
    recommended_at = db.Column(db.DateTime, default=datetime.utcnow)
    was_liked = db.Column(db.Boolean, default=None)  # User feedback: True=liked, False=disliked, None=no feedback

class Watchlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Same id/content_type convention as Recommendation.
    content_type = db.Column(db.String(10), nullable=False, default='movie')
    tmdb_id = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    release_date = db.Column(db.String(20))
    poster_path = db.Column(db.String(255))
    overview = db.Column(db.Text)
    vote_average = db.Column(db.Float)
    genres = db.Column(db.JSON)  # Store detailed genre info as JSON
    # Books carry authors rather than genres; stored as a JSON array of names.
    authors = db.Column(db.JSON)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    # One entry per item per user, scoped by content type since movie and TV
    # ids can collide numerically.
    __table_args__ = (db.UniqueConstraint('user_id', 'content_type', 'tmdb_id', name='unique_user_item_watchlist'),)
