"""
Authentication routes — Google OAuth 2.0 / OIDC.

Blueprint registered at /api/auth.

Routes:
  GET  /api/auth/google           — start OAuth flow (redirects to Google)
  GET  /api/auth/google/callback  — OAuth callback (exchanges code, creates session)
  GET  /api/auth/me               — return current authenticated user
  POST /api/auth/logout           — invalidate session, clear cookies
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, make_response, redirect, request

from .google_oauth import (
    build_authorization_url,
    decode_id_token_payload,
    exchange_code_for_tokens,
    generate_state,
    get_user_info,
    validate_id_token_claims,
)
from .middleware import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    generate_csrf_token,
    get_current_user,
)
from .session_store import (
    cleanup_expired_sessions,
    create_session,
    delete_session,
)
from .user_store import find_by_oauth_subject, create_user

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


# ── DB-backed OAuth state (same pattern as jira/routes.py) ────────────────────

_STATE_TTL_SECONDS = 600  # 10 minutes

try:
    from db import execute as _db_execute, query as _db_query
except Exception:
    def _db_execute(*a, **kw):
        raise RuntimeError("DB unavailable for OAuth state")

    def _db_query(*a, **kw):
        raise RuntimeError("DB unavailable for OAuth state")


def _persist_oauth_state(state: str, redirect_uri: str) -> None:
    """Store state in the DB with 10-minute TTL."""
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=_STATE_TTL_SECONDS)
    ).isoformat()
    try:
        _db_execute(
            "INSERT INTO projects_data (id, row_type, metadata, created_at) "
            "VALUES (%s, 'google_oauth_state', %s, NOW())",
            (
                str(uuid.uuid4()),
                json.dumps({"state": state, "redirect_uri": redirect_uri, "expires_at": expires_at}),
            ),
        )
    except Exception as exc:
        logger.warning("[Auth State] DB persist failed: %s", exc)


def _pop_oauth_state(state: str) -> str | None:
    """
    Look up and consume a state token. Returns the redirect_uri or None.
    Deletes the row after successful lookup.
    """
    try:
        rows = _db_query(
            "SELECT id, metadata FROM projects_data "
            "WHERE row_type = 'google_oauth_state' "
            "  AND metadata::jsonb->>'state' = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (state,),
        )
        if not rows:
            return None

        raw = rows[0].get("metadata")
        meta = json.loads(raw) if isinstance(raw, str) else (raw or {})

        # Check TTL
        expires_at = meta.get("expires_at", "")
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) > exp:
                    logger.warning("[Auth State] State token expired")
                    _db_execute(
                        "DELETE FROM projects_data WHERE id = %s", (rows[0]["id"],)
                    )
                    return None
            except (ValueError, TypeError):
                pass

        # Consume (delete)
        _db_execute("DELETE FROM projects_data WHERE id = %s", (rows[0]["id"],))
        return meta.get("redirect_uri", "/")

    except Exception as exc:
        logger.exception("[Auth State] DB lookup failed: %s", exc)
        return None


# ── Cookie helpers ────────────────────────────────────────────────────────────


def _is_production() -> bool:
    env_name = (
        os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or os.getenv("FLASK_ENV") or os.getenv("NODE_ENV") or ""
    ).strip().lower()
    return env_name in {"production", "prod", "staging"}


def _frontend_url() -> str:
    """Frontend base URL — same pattern as jira/routes.py."""
    url = os.environ.get(
        "FRONTEND_URL",
        "http://airbrake.s3-website-us-east-1.amazonaws.com",
    )
    return url.rstrip("/")


def _set_session_cookies(response, session_token: str, csrf_token: str):
    """Set the session and CSRF cookies on the response."""
    is_prod = _is_production()

    # Session cookie — HttpOnly, not accessible to JavaScript
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=is_prod,
        samesite="Lax",
        path="/",
        max_age=24 * 60 * 60,  # 24 hours
    )

    # CSRF cookie — NOT HttpOnly, JavaScript needs to read it
    response.set_cookie(
        CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=is_prod,
        samesite="Lax",
        path="/",
        max_age=24 * 60 * 60,
    )


def _clear_session_cookies(response):
    """Clear session and CSRF cookies."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/auth/google — Start OAuth flow
# ═══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/google")
def google_login():
    """
    Initiate Google OAuth 2.0 login.

    Generates a CSRF state token, persists it in the DB, and redirects
    the user to Google's authorization endpoint.

    Query params:
      redirect_uri (optional) — frontend path to return to after login
    """
    redirect_uri = request.args.get("redirect_uri", "/dashboard")

    try:
        state = generate_state()
        _persist_oauth_state(state, redirect_uri)
        auth_url = build_authorization_url(state)
        logger.info("[Auth] Initiating Google OAuth login")
        return redirect(auth_url)
    except EnvironmentError as exc:
        logger.error("[Auth] Google OAuth config error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/auth/google/callback — OAuth callback
# ═══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/google/callback")
def google_callback():
    """
    Handle the OAuth callback from Google.

    1. Validate state (CSRF protection)
    2. Exchange authorization code for tokens
    3. Decode and validate the ID token
    4. Look up user by oauth_provider + oauth_subject
    5. Reject unknown users (403)
    6. Create server-side session
    7. Set cookies and redirect to frontend
    """
    frontend_url = _frontend_url()

    # Check for error from Google
    error = request.args.get("error")
    if error:
        logger.warning("[Auth Callback] Google returned error: %s", error)
        return redirect(f"{frontend_url}?auth_error={error}")

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not state:
        logger.warning("[Auth Callback] Missing code or state parameter")
        return redirect(f"{frontend_url}?auth_error=missing_params")

    # 1. Validate state
    original_redirect = _pop_oauth_state(state)
    if original_redirect is None:
        logger.warning("[Auth Callback] Invalid or expired state token")
        return redirect(f"{frontend_url}?auth_error=invalid_state")

    # 2. Exchange code for tokens
    try:
        token_response = exchange_code_for_tokens(code)
    except Exception as exc:
        logger.error("[Auth Callback] Token exchange failed: %s", exc)
        return redirect(f"{frontend_url}?auth_error=token_exchange_failed")

    access_token = token_response.get("access_token")
    id_token_raw = token_response.get("id_token")

    if not access_token:
        logger.error("[Auth Callback] No access_token in response")
        return redirect(f"{frontend_url}?auth_error=no_access_token")

    # 3. Decode and validate ID token
    user_info = None
    if id_token_raw:
        try:
            id_token_payload = decode_id_token_payload(id_token_raw)
            if validate_id_token_claims(id_token_payload):
                user_info = {
                    "sub": id_token_payload.get("sub"),
                    "email": id_token_payload.get("email"),
                    "email_verified": id_token_payload.get("email_verified", False),
                }
        except Exception as exc:
            logger.warning("[Auth Callback] ID token decode failed: %s", exc)

    # Fallback to userinfo endpoint if ID token didn't work
    if not user_info or not user_info.get("sub"):
        try:
            user_info = get_user_info(access_token)
        except Exception as exc:
            logger.error("[Auth Callback] UserInfo fetch failed: %s", exc)
            return redirect(f"{frontend_url}?auth_error=userinfo_failed")

    # 4. Extract identity
    provider = "google"
    subject = user_info.get("sub", "")
    email = user_info.get("email", "")
    email_verified = user_info.get("email_verified", False)

    if not subject:
        logger.error("[Auth Callback] No 'sub' claim in user info")
        return redirect(f"{frontend_url}?auth_error=no_subject")

    if not email_verified:
        logger.warning("[Auth Callback] Email not verified for sub=%s", subject)
        return redirect(f"{frontend_url}?auth_error=email_not_verified")

    # 5. Look up user in Aurora DSQL — auto-create if not found
    user = find_by_oauth_subject(provider, subject)

    if not user:
        # Auto-register: create a new user with 'viewer' role
        # (first user ever gets 'admin' role automatically)
        logger.info(
            "[Auth Callback] New user — auto-registering: provider=%s sub=%s email=%s",
            provider, subject, email,
        )
        user = create_user(
            email=email,
            provider=provider,
            subject=subject,
            role="viewer",
        )
        if not user:
            logger.error("[Auth Callback] Auto-registration failed for email=%s", email)
            return redirect(f"{frontend_url}?auth_error=registration_failed")

    # 6. Create server-side session
    try:
        # Clean up expired sessions opportunistically
        cleanup_expired_sessions()
        session_token = create_session(user["id"])
    except Exception as exc:
        logger.error("[Auth Callback] Session creation failed: %s", exc)
        return redirect(f"{frontend_url}?auth_error=session_failed")

    # 7. Set cookies and redirect to frontend
    csrf_token = generate_csrf_token()

    # Build redirect URL — go to frontend root with query params
    # (same pattern as Jira OAuth — S3 static hosting only serves root)
    redirect_target = f"{frontend_url}?auth_success=true&redirect={original_redirect}"

    response = make_response(redirect(redirect_target))
    _set_session_cookies(response, session_token, csrf_token)

    logger.info(
        "[Auth Callback] Login successful: user_id=%s email=%s role=%s",
        user["id"], user["email"], user["role"],
    )
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/auth/me — Current user info
# ═══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/me")
def auth_me():
    """
    Return the currently authenticated user.

    Returns:
      200: { "authenticated": true, "user": { "id", "email", "role" } }
      401: { "authenticated": false, "error": "..." }
    """
    user = get_current_user()
    if not user:
        return jsonify({
            "authenticated": False,
            "error": "Not authenticated",
        }), 401

    return jsonify({
        "authenticated": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
        },
    })


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/auth/logout — End session
# ═══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/logout", methods=["POST"])
def auth_logout():
    """
    Invalidate the current session and clear cookies.

    Returns 200 with a confirmation message.
    """
    # Get the session token from cookie
    session_token = request.cookies.get(SESSION_COOKIE_NAME)

    if session_token:
        try:
            delete_session(session_token)
        except Exception as exc:
            logger.warning("[Auth Logout] Session deletion failed: %s", exc)

    response = make_response(jsonify({"message": "Logged out successfully"}))
    _clear_session_cookies(response)

    logger.info("[Auth] User logged out")
    return response
