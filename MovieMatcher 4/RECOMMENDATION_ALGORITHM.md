# Movie Recommendation Algorithm

## Overview
The recommendation system analyzes user preferences from 4 input movies and uses multiple weighted factors to find similar movies through the TMDB API. This comprehensive system includes collaborative filtering approximation and emotional/tonal matching.

## Algorithm Factors (Priority Order)

### 1. **Enhanced Genre Matching** (Highest Priority - 10 points per match × frequency)
- **Frequency Vector**: Counts how many times each genre appears in user's 4 movies
- **Scoring**: 10 points per matching genre, multiplied by frequency count
- **Example**: If Action appears in 3/4 user movies, Action candidates get 10×3=30 points
- **Logic**: Genres appearing more frequently get proportionally higher weight

### 2. **User Feedback Learning** (High Priority - +12/-8 points per genre)
- **Personalization**: Learns from user's "Love It" / "Not For Me" responses
- **Scoring**: +12 points for each liked genre, -8 points for each disliked genre
- **Memory**: Analyzes last 20 feedback responses for optimal performance
- **Conflict Resolution**: Liked genres override disliked (prioritizes positive feedback)

### 3. **Enhanced Rating Quality** (Medium-High Priority - up to 17 points)
- **Base Rating Score**:
  - 8.0+ rating: +10 points
  - 7.5-7.9 rating: +6 points  
  - 7.0-7.4 rating: +2 points
  - <6.0 rating: -10 points (penalty)
- **Social Proof Bonus**: +2 points if vote_count ≥ 1000
- **Alternative Formula**: rating × log(vote_count + 1) ÷ 10 (max 5 points)
- **Logic**: Higher ratings with more votes indicate reliable quality

### 4. **Collaborative Filtering Approximation** (+10 points)
- **Similar Movies**: Calls TMDB's /movie/{id}/similar for each user movie
- **Candidate Pool**: Builds list of movies similar to user's preferences
- **Scoring**: +10 points if candidate appears in this collaborative set
- **Benefit**: Adds "users who liked X also liked Y" behavior without user-user data

### 5. **Emotional/Tonal Matching** (up to 15 points)
- **Tone Inference**: Analyzes user movies for emotional themes
- **Tone Categories**: inspirational, dark, uplifting, dramatic, thrilling, romantic, comedic
- **Analysis Methods**:
  - Genre combinations (Drama+History→inspirational)
  - TMDB keywords endpoint
  - Overview text analysis
- **Scoring**: +5 points per tone match, weighted by user's tone strength
- **Example**: If user prefers dark themes, candidates with noir/gritty keywords get bonus points

### 6. **Enhanced Popularity Decay** (Medium Priority - max 8 points)
- **Optimal Range**: +8 points for popularity 20-150 (sweet spot for discovery)
- **Mainstream Penalty**: -2 points if popularity >300 (too mainstream)
- **Low Popularity**: Multiply score by 0.8 if popularity <10 AND total score <20
- **Goal**: Balance discoverability with avoiding overly popular or obscure content

### 7. **Content Safety Filter** (Essential Filter - Boolean)
- **Explicit Content**: Filters out pornographic movies only
- **Filters Applied**:
  - `include_adult: False` in API calls
  - `adult=true` flag check on candidates
  - Title keyword filtering: "porn", "xxx", "hardcore"
- **Allows**: R-rated movies with mature themes, violence, strong language
- **Blocks**: Explicitly pornographic or adult films
- **Priority**: Absolute requirement (eliminates candidates before scoring)

## Data Sources & Processing

### **Primary Sources** (Concurrent API Calls)
1. **Genre Discovery**: TMDB discover endpoint with user's top genres
2. **Similar Movies**: TMDB similar movies for user's highest-rated input movie

### **Performance Optimizations**
- **Concurrent Requests**: 2 parallel API calls with 2-second timeout
- **Candidate Limit**: Process up to 60 movies for speed vs variety balance
- **Caching**: User preference cache to avoid repeated database queries
- **Quality Filters**: Pre-filter by rating (≥6.0), poster availability, meaningful overview

### **Selection Process**
1. **Scoring**: Calculate total score for each candidate using above factors
2. **Ranking**: Sort candidates by total score (highest first)
3. **Randomization**: Select from top 20 candidates using weighted random choice
4. **Variety**: Ensures different recommendations on repeat requests

## Example Scoring

**User Input**: 
- Avengers (Action/Adventure) 
- The Dark Knight (Action/Crime)
- Inception (Action/Sci-Fi)
- Pulp Fiction (Crime/Drama)

**Analysis**:
- Genre Frequency: Action(3), Crime(2), Adventure(1), Drama(1), Sci-Fi(1)
- Inferred Tone: Thrilling (Action+Sci-Fi), Dark (Crime themes)
- User Feedback: Previously liked Action, disliked Romance

**Candidate Movie**: "Mad Max: Fury Road"
- Genres: Action, Adventure, Thriller
- Rating: 8.1/10, Vote Count: 1,200
- Popularity: 85
- Keywords: action-packed, post-apocalyptic, intense
- Appears in "similar to Avengers" results

**Score Calculation**:
- Enhanced Genre Matching: Action(3×10) + Adventure(1×10) = 40 points
- User Feedback: Action(+12) = +12 points
- Rating Quality: 8.1(+10) + vote_count_bonus(+2) = +12 points
- Popularity Balance: 85 (+8) = +8 points
- Collaborative Filtering: Similar to Avengers (+10) = +10 points
- Tonal Matching: Thrilling theme match (+5) = +5 points
- **Total Score**: 87 points

## Continuous Learning
- **Feedback Loop**: Each "Love It" / "Not For Me" improves future recommendations
- **Genre Preferences**: Builds user profile of liked/disliked genres over time
- **Conflict Resolution**: Handles cases where user feedback conflicts
- **Memory**: Balances personalization with performance by limiting feedback history

This algorithm balances accuracy, performance, content safety, and personalization to deliver relevant movie recommendations.