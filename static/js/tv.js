class TVRecommendationApp {
    constructor() {
        this.imageBaseURL = 'https://image.tmdb.org/t/p/w500';
        this.userTVSeries = [];
        this.recommendedTVIds = new Set();
        this.currentRecommendation = null;
        this.suggestionTimeouts = new Map();
        
        this.initializeApp();
    }

    initializeApp() {
        this.loadElements();
        this.attachEventListeners();
    }

    loadElements() {
        this.tvForm = document.getElementById('tvForm');
        this.tvInputs = document.querySelectorAll('.tv-input');
        this.recommendBtn = document.getElementById('recommendBtn');
        
        this.loadingState = document.getElementById('loadingState');
        this.errorAlert = document.getElementById('errorAlert');
        this.errorMessage = document.getElementById('errorMessage');
        this.recommendationCard = document.getElementById('recommendationCard');
        
        this.tvPoster = document.getElementById('tvPoster');
        this.tvTitle = document.getElementById('tvTitle');
        this.tvYear = document.getElementById('tvYear');
        this.tvRating = document.getElementById('tvRating');
        this.tvGenres = document.getElementById('tvGenres');
        this.tvOverview = document.getElementById('tvOverview');
        this.tvReasoning = document.getElementById('tvReasoning');
        this.tvReasoningText = document.getElementById('tvReasoningText');
        
        this.getAnotherBtn = document.getElementById('getAnotherBtn');
        this.resetBtn = document.getElementById('resetBtn');
        this.likeBtn = document.getElementById('likeBtn');
        this.dislikeBtn = document.getElementById('dislikeBtn');
        this.addToWatchlistBtn = document.getElementById('addToWatchlistBtn');
    }

    attachEventListeners() {
        this.tvForm.addEventListener('submit', (e) => this.handleFormSubmit(e));
        this.getAnotherBtn.addEventListener('click', () => this.getAnotherRecommendation());
        this.resetBtn.addEventListener('click', () => this.resetApp());
        this.likeBtn.addEventListener('click', () => this.handleLikeFeedback(true));
        this.dislikeBtn.addEventListener('click', () => this.handleLikeFeedback(false));
        this.addToWatchlistBtn.addEventListener('click', () => this.addToWatchlist());
        
        this.tvInputs.forEach((input, index) => {
            input.addEventListener('input', (event) => this.handleInputChange(event, index + 1));
            input.addEventListener('blur', () => {
                setTimeout(() => this.hideSuggestions(index + 1), 200);
            });
        });
    }

    async handleFormSubmit(e) {
        e.preventDefault();
        
        const tvTitles = [];
        this.tvInputs.forEach(input => {
            if (input.value.trim()) {
                tvTitles.push(input.value.trim());
            }
        });
        
        if (tvTitles.length < 3) {
            this.showError('Please enter at least 3 TV series to get a recommendation.');
            return;
        }
        
        this.hideError();
        this.hideAllSuggestions();
        
        try {
            this.userTVSeries = [];
            for (const title of tvTitles) {
                const tvShow = await this.searchTV(title);
                if (tvShow) {
                    this.userTVSeries.push(tvShow);
                }
            }
            
            if (this.userTVSeries.length < 4) {
                this.showError('Could not find all TV series. Please check the titles and try again.');
                return;
            }
            
            await this.getRecommendation();
            
        } catch (error) {
            console.error('Error:', error);
            this.showError('Sorry, something went wrong. Please try again.');
        }
    }

    async searchTV(title) {
        try {
            const response = await fetch(`/search_tv?query=${encodeURIComponent(title)}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                throw new Error('Invalid response format from server');
            }
            
            const data = await response.json();
            console.log('TV search response:', data);
            
            if (Array.isArray(data) && data.length > 0) {
                // Return the first result that matches closely
                const exactMatch = data.find(tv => 
                    tv.name.toLowerCase().includes(title.toLowerCase()) ||
                    title.toLowerCase().includes(tv.name.toLowerCase())
                );
                return exactMatch || data[0];
            }
            
            console.warn(`No TV series found for: ${title}`);
            return null;
        } catch (error) {
            console.error('Error searching for TV series:', error);
            throw error;
        }
    }

    async getRecommendation() {
        this.showLoading(true);
        
        try {
            const response = await fetch('/get_tv_recommendation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ tv_series: this.userTVSeries })
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
        if (this.userTVSeries.length === 0) {
            this.showError('Please select your favorite TV series first.');
            return;
        }
        
        await this.getRecommendation();
    }

    async displayRecommendation(tvShow) {
        try {
            this.currentRecommendation = tvShow;
            
            this.tvTitle.textContent = tvShow.title || tvShow.name;
            this.tvYear.textContent = tvShow.first_air_date ? tvShow.first_air_date.split('-')[0] : 'Unknown';
            this.tvRating.textContent = tvShow.vote_average ? tvShow.vote_average.toFixed(1) : 'N/A';
            this.tvOverview.textContent = tvShow.overview || 'No description available.';
            
            if (tvShow.poster_path) {
                const posterUrl = `${this.imageBaseURL}${tvShow.poster_path}`;
                this.tvPoster.src = posterUrl;
                this.tvPoster.alt = `${tvShow.title || tvShow.name} Poster`;
            } else {
                this.tvPoster.src = this.getPlaceholderImage();
                this.tvPoster.alt = 'No Poster Available';
            }
            
            if (tvShow.genres && tvShow.genres.length > 0) {
                this.tvGenres.innerHTML = '';
                tvShow.genres.forEach(genre => {
                    const genreBadge = document.createElement('span');
                    genreBadge.className = 'badge bg-info me-1 mb-1';
                    genreBadge.textContent = genre.name;
                    this.tvGenres.appendChild(genreBadge);
                });
            }
            
            // Show reasoning if available
            if (tvShow.reasoning) {
                this.tvReasoningText.textContent = tvShow.reasoning;
                this.tvReasoning.style.display = 'block';
            } else {
                this.tvReasoning.style.display = 'none';
            }
            
            this.resetFeedbackButtons();
            this.showRecommendation();
            
        } catch (error) {
            console.error('Error displaying recommendation:', error);
            this.showError('Error loading TV series details.');
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
            this.searchTVForSuggestions(query, inputNumber);
        }, 300));
    }

    async searchTVForSuggestions(query, inputNumber) {
        if (query.length < 2) {
            this.hideSuggestions(inputNumber);
            return;
        }
        
        try {
            const response = await fetch(`/get_tv_suggestions?query=${encodeURIComponent(query)}`);
            
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
        
        suggestions.forEach(tv => {
            const suggestionItem = document.createElement('div');
            suggestionItem.className = 'suggestion-item p-2 border-bottom';
            suggestionItem.style.cursor = 'pointer';
            
            let posterHtml = '';
            if (tv.poster_path) {
                posterHtml = `<img src="${tv.poster_path}" alt="${tv.name}" class="suggestion-poster me-2" style="width: 40px; height: 60px; object-fit: cover; border-radius: 4px;" onerror="this.style.display='none'">`;
            }
            
            suggestionItem.innerHTML = `
                <div class="d-flex align-items-center">
                    ${posterHtml}
                    <div class="flex-grow-1">
                        <div class="fw-bold">${tv.name}</div>
                        <div class="text-muted small">${tv.first_air_date ? tv.first_air_date.split('-')[0] : 'Unknown Year'}</div>
                    </div>
                </div>
            `;
            
            suggestionItem.addEventListener('click', () => {
                const input = document.getElementById(`tv${inputNumber}`);
                if (input) {
                    input.value = tv.name;
                    input.dataset.tvData = JSON.stringify(tv);
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
        
        this.updateFeedbackButtons(liked);
        setTimeout(() => this.getAnotherRecommendation(), 1000);
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
        
        this.showSuccess('Added to watchlist!');
        this.addToWatchlistBtn.classList.add('d-none');
    }

    resetApp() {
        this.userTVSeries = [];
        this.recommendedTVIds.clear();
        this.currentRecommendation = null;
        
        this.tvInputs.forEach(input => {
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
    new TVRecommendationApp();
});