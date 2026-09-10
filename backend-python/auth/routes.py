"""
Authentication routes — local username + password login.

Blueprint registered at /api/auth.

Routes:
  POST /api/auth/login  — authenticate with username + password (users.json)
  GET  /api/auth/me     — return current authenticated user + csrf_token in body
  GET  /api/auth/csrf   — issue / refresh the CSRF token (authenticated)
  POST /api/auth/logout — invalidate session, clear cookies
"""

import logging
import os

from flask import Blueprint, jsonify, make_response, request

from .local_auth import authenticate_user
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

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_production() -> bool:
    env_name = (
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("FLASK_ENV")
        or os.getenv("NODE_ENV")
        or ""
    ).strip().lower()
    return env_name in {"production", "prod", "staging"}


def _set_session_cookies(response, session_token: str, csrf_token: str):
    """Set the session and CSRF cookies on the response."""
    is_prod = _is_production()
    samesite_value = "None" if is_prod else "Lax"
    secure_value = is_prod

    # Session cookie — HttpOnly, not readable by JavaScript
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=secure_value,
        samesite=samesite_value,
        path="/",
        max_age=24 * 60 * 60,  # 24 hours
    )

    # CSRF cookie — NOT HttpOnly; JavaScript must read it for cross-domain use
    response.set_cookie(
        CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=secure_value,
        samesite=samesite_value,
        path="/",
        max_age=24 * 60 * 60,
    )


def _clear_session_cookies(response):
    """Expire session and CSRF cookies."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/auth/login — Username + password login
# ═══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/login", methods=["POST"])
def auth_login():
    """
    Authenticate with username and password against users.json.

    Request body (JSON):
      { "username": "admin", "password": "..." }

    Successful response (200):
      {
        "authenticated": true,
        "user": { "id": "USR001", "username": "admin", "role": "admin" },
        "session_token": "<token>",
        "csrf_token": "<token>"
      }

    Failure response (401):
      { "authenticated": false, "error": "invalid_credentials",
        "message": "Invalid username or password." }

    Security:
      - role is read exclusively from users.json; it is NOT accepted from the client
      - password is never logged
      - identical error for unknown user vs wrong password (no enumeration)
    """
    body = request.get_json(silent=True) or {}

    username = body.get("username", "")
    password = body.get("password", "")

    if not username or not password:
        return jsonify({
            "authenticated": False,
            "error": "invalid_credentials",
            "message": "Invalid username or password.",
        }), 401

    # Verify credentials — role comes from users.json, never from the request
    user = authenticate_user(username, password)

    if not user:
        return jsonify({
            "authenticated": False,
            "error": "invalid_credentials",
            "message": "Invalid username or password.",
        }), 401

    # Create server-side session
    try:
        cleanup_expired_sessions()
        session_token = create_session(user["id"])
    except Exception as exc:
        logger.error("[Auth Login] Session creation failed: %s", exc)
        return jsonify({
            "authenticated": False,
            "error": "session_error",
            "message": "Login failed. Please try again.",
        }), 500

    csrf_token = generate_csrf_token()

    logger.info(
        "[Auth Login] Login successful: id=%s username=%s role=%s",
        user["id"],
        user["username"],
        user["role"],
    )

    response_data = {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
        },
        "session_token": session_token,
        "csrf_token": csrf_token,
    }

    response = make_response(jsonify(response_data), 200)
    _set_session_cookies(response, session_token, csrf_token)
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/auth/me — Current user info
# ═══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/me")
def auth_me():
    """
    Return the currently authenticated user.

    In cross-domain deployments the frontend JavaScript cannot read the
    csrf_token cookie (different domain). We therefore also return the
    CSRF token in the JSON body so the React app can store it in memory
    and send it as X-CSRF-Token on every state-changing request.

    Returns:
      200: { "authenticated": true,
             "user": { "id", "username", "role" },
             "csrf_token": "<token>" }
      401: { "authenticated": false, "error": "..." }
    """
    user = get_current_user()
    if not user:
        return jsonify({
            "authenticated": False,
            "error": "Not authenticated",
        }), 401

    # Surface CSRF token in response body for cross-domain frontends.
    csrf_from_cookie = request.cookies.get(CSRF_COOKIE_NAME, "")

    # Build the user object — username falls back to id for sessions created
    # before the username field was added (e.g. dev tokens).
    user_obj = {
        "id": user["id"],
        "username": user.get("username") or user.get("email") or user["id"],
        "role": user["role"],
    }

    response_data = {
        "authenticated": True,
        "user": user_obj,
        "csrf_token": csrf_from_cookie or "",
    }

    if not csrf_from_cookie:
        # Mint a fresh CSRF token and set it as a cookie on this response.
        new_csrf = generate_csrf_token()
        response_data["csrf_token"] = new_csrf
        resp = make_response(jsonify(response_data))

        is_prod = _is_production()
        resp.set_cookie(
            CSRF_COOKIE_NAME,
            value=new_csrf,
            httponly=False,
            secure=is_prod,
            samesite="None" if is_prod else "Lax",
            path="/",
            max_age=24 * 60 * 60,
        )
        return resp

    return jsonify(response_data)


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/auth/csrf — Issue / refresh CSRF token
# ═══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/csrf")
def auth_csrf():
    """
    Return a fresh CSRF token for authenticated cross-domain callers.

    Called by the React frontend after a page refresh when the in-memory
    CSRF token has been lost.

    Requires:   valid session_token cookie (or Bearer header in dev)
    Returns:    200 { "csrf_token": "<token>" }
                401 if no valid session
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401

    existing = request.cookies.get(CSRF_COOKIE_NAME, "")
    csrf_token = existing if existing else generate_csrf_token()

    resp = make_response(jsonify({"csrf_token": csrf_token}))

    if not existing:
        is_prod = _is_production()
        resp.set_cookie(
            CSRF_COOKIE_NAME,
            value=csrf_token,
            httponly=False,
            secure=is_prod,
            samesite="None" if is_prod else "Lax",
            path="/",
            max_age=24 * 60 * 60,
        )

    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/auth/logout — End session
# ═══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/logout", methods=["POST"])
def auth_logout():
    """
    Invalidate the current session and clear cookies.

    Returns 200 with a confirmation message.
    """
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
