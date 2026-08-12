"""
Authentication and CSRF middleware.

Provides:
  - require_auth()       — decorator/helper that validates the session cookie
  - get_current_user()   — returns the authenticated user or None
  - csrf_protect()       — Double-Submit Cookie CSRF protection
"""

import functools
import logging
import os
import secrets
from typing import Optional

from flask import g, jsonify, request

from .session_store import get_session
from .user_store import find_by_id

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

SESSION_COOKIE_NAME = "session_token"
CSRF_COOKIE_NAME = "csrf_token"

# Methods that require CSRF validation
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths exempt from CSRF (e.g. ingest endpoints called by external services)
_CSRF_EXEMPT_PREFIXES = (
    "/api/ingest/",
    "/api/auth/google/callback",  # GET redirect from Google
    "/api/jira/webhook",          # Server-to-server from Jira
    "/api/jira/callback",         # GET redirect from Atlassian
)

# Paths that do NOT require authentication
_PUBLIC_PATHS = (
    "/api/health",
    "/api/auth/",
    "/api/ingest/",
    "/api/docs",
    "/api/debug/",
)


def _is_public_path(path: str) -> bool:
    """Return True if the path does not require authentication."""
    for prefix in _PUBLIC_PATHS:
        if path.startswith(prefix):
            return True
    return False


def _is_dev_auth_enabled() -> bool:
    """Return True if DEV_AUTH=1 is explicitly set AND we are NOT in production."""
    env_name = (
        os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or os.getenv("FLASK_ENV") or os.getenv("NODE_ENV") or ""
    ).strip().lower()
    is_production = env_name in {"production", "prod", "staging"}
    dev_auth_flag = os.getenv("DEV_AUTH", "").strip().lower() in ("1", "true", "yes")
    return dev_auth_flag and not is_production


# ── Dev session tokens (only active when DEV_AUTH=1 in non-production) ────────
_DEV_SESSIONS = {
    "dev-token-admin": {"userId": "dev-admin", "role": "admin"},
    "dev-token-developer": {"userId": "dev-developer", "role": "developer"},
    "dev-token-viewer": {"userId": "dev-viewer", "role": "viewer"},
}


def _resolve_dev_session(token: str) -> Optional[dict]:
    """
    If dev auth is enabled, resolve the dev token to a fake user dict.
    Returns None if dev auth is disabled or the token is not recognized.
    """
    if not _is_dev_auth_enabled():
        return None
    session = _DEV_SESSIONS.get(token)
    if not session:
        return None
    return {
        "id": session["userId"],
        "email": f"{session['userId']}@dev.local",
        "role": session["role"],
        "oauth_provider": "dev",
        "oauth_subject": session["userId"],
    }


# ── Session resolution ────────────────────────────────────────────────────────


def _extract_session_token() -> Optional[str]:
    """
    Extract the session token from the request.

    Priority:
    1. session_token cookie (preferred — HttpOnly)
    2. Authorization: Bearer <token> header (for API clients / dev tokens)
    """
    # Cookie first
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token

    # Bearer token fallback
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    return None


def get_current_user() -> Optional[dict]:
    """
    Resolve the current authenticated user from the request.

    Checks g.current_user first (cached from earlier middleware call).
    Returns dict with {id, email, role, oauth_provider, oauth_subject} or None.
    """
    # Already resolved in this request?
    if hasattr(g, "current_user") and g.current_user is not None:
        return g.current_user

    token = _extract_session_token()
    if not token:
        return None

    # Try dev token first (only works if DEV_AUTH=1 and not production)
    dev_user = _resolve_dev_session(token)
    if dev_user:
        g.current_user = dev_user
        return dev_user

    # Real session lookup
    session_data = get_session(token)
    if not session_data:
        return None

    user_id = session_data.get("user_id")
    if not user_id:
        return None

    user = find_by_id(user_id)
    if not user:
        return None

    g.current_user = user
    return user


def require_auth(f=None, *, roles=None):
    """
    Decorator that requires a valid authenticated session.

    Usage:
        @require_auth
        def my_route():
            user = g.current_user
            ...

        @require_auth(roles=["admin"])
        def admin_only():
            ...

    If roles is specified, the user's role must be in the list.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401
            if roles and user.get("role") not in roles:
                return jsonify({"error": "Forbidden", "message": "Insufficient permissions."}), 403
            return func(*args, **kwargs)
        return wrapper

    # Support both @require_auth and @require_auth(roles=[...])
    if f is not None:
        return decorator(f)
    return decorator


# ── CSRF Protection ───────────────────────────────────────────────────────────


def generate_csrf_token() -> str:
    """Generate a random CSRF token."""
    return secrets.token_urlsafe(32)


def csrf_protect():
    """
    Double-Submit Cookie CSRF protection.

    For state-changing methods (POST, PUT, PATCH, DELETE):
    - The request must include an X-CSRF-Token header
    - The header value must match the csrf_token cookie

    Exempt paths and safe methods are skipped.
    """
    # Skip safe methods
    if request.method not in _CSRF_METHODS:
        return None

    # Skip exempt paths
    for prefix in _CSRF_EXEMPT_PREFIXES:
        if request.path.startswith(prefix):
            return None

    # Skip CSRF check for dev tokens when dev auth is enabled
    if _is_dev_auth_enabled():
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:].strip() in _DEV_SESSIONS:
            return None

    # Skip CSRF if path is public (no auth required anyway)
    if _is_public_path(request.path):
        return None

    # Get the CSRF cookie value
    cookie_csrf = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_csrf:
        logger.warning("[CSRF] Missing csrf_token cookie for %s %s", request.method, request.path)
        return jsonify({"error": "Forbidden", "message": "Missing CSRF token."}), 403

    # Get the header value
    header_csrf = request.headers.get("X-CSRF-Token", "").strip()
    if not header_csrf:
        logger.warning("[CSRF] Missing X-CSRF-Token header for %s %s", request.method, request.path)
        return jsonify({"error": "Forbidden", "message": "Missing CSRF token header."}), 403

    # Compare (constant-time)
    if not secrets.compare_digest(cookie_csrf, header_csrf):
        logger.warning("[CSRF] Token mismatch for %s %s", request.method, request.path)
        return jsonify({"error": "Forbidden", "message": "CSRF token mismatch."}), 403

    return None
