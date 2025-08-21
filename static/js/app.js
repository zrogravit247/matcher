class ContentRecommendationApp {
    constructor() {
        this.imageBaseURL = 'https://image.tmdb.org/t/p/w500';
        this.userItems = [];
        this.recommendedItemIds = new Set();
        this.currentRecommendation = null;
        this.suggestionTimeouts = new Map();
        this.currentContentType = 'movies';
        
        this.initializeApp();
    }

    initializeApp() {
        this.loadElements();
        this.attachEventListeners();
    }

    loadElements() {
        // Form elements
        this.contentForm = document.getElementById('contentForm');
        this.contentInputs = document.querySelectorAll('.content-input');
        this.recommendBtn = document.getElementById('recommendBtn');
        this.contentTypeRadios = document.querySelectorAll('input[name="contentType"]');
        
        // Display elements
        this.loadingState = document.getElementById('loadingState');
        this.errorAlert = document.getElementById('errorAlert');
        this.errorMessage = document.getElementById('errorMessage');
        this.recommendationCard = document.getElementById('recommendationCard');
        this.formTitle = document.getElementById('formTitle');
        this.recommendBtnText = document.getElementById('recommendBtnText');
        this.loadingText = document.getElementById('loadingText');
        this.recommendationTitle = document.getElementById('recommendationTitle');
        
        // Content result elements
        this.contentPoster = document.getElementById('contentPoster');
        this.movieTitle = document.getElementById('movieTitle');
        this.movieYear = document.getElementById('movieYear');
        this.movieRating = document.getElementById('movieRating');
        this.movieGenres = document.getElementById('movieGenres');
        this.movieOverview = document.getElementById('movieOverview');
        
        // Action buttons
        this.getAnotherBtn = document.getElementById('getAnotherBtn');
        this.resetBtn = document.getElementById('resetBtn');
        this.likeBtn = document.getElementById('likeBtn');
        this.dislikeBtn = document.getElementById('dislikeBtn');
        this.watchedBtn = document.getElementById('watchedBtn');
        this.notWatchedBtn = document.getElementById('notWatchedBtn');
        this.addToWatchlistBtn = document.getElementById('addToWatchlistBtn');
    }

    attachEventListeners() {
        this.contentForm.addEventListener('submit', (e) => this.handleFormSubmit(e));
        this.getAnotherBtn.addEventListener('click', () => this.getAnotherRecommendation());
        
        // Content type selection
        this.contentTypeRadios.forEach(radio => {
            radio.addEventListener('change', (e) => this.handleContentTypeChange(e));
        });
        this.resetBtn.addEventListener('click', () => this.resetApp());
        this.likeBtn.addEventListener('click', () => this.handleLikeFeedback(true));
        this.dislikeBtn.addEventListener('click', () => this.handleLikeFeedback(false));
        this.watchedBtn.addEventListener('click', () => this.handleWatchedStatus(true));
        this.notWatchedBtn.addEventListener('click', () => this.handleWatchedStatus(false));
        this.addToWatchlistBtn.addEventListener('click', () => this.addToWatchlist());
        
        // Add auto-suggestion listeners for each content input
        this.contentInputs.forEach((input, index) => {
            const inputNumber = index + 1;
            input.addEventListener('input', (e) => this.handleInputChange(e, inputNumber));
            input.addEventListener('blur', (e) => {
                // Delay hiding suggestions to allow for clicks
                setTimeout(() => this.hideSuggestions(inputNumber), 200);
            });
            input.addEventListener('focus', (e) => {
                if (e.target.value.length > 2) {
                    this.handleInputChange(e, inputNumber);
                }
            });
        });
        
        // Hide suggestions when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.position-relative')) {
                this.hideAllSuggestions();
            }
        });
    }

    handleContentTypeChange(e) {
        this.currentContentType = e.target.value;
        this.updateUIForContentType();
        this.resetApp();
    }
    
    updateUIForContentType() {
        const contentLabels = document.querySelectorAll('.content-label');
        const contentInputs = document.querySelectorAll('.content-input');
        
        switch (this.currentContentType) {
            case 'movies':
                this.formTitle.innerHTML = '<i class="fas fa-heart text-danger me-2"></i>Your Favorites';
                this.recommendBtnText.textContent = 'Give me a recommendation!';
                this.loadingText.textContent = 'Finding the perfect movie for you...';
                contentLabels.forEach((label, index) => {
                    label.textContent = `Pick #${index + 1}`;
                });
                contentInputs.forEach((input, index) => {
                    const placeholders = ['e.g., The Dark Knight', 'e.g., Inception', 'e.g., Pulp Fiction', 'e.g., Interstellar'];
                    input.placeholder = placeholders[index] || `Movie ${index + 1}`;
                });
                break;
            case 'tv':
                this.formTitle.innerHTML = '<i class="fas fa-heart text-danger me-2"></i>Your Favorites';
                this.recommendBtnText.textContent = 'Give me a recommendation!';
                this.loadingText.textContent = 'Finding the perfect TV series for you...';
                contentLabels.forEach((label, index) => {
                    label.textContent = `Pick #${index + 1}`;
                });
                contentInputs.forEach((input, index) => {
                    const placeholders = ['e.g., Breaking Bad', 'e.g., Game of Thrones', 'e.g., The Office', 'e.g., Stranger Things'];
                    input.placeholder = placeholders[index] || `TV Series ${index + 1}`;
                });
                break;
            case 'books':
                this.formTitle.innerHTML = '<i class="fas fa-heart text-danger me-2"></i>Your Favorites';
                this.recommendBtnText.textContent = 'Give me a recommendation!';
                this.loadingText.textContent = 'Finding the perfect book for you...';
                contentLabels.forEach((label, index) => {
                    label.textContent = `Pick #${index + 1}`;
                });
                contentInputs.forEach((input, index) => {
                    const placeholders = ['e.g., The Great Gatsby', 'e.g., To Kill a Mockingbird', 'e.g., 1984', 'e.g., Pride and Prejudice'];
                    input.placeholder = placeholders[index] || `Book ${index + 1}`;
                });
                break;
        }
    }

    async handleFormSubmit(e) {
        e.preventDefault();
        
        // Get all content titles
        const contentTitles = [];
        this.contentInputs.forEach(input => {
            if (input.value.trim()) {
                contentTitles.push(input.value.trim());
            }
        });
        
        if (contentTitles.length < 4) {
            const contentName = this.currentContentType === 'books' ? 'books' : 
                              this.currentContentType === 'tv' ? 'TV series' : 'movies';
            this.showError(`Please enter all 4 ${contentName} to get a recommendation.`);
            return;
        }
        
        this.hideError();
        this.hideAllSuggestions();
        
        try {
            // Search for each item and collect details
            this.userItems = [];
            for (const title of contentTitles) {
                const item = await this.searchContent(title);
                if (item) {
                    this.userItems.push(item);
                }
            }
            
            if (this.userItems.length < 4) {
                const contentName = this.currentContentType === 'books' ? 'books' : 
                                  this.currentContentType === 'tv' ? 'TV series' : 'movies';
                this.showError(`Could not find all ${contentName}. Please check the titles and try again.`);
                return;
            }
            
            // Get recommendation
            await this.getRecommendation();
            
        } catch (error) {
            console.error('Error:', error);
            this.showError('Sorry, something went wrong. Please try again.');
        }
    }

    async searchContent(title) {
        try {
            let endpoint;
            switch (this.currentContentType) {
                case 'movies':
                    endpoint = '/search_movie';
                    break;
                case 'tv':
                    endpoint = '/search_tv';
                    break;
                case 'books':
                    endpoint = '/search_book';
                    break;
                default:
                    endpoint = '/search_movie';
            }
            
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ title: title })
            });

            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || `API request failed: ${response.status}`);
            }

            return data.movie;
        } catch (error) {
            console.error(`Error searching for movie "${title}":`, error);
            throw new Error(`Failed to search for "${title}". ${error.message}`);
        }
    }

    async getRecommendation() {
        try {
            const excludedIds = Array.from(this.recommendedMovieIds);
            
            const response = await fetch('/api/get-recommendation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    movies: this.userMovies,
                    excluded_ids: excludedIds
                })
            });

            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || `API request failed: ${response.status}`);
            }

            // Add to recommended set to avoid future duplicates
            this.recommendedMovieIds.add(data.recommendation.id);

            return data.recommendation;

        } catch (error) {
            console.error('Error getting recommendation:', error);
            throw error;
        }
    }

    async getAnotherRecommendation() {
        if (this.userItems.length === 0) {
            this.showError('Please select your favorites first.');
            return;
        }
        
        await this.getRecommendation();
    }

    async displayRecommendation(movie) {
        try {
            this.currentRecommendation = movie;
            
            // Get detailed movie information including genres
            const detailedMovie = await this.getMovieDetails(movie.id);
            
            this.movieTitle.textContent = movie.title;
            this.movieYear.textContent = movie.release_date ? new Date(movie.release_date).getFullYear() : 'Unknown';
            this.movieRating.textContent = `★ ${movie.vote_average.toFixed(1)}/10`;
            this.movieOverview.textContent = movie.overview || 'No overview available.';

            // Set poster image with error handling
            if (movie.poster_path) {
                const posterUrl = `${this.imageBaseURL}${movie.poster_path}`;
                this.moviePoster.onload = () => {
                    this.moviePoster.style.opacity = '1';
                };
                this.contentPoster.onerror = () => {
                    console.warn('Failed to load poster:', posterUrl);
                    this.contentPoster.src = this.getPlaceholderImage();
                };
                this.contentPoster.style.opacity = '0.5';
                this.contentPoster.src = posterUrl;
                this.contentPoster.alt = `${movie.title} Poster`;
            } else {
                this.contentPoster.src = this.getPlaceholderImage();
                this.contentPoster.alt = 'No Poster Available';
                this.contentPoster.style.opacity = '1';
            }

            // Display genres
            if (detailedMovie && detailedMovie.genres) {
                this.movieGenres.innerHTML = '';
                detailedMovie.genres.forEach(genre => {
                    const genreBadge = document.createElement('span');
                    genreBadge.className = 'badge bg-info me-1 mb-1';
                    genreBadge.textContent = genre.name;
                    this.movieGenres.appendChild(genreBadge);
                });
            }

            // Reset all feedback buttons and poster styling
            this.resetFeedbackButtons();
            this.addToWatchlistBtn.classList.add('d-none');
            
            // Reset poster styling
            if (this.contentPoster) {
                this.contentPoster.style.filter = 'none';
            }

            this.showRecommendation();

        } catch (error) {
            console.error('Error displaying recommendation:', error);
            this.showError('Error loading movie details.');
        }
    }

    async getMovieDetails(movieId) {
        try {
            const response = await fetch(`/api/movie-details/${movieId}`);
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || `API request failed: ${response.status}`);
            }

            return data.movie;
        } catch (error) {
            console.error('Error getting movie details:', error);
            return null;
        }
    }

    resetApp() {
        // Clear form
        this.movieForm.reset();
        
        // Reset data
        this.userMovies = [];
        this.recommendedMovieIds.clear();
        
        // Hide states
        this.hideRecommendation();
        this.hideError();
        this.showLoading(false);
        
        // Focus first input
        this.movieInputs[0].focus();
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
        this.errorAlert.scrollIntoView({ behavior: 'smooth', block: 'center' });
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

    handleInputChange(event, inputNumber) {
        const query = event.target.value.trim();
        
        // Clear previous timeout
        if (this.suggestionTimeouts.has(inputNumber)) {
            clearTimeout(this.suggestionTimeouts.get(inputNumber));
        }
        
        if (query.length < 3) {
            this.hideSuggestions(inputNumber);
            return;
        }
        
        // Debounce the search
        const timeout = setTimeout(() => {
            this.searchContentForSuggestions(query, inputNumber);
        }, 300);
        
        this.suggestionTimeouts.set(inputNumber, timeout);
    }

    async searchContentForSuggestions(query, inputNumber) {
        if (query.length < 2) {
            this.hideSuggestions(inputNumber);
            return;
        }
        
        try {
            let endpoint;
            switch (this.currentContentType) {
                case 'movies':
                    endpoint = '/get_movie_suggestions';
                    break;
                case 'tv':
                    endpoint = '/get_tv_suggestions';
                    break;
                case 'books':
                    endpoint = '/get_book_suggestions';
                    break;
                default:
                    endpoint = '/get_movie_suggestions';
            }
            
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query })
            });
            
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            
            const data = await response.json();
            this.displaySuggestions(data.suggestions || [], inputNumber);
            
        } catch (error) {
            console.error('Error fetching suggestions:', error);
            this.hideSuggestions(inputNumber);
        }
    }

    displaySuggestions(movies, inputNumber) {
        const suggestionsContainer = document.getElementById(`suggestions${inputNumber}`);
        suggestionsContainer.innerHTML = '';
        
        if (movies.length === 0) {
            suggestionsContainer.style.display = 'none';
            return;
        }
        
        movies.forEach(movie => {
            const suggestionItem = document.createElement('div');
            suggestionItem.className = 'suggestion-item';
            
            const posterUrl = movie.poster_path 
                ? `${this.imageBaseURL}${movie.poster_path}`
                : 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA0MCA2MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjY2NjIi8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvbnQtZmFtaWx5PSJBcmlhbCIgZm9udC1zaXplPSIxMCIgZmlsbD0iIzk5OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPk5vIEltYWdlPC90ZXh0Pjwvc3ZnPg==';
            
            const year = movie.release_date ? new Date(movie.release_date).getFullYear() : '';
            
            suggestionItem.innerHTML = `
                <img src="${posterUrl}" alt="${movie.title}" class="suggestion-poster">
                <div class="suggestion-info">
                    <div class="suggestion-title">${movie.title}</div>
                    <div class="suggestion-year">${year}</div>
                </div>
            `;
            
            suggestionItem.addEventListener('click', () => {
                document.getElementById(`movie${inputNumber}`).value = movie.title;
                this.hideSuggestions(inputNumber);
            });
            
            suggestionsContainer.appendChild(suggestionItem);
        });
        
        suggestionsContainer.style.display = 'block';
    }

    hideSuggestions(inputNumber) {
        const suggestionsContainer = document.getElementById(`suggestions${inputNumber}`);
        if (suggestionsContainer) {
            suggestionsContainer.style.display = 'none';
        }
    }

    hideAllSuggestions() {
        for (let i = 1; i <= 4; i++) {
            this.hideSuggestions(i);
        }
    }

    handleLikeFeedback(liked) {
        if (!this.currentRecommendation) return;
        
        // Update button styles
        if (liked) {
            this.likeBtn.classList.remove('btn-outline-success');
            this.likeBtn.classList.add('btn-success');
            this.dislikeBtn.classList.remove('btn-danger');
            this.dislikeBtn.classList.add('btn-outline-danger');
            this.showSuccess('Thanks for the feedback! Getting another recommendation...');
            
            // Automatically get another recommendation after positive feedback
            setTimeout(() => {
                this.getAnotherRecommendation();
            }, 1500);
        } else {
            this.dislikeBtn.classList.remove('btn-outline-danger');
            this.dislikeBtn.classList.add('btn-danger');
            this.likeBtn.classList.remove('btn-success');
            this.likeBtn.classList.add('btn-outline-success');
            this.showSuccess('Thanks for the feedback! We will learn from this...');
            
            // Get another recommendation after negative feedback
            setTimeout(() => {
                this.getAnotherRecommendation();
            }, 1500);
        }
        
        // Send feedback to backend
        this.sendRecommendationFeedback(this.currentRecommendation.id, liked);
    }

    handleWatchedStatus(watched) {
        if (!this.currentRecommendation) return;
        
        // Grey out the poster
        const posterImg = this.moviePoster;
        if (posterImg) {
            posterImg.style.filter = 'grayscale(100%) opacity(0.6)';
        }
        
        // Update button styles
        if (watched) {
            this.watchedBtn.classList.remove('btn-outline-warning');
            this.watchedBtn.classList.add('btn-warning');
            this.notWatchedBtn.classList.remove('btn-info');
            this.notWatchedBtn.classList.add('btn-outline-info');
            this.addToWatchlistBtn.classList.add('d-none');
            
            this.showSuccess('Got it! Getting another recommendation...');
            // Automatically get another recommendation
            setTimeout(() => {
                this.getAnotherRecommendation();
            }, 1500);
        } else {
            this.notWatchedBtn.classList.remove('btn-outline-info');
            this.notWatchedBtn.classList.add('btn-info');
            this.watchedBtn.classList.remove('btn-warning');
            this.watchedBtn.classList.add('btn-outline-warning');
            this.addToWatchlistBtn.classList.remove('d-none');
            
            this.showSuccess('Added to your watchlist! Getting another recommendation...');
            // Add to watchlist and get another recommendation
            this.addToWatchlist();
            setTimeout(() => {
                this.getAnotherRecommendation();
            }, 1500);
        }
    }

    async sendRecommendationFeedback(movieId, liked) {
        try {
            await fetch('/api/recommendation-feedback', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    recommendation_id: movieId,
                    liked: liked
                })
            });
        } catch (error) {
            console.error('Error sending feedback:', error);
        }
    }

    resetFeedbackButtons() {
        // Reset like/dislike buttons
        this.likeBtn.classList.remove('btn-success');
        this.likeBtn.classList.add('btn-outline-success');
        this.dislikeBtn.classList.remove('btn-danger');
        this.dislikeBtn.classList.add('btn-outline-danger');
        
        // Reset watched buttons
        this.watchedBtn.classList.remove('btn-warning');
        this.watchedBtn.classList.add('btn-outline-warning');
        this.notWatchedBtn.classList.remove('btn-info');
        this.notWatchedBtn.classList.add('btn-outline-info');
    }

    async addToWatchlist() {
        if (!this.currentRecommendation) return;
        
        try {
            const response = await fetch('/api/add-to-watchlist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    movie_id: this.currentRecommendation.id,
                    title: this.currentRecommendation.title
                })
            });
            
            if (response.ok) {
                this.showSuccess('Movie added to your watchlist!');
                this.addToWatchlistBtn.innerHTML = '<i class="fas fa-check me-2"></i>Added to Watchlist';
                this.addToWatchlistBtn.disabled = true;
            } else {
                const data = await response.json();
                this.showError(data.error || 'Failed to add to watchlist');
            }
        } catch (error) {
            this.showError('Failed to add to watchlist');
        }
    }

    showSuccess(message) {
        // Create a temporary success alert
        const successAlert = document.createElement('div');
        successAlert.className = 'alert alert-success alert-dismissible fade show';
        successAlert.innerHTML = `
            <i class="fas fa-check-circle me-2"></i>
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        // Insert at the top of the container
        const container = document.querySelector('.container');
        if (container && container.firstChild) {
            container.insertBefore(successAlert, container.firstChild.nextSibling);
        }
        
        // Auto-dismiss after 3 seconds
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

// Initialize the app when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.contentApp = new ContentRecommendationApp();
    window.contentApp.updateUIForContentType(); // Set initial UI state
});
