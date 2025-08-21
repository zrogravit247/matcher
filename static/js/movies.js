class MovieRecommendationApp {
    constructor() {
        this.imageBaseURL = 'https://image.tmdb.org/t/p/w500';
        this.userMovies = [];
        this.recommendedMovieIds = new Set();
        this.currentRecommendation = null;
        this.suggestionTimeouts = new Map();
        
        this.initializeApp();
    }

    initializeApp() {
        this.loadElements();
        this.attachEventListeners();
    }

    loadElements() {
        this.movieForm = document.getElementById('movieForm');
        this.movieInputs = document.querySelectorAll('.movie-input');
        this.recommendBtn = document.getElementById('recommendBtn');
        
        this.loadingState = document.getElementById('loadingState');
        this.errorAlert = document.getElementById('errorAlert');
        this.errorMessage = document.getElementById('errorMessage');
        this.recommendationCard = document.getElementById('recommendationCard');
        
        this.moviePoster = document.getElementById('moviePoster');
        this.movieTitle = document.getElementById('movieTitle');
        this.movieYear = document.getElementById('movieYear');
        this.movieRating = document.getElementById('movieRating');
        this.movieGenres = document.getElementById('movieGenres');
        this.movieOverview = document.getElementById('movieOverview');
        this.movieReasoning = document.getElementById('movieReasoning');
        this.reasoningText = document.getElementById('reasoningText');
        
        this.getAnotherBtn = document.getElementById('getAnotherBtn');
        this.resetBtn = document.getElementById('resetBtn');
        this.likeBtn = document.getElementById('likeBtn');
        this.dislikeBtn = document.getElementById('dislikeBtn');
        this.addToWatchlistBtn = document.getElementById('addToWatchlistBtn');
    }

    attachEventListeners() {
        this.movieForm.addEventListener('submit', (e) => this.handleFormSubmit(e));
        this.getAnotherBtn.addEventListener('click', () => this.getAnotherRecommendation());
        this.resetBtn.addEventListener('click', () => this.resetApp());
        this.likeBtn.addEventListener('click', () => this.handleLikeFeedback(true));
        this.dislikeBtn.addEventListener('click', () => this.handleLikeFeedback(false));
        this.addToWatchlistBtn.addEventListener('click', () => this.addToWatchlist());
        
        this.movieInputs.forEach((input, index) => {
            input.addEventListener('input', (event) => this.handleInputChange(event, index + 1));
            input.addEventListener('blur', () => {
                setTimeout(() => this.hideSuggestions(index + 1), 200);
            });
        });
    }

    async handleFormSubmit(e) {
        e.preventDefault();
        
        const movieTitles = [];
        this.movieInputs.forEach(input => {
            if (input.value.trim()) {
                movieTitles.push(input.value.trim());
            }
        });
        
        if (movieTitles.length < 3) {
            this.showError('Please enter at least 3 movies to get a recommendation.');
            return;
        }
        
        this.hideError();
        this.hideAllSuggestions();
        
        try {
            this.userMovies = [];
            for (const title of movieTitles) {
                const movie = await this.searchMovie(title);
                if (movie) {
                    this.userMovies.push(movie);
                }
            }
            
            if (this.userMovies.length < 3) {
                const errorMsg = this.userMovies.length === 0 
                    ? 'Could not find any movies. Please check the titles and try again.'
                    : `Found ${this.userMovies.length} out of ${movieTitles.length} movies. Please check the remaining titles and try again.`;
                this.showError(errorMsg);
                return;
            }
            
            await this.getRecommendation();
            
        } catch (error) {
            console.error('Error:', error);
            this.showError('Sorry, something went wrong. Please try again.');
        }
    }

    async searchMovie(title) {
        try {
            const response = await fetch(`/search_movie?query=${encodeURIComponent(title)}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                throw new Error('Invalid response format from server');
            }
            
            const data = await response.json();
            console.log('Movie search response:', data);
            
            if (Array.isArray(data) && data.length > 0) {
                // Return the first result that matches closely
                const exactMatch = data.find(movie => 
                    movie.title.toLowerCase().includes(title.toLowerCase()) ||
                    title.toLowerCase().includes(movie.title.toLowerCase())
                );
                return exactMatch || data[0];
            }
            
            console.warn(`No movies found for: ${title}`);
            return null;
        } catch (error) {
            console.error('Error searching for movie:', error);
            throw error;
        }
    }

    async getRecommendation() {
        this.showLoading(true);
        
        try {
            const response = await fetch('/get_movie_recommendation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ movies: this.userMovies })
            });
            
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            
            const data = await response.json();
            
            if (data.error) {
                this.showError(data.error);
                return;
            }
            
            await this.displayRecommendation(data.recommendation);
            
        } catch (error) {
            console.error('Error getting recommendation:', error);
            this.showError('Sorry, we couldn\'t get a recommendation right now. Please try again.');
        } finally {
            this.showLoading(false);
        }
    }

    async getAnotherRecommendation() {
        if (this.userMovies.length === 0) {
            this.showError('Please select your favorite movies first.');
            return;
        }
        
        await this.getRecommendation();
    }

    async displayRecommendation(movie) {
        try {
            this.currentRecommendation = movie;
            
            this.movieTitle.textContent = movie.title;
            this.movieYear.textContent = movie.release_date ? movie.release_date.split('-')[0] : 'Unknown';
            this.movieRating.textContent = movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A';
            this.movieOverview.textContent = movie.overview || 'No description available.';
            
            if (movie.poster_path) {
                const posterUrl = `${this.imageBaseURL}${movie.poster_path}`;
                this.moviePoster.src = posterUrl;
                this.moviePoster.alt = `${movie.title} Poster`;
            } else {
                this.moviePoster.src = this.getPlaceholderImage();
                this.moviePoster.alt = 'No Poster Available';
            }
            
            if (movie.genres && movie.genres.length > 0) {
                this.movieGenres.innerHTML = '';
                movie.genres.forEach(genre => {
                    const genreBadge = document.createElement('span');
                    genreBadge.className = 'badge bg-info me-1 mb-1';
                    genreBadge.textContent = genre.name;
                    this.movieGenres.appendChild(genreBadge);
                });
            }
            
            // Show reasoning if available
            if (movie.reasoning) {
                this.reasoningText.textContent = movie.reasoning;
                this.movieReasoning.style.display = 'block';
            } else {
                this.movieReasoning.style.display = 'none';
            }
            
            this.resetFeedbackButtons();
            this.showRecommendation();
            
        } catch (error) {
            console.error('Error displaying recommendation:', error);
            this.showError('Error loading movie details.');
        }
    }

    handleInputChange(event, inputNumber) {
        const query = event.target.value.trim();
        
        if (this.suggestionTimeouts.has(inputNumber)) {
            clearTimeout(this.suggestionTimeouts.get(inputNumber));
        }
        
        if (query.length < 2) {
            this.hideSuggestions(inputNumber);
            return;
        }
        
        this.suggestionTimeouts.set(inputNumber, setTimeout(() => {
            this.searchMovieForSuggestions(query, inputNumber);
        }, 300));
    }

    async searchMovieForSuggestions(query, inputNumber) {
        if (query.length < 2) {
            this.hideSuggestions(inputNumber);
            return;
        }
        
        try {
            const response = await fetch(`/get_movie_suggestions?query=${encodeURIComponent(query)}`);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const suggestions = await response.json();
            this.displaySuggestions(suggestions || [], inputNumber);
            
        } catch (error) {
            console.error('Error getting suggestions:', error);
            this.hideSuggestions(inputNumber);
        }
    }

    displaySuggestions(suggestions, inputNumber) {
        const suggestionsContainer = document.getElementById(`suggestions${inputNumber}`);
        
        if (!suggestionsContainer) {
            console.error(`Suggestions container not found: suggestions${inputNumber}`);
            return;
        }
        
        suggestionsContainer.innerHTML = '';
        
        if (!suggestions || suggestions.length === 0) {
            suggestionsContainer.classList.add('d-none');
            return;
        }
        
        suggestions.forEach(movie => {
            const suggestionItem = document.createElement('div');
            suggestionItem.className = 'suggestion-item p-2 border-bottom';
            suggestionItem.style.cursor = 'pointer';
            
            let posterHtml = '';
            if (movie.poster_path) {
                posterHtml = `<img src="${movie.poster_path}" alt="${movie.title}" class="suggestion-poster me-2" style="width: 40px; height: 60px; object-fit: cover; border-radius: 4px;" onerror="this.style.display='none'">`;
            }
            
            suggestionItem.innerHTML = `
                <div class="d-flex align-items-center">
                    ${posterHtml}
                    <div class="flex-grow-1">
                        <div class="fw-bold">${movie.title}</div>
                        <div class="text-muted small">${movie.release_date ? movie.release_date.split('-')[0] : 'Unknown Year'}</div>
                    </div>
                </div>
            `;
            
            suggestionItem.addEventListener('click', () => {
                const input = document.getElementById(`movie${inputNumber}`);
                if (input) {
                    input.value = movie.title;
                    input.dataset.movieData = JSON.stringify(movie);
                }
                this.hideSuggestions(inputNumber);
            });
            
            suggestionsContainer.appendChild(suggestionItem);
        });
        
        suggestionsContainer.classList.remove('d-none');
    }

    hideSuggestions(inputNumber) {
        const suggestionsContainer = document.getElementById(`suggestions${inputNumber}`);
        if (suggestionsContainer) {
            suggestionsContainer.classList.add('d-none');
            suggestionsContainer.innerHTML = '';
        }
    }

    hideAllSuggestions() {
        for (let i = 1; i <= 4; i++) {
            this.hideSuggestions(i);
        }
    }

    async handleLikeFeedback(liked) {
        if (!this.currentRecommendation) return;
        
        try {
            await fetch('/recommendation_feedback', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    movie_id: this.currentRecommendation.id,
                    liked: liked
                })
            });
            
            this.updateFeedbackButtons(liked);
            setTimeout(() => this.getAnotherRecommendation(), 1000);
            
        } catch (error) {
            console.error('Error sending feedback:', error);
        }
    }

    updateFeedbackButtons(liked) {
        this.resetFeedbackButtons();
        if (liked) {
            this.likeBtn.classList.remove('btn-outline-success');
            this.likeBtn.classList.add('btn-success');
        } else {
            this.dislikeBtn.classList.remove('btn-outline-danger');
            this.dislikeBtn.classList.add('btn-danger');
        }
    }

    resetFeedbackButtons() {
        this.likeBtn.classList.remove('btn-success');
        this.likeBtn.classList.add('btn-outline-success');
        this.dislikeBtn.classList.remove('btn-danger');
        this.dislikeBtn.classList.add('btn-outline-danger');
    }

    async addToWatchlist() {
        if (!this.currentRecommendation) return;
        
        try {
            const response = await fetch('/add_to_watchlist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    movie_id: this.currentRecommendation.id,
                    title: this.currentRecommendation.title,
                    release_date: this.currentRecommendation.release_date,
                    poster_path: this.currentRecommendation.poster_path,
                    overview: this.currentRecommendation.overview,
                    vote_average: this.currentRecommendation.vote_average,
                    genres: this.currentRecommendation.genres
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showSuccess('Added to watchlist!');
                this.addToWatchlistBtn.classList.add('d-none');
            } else {
                this.showError(data.error || 'Failed to add to watchlist');
            }
            
        } catch (error) {
            console.error('Error adding to watchlist:', error);
            this.showError('Failed to add to watchlist');
        }
    }

    resetApp() {
        this.userMovies = [];
        this.recommendedMovieIds.clear();
        this.currentRecommendation = null;
        
        this.movieInputs.forEach(input => {
            input.value = '';
        });
        
        this.hideRecommendation();
        this.hideError();
        this.showLoading(false);
        this.hideAllSuggestions();
        this.resetFeedbackButtons();
    }

    showLoading(show) {
        if (show) {
            this.loadingState.classList.remove('d-none');
            this.recommendBtn.disabled = true;
        } else {
            this.loadingState.classList.add('d-none');
            this.recommendBtn.disabled = false;
        }
    }

    showError(message) {
        this.errorMessage.textContent = message;
        this.errorAlert.classList.remove('d-none');
    }

    hideError() {
        this.errorAlert.classList.add('d-none');
    }

    showRecommendation() {
        this.recommendationCard.classList.remove('d-none');
        this.recommendationCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    hideRecommendation() {
        this.recommendationCard.classList.add('d-none');
    }

    showSuccess(message) {
        const successAlert = document.createElement('div');
        successAlert.className = 'alert alert-success alert-dismissible fade show';
        successAlert.innerHTML = `
            <i class="fas fa-check-circle me-2"></i>
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        const container = document.querySelector('.container');
        if (container && container.firstChild) {
            container.insertBefore(successAlert, container.firstChild.nextSibling);
        }
        
        setTimeout(() => {
            if (successAlert.parentNode) {
                successAlert.remove();
            }
        }, 3000);
    }

    getPlaceholderImage() {
        return 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzAwIiBoZWlnaHQ9IjQ1MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjMzc0MTUxIi8+PHRleHQgeD0iNTAlIiB5PSI0NSUiIGZvbnQtZmFtaWx5PSJBcmlhbCIgZm9udC1zaXplPSIxNiIgZmlsbD0iIzk0YTNiOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPk5vIFBvc3RlcjwvdGV4dD48dGV4dCB4PSI1MCUiIHk9IjU1JSIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjE0IiBmaWxsPSIjNjM3Mzg0IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+QXZhaWxhYmxlPC90ZXh0Pjwvc3ZnPg==';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new MovieRecommendationApp();
});