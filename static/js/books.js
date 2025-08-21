class BookRecommendationApp {
    constructor() {
        this.userBooks = [];
        this.recommendedBookIds = new Set();
        this.currentRecommendation = null;
        this.suggestionTimeouts = new Map();
        
        this.initializeApp();
    }

    initializeApp() {
        this.loadElements();
        this.attachEventListeners();
    }

    loadElements() {
        this.bookForm = document.getElementById('bookForm');
        this.bookInputs = document.querySelectorAll('.book-input');
        this.recommendBtn = document.getElementById('recommendBtn');
        
        this.loadingState = document.getElementById('loadingState');
        this.errorAlert = document.getElementById('errorAlert');
        this.errorMessage = document.getElementById('errorMessage');
        this.recommendationCard = document.getElementById('recommendationCard');
        
        this.bookCover = document.getElementById('bookCover');
        this.bookTitle = document.getElementById('bookTitle');
        this.bookAuthors = document.getElementById('bookAuthors');
        this.bookYear = document.getElementById('bookYear');
        this.bookRating = document.getElementById('bookRating');
        this.bookCategories = document.getElementById('bookCategories');
        this.bookDescription = document.getElementById('bookDescription');
        this.bookReasoning = document.getElementById('bookReasoning');
        this.bookReasoningText = document.getElementById('bookReasoningText');
        
        this.getAnotherBtn = document.getElementById('getAnotherBtn');
        this.resetBtn = document.getElementById('resetBtn');
        this.likeBtn = document.getElementById('likeBtn');
        this.dislikeBtn = document.getElementById('dislikeBtn');
        this.addToWatchlistBtn = document.getElementById('addToWatchlistBtn');
    }

    attachEventListeners() {
        this.bookForm.addEventListener('submit', (e) => this.handleFormSubmit(e));
        this.getAnotherBtn.addEventListener('click', () => this.getAnotherRecommendation());
        this.resetBtn.addEventListener('click', () => this.resetApp());
        this.likeBtn.addEventListener('click', () => this.handleLikeFeedback(true));
        this.dislikeBtn.addEventListener('click', () => this.handleLikeFeedback(false));
        this.addToWatchlistBtn.addEventListener('click', () => this.addToWatchlist());
        
        this.bookInputs.forEach((input, index) => {
            input.addEventListener('input', (event) => this.handleInputChange(event, index + 1));
            input.addEventListener('blur', () => {
                setTimeout(() => this.hideSuggestions(index + 1), 200);
            });
        });
    }

    async handleFormSubmit(e) {
        e.preventDefault();
        
        const bookTitles = [];
        this.bookInputs.forEach(input => {
            if (input.value.trim()) {
                bookTitles.push(input.value.trim());
            }
        });
        
        if (bookTitles.length < 3) {
            this.showError('Please enter at least 3 books to get a recommendation.');
            return;
        }
        
        this.hideError();
        this.hideAllSuggestions();
        
        try {
            this.userBooks = [];
            for (const title of bookTitles) {
                const book = await this.searchBook(title);
                if (book) {
                    this.userBooks.push(book);
                }
            }
            
            if (this.userBooks.length < 3) {
                const errorMsg = this.userBooks.length === 0 
                    ? 'Could not find any books. Please check the titles and try again.'
                    : `Found ${this.userBooks.length} out of ${bookTitles.length} books. Please check the remaining titles and try again.`;
                this.showError(errorMsg);
                return;
            }
            
            await this.getRecommendation();
            
        } catch (error) {
            console.error('Error:', error);
            this.showError('Sorry, something went wrong. Please try again.');
        }
    }

    async searchBook(title) {
        try {
            // First try to get the book from stored data if user selected from suggestions
            const input = Array.from(this.bookInputs).find(inp => inp.value.trim() === title);
            if (input && input.dataset.bookData) {
                try {
                    return JSON.parse(input.dataset.bookData);
                } catch (e) {
                    // If parsing fails, continue with API search
                }
            }
            
            // Search via API
            const response = await fetch(`/search_book?query=${encodeURIComponent(title)}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                throw new Error('Invalid response format from server');
            }
            
            const data = await response.json();
            console.log('Book search response:', data);
            
            if (Array.isArray(data) && data.length > 0) {
                const exactMatch = data.find(book => 
                    book.title.toLowerCase().includes(title.toLowerCase()) ||
                    title.toLowerCase().includes(book.title.toLowerCase())
                );
                return exactMatch || data[0];
            }
            
            return null;
        } catch (error) {
            console.error('Error searching for book:', error);
            return null;
        }
    }

    async getRecommendation() {
        this.showLoading(true);
        
        try {
            const response = await fetch('/get_book_recommendation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ books: this.userBooks })
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
        if (this.userBooks.length === 0) {
            this.showError('Please select your favorite books first.');
            return;
        }
        
        await this.getRecommendation();
    }

    async displayRecommendation(book) {
        try {
            this.currentRecommendation = book;
            
            this.bookTitle.textContent = book.title;
            this.bookAuthors.textContent = book.authors ? book.authors.join(', ') : 'Unknown Author';
            this.bookYear.textContent = book.published_date ? book.published_date.split('-')[0] : 'Unknown';
            this.bookRating.textContent = book.vote_average ? book.vote_average.toFixed(1) : 'N/A';
            this.bookDescription.textContent = book.overview || 'No description available.';
            
            if (book.poster_path) {
                this.bookCover.src = book.poster_path;
                this.bookCover.alt = `${book.title} Cover`;
            } else {
                this.bookCover.src = this.getPlaceholderImage();
                this.bookCover.alt = 'No Cover Available';
            }
            
            if (book.categories && book.categories.length > 0) {
                this.bookCategories.innerHTML = '';
                book.categories.forEach(category => {
                    const categoryBadge = document.createElement('span');
                    categoryBadge.className = 'badge bg-info me-1 mb-1';
                    categoryBadge.textContent = category;
                    this.bookCategories.appendChild(categoryBadge);
                });
            }
            
            // Show reasoning if available
            if (book.reasoning) {
                this.bookReasoningText.textContent = book.reasoning;
                this.bookReasoning.style.display = 'block';
            } else {
                this.bookReasoning.style.display = 'none';
            }
            
            this.resetFeedbackButtons();
            this.showRecommendation();
            
        } catch (error) {
            console.error('Error displaying recommendation:', error);
            this.showError('Error loading book details.');
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
            this.searchBookForSuggestions(query, inputNumber);
        }, 300));
    }

    async searchBookForSuggestions(query, inputNumber) {
        if (query.length < 2) {
            this.hideSuggestions(inputNumber);
            return;
        }
        
        try {
            const response = await fetch(`/get_book_suggestions?query=${encodeURIComponent(query)}`);
            
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
        
        suggestions.forEach(book => {
            const suggestionItem = document.createElement('div');
            suggestionItem.className = 'suggestion-item p-2 border-bottom';
            suggestionItem.style.cursor = 'pointer';
            
            let posterHtml = '';
            if (book.poster_path) {
                posterHtml = `<img src="${book.poster_path}" alt="${book.title}" class="suggestion-poster me-2" style="width: 40px; height: 60px; object-fit: cover; border-radius: 4px;" onerror="this.style.display='none'">`;
            }
            
            suggestionItem.innerHTML = `
                <div class="d-flex align-items-center">
                    ${posterHtml}
                    <div class="flex-grow-1">
                        <div class="fw-bold">${book.title}</div>
                        <div class="text-muted small">${book.authors ? book.authors.join(', ') : 'Unknown Author'}</div>
                    </div>
                </div>
            `;
            
            suggestionItem.addEventListener('click', () => {
                const input = document.getElementById(`book${inputNumber}`);
                if (input) {
                    input.value = book.title;
                    input.dataset.bookData = JSON.stringify(book);
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
        
        this.showSuccess('Added to reading list!');
        this.addToWatchlistBtn.classList.add('d-none');
    }

    resetApp() {
        this.userBooks = [];
        this.recommendedBookIds.clear();
        this.currentRecommendation = null;
        
        this.bookInputs.forEach(input => {
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
        return 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjMwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjMzc0MTUxIi8+PHRleHQgeD0iNTAlIiB5PSI0NSUiIGZvbnQtZmFtaWx5PSJBcmlhbCIgZm9udC1zaXplPSIxNiIgZmlsbD0iIzk0YTNiOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPk5vIENvdmVyPC90ZXh0Pjx0ZXh0IHg9IjUwJSIgeT0iNTUlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTQiIGZpbGw9IiM2MzczODQiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj5BdmFpbGFibGU8L3RleHQ+PC9zdmc+';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new BookRecommendationApp();
});