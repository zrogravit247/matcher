// Like/dislike store shared by the movie, TV, and book pages.
//
// Guests: feedback is kept in this browser's localStorage only - never sent to
// the database - and replayed with each recommendation request so it still
// shapes results instantly. Signing in uploads it once and hands over to the
// server, which then syncs it across devices.
const FeedbackStore = {
    key(contentType) {
        return `matcher_feedback_${contentType}`;
    },

    all(contentType) {
        try {
            const raw = localStorage.getItem(this.key(contentType));
            return raw ? JSON.parse(raw) : [];
        } catch (error) {
            return [];
        }
    },

    // Records locally first (so the next request reflects it even for guests),
    // then tells the server, which persists it only for signed-in accounts.
    async record(contentType, item, liked) {
        const entry = {
            id: String(item.id),
            liked: liked,
            genre_ids: item.genre_ids || item.categories || [],
            content_type: contentType
        };

        const entries = this.all(contentType).filter(e => e.id !== entry.id);
        entries.push(entry);
        try {
            localStorage.setItem(this.key(contentType), JSON.stringify(entries.slice(-30)));
        } catch (error) {
            // Storage full or blocked (e.g. private mode): the server-side
            // path still works for signed-in users.
        }

        try {
            await fetch('/api/recommendation_feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: entry.id, liked: liked, content_type: contentType })
            });
        } catch (error) {
            console.error('Failed to send feedback:', error);
        }
    },

    // Called once after sign-in: hand local feedback to the account, then stop
    // keeping a local copy since the server now owns it.
    async syncToAccount() {
        const all = ['movie', 'tv', 'book'].flatMap(type => this.all(type));
        if (all.length === 0) return;

        try {
            const response = await fetch('/api/sync_feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ feedback: all })
            });
            if (response.ok) {
                ['movie', 'tv', 'book'].forEach(type => localStorage.removeItem(this.key(type)));
            }
        } catch (error) {
            console.error('Failed to sync feedback:', error);
        }
    }
};
