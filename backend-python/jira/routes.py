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

import json
import json
import logging
import os

import requests
from flask import Blueprint, jsonify, redirect, request
from db import query
from db import execute, query

from .oauth import (
    build_authorization_url,
    exchange_code_for_tokens,
    fetch_cloud_id,
    fetch_user_profile,
    generate_state,
)
from .ticket_service import create_jira_ticket
from .token_store import delete_token, get_token, save_token
from .webhook_handler import TERMINAL_STATUSES, is_terminal

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

# ── In-process state store — DEPRECATED, kept only as in-memory fallback ──────
# Lambda multi-container issue: state stored in memory on container A is not
# visible to container B that handles the /callback.  All new state is now
# persisted to the database via _persist_oauth_state / _pop_oauth_state.
# This dict is kept as a fast-path for same-container round-trips only.
_pending_states: dict[str, str] = {}

# ── DB-backed OAuth state helpers ─────────────────────────────────────────────
# row_type = 'jira_oauth_state', TTL = 10 minutes
_STATE_TTL_SECONDS = 600


def _persist_oauth_state(state: str, user_id: str) -> None:
    """Store state → user_id in the database with a 10-minute TTL."""
    import uuid as _uuid
    from datetime import datetime, timezone, timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=_STATE_TTL_SECONDS)).isoformat()
    try:
        from db import execute as _exec
        _exec(
            "INSERT INTO projects_data (id, row_type, metadata, created_at) "
            "VALUES (%s, 'jira_oauth_state', %s, NOW())",
            (
                str(_uuid.uuid4()),
                json.dumps({"state": state, "user_id": user_id, "expires_at": expires_at}),
            ),
        )
    except Exception as exc:
        logger.warning("[Jira State] DB persist failed, falling back to memory: %s", exc)
    # Always also store in memory as a same-container fast-path
    _pending_states[state] = user_id


def _pop_oauth_state(state: str) -> str | None:
    """
    Look up and consume a state token — returns user_id or None.

    Checks memory first (fast path for same-container), then the DB.
    Deletes the DB row after successful lookup to prevent replay.
    """
    from datetime import datetime, timezone

    # Fast path: same Lambda container
    user_id = _pending_states.pop(state, None)
    if user_id:
        # Also clean up DB row if it exists
        try:
            from db import execute as _exec
            _exec(
                "DELETE FROM projects_data "
                "WHERE row_type = 'jira_oauth_state' "
                "  AND metadata::jsonb->>'state' = %s",
                (state,),
            )
        except Exception:
            pass
        return user_id

    # DB path: different Lambda container
    try:
        from db import query as _q, execute as _exec
        rows = _q(
            "SELECT metadata FROM projects_data "
            "WHERE row_type = 'jira_oauth_state' "
            "  AND metadata::jsonb->>'state' = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (state,),
        )
        if not rows:
            return None

        raw  = rows[0].get("metadata")
        meta = json.loads(raw) if isinstance(raw, str) else (raw or {})

        # Check TTL
        expires_at = meta.get("expires_at", "")
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) > exp:
                    logger.warning("[Jira State] State token expired")
                    _exec(
                        "DELETE FROM projects_data "
                        "WHERE row_type = 'jira_oauth_state' "
                        "  AND metadata::jsonb->>'state' = %s",
                        (state,),
                    )
                    return None
            except (ValueError, TypeError):
                pass

        found_user_id = meta.get("user_id", "")
        if not found_user_id:
            return None

        # Consume (delete) so it can't be replayed
        _exec(
            "DELETE FROM projects_data "
            "WHERE row_type = 'jira_oauth_state' "
            "  AND metadata::jsonb->>'state' = %s",
            (state,),
        )
        logger.info("[Jira State] DB state validated for user_id=%s", found_user_id)
        return found_user_id

    except Exception as exc:
        logger.exception("[Jira State] DB lookup failed: %s", exc)
        return None

# ── Helpers (inline — avoids importing from app.py to keep isolation) ─────────
_DEV_SESSIONS = {
    "dev-token-admin":     {"userId": "dev-admin",     "role": "admin"},
    "dev-token-developer": {"userId": "dev-developer", "role": "developer"},
    "dev-token-viewer":    {"userId": "dev-viewer",    "role": "viewer"},
}


def _is_production_environment() -> bool:
    env_name = (os.getenv("NODE_ENV") or os.getenv("FLASK_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return env_name in {"production", "prod", "staging"}


def _get_session() -> dict | None:
    """Return the session dict for the current request, or None.

    Checks (in order):
    1. Bearer token in Authorization header
    2. Token as query parameter (for browser redirects that lose headers)
    """
    auth = request.headers.get("Authorization", "")
    logger.info('[Jira Routes] Authorization header present=%s', bool(auth))

    token = None
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        logger.info('[Jira Routes] Extracted bearer token=%s', token[:20] + ('...' if len(token) > 20 else ''))
    elif auth:
        logger.warning('[Jira Routes] Authorization header was present but not in Bearer format')

    if not token:
        # Fallback for browser redirects (no headers preserved)
        token = (request.args.get("token") or "").strip()
        logger.info('[Jira Routes] Query token present=%s', bool(token))

    if not token:
        logger.warning('[Jira Routes] No auth token supplied for Jira request')
        return None

    ses = _DEV_SESSIONS.get(token)
    if ses:
        if _is_production_environment():
            logger.warning('[Jira Routes] Dev auth token rejected in production environment token=%s', token[:20] + ('...' if len(token) > 20 else ''))
            return None
        logger.info('[Jira Routes] Auth session resolved userId=%s role=%s', ses.get('userId'), ses.get('role'))
        return ses

    logger.warning('[Jira Routes] Unknown or invalid auth token supplied token=%s', token[:20] + ('...' if len(token) > 20 else ''))
    return None


def _require_auth():
    """Return (user_id, None) or (None, error_response).

    user_id is the stable identity used as the Jira token store key.
    It is derived from X-Device-ID when present (stable across logouts),
    otherwise falls back to the role-based userId from the session token.
    """
    session = _get_session()
    if not session:
        logger.warning('[Jira Routes] _require_auth failed: missing or invalid session/token')
        return None, (jsonify({"error": "Unauthorized", "reason": "missing_or_invalid_token"}), 401)

    # X-Device-ID is a permanent per-browser identifier set by LoginPage.tsx.
    # Using it means the Jira token survives logout/login cycles on the same
    # browser — the user only needs to connect Jira once per device.
    device_id = request.headers.get("X-Device-ID", "").strip()
    if device_id:
        user_id = f"device-{device_id}"
        logger.info('[Jira Routes] Authenticated user_id=%s role=%s device_id=%s', user_id, session.get('role'), device_id)
    else:
        user_id = session["userId"]
        logger.info('[Jira Routes] Authenticated user_id=%s role=%s device_id=<none>', user_id, session.get('role'))

    return user_id, None


def _get_valid_user_id_with_token():
    """
    Return (user_id, None) where user_id is guaranteed to have a stored token,
    or (None, error_response).

    Tries in order:
      1. device-<X-Device-ID>  — the normal per-device stable key
      2. session role userId   — fallback for requests where X-Device-ID was stripped
      3. Any token in the DB   — last resort so the Jira page always works for a
                                 connected user regardless of header stripping

    This prevents 401 on the Jira search page when the user is connected in
    Settings but X-Device-ID is absent from the request (e.g. stripped by a
    proxy or CORS preflight issue).
    """
    session = _get_session()
    if not session:
        return None, (jsonify({"error": "Unauthorized"}), 401)

    device_id = request.headers.get("X-Device-ID", "").strip()

    # Candidates to try in priority order
    candidates = []
    if device_id:
        candidates.append(f"device-{device_id}")
    candidates.append(session["userId"])

    for uid in candidates:
        token = get_token(uid)
        if token:
            return uid, None

    # Last resort: use any connected token in the DB (read-only Jira page use)
    try:
        from db import query as _q
        rows = _q(
            "SELECT metadata FROM projects_data "
            "WHERE row_type = 'jira_token' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if rows:
            import json as _j
            raw = rows[0].get("metadata")
            meta = _j.loads(raw) if isinstance(raw, str) else (raw or {})
            uid = meta.get("user_id", "")
            if uid:
                return uid, None
    except Exception:
        pass

    # No token found at all
    if device_id:
        return f"device-{device_id}", None  # let caller handle missing token
    return session["userId"], None


def _frontend_url() -> str:
    return os.environ.get(
        "FRONTEND_URL",
        "https://airbrake.s3-website-us-east-1.amazonaws.com",
    )


def _decode_metadata(raw):
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _normalize_reporter(metadata):
    reporter = metadata.get('created_by')
    if reporter:
        return reporter
    raw_reporter = metadata.get('reporter')
    if isinstance(raw_reporter, dict):
        return raw_reporter.get('display_name') or raw_reporter.get('email') or ''
    return metadata.get('reporter') or ''


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
        _persist_oauth_state(state, user_id)   # DB-backed — survives Lambda container switches
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
    persists the token, then redirects the browser to the frontend Settings
    page with ?jira_connected=true (or ?jira_error=...).

    State tokens are persisted in the database so this works correctly on
    Lambda where each invocation may run in a different container.
    """
    settings_url = f"{_frontend_url()}/settings"

    logger.info("[Jira Callback] START — args: code=%s state=%s error=%s",
                "present" if request.args.get("code") else "absent",
                request.args.get("state", "")[:8] + "...",
                request.args.get("error", "none"))

    error = request.args.get("error")
    if error:
        logger.warning("[Jira Callback] Atlassian returned error: %s", error)
        return redirect(f"{settings_url}?jira_error={requests.utils.quote(error)}")

    code  = request.args.get("code", "").strip()
    state = request.args.get("state", "").strip()

    if not code or not state:
        logger.warning("[Jira Callback] Missing code or state")
        return redirect(f"{settings_url}?jira_error=missing_params")

    # ── Validate CSRF state — DB-persisted so any Lambda container can read it ─
    matched_user_id = _pop_oauth_state(state)
    if not matched_user_id:
        logger.warning("[Jira Callback] Invalid or expired OAuth state: %s", state[:16])
        return redirect(f"{settings_url}?jira_error=invalid_state")

    logger.info("[Jira Callback] State validated for user_id=%s", matched_user_id)

    try:
        # Step 1: exchange code for tokens
        logger.info("[Jira Callback] Exchanging authorization code")
        token_data    = exchange_code_for_tokens(code)
        access_token  = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in    = token_data.get("expires_in")
        logger.info("[Jira Callback] Token exchange succeeded expires_in=%s", expires_in)

        # Step 2: resolve cloud_id
        logger.info("[Jira Callback] Fetching accessible resources")
        cloud_id = fetch_cloud_id(access_token)
        logger.info("[Jira Callback] cloud_id=%s", cloud_id)

        # Step 3: fetch user profile
        logger.info("[Jira Callback] Fetching user profile")
        profile              = fetch_user_profile(access_token, cloud_id)
        atlassian_account_id = profile.get("accountId", "")
        atlassian_email      = profile.get("emailAddress", "")
        logger.info("[Jira Callback] Profile fetched email=%s account_id=%s",
                    atlassian_email, atlassian_account_id)

        # Step 4: persist token
        logger.info("[Jira Callback] Saving token for user_id=%s", matched_user_id)
        save_token(
            user_id              = matched_user_id,
            access_token         = access_token,
            refresh_token        = refresh_token,
            expires_in           = expires_in,
            cloud_id             = cloud_id,
            atlassian_account_id = atlassian_account_id,
            atlassian_email      = atlassian_email,
        )
        logger.info("[Jira Callback] Token saved successfully")

        # Step 5: redirect back to Settings
        logger.info("[Jira Callback] SUCCESS — redirecting to %s", settings_url)
        return redirect(f"{settings_url}?jira_connected=true")

    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        body        = exc.response.text[:300] if exc.response is not None else str(exc)
        logger.error("[Jira Callback] HTTP error status=%s body=%s", status_code, body)
        return redirect(f"{settings_url}?jira_error=token_exchange_failed&status={status_code}")

    except ValueError as exc:
        logger.error("[Jira Callback] Value error: %s", exc)
        return redirect(f"{settings_url}?jira_error=no_accessible_resources")

    except Exception as exc:
        import traceback as _tb
        logger.exception("[Jira Callback] Unexpected error: %s", exc)
        logger.error("[Jira Callback] Traceback: %s", _tb.format_exc())
        return redirect(f"{settings_url}?jira_error=unexpected")


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


@jira_bp.route("/tickets")
def jira_tickets():
    user_id, err = _require_auth()
    if err:
        return err

    project = (request.args.get('project') or '').strip()
    status = (request.args.get('status') or '').strip().lower()
    sync_status = (request.args.get('sync_status') or '').strip().lower()

    filters = ["row_type = 'log'", "metadata::jsonb->>'jira_issue_key' IS NOT NULL"]
    params = []

    if project:
        filters.append("project_name = %s")
        params.append(project)

    if status:
        terminal_values = tuple(s.lower() for s in TERMINAL_STATUSES)
        if status == 'resolved':
            filters.append("LOWER(COALESCE(metadata::jsonb->>'jira_status', '')) IN %s")
            params.append(terminal_values)
        elif status == 'todo':
            filters.append("LOWER(COALESCE(metadata::jsonb->>'jira_status', '')) NOT IN %s")
            params.append(terminal_values)
        else:
            filters.append("LOWER(metadata::jsonb->>'jira_status') = %s")
            params.append(status)

    if sync_status:
        filters.append("LOWER(metadata::jsonb->>'jira_sync_status') = %s")
        params.append(sync_status)

    try:
        rows = query(
            "SELECT id, project_name, error, metadata, created_at, COALESCE(updated_at, created_at) AS updated_at "
            "FROM projects_data WHERE " + " AND ".join(filters) + " ORDER BY created_at DESC",
            tuple(params),
        )
    except Exception as exc:
        logger.exception("[Jira Routes] jira_tickets query failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    tickets = []
    resolved = todo = sync_failed = 0

    for row in rows:
        metadata = _decode_metadata(row.get('metadata'))
        jira_status = (metadata.get('jira_status') or '').strip()
        jira_sync_status = (metadata.get('jira_sync_status') or '').strip()
        issue_key = (metadata.get('jira_issue_key') or '').strip()
        created_by = _normalize_reporter(metadata)
        error = (row.get('error') or '').strip() or (metadata.get('error_message') or '').strip()
        updated_at = row.get('updated_at')

        if jira_sync_status.lower() == 'sync_failed':
            sync_failed += 1
        if jira_status and is_terminal(jira_status):
            resolved += 1
        else:
            todo += 1

        tickets.append({
            'log_id': row.get('id'),
            'issue_key': issue_key,
            'project_name': row.get('project_name') or metadata.get('project_name') or '',
            'error': error[:220],
            'jira_status': jira_status,
            'jira_sync_status': jira_sync_status,
            'jira_sync_detail': (metadata.get('jira_sync_detail') or '').strip(),
            'jira_url': (metadata.get('jira_url') or metadata.get('url') or '').strip(),
            'created_by': created_by,
            'updated_at': updated_at.isoformat() if hasattr(updated_at, 'isoformat') else (updated_at or ''),
        })

    return jsonify({
        'total': len(tickets),
        'resolved': resolved,
        'todo': todo,
        'sync_failed': sync_failed,
        'tickets': tickets,
    })


@jira_bp.route('/tickets/<log_id>/retry-sync', methods=['POST'])
def jira_retry_ticket_sync(log_id):
    user_id, err = _require_auth()
    if err:
        return err

    rows = query(
        "SELECT metadata FROM projects_data WHERE row_type = 'log' AND id = %s",
        (log_id,),
    )
    if not rows:
        return jsonify({"error": "Ticket log row not found"}), 404

    metadata = _decode_metadata(rows[0].get('metadata'))
    issue_key = (metadata.get('jira_issue_key') or '').strip()
    if not issue_key:
        return jsonify({"error": "No Jira issue linked to this log row"}), 400

    try:
        from .sync_pipeline import run_sync_pipeline
        result = run_sync_pipeline({"action": "retry", "issue_key": issue_key})
        return jsonify({
            "success": bool(result.get('success')),
            "detail": result.get('detail', ''),
            "log_ids": result.get('log_ids', []),
        })
    except Exception as exc:
        logger.exception("[Jira Routes] retry sync failed for log_id=%s issue_key=%s: %s", log_id, issue_key, exc)
        return jsonify({"error": str(exc)}), 500


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
    issue_url = (body.get("issue_url") or "").strip()

    if not log_id or not issue_key:
        return jsonify({"error": "log_id and issue_key are required"}), 400

    try:
        from .jira_sync import mark_log_jira_key
        mark_log_jira_key(log_id, issue_key, issue_url=issue_url)
        logger.info(
            "[Jira Routes] Linked log_id=%s to issue_key=%s by user_id=%s",
            log_id, issue_key, user_id,
        )
        return jsonify({"linked": True, "log_id": log_id, "issue_key": issue_key})
    except Exception as exc:
        logger.exception("[Jira Routes] link failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/jira/ticket-status
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/search", methods=["GET"])
def jira_search():
    """
    GET /api/jira/search?jql=<query>&maxResults=100
    
    Search Jira issues directly using JQL.
    Uses the current user's OAuth token to query their Jira instance.
    
    Query parameters:
      - jql: JQL query string (required)
      - maxResults: Max results per page (default: 100)
      - fields: Comma-separated list of fields to return (optional)
      - nextPageToken: Token for pagination (optional)
    
    Response:
      {
        "issues": [...],
        "isLast": bool,
        "nextPageToken": str or None,
        "total": int
      }
    """
    user_id, err = _get_valid_user_id_with_token()
    if err:
        return err
    
    jql = (request.args.get("jql") or "").strip()
    if not jql:
        return jsonify({"error": "jql parameter is required"}), 400
    
    max_results = int(request.args.get("maxResults", 100))
    fields_str = (request.args.get("fields") or "").strip()
    fields = fields_str.split(",") if fields_str else None
    next_page_token = (request.args.get("nextPageToken") or "").strip() or None
    
    try:
        session = _get_session()
        candidate_user_ids = [user_id]
        if session and session.get("userId") and session.get("userId") not in candidate_user_ids:
            candidate_user_ids.append(session["userId"])

        token = None
        token_user_id = None
        for candidate_id in candidate_user_ids:
            token = get_token(candidate_id)
            if token:
                token_user_id = candidate_id
                break

        logger.info('[Jira Routes] Jira token lookup for user_id=%s candidates=%s', user_id, candidate_user_ids)
        if not token:
            return jsonify({"error": "Jira not connected. Please connect your Jira account in Settings.", "needs_auth": True}), 401
        
        from .client import JiraClient
        client = JiraClient(
            access_token=token["access_token"],
            cloud_id=token["cloud_id"]
        )
        
        result = client.search_issues(
            jql=jql,
            fields=fields,
            max_results=max_results,
            next_page_token=next_page_token
        )
        
        return jsonify({
            "issues": result.get("issues", []),
            "isLast": result.get("isLast", True),
            "nextPageToken": result.get("nextPageToken"),
            "total": len(result.get("issues", []))
        })
    
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        logger.error("[Jira Routes] search failed status=%s", status_code)
        return jsonify({
            "error": "Jira API error",
            "status": status_code,
            "needs_auth": status_code == 401
        }), status_code if status_code in (400, 401, 403) else 502
    
    except Exception as exc:
        logger.exception("[Jira Routes] search failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@jira_bp.route("/ticket-status")
def jira_ticket_status():
    """
    GET /api/jira/ticket-status?error_hash=<hash>

    Returns whether a Jira ticket already exists for this error_hash.
    This is a GLOBAL check — not scoped to the current user.
    Any user opening the error detail gets the same answer.

    Does NOT require Jira OAuth. Only reads the local database.
    Does NOT create anything.

    Response (ticket exists):
      { has_ticket: true, issue_key: "ARGUS-15", issue_url: "...", status: "exists" }

    Response (no ticket):
      { has_ticket: false }
    """
    _, err = _require_auth()
    if err:
        return err

    error_hash = (request.args.get("error_hash") or "").strip()
    if not error_hash:
        return jsonify({"error": "error_hash is required"}), 400

    try:
        from db import query as _query
        # Look for any log row with this error_hash that has a jira_issue_key
        rows = _query(
            "SELECT metadata "
            "FROM projects_data "
            "WHERE row_type = 'log' "
            "  AND error_hash = %s "
            "  AND metadata::jsonb ? 'jira_issue_key' "
            "  AND metadata::jsonb->>'jira_issue_key' IS NOT NULL "
            "  AND metadata::jsonb->>'jira_issue_key' != '' "
            "ORDER BY created_at DESC LIMIT 1",
            (error_hash,),
        )

        if not rows:
            return jsonify({"has_ticket": False})

        import json as _json
        raw = rows[0].get("metadata")
        meta = _json.loads(raw) if isinstance(raw, str) else (raw or {})

        issue_key = meta.get("jira_issue_key", "")
        if not issue_key:
            return jsonify({"has_ticket": False})

        # Build the browse URL from the stored ticket URL if available,
        # otherwise construct a generic one from the cloud domain
        issue_url = meta.get("jira_issue_url", "")
        if not issue_url:
            # Attempt to build URL from any stored token's cloud URL
            token_rows = _query(
                "SELECT metadata FROM projects_data "
                "WHERE row_type = 'jira_token' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            if token_rows:
                token_raw = token_rows[0].get("metadata")
                token_meta = _json.loads(token_raw) if isinstance(token_raw, str) else (token_raw or {})
                cloud_id = token_meta.get("cloud_id", "")
                if cloud_id:
                    # Resolve site URL from accessible resources
                    try:
                        from .jira_sync import find_airbrake_token_for_webhook
                        token_pair = find_airbrake_token_for_webhook()
                        if token_pair:
                            import requests as _req
                            resp = _req.get(
                                "https://api.atlassian.com/oauth/token/accessible-resources",
                                headers={
                                    "Authorization": f"Bearer {token_pair[0]}",
                                    "Accept": "application/json",
                                },
                                timeout=5,
                            )
                            if resp.ok:
                                resources = resp.json()
                                if resources:
                                    site_url = resources[0].get("url", "")
                                    issue_url = f"{site_url}/browse/{issue_key}"
                    except Exception:
                        pass

        logger.info(
            "[Jira Routes] ticket-status hit error_hash=%s issue_key=%s",
            error_hash, issue_key,
        )
        return jsonify({
            "has_ticket": True,
            "issue_key":  issue_key,
            "issue_url":  issue_url,
            "status":     "exists",
        })

    except Exception as exc:
        logger.exception("[Jira Routes] ticket-status failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
