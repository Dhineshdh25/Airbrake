"""
Jira OAuth + ticket creation routes.

Registers a Flask blueprint at URL prefix /api/jira.

Routes:
  GET  /api/jira/login      — start OAuth flow (redirects to Atlassian)
  GET  /api/jira/callback   — OAuth callback (exchanges code, saves token)
  GET  /api/jira/status     — check whether the current user is connected
  POST /api/jira/create     — create a Jira ticket from error data
  POST /api/jira/disconnect — remove the current user's stored token

All routes that need an authenticated user require a valid Bearer token in
the Authorization header (same DEV_SESSIONS pattern used by the rest of app.py).
"""

import logging
import os

import requests
from flask import Blueprint, jsonify, redirect, request

from .oauth import (
    build_authorization_url,
    exchange_code_for_tokens,
    fetch_cloud_id,
    fetch_user_profile,
    generate_state,
)
from .ticket_service import create_jira_ticket
from .token_store import delete_token, get_token, save_token

logger = logging.getLogger(__name__)

jira_bp = Blueprint("jira", __name__, url_prefix="/api/jira")

# ── In-process state store — only used for the brief OAuth round-trip ─────────
# Maps user_id → CSRF state token.  Cleared after the callback is handled.
#
# Lambda architecture note:
#   Each Lambda container is single-process. The OAuth round-trip (login →
#   Atlassian → callback) completes within one browser session and typically
#   hits the same warm container because Atlassian redirects back within
#   seconds.  If the callback lands on a *different* warm container (cold
#   start race), the state lookup fails and the user is redirected to
#   ?jira_error=invalid_state — they simply click "Connect Jira" again.
#   This is a one-time inconvenience, not a security issue.  No token is
#   issued on state mismatch.
#
#   Phase 2 hardening (when needed): persist state tokens in projects_data
#   with row_type='jira_oauth_state' + TTL so all containers share them.
_pending_states: dict[str, str] = {}

# ── Helpers (inline — avoids importing from app.py to keep isolation) ─────────
_DEV_SESSIONS = {
    "dev-token-admin":     {"userId": "dev-admin",     "role": "admin"},
    "dev-token-developer": {"userId": "dev-developer", "role": "developer"},
    "dev-token-viewer":    {"userId": "dev-viewer",    "role": "viewer"},
}


def _get_session() -> dict | None:
    """Return the session dict for the current request, or None."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return _DEV_SESSIONS.get(token)
    return None


def _require_auth():
    """Return (user_id, None) or (None, error_response)."""
    session = _get_session()
    if not session:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return session["userId"], None


def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "http://localhost:3000")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/jira/login
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/initiate", methods=["POST"])
def jira_initiate():
    """
    POST /api/jira/initiate

    Authenticated endpoint (Bearer token required).
    Generates a CSRF state token, stores the user_id → state mapping,
    and returns the Atlassian authorization URL for the frontend to
    navigate to.

    The frontend calls this via apiFetch (which attaches the Bearer token),
    then does window.location.href = data.redirect_url.
    No credentials ever appear in a URL.

    Response: { redirect_url: str }
    """
    user_id, err = _require_auth()
    if err:
        return err

    try:
        state = generate_state()
        _pending_states[state] = user_id          # state → user_id
        redirect_url = build_authorization_url(state)
        logger.info("[Jira Routes] OAuth initiate for user_id=%s", user_id)
        return jsonify({"redirect_url": redirect_url})
    except EnvironmentError as exc:
        logger.error("[Jira Routes] initiate config error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@jira_bp.route("/login")
def jira_login():
    """
    GET /api/jira/login  — legacy/direct browser navigation fallback.

    This route exists only so that any bookmark or direct link still works.
    It cannot be authenticated (browser navigation cannot attach headers),
    so it redirects to the frontend Settings page where the user can click
    "Connect Jira" which uses the proper /initiate flow.
    """
    return redirect(f"{_frontend_url()}/settings?jira_connect=1")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/jira/callback
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/callback")
def jira_callback():
    """
    Atlassian redirects here after the user grants/denies consent.

    Exchanges the authorization code for tokens, fetches cloud + profile,
    persists the token, then redirects the browser to the frontend with a
    ?jira_connected=true (or ?jira_error=...) query parameter.
    """
    error = request.args.get("error")
    if error:
        logger.warning("[Jira Routes] OAuth callback error: %s", error)
        return redirect(f"{_frontend_url()}?jira_error={error}")

    code  = request.args.get("code", "")
    state = request.args.get("state", "")

    # ── Validate CSRF state ───────────────────────────────────────────────────
    # Look up which user_id this state belongs to
    matched_user_id = _pending_states.pop(state, None)

    if not matched_user_id:
        logger.warning("[Jira Routes] Invalid or expired OAuth state token")
        return redirect(f"{_frontend_url()}?jira_error=invalid_state")

    try:
        # Exchange code for tokens
        token_data = exchange_code_for_tokens(code)
        access_token  = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in    = token_data.get("expires_in")

        # Resolve Atlassian cloud_id and user profile
        cloud_id = fetch_cloud_id(access_token)
        profile  = fetch_user_profile(access_token, cloud_id)

        atlassian_account_id = profile.get("accountId", "")
        atlassian_email      = profile.get("emailAddress", "")

        # Persist token bound to this Airbrake user
        save_token(
            user_id              = matched_user_id,
            access_token         = access_token,
            refresh_token        = refresh_token,
            expires_in           = expires_in,
            cloud_id             = cloud_id,
            atlassian_account_id = atlassian_account_id,
            atlassian_email      = atlassian_email,
        )

        logger.info(
            "[Jira Routes] OAuth callback success user_id=%s email=%s",
            matched_user_id, atlassian_email,
        )
        return redirect(f"{_frontend_url()}?jira_connected=true")

    except requests.HTTPError as exc:
        logger.error("[Jira Routes] Token exchange HTTP error: %s", exc)
        return redirect(f"{_frontend_url()}?jira_error=token_exchange_failed")
    except Exception as exc:
        logger.exception("[Jira Routes] Unexpected callback error: %s", exc)
        return redirect(f"{_frontend_url()}?jira_error=unexpected")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/jira/status
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/status")
def jira_status():
    """
    Return whether the current user has a connected Jira account.

    Response: { connected: bool, email: str, account_id: str }
    Never returns token values.
    """
    user_id, err = _require_auth()
    if err:
        return err

    token = get_token(user_id)
    if token:
        return jsonify({
            "connected":  True,
            "email":      token.get("atlassian_email", ""),
            "account_id": token.get("atlassian_account_id", ""),
        })
    return jsonify({"connected": False, "email": "", "account_id": ""})


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/jira/create
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/create", methods=["POST"])
def jira_create():
    """
    Create a Jira ticket using the current user's OAuth token.

    Body (all optional except error_message):
      {
        "project_name":      str,
        "error_group":       str,
        "error_message":     str,   ← required
        "error_detail":      str,
        "error_hash":        str,
        "occurrence_count":  int,
        "status":            str,
        "solution":          str,
        "ai_recommendation": str,
        "timestamp":         str,
        "file_name":         str,
        "jira_project_key":  str    ← overrides JIRA_PROJECT_KEY env var
      }

    Response (success):  { success: true, key: str, id: str, url: str }
    Response (error):    { error: str }  + appropriate HTTP status
    """
    user_id, err = _require_auth()
    if err:
        return err

    body = request.get_json(silent=True) or {}

    if not body.get("error_message"):
        return jsonify({"error": "error_message is required"}), 400

    logger.info(
        "[Jira Routes] create ticket requested by user_id=%s error=%s",
        user_id,
        (body.get("error_message") or "")[:80],
    )

    try:
        result = create_jira_ticket(user_id=user_id, error_data=body)
        return jsonify({"success": True, **result})

    except RuntimeError as exc:
        # No token / expired and refresh failed
        return jsonify({"error": str(exc), "needs_auth": True}), 401

    except ValueError as exc:
        # Missing project key etc.
        return jsonify({"error": str(exc)}), 400

    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        detail      = exc.response.text[:500] if exc.response is not None else str(exc)
        # Parse Jira's error format: {"errorMessages":[], "errors":{"project":"..."}}
        user_message = "Jira API returned an error"
        try:
            import json as _json
            jira_err = _json.loads(exc.response.text) if exc.response else {}
            msgs = jira_err.get("errorMessages", [])
            errs = jira_err.get("errors", {})
            if msgs:
                user_message = msgs[0]
            elif errs:
                user_message = "; ".join(f"{k}: {v}" for k, v in errs.items())
        except Exception:
            pass
        logger.error(
            "[Jira Routes] Jira API error status=%s detail=%s",
            status_code, detail,
        )
        return jsonify({
            "error":        user_message,
            "status":       status_code,
            "detail":       detail,
            "needs_auth":   status_code == 401,
        }), status_code if status_code in (400, 401, 403) else 502

    except Exception as exc:
        import traceback
        logger.exception("[Jira Routes] Unexpected create error: %s", exc)
        return jsonify({
            "error":     "Unexpected error creating Jira ticket",
            "exception": type(exc).__name__,
            "message":   str(exc),
        }), 500


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/jira/disconnect
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/disconnect", methods=["POST"])
def jira_disconnect():
    """Remove the current user's Jira OAuth token (disconnect)."""
    user_id, err = _require_auth()
    if err:
        return err

    delete_token(user_id)
    logger.info("[Jira Routes] User disconnected Jira user_id=%s", user_id)
    return jsonify({"disconnected": True})
