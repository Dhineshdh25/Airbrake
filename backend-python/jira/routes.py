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

# ── Legacy shared userIds that must never hold Jira tokens ───────────────────
# These were the old role-based keys used before per-device isolation.
# Any token stored under these keys is visible to ALL users on that role.
_LEGACY_SHARED_USER_IDS = {"dev-admin", "dev-developer", "dev-viewer"}


def _purge_legacy_shared_tokens() -> None:
    """Delete any Jira tokens stored under the old shared role-based userIds.

    Called on every /status request so the cleanup happens automatically
    the first time any user loads Settings after the device_id fix deploys.
    Safe to call repeatedly — deletes nothing if already clean.
    """
    try:
        from db import execute
        for uid in _LEGACY_SHARED_USER_IDS:
            execute(
                "DELETE FROM projects_data "
                "WHERE row_type = 'jira_token' "
                "AND metadata::jsonb->>'user_id' = %s",
                (uid,),
            )
    except Exception as exc:
        logger.warning("[Jira Routes] Legacy token purge failed (non-fatal): %s", exc)

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
    """Return the session dict for the current request, or None.
    
    Checks (in order):
    1. Bearer token in Authorization header
    2. Token as query parameter (for browser redirects that lose headers)
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return _DEV_SESSIONS.get(token)

    # Fallback for browser redirects (no headers preserved)
    query_token = (request.args.get("token") or "").strip()
    if query_token:
        return _DEV_SESSIONS.get(query_token)

    return None


def _require_auth():
    """Return (user_id, None) or (None, error_response).

    user_id is the stable identity used as the Jira token store key.
    It is derived from X-Device-ID when present (stable across logouts),
    otherwise falls back to the role-based userId from the session token.
    """
    session = _get_session()
    if not session:
        return None, (jsonify({"error": "Unauthorized"}), 401)

    # X-Device-ID is a permanent per-browser identifier set by LoginPage.tsx.
    # Using it means the Jira token survives logout/login cycles on the same
    # browser — the user only needs to connect Jira once per device.
    device_id = request.headers.get("X-Device-ID", "").strip()
    if device_id:
        user_id = f"device-{device_id}"
    else:
        user_id = session["userId"]

    return user_id, None


def _frontend_url() -> str:
    return os.environ.get(
        "FRONTEND_URL",
        "https://airbrake.s3-website-us-east-1.amazonaws.com",
    )


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

    # ── One-time cleanup of legacy shared tokens ──────────────────────────────
    # Before device_id was introduced, tokens were stored under shared role-based
    # userIds (dev-admin, dev-developer, dev-viewer). These must be deleted so
    # they stop appearing as connected for everyone on that role.
    # Safe to run on every status call — execute() is a no-op if nothing matches.
    _purge_legacy_shared_tokens()

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

# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/jira/webhook
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/webhook", methods=["POST"])
def jira_webhook():
    """
    POST /api/jira/webhook

    Receives Jira webhook events and triggers the sync pipeline when
    an issue reaches a terminal status (Done / Closed / Resolved).

    This endpoint is intentionally unauthenticated — Jira calls it
    server-to-server, not from a browser. Security is provided by a
    shared secret in the JIRA_WEBHOOK_SECRET env var (optional but
    strongly recommended in production).

    Jira sends webhooks for:
      jira:issue_updated     — field edits, transitions, assignments
      jira:issue_transitioned
      comment_created
      comment_updated
      jira:issue_deleted

    Only terminal-status events trigger solution extraction.
    All others are acknowledged immediately and ignored.

    Response: always 200 so Jira does not retry unnecessarily.
    Errors are logged internally but never surfaced to Jira.
    """
    # ── Optional shared secret validation ────────────────────────────────────
    webhook_secret = os.environ.get("JIRA_WEBHOOK_SECRET", "")
    if webhook_secret:
        provided = request.headers.get("X-Jira-Webhook-Secret", "")
        if provided != webhook_secret:
            logger.warning("[Jira Webhook] Invalid webhook secret — request rejected")
            return jsonify({"error": "Forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    webhook_event = payload.get("webhookEvent", "unknown")

    logger.info(
        "[Jira Webhook] Received event=%s issue=%s",
        webhook_event,
        (payload.get("issue") or {}).get("key", "?"),
    )

    # ── Parse the event ───────────────────────────────────────────────────────
    from .webhook_handler import parse_webhook
    event = parse_webhook(payload)

    if event is None:
        logger.debug("[Jira Webhook] Event ignored: %s", webhook_event)
        return jsonify({"status": "ignored", "event": webhook_event}), 200

    logger.info(
        "[Jira Webhook] Parsed event action=%s issue=%s is_terminal=%s",
        event.get("action"), event.get("issue_key"), event.get("is_terminal"),
    )

    # ── Handle reopen transitions separately ────────────────────────────────
    if event.get("is_reopen"):
        try:
            from .jira_sync import reopen_linked_airbrake_errors
            result = reopen_linked_airbrake_errors(
                event.get("issue_key", ""),
                event.get("status") or event.get("transition_name") or "Reopened",
            )
            logger.info("[Jira Webhook] Reopen result: %s", result)
            return jsonify({
                "status":    "processed",
                "action":    "reopen",
                "issue_key": event.get("issue_key"),
                "reopened":  result.get("reopened", 0),
            }), 200
        except Exception as exc:
            logger.exception("[Jira Webhook] Reopen handler failed: %s", exc)
            return jsonify({"status": "error", "action": "reopen", "issue_key": event.get("issue_key"), "error": str(exc)}), 200

    # ── Only sync when issue reaches a terminal state ─────────────────────────
    if not event.get("is_terminal"):
        return jsonify({
            "status":    "acknowledged",
            "action":    event.get("action"),
            "issue_key": event.get("issue_key"),
            "reason":    "status_not_terminal",
        }), 200

    # ── Run sync pipeline asynchronously (best-effort) ────────────────────────
    # We respond to Jira immediately (within 30s timeout) and run the pipeline
    # synchronously on Lambda. For high-volume environments this should move
    # to an SQS queue, but for Phase 2 synchronous is correct and simpler.
    try:
        from .sync_pipeline import run_sync_pipeline
        result = run_sync_pipeline(event)
        logger.info(
            "[Jira Webhook] Sync pipeline result: %s",
            {k: v for k, v in result.items() if k != "raw"},
        )
        return jsonify({
            "status":      "processed",
            "issue_key":   event.get("issue_key"),
            "success":     result.get("success"),
            "solution_id": result.get("solution_id"),
            "log_ids":     result.get("log_ids", []),
            "detail":      result.get("detail"),
        }), 200

    except Exception as exc:
        import traceback as _tb
        logger.exception("[Jira Webhook] Sync pipeline raised unexpectedly: %s", exc)
        # Always return 200 so Jira does not keep retrying
        return jsonify({
            "status":    "error",
            "issue_key": event.get("issue_key"),
            "error":     str(exc),
        }), 200


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/jira/link
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/link", methods=["POST"])
def jira_link():
    """
    POST /api/jira/link

    Link an Airbrake log row to a Jira issue key.
    Called automatically after POST /api/jira/create succeeds so the
    webhook can later find which log row a Jira ticket belongs to.

    Body: { "log_id": str, "issue_key": str }
    """
    user_id, err = _require_auth()
    if err:
        return err

    body      = request.get_json(silent=True) or {}
    log_id    = (body.get("log_id") or "").strip()
    issue_key = (body.get("issue_key") or "").strip()

    if not log_id or not issue_key:
        return jsonify({"error": "log_id and issue_key are required"}), 400

    try:
        from .jira_sync import mark_log_jira_key
        mark_log_jira_key(log_id, issue_key)
        logger.info(
            "[Jira Routes] Linked log_id=%s to issue_key=%s by user_id=%s",
            log_id, issue_key, user_id,
        )
        return jsonify({"linked": True, "log_id": log_id, "issue_key": issue_key})
    except Exception as exc:
        logger.exception("[Jira Routes] link failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
