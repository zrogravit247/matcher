// Shared Google Sign-In widget. Renders into #authArea on every page:
// a "Sign in with Google" button for guests, or the account chip with a
// sign-out action once signed in. Sign-in is skipped entirely if the
// server has no GOOGLE_CLIENT_ID configured.
class AuthWidget {
    constructor() {
        this.container = document.getElementById('authArea');
        if (this.container) {
            this.init();
        }
    }

    async init() {
        try {
            const response = await fetch('/api/me');
            if (!response.ok) return;
            this.me = await response.json();

            if (this.me.signed_in) {
                this.renderUserChip();
            } else if (this.me.google_client_id) {
                this.renderSignInButton();
            }
        } catch (error) {
            console.error('Auth widget failed to load:', error);
        }
    }

    renderSignInButton() {
        const buttonHost = document.createElement('div');
        this.container.appendChild(buttonHost);

        const script = document.createElement('script');
        script.src = 'https://accounts.google.com/gsi/client';
        script.async = true;
        script.onload = () => {
            google.accounts.id.initialize({
                client_id: this.me.google_client_id,
                callback: (response) => this.handleCredential(response)
            });
            google.accounts.id.renderButton(buttonHost, {
                theme: 'filled_black',
                size: 'medium',
                shape: 'pill',
                text: 'signin_with'
            });
        };
        document.head.appendChild(script);
    }

    async handleCredential(response) {
        try {
            const result = await fetch('/auth/google', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credential: response.credential })
            });
            if (result.ok) {
                // Hand any guest feedback to the account before reloading, so
                // signing in doesn't discard the taste profile built as a guest.
                if (window.FeedbackStore) {
                    await FeedbackStore.syncToAccount();
                }
                window.location.reload();
            } else {
                const data = await result.json();
                console.error('Sign-in failed:', data.error);
            }
        } catch (error) {
            console.error('Sign-in failed:', error);
        }
    }

    renderUserChip() {
        const chip = document.createElement('div');
        chip.className = 'd-flex align-items-center gap-2 justify-content-center';

        const avatar = this.me.avatar_url
            ? `<img src="${this.me.avatar_url}" alt="" referrerpolicy="no-referrer" style="width: 28px; height: 28px; border-radius: 50%;">`
            : '<i class="fas fa-user-circle" style="font-size: 24px;"></i>';

        chip.innerHTML = `
            ${avatar}
            <span class="small">${this.me.name || this.me.email || 'Signed in'}</span>
            <button type="button" class="btn btn-outline-secondary btn-sm" id="signOutBtn">Sign out</button>
        `;
        this.container.appendChild(chip);

        chip.querySelector('#signOutBtn').addEventListener('click', async () => {
            await fetch('/auth/logout', { method: 'POST' });
            window.location.reload();
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new AuthWidget();
});
