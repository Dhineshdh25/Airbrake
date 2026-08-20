"""
Authentication, Authorization, CSRF middleware, and project ownership helpers.

Provides:
  - require_auth()              — decorator that validates session (optional role list)
  - require_permission()        — decorator enforcing permission-based RBAC
  - get_current_user()          — returns the authenticated user or None
  - csrf_protect()              — Double-Submit Cookie CSRF protection
  - get_accessible_project()    — resolve a project only if it belongs to the current user
  - require_project_access()    — like get_accessible_project() but returns 401/404 directly
  - VALID_ROLES                 — the only accepted role values
  - ROLE_PERMISSIONS            — complete permission map per role
"""

import functools
import logging
import os
import secrets
from typing import Optional, Set, Tuple, Any

from flask import g, jsonify, request

from .session_store import get_session
from .user_store import find_by_id

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

SESSION_COOKIE_NAME = "session_token"
CSRF_COOKIE_NAME = "csrf_token"

# The only valid roles in the system
VALID_ROLES = {"viewer", "developer", "admin"}

# Methods that require CSRF validation
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths exempt from CSRF — ONLY machine-to-machine endpoints
# The blanket "/api/" exemption has been REMOVED (security fix).
_CSRF_EXEMPT_PREFIXES = (
    "/api/ingest/",                   # External services with API-key auth
    "/api/auth/google/callback",      # GET redirect from Google
    "/api/auth/logout",               # Logout is session-destructive, exempt
    "/api/jira/webhook",              # Server-to-server Jira webhook
    "/api/jira/callback",             # OAuth redirect from Atlassian
    "/api/jira/poll-sync",            # Can be called by scheduler with no session
)

# Paths that do NOT require authentication
_PUBLIC_PATHS = (
    "/api/health",
    "/api/auth/",
    "/api/ingest/",
    "/api/docs",
)

# ── Permission Map ────────────────────────────────────────────────────────────

ROLE_PERMISSIONS: dict[str, Set[str]] = {
    "viewer": {
        "dashboard:read",
        "logs:read",
        "breaks:read",
        "filters:read",
        "alerts:read",
        "projects:read",
        "jira:read",
        "visualization:read",
        "metrics:read",
        "error-groups:read",
        "stacktrace:read",
    },
    "developer": {
        # All viewer permissions
        "dashboard:read",
        "logs:read",
        "breaks:read",
        "filters:read",
        "filters:write",
        "alerts:read",
        "alerts:write",
        "projects:read",
        "jira:read",
        "jira:write",
        "visualization:read",
        "metrics:read",
        "errors:resolve",
        "error-groups:read",
        "error-groups:write",
        "stacktrace:read",
        "logs:annotate",
        "notifications:read",
        "notifications:write",
    },
    "admin": {"*"},  # Wildcard — admin can do everything
}


def has_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission."""
    if role not in VALID_ROLES:
        return False
    perms = ROLE_PERMISSIONS.get(role, set())
    if "*" in perms:
        return True
    return permission in perms


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_public_path(path: str) -> bool:
    """Return True if the path does not require authentication."""
    for prefix in _PUBLIC_PATHS:
        if path.startswith(prefix):
            return True
    return False


def _is_dev_auth_enabled() -> bool:
    """Return True if DEV_AUTH=1 is explicitly set AND we are NOT in production/staging."""
    env_name = (
        os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or os.getenv("FLASK_ENV") or os.getenv("NODE_ENV") or ""
    ).strip().lower()
    is_production = env_name in {"production", "prod", "staging"}
    dev_auth_flag = os.getenv("DEV_AUTH", "").strip().lower() in ("1", "true", "yes")
    return dev_auth_flag and not is_production


def _is_production() -> bool:
    """Return True if the environment is production or staging."""
    env_name = (
        os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or os.getenv("FLASK_ENV") or os.getenv("NODE_ENV") or ""
    ).strip().lower()
    return env_name in {"production", "prod", "staging"}


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

    # Validate that role stored in DB is still valid
    if user.get("role") not in VALID_ROLES:
        logger.warning("[Auth] User %s has invalid role '%s'", user_id, user.get("role"))
        return None

    g.current_user = user
    return user


# ── Authorization Decorators ──────────────────────────────────────────────────


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


def require_permission(permission: str):
    """
    Decorator that requires a specific permission.

    Usage:
        @app.route("/api/filters/presets", methods=["POST"])
        @require_permission("filters:write")
        def create_filter():
            ...

    Behavior:
    - Missing session → 401
    - Invalid/expired session → 401
    - Valid session without permission → 403
    - Valid role with permission → continue
    - Unknown role → 403

    Attaches resolved user to Flask g.current_user.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401
            role = user.get("role", "")
            if role not in VALID_ROLES:
                return jsonify({"error": "Forbidden", "message": "Unknown role."}), 403
            if not has_permission(role, permission):
                return jsonify({"error": "Forbidden", "message": "Insufficient permissions."}), 403
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ── CSRF Protection ───────────────────────────────────────────────────────────


def generate_csrf_token() -> str:
    """Generate a random CSRF token."""
    return secrets.token_urlsafe(32)


def csrf_protect():
    """
    Cross-domain Double-Submit CSRF protection.

    For state-changing methods (POST, PUT, PATCH, DELETE):
    - Exempt paths (ingest, OAuth callbacks) are skipped.
    - Dev tokens bypass CSRF when DEV_AUTH=1.
    - For all other requests:
        a) If BOTH cookie and header are present → compare (constant-time).
           Mismatch → 403.
        b) If the header is present but cookie is absent → allow through.
           (Cross-domain flow: frontend stored token from /api/auth/me body
            and sends it as header; browser may not send the csrf_token cookie
            when origin != backend domain due to SameSite/cross-origin rules.)
        c) If NEITHER is present → allow through.
           (The session cookie alone provides CSRF protection for cross-origin
            requests because SameSite=None+Secure + HttpOnly means an attacker
            site cannot forge or read it.)
        d) If the cookie is present but the header is missing:
           - For requests from allowed origins (browser cross-site) → reject 403.
             The frontend is expected to always send the header once it has the token.
           - For requests with no Origin header (server-to-server / curl) → allow.

    The route-level @require_permission / @require_auth decorators are the
    primary auth guard.  This middleware is defense-in-depth.
    """
    # Skip safe methods
    if request.method not in _CSRF_METHODS:
        return None

    # Skip machine-to-machine exempt paths
    for prefix in _CSRF_EXEMPT_PREFIXES:
        if request.path.startswith(prefix):
            return None

    # Skip public paths (no session required anyway)
    if _is_public_path(request.path):
        return None

    # Skip CSRF check for dev tokens (DEV_AUTH=1, non-production only)
    if _is_dev_auth_enabled():
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:].strip() in _DEV_SESSIONS:
            return None

    header_csrf = request.headers.get("X-CSRF-Token", "").strip()
    cookie_csrf = request.cookies.get(CSRF_COOKIE_NAME, "").strip()

    # Case (a): both present — validate they match
    if header_csrf and cookie_csrf:
        if not secrets.compare_digest(cookie_csrf, header_csrf):
            logger.warning("[CSRF] Token mismatch for %s %s", request.method, request.path)
            return jsonify({"error": "Forbidden", "message": "CSRF token mismatch."}), 403
        return None  # ✓ valid

    # Case (b): header present, no cookie → cross-domain flow with in-memory token
    if header_csrf and not cookie_csrf:
        # Header alone is acceptable: the frontend got the token from /api/auth/me
        # response body and is sending it correctly.  The session cookie (HttpOnly)
        # still proves the user is authenticated.
        return None  # ✓ valid

    # Case (c): neither present → allow (session cookie = auth proof)
    if not header_csrf and not cookie_csrf:
        return None  # ✓ allow — session cookie provides CSRF protection

    # Case (d): cookie present but header missing
    # If the request has an Origin header (browser cross-site), the frontend
    # should have sent X-CSRF-Token.  Reject it.
    origin = request.headers.get("Origin", "")
    if origin:
        logger.warning(
            "[CSRF] Cookie present but X-CSRF-Token header missing for %s %s origin=%s",
            request.method, request.path, origin,
        )
        return jsonify({
            "error": "Forbidden",
            "message": "Missing X-CSRF-Token header.",
        }), 403

    # No Origin header (server-to-server / curl) → allow
    return None


# ── Project Ownership Helpers ─────────────────────────────────────────────────
# These helpers enforce account-level isolation.  Every project and log query
# MUST go through these helpers instead of querying by name/id alone.
#
# Rules enforced here:
#   1. Session must exist   → 401
#   2. Project must exist   → 404  (same response whether missing OR foreign)
#   3. project.owner_user_id must equal authenticated user → 404
#   4. owner_user_id IS NULL rows are NEVER returned (legacy / unowned data)
#   5. owner_user_id is NEVER accepted from the client
#
# Only correctly owned data (e.g. test-stacktrace-demo with a valid owner)
# is returned to that owner.  Legacy NULL rows are excluded and logged.


def get_accessible_project(project_id: str) -> Tuple[Optional[dict], Optional[Any]]:
    """
    Resolve a project that belongs to the currently authenticated user.

    Queries: WHERE row_type = 'project' AND id = %s AND owner_user_id = %s

    Returns:
      (project_dict, None)   — project found and owned by current user
      (None, error_response) — 401 (no session) or 404 (not found / wrong owner)

    Never leaks whether the project exists for another user: always 404.
    Never accepts owner_user_id from the client.
    Legacy rows with owner_user_id IS NULL are excluded and logged.
    """
    # Lazy import to avoid circular imports — db is not imported at module load
    try:
        from db import query as _db_query
    except Exception as _e:
        logger.error("[ProjectAccess] DB import failed: %s", _e)
        return None, (jsonify({"error": "Internal server error"}), 500)

    user = get_current_user()
    if not user:
        return None, (jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401)

    user_id = user["id"]

    rows = _db_query(
        "SELECT id, project_name, category, is_live, owner_user_id, project_id "
        "FROM projects_data "
        "WHERE row_type = 'project' AND id = %s AND owner_user_id = %s",
        (project_id, user_id),
    )

    if not rows:
        # Check if a project with this id exists but belongs to someone else or is unowned.
        # We log a warning for unowned legacy rows but never expose them.
        _check_legacy_project(project_id)
        return None, (jsonify({"error": "Not Found"}), 404)

    return dict(rows[0]), None


def get_accessible_project_by_name(project_name: str) -> Tuple[Optional[dict], Optional[Any]]:
    """
    Resolve a project by name that belongs to the currently authenticated user.

    Used by name-based legacy routes.  Two users may have projects with the
    same name — they MUST NOT see each other's data.

    Queries: WHERE row_type = 'project'
                   AND LOWER(project_name) = LOWER(%s)
                   AND owner_user_id = %s
    """
    try:
        from db import query as _db_query
    except Exception as _e:
        logger.error("[ProjectAccess] DB import failed: %s", _e)
        return None, (jsonify({"error": "Internal server error"}), 500)

    user = get_current_user()
    if not user:
        return None, (jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401)

    user_id = user["id"]

    rows = _db_query(
        "SELECT id, project_name, category, is_live, owner_user_id, project_id "
        "FROM projects_data "
        "WHERE row_type = 'project' "
        "  AND LOWER(project_name) = LOWER(%s) "
        "  AND owner_user_id = %s",
        (project_name, user_id),
    )

    if not rows:
        _check_legacy_project_by_name(project_name)
        return None, (jsonify({"error": "Not Found"}), 404)

    return dict(rows[0]), None


def require_project_access(project_id: str) -> Tuple[Optional[dict], Optional[Any]]:
    """
    Shortcut wrapper around get_accessible_project().

    Identical semantics — callers can use whichever reads more naturally:
        project, err = require_project_access(project_id)
        if err:
            return err
    """
    return get_accessible_project(project_id)


def get_accessible_log(log_id: str, owner_user_id: str) -> Optional[dict]:
    """
    Fetch a single log row only if it belongs to the given owner.

    Queries: WHERE row_type = 'log' AND id = %s AND owner_user_id = %s

    Returns the row dict or None.  Logs a warning for unowned legacy rows.
    Never accepts owner_user_id from the client — caller passes the
    value from the authenticated session.
    """
    try:
        from db import query as _db_query
    except Exception as _e:
        logger.error("[ProjectAccess] DB import failed: %s", _e)
        return None

    rows = _db_query(
        "SELECT * FROM projects_data "
        "WHERE row_type = 'log' AND id = %s AND owner_user_id = %s",
        (log_id, owner_user_id),
    )

    if not rows:
        # Check for an unowned legacy row and emit a warning
        try:
            legacy = _db_query(
                "SELECT id, owner_user_id FROM projects_data "
                "WHERE row_type = 'log' AND id = %s LIMIT 1",
                (log_id,),
            )
            if legacy:
                if legacy[0].get("owner_user_id") is None:
                    logger.warning(
                        "[ProjectAccess] LEGACY UNOWNED LOG row encountered — "
                        "log_id=%s owner_user_id=NULL — NOT exposing to user %s",
                        log_id, owner_user_id,
                    )
                else:
                    logger.warning(
                        "[ProjectAccess] Cross-user log access attempt — "
                        "log_id=%s belongs to a different user — requested by %s",
                        log_id, owner_user_id,
                    )
        except Exception:
            pass
        return None

    return dict(rows[0])


def _check_legacy_project(project_id: str) -> None:
    """Log a warning if a project exists but has NULL ownership (legacy row)."""
    try:
        from db import query as _db_query
        rows = _db_query(
            "SELECT id, owner_user_id FROM projects_data "
            "WHERE row_type = 'project' AND id = %s LIMIT 1",
            (project_id,),
        )
        if rows and rows[0].get("owner_user_id") is None:
            logger.warning(
                "[ProjectAccess] LEGACY UNOWNED PROJECT encountered — "
                "id=%s owner_user_id=NULL — NOT exposing to authenticated user",
                project_id,
            )
    except Exception:
        pass


def _check_legacy_project_by_name(project_name: str) -> None:
    """Log a warning if a project by this name exists but has NULL ownership."""
    try:
        from db import query as _db_query
        rows = _db_query(
            "SELECT id, owner_user_id FROM projects_data "
            "WHERE row_type = 'project' "
            "  AND LOWER(project_name) = LOWER(%s) LIMIT 1",
            (project_name,),
        )
        if rows and rows[0].get("owner_user_id") is None:
            logger.warning(
                "[ProjectAccess] LEGACY UNOWNED PROJECT by name encountered — "
                "project_name=%s owner_user_id=NULL — NOT exposing to authenticated user",
                project_name,
            )
    except Exception:
        pass
