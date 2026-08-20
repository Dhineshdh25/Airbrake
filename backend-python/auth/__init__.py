"""
Authentication package — Google OAuth 2.0 / OIDC login.

Registers the auth_bp Flask blueprint at /api/auth.
Provides middleware for session-based authentication, CSRF protection,
and project ownership enforcement.
"""
from .routes import auth_bp  # noqa: F401 — re-exported for app.py
from .middleware import (  # noqa: F401
    require_auth,
    require_permission,
    get_current_user,
    csrf_protect,
    has_permission,
    VALID_ROLES,
    ROLE_PERMISSIONS,
    get_accessible_project,
    get_accessible_project_by_name,
    require_project_access,
    get_accessible_log,
)
