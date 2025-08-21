from app import db
from datetime import datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to user movies and recommendations
    user_movies = db.relationship('UserMovie', backref='user', lazy=True, cascade='all, delete-orphan')
    recommendations = db.relationship('Recommendation', backref='user', lazy=True, cascade='all, delete-orphan')
    watchlist = db.relationship('Watchlist', backref='user', lazy=True, cascade='all, delete-orphan')

class UserMovie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tmdb_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    release_date = db.Column(db.String(20))
    poster_path = db.Column(db.String(255))
    overview = db.Column(db.Text)
    vote_average = db.Column(db.Float)
    genre_ids = db.Column(db.JSON)  # Store as JSON array
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

class Recommendation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tmdb_id = db.Column(db.Integer, nullable=False)
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
    tmdb_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    release_date = db.Column(db.String(20))
    poster_path = db.Column(db.String(255))
    overview = db.Column(db.Text)
    vote_average = db.Column(db.Float)
    genres = db.Column(db.JSON)  # Store detailed genre info as JSON
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Ensure unique movie per user
    __table_args__ = (db.UniqueConstraint('user_id', 'tmdb_id', name='unique_user_movie_watchlist'),)

class Genre(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    
    def __repr__(self):
        return f'<Genre {self.name}>'