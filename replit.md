# Movie Recommendation Platform

## Project Overview
A dynamic media recommendation platform that leverages advanced machine learning to curate personalized content across diverse literary and cinematic landscapes, with enhanced cross-media suggestion capabilities.

**Purpose:** Provide intelligent recommendations for movies, TV shows, and books using TMDB and Google Books APIs
**Current State:** Production-ready Flask application with recommendation engine - VERIFIED FOR DEPLOYMENT

## Key Technologies
- Python Flask backend
- TMDB API integration  
- Google Books API
- Advanced recommendation system with multi-genre content tracking
- Intelligent cross-media suggestion algorithm
- International content exploration engine
- PostgreSQL database
- Gunicorn WSGI server

## Project Architecture
- **main.py**: Application entry point that imports the Flask app
- **app.py**: Core Flask application with routes, API integrations, and recommendation logic
- **models.py**: SQLAlchemy database models for users, ratings, and recommendations
- **templates/**: HTML templates for different pages (movies, books, TV, watchlist)
- **static/**: CSS, JavaScript, and asset files
- **pyproject.toml & setup.py**: Python package configuration with proper build system setup

## Recent Changes
- **2025-07-30**: Fixed deployment configuration issues and Python package build failure
  - Added Python version requirement (>=3.11) to pyproject.toml
  - Created setup.py as fallback build configuration with proper setuptools integration
  - Updated pyproject.toml with comprehensive setuptools configuration and metadata
  - Added MANIFEST.in for proper package data inclusion
  - Created README.md for project documentation
  - Removed uv.lock file to prevent package manager conflicts
  - Enhanced build system with setuptools_scm and proper package discovery

- **2025-07-30**: Applied deployment fixes for UV package manager conflicts
  - Created build_config.py to configure environment variables for deployment
  - Added deploy.py script for comprehensive deployment preparation
  - Created fix_deployment.sh script to apply all suggested fixes
  - Set environment variables to disable package caching (UV_NO_CACHE=1)
  - Forced fresh package installation (PIP_FORCE_REINSTALL=1)
  - Included development dependencies in deployment build (UV_INCLUDE_DEV=1)
  - Removed UV lock files and cache directories to prevent conflicts
  - Updated setup.py with build compatibility configurations
  - Enhanced MANIFEST.in to exclude conflicting package manager files

## Deployment Configuration
- **Main file**: main.py (imports Flask app from app.py)
- **Port**: 5000 (configured for Replit deployment)
- **Database**: PostgreSQL with proper connection pooling
- **Build system**: Setuptools with both pyproject.toml and setup.py support

## User Preferences
*To be updated as user preferences are expressed*

## API Keys Required
- TMDB API Key: Configured for movie/TV data
- Google Books API Key: Required for book recommendations (via GOOGLE_API_KEY environment variable)