"""
Authentication package — Google OAuth 2.0 / OIDC login.

Registers the auth_bp Flask blueprint at /api/auth.
Provides middleware for session-based authentication and CSRF protection.
"""
from .routes import auth_bp  # noqa: F401 — re-exported for app.py
from .middleware import require_auth, get_current_user, csrf_protect  # noqa: F401
