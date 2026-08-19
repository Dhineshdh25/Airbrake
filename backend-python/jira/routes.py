"""
Jira OAuth + ticket creation routes.

Registers a Flask blueprint at URL prefix /api/jira.

Routes:
  GET  /api/jira/login      — start OAuth flow (redirects to Atlassian)
  GET  /api/jira/callback   — OAuth callback (exchanges code, saves token)
  GET  /api/jira/status     — check whether the current user is connected
  POST /api/jira/create     — create a Jira ticket from error data
  POST /api/jira/disconnect — remove the current user's stored token

All routes that need an authenticated user require a valid server-side session
(cookie-based authentication via the auth middleware).
"""

import json
import logging
import os

import requests
from flask import Blueprint, jsonify, redirect, request
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
# Device-based tokens (device-*) are migrated transparently on first access
# by _get_valid_user_id_with_token() — no bulk cleanup needed for those.
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

# ── Helpers — unified auth using the shared auth.middleware package ───────────
# auth/ is deployed to Lambda alongside jira/.
# In production (APP_ENV=production), only real Google OAuth sessions work.
# In dev (DEV_AUTH=1 and APP_ENV!=production), dev tokens also work.
from auth.middleware import get_current_user as _get_current_user, _is_dev_auth_enabled
from auth.middleware import _DEV_SESSIONS


def _is_production_environment() -> bool:
    env_name = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or os.getenv("FLASK_ENV") or "").strip().lower()
    return env_name in {"production", "prod", "staging"}


def _get_session() -> dict | None:
    """Resolve the current session using the shared auth middleware."""
    user = _get_current_user()
    if user:
        return {"userId": user["id"], "role": dev_user["role"]}
    return None


def _require_auth():
    """Return (user_id, None) or (None, error_response).

    user_id is stable across logouts — derived from:
    1. Real Google OAuth session (production)
    2. Dev session token (DEV_AUTH=1, non-production only)

    X-Device-ID is used as a migration key for Jira tokens stored before
    the unified auth was introduced. The real user_id from the session is
    always the primary key.
    """
    session = _get_session()
    if not session:
        return None, (jsonify({"error": "Unauthorized"}), 401)

    user_id = session["userId"]

    # X-Device-ID migration: if no token under user_id, check legacy device key
    device_id = request.headers.get("X-Device-ID", "").strip()
    if device_id:
        token = get_token(user_id)
        if not token:
            # Check legacy device-based key and migrate if found
            legacy_key = f"device-{device_id}"
            legacy_token = get_token(legacy_key)
            if legacy_token:
                logger.info(
                    "[Jira Routes] Migrating token from legacy device key=%s to user_id=%s",
                    legacy_key, user_id,
                )
                try:
                    save_token(
                        user_id=user_id,
                        access_token=legacy_token.get("access_token", ""),
                        refresh_token=legacy_token.get("refresh_token", ""),
                        expires_in=None,
                        cloud_id=legacy_token.get("cloud_id", ""),
                        atlassian_account_id=legacy_token.get("atlassian_account_id", ""),
                        atlassian_email=legacy_token.get("atlassian_email", ""),
                        site_url=legacy_token.get("site_url", ""),
                    )
                    delete_token(legacy_key)
                except Exception as exc:
                    logger.warning("[Jira Routes] Token migration failed: %s", exc)

    return user_id, None


def _get_valid_user_id_with_token():
    """
    Return (user_id, None) where user_id is guaranteed to have a stored token,
    or (None, error_response).

    Tries in order:
      1. Authenticated Airbrake user_id from session
      2. Legacy device-<X-Device-ID> key (migration compatibility)

    If the user has a token under the legacy device-based key but not
    under their real user_id, we transparently migrate it.
    """
    session = _get_session()
    if not session:
        return None, (jsonify({"error": "Unauthorized"}), 401)

    user_id = session["userId"]

    # Primary: check for token under the authenticated user_id
    token = get_token(user_id)
    if token:
        return user_id, None

    # Migration path: check legacy device-based key and migrate if found
    device_id = request.headers.get("X-Device-ID", "").strip()
    if device_id:
        legacy_key = f"device-{device_id}"
        legacy_token = get_token(legacy_key)
        if legacy_token:
            logger.info(
                "[Jira Routes] Migrating Jira token from legacy key=%s to user_id=%s",
                legacy_key, user_id,
            )
            _migrate_token(legacy_key, user_id, legacy_token)
            return user_id, None

    return user_id, None  # let caller handle missing token


def _migrate_token(old_key: str, new_key: str, token_data: dict) -> None:
    """
    Migrate a Jira token from a legacy key to the new authenticated user_id.

    Copies the token data under the new key, then deletes the old row.
    Preserves all token credentials (access_token, refresh_token, etc.).
    """
    try:
        save_token(
            user_id=new_key,
            access_token=token_data.get("access_token", ""),
            refresh_token=token_data.get("refresh_token", ""),
            expires_in=None,  # preserve existing expires_at via direct copy below
            cloud_id=token_data.get("cloud_id", ""),
            atlassian_account_id=token_data.get("atlassian_account_id", ""),
            atlassian_email=token_data.get("atlassian_email", ""),
            site_url=token_data.get("site_url", ""),
        )
        # If the original had a specific expires_at, update the new row
        if token_data.get("expires_at"):
            from db import query as _q
            rows = _q(
                "SELECT id, metadata FROM projects_data "
                "WHERE row_type = 'jira_token' AND metadata::jsonb->>'user_id' = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (new_key,),
            )
            if rows:
                import json as _j
                raw = rows[0].get("metadata")
                meta = _j.loads(raw) if isinstance(raw, str) else (raw or {})
                meta["expires_at"] = token_data["expires_at"]
                execute(
                    "UPDATE projects_data SET metadata = %s WHERE id = %s",
                    (_j.dumps(meta), rows[0]["id"]),
                )

        # Delete the old key
        delete_token(old_key)
        logger.info("[Jira Routes] Token migrated from %s to %s", old_key, new_key)
    except Exception as exc:
        logger.warning("[Jira Routes] Token migration failed (non-fatal): %s", exc)


def _frontend_url() -> str:
    """Return the frontend base URL with trailing slash stripped.

    Read from FRONTEND_URL env var — must be set in Lambda.
    Default is the HTTP S3 static website URL (NOT https — S3 static
    hosting only supports http on the s3-website endpoint).
    """
    url = os.environ.get(
        "FRONTEND_URL",
        "http://airbrake.s3-website-us-east-1.amazonaws.com",
    )
    return url.rstrip("/")


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


@jira_bp.route("/debug-config")
def jira_debug_config():
    """
    GET /api/jira/debug-config

    Returns the exact OAuth configuration the backend is using.
    Use this to verify what redirect_uri is being sent to Atlassian
    and compare it against the Atlassian Developer Console.

    Remove this endpoint after the OAuth flow is confirmed working.
    """
    from .oauth import get_credentials
    client_id, _, redirect_uri = get_credentials()
    frontend = _frontend_url()
    return jsonify({
        "atlassian_client_id":      client_id or "(NOT SET)",
        "atlassian_callback_url":   redirect_uri,
        "frontend_url":             frontend,
        "settings_redirect_target": f"{frontend}/settings",
        "env_vars_present": {
            "ATLASSIAN_CLIENT_ID":     bool(client_id),
            "ATLASSIAN_CLIENT_SECRET": bool(os.environ.get("ATLASSIAN_CLIENT_SECRET")),
            "ATLASSIAN_CALLBACK_URL":  bool(os.environ.get("ATLASSIAN_CALLBACK_URL")),
            "JIRA_PROJECT_KEY":        bool(os.environ.get("JIRA_PROJECT_KEY")),
            "FRONTEND_URL":            bool(os.environ.get("FRONTEND_URL")),
        },
        "instructions": (
            "The value of 'atlassian_callback_url' must EXACTLY match "
            "the Callback URL registered in your Atlassian Developer Console app. "
            "No trailing slash, same protocol, same host."
        ),
    })


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
    persists the token, then redirects the browser to the frontend root URL
    with ?jira_connected=true&redirect=/settings

    We redirect to ROOT (not /settings) because S3 static hosting only serves
    index.html for the root path. Any other path (e.g. /settings) returns
    ERR_CONNECTION_CLOSED. The frontend JiraSettings component detects the
    query params and navigates to /settings internally via React Router.
    """
    root_url = _frontend_url()   # e.g. http://airbrake.s3-website-us-east-1.amazonaws.com

    logger.info("[Jira Callback] START — code=%s state=%s error=%s",
                "present" if request.args.get("code") else "absent",
                (request.args.get("state", "")[:8] + "...") if request.args.get("state") else "absent",
                request.args.get("error", "none"))

    error = request.args.get("error")
    if error:
        logger.warning("[Jira Callback] Atlassian returned error: %s", error)
        return redirect(f"{root_url}/?jira_error={requests.utils.quote(error)}")

    code  = request.args.get("code", "").strip()
    state = request.args.get("state", "").strip()

    if not code or not state:
        logger.warning("[Jira Callback] Missing code or state")
        return redirect(f"{root_url}/?jira_error=missing_params")

    # ── Validate CSRF state — DB-persisted so any Lambda container can read it ─
    matched_user_id = _pop_oauth_state(state)
    if not matched_user_id:
        logger.warning("[Jira Callback] Invalid or expired OAuth state: %s", state[:16])
        return redirect(f"{root_url}/?jira_error=invalid_state")

    logger.info("[Jira Callback] State validated for user_id=%s", matched_user_id)

    try:
        logger.info("[Jira Callback] Exchanging authorization code")
        token_data    = exchange_code_for_tokens(code)
        access_token  = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in    = token_data.get("expires_in")
        logger.info("[Jira Callback] Token exchange succeeded expires_in=%s", expires_in)

        logger.info("[Jira Callback] Fetching accessible resources")
        cloud_id = fetch_cloud_id(access_token)
        logger.info("[Jira Callback] cloud_id=%s", cloud_id)
        
        # Fetch the Jira site URL for browser navigation
        from .oauth import fetch_site_url
        site_url = fetch_site_url(access_token)
        logger.info("[Jira Callback] site_url=%s", site_url)

        logger.info("[Jira Callback] Fetching user profile")
        profile              = fetch_user_profile(access_token, cloud_id)
        atlassian_account_id = profile.get("accountId", "")
        atlassian_email      = profile.get("emailAddress", "")
        logger.info("[Jira Callback] Profile fetched email=%s", atlassian_email)

        logger.info("[Jira Callback] Saving token for user_id=%s", matched_user_id)
        save_token(
            user_id              = matched_user_id,
            access_token         = access_token,
            refresh_token        = refresh_token,
            expires_in           = expires_in,
            cloud_id             = cloud_id,
            atlassian_account_id = atlassian_account_id,
            atlassian_email      = atlassian_email,
            site_url             = site_url,
        )
        logger.info("[Jira Callback] Token saved — redirecting to %s", root_url)
        return redirect(f"{root_url}/?jira_connected=true")
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        body        = exc.response.text[:300] if exc.response is not None else str(exc)
        logger.error("[Jira Callback] HTTP error status=%s body=%s", status_code, body)
        return redirect(f"{root_url}/?jira_error=token_exchange_failed")

    except ValueError as exc:
        logger.error("[Jira Callback] Value error: %s", exc)
        return redirect(f"{root_url}/?jira_error=no_accessible_resources")

    except Exception as exc:
        import traceback as _tb
        logger.exception("[Jira Callback] Unexpected error: %s", exc)
        return redirect(f"{root_url}/?jira_error=unexpected")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/jira/status
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/status")
def jira_status():
    """
    Return whether the current user has a connected Jira account.

    Response: { connected: bool, email: str, account_id: str, site_url: str }
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
            "site_url":   token.get("site_url", ""),
        })
    return jsonify({"connected": False, "email": "", "account_id": "", "site_url": ""})


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
    GET /api/jira/search
    
    Search Jira issues with automatic project discovery and proper JQL construction.
    Uses the current user's OAuth token to query their Jira instance.
    
    Query parameters:
      - status: Filter by status name (optional)
      - priority: Filter by priority name (optional)
      - assignee: Filter by assignee display name (optional)
      - search: Text search in summary and description (optional)
      - maxResults: Max results per page (default: 200)
      - nextPageToken: Token for pagination (optional)
    
    Response:
      {
        "issues": [...],
        "isLast": bool,
        "nextPageToken": str or None,
        "total": int,
        "project_key": str  (the project used in the query)
      }
    """
    user_id, err = _get_valid_user_id_with_token()
    if err:
        return err
    
    # Parse query parameters
    status_filter = (request.args.get("status") or "").strip()
    priority_filter = (request.args.get("priority") or "").strip()
    assignee_filter = (request.args.get("assignee") or "").strip()
    search_text = (request.args.get("search") or "").strip()
    max_results = int(request.args.get("maxResults", 200))
    next_page_token = (request.args.get("nextPageToken") or "").strip() or None
    
    logger.info(
        "[Jira Routes] /api/jira/search START\n"
        "  user_id: %s\n"
        "  status: %s\n"
        "  priority: %s\n"
        "  assignee: %s\n"
        "  search: %s\n"
        "  maxResults: %d\n"
        "  nextPageToken: %s",
        user_id, status_filter, priority_filter, assignee_filter, search_text, max_results, next_page_token
    )
    
    try:
        # Get the user's token using the authenticated user_id
        token = get_token(user_id)

        # Migration path: check legacy device-based key
        if not token:
            device_id = request.headers.get("X-Device-ID", "").strip()
            if device_id:
                legacy_key = f"device-{device_id}"
                token = get_token(legacy_key)
                if token:
                    logger.info("[Jira Routes] search: migrating token from %s to %s", legacy_key, user_id)
                    _migrate_token(legacy_key, user_id, token)

        logger.info('[Jira Routes] Jira token lookup for user_id=%s', user_id)
        if not token:
            return jsonify({"error": "Jira not connected. Please connect your Jira account in Settings.", "needs_auth": True}), 401
        
        from .client import JiraClient
        client = JiraClient(
            access_token=token["access_token"],
            cloud_id=token["cloud_id"]
        )
        
        # Step 1: Get accessible projects
        logger.info("[Jira Routes] Fetching accessible projects")
        projects = client.get_accessible_projects()
        
        if not projects:
            logger.warning("[Jira Routes] User has no accessible projects")
            return jsonify({
                "issues": [],
                "isLast": True,
                "nextPageToken": None,
                "total": 0,
                "message": "No accessible Jira projects found. Please ensure you have access to at least one project."
            })
        
        # Step 2: Use the first project as the default
        default_project = projects[0]
        project_key = default_project.get("key")
        
        logger.info(
            "[Jira Routes] Using default project: %s (out of %d accessible projects)",
            project_key, len(projects)
        )
        
        # Step 3: Build JQL query with project restriction
        jql_parts = [f'project = "{project_key}"']
        
        if status_filter:
            jql_parts.append(f'status = "{status_filter}"')
        
        if priority_filter:
            jql_parts.append(f'priority = "{priority_filter}"')
        
        if assignee_filter:
            # Assignee filter requires accountId, but we have displayName
            # Use text search to approximate this
            jql_parts.append(f'assignee in ({assignee_filter})')
        
        if search_text:
            # Escape quotes in search text
            escaped_search = search_text.replace('"', '\\"')
            jql_parts.append(f'(summary ~ "{escaped_search}" OR description ~ "{escaped_search}")')
        
        # Always sort by updated DESC
        jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
        
        logger.info(
            "[Jira Routes] Generated JQL:\n"
            "  %s\n"
            "  Accessible projects: %s",
            jql,
            [p.get("key") for p in projects]
        )
        
        # Step 4: Execute search with explicit fields required by frontend
        result = client.search_issues(
            jql=jql,
            fields=[
                "summary",
                "project",
                "status",
                "priority",
                "assignee",
                "created",
                "updated"
            ],
            max_results=max_results,
            next_page_token=next_page_token
        )
        
        logger.info(
            "[Jira Routes] Search completed successfully\n"
            "  Returned: %d issues\n"
            "  isLast: %s\n"
            "  nextPageToken: %s",
            len(result.get("issues", [])),
            result.get("isLast"),
            result.get("nextPageToken")
        )
        
        # Get the Jira site URL for browser navigation
        site_url = token.get("site_url", "")
        
        return jsonify({
            "issues": result.get("issues", []),
            "isLast": result.get("isLast", True),
            "nextPageToken": result.get("nextPageToken"),
            "total": len(result.get("issues", [])),
            "project_key": project_key,
            "site_url": site_url,
        })
    
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        error_body = exc.response.text[:1000] if exc.response is not None else str(exc)
        
        # Parse Jira's error response for better debugging
        user_message = "Jira API error"
        try:
            if exc.response is not None:
                jira_error = exc.response.json()
                error_messages = jira_error.get("errorMessages", [])
                errors_dict = jira_error.get("errors", {})
                
                if error_messages:
                    user_message = "; ".join(error_messages)
                elif errors_dict:
                    user_message = "; ".join(f"{k}: {v}" for k, v in errors_dict.items())
                else:
                    user_message = error_body
        except Exception:
            user_message = error_body
        
        logger.error(
            "[Jira Routes] search FAILED\n"
            "  Status: %s\n"
            "  Error body: %s",
            status_code, error_body
        )
        
        return jsonify({
            "error": user_message,
            "status": status_code,
            "needs_auth": status_code == 401,
            "detail": error_body[:500]
        }), status_code if status_code in (400, 401, 403) else 502
    
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.exception("[Jira Routes] search failed with exception: %s\n%s", exc, tb)
        return jsonify({
            "error": str(exc),
            "exception_type": type(exc).__name__,
            "traceback": tb[:1000]
        }), 500


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

    log_id = (request.args.get("log_id") or "").strip()
    if not log_id:
        return jsonify({"has_ticket": False})  # no log_id = no ticket to check

    try:
        from db import query as _query
        rows = _query(
            "SELECT metadata "
            "FROM projects_data "
            "WHERE row_type = 'log' "
            "  AND id = %s "
            "  AND metadata::jsonb ? 'jira_issue_key' "
            "  AND metadata::jsonb->>'jira_issue_key' IS NOT NULL "
            "  AND metadata::jsonb->>'jira_issue_key' != '' ",
            (log_id,),
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
            "[Jira Routes] ticket-status log_id=%s issue_key=%s",
            log_id, issue_key,
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


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/jira/poll-sync
# ═══════════════════════════════════════════════════════════════════════════════

@jira_bp.route("/poll-sync", methods=["POST"])
def jira_poll_sync():
    """
    POST /api/jira/poll-sync

    Polls all open Airbrake log rows that have a linked Jira ticket and checks
    whether their ticket has moved to a terminal status (Done/Closed/Resolved).
    For each ticket that is Done, runs the full sync pipeline (same as webhook).

    This is the webhook-free alternative — call this on a schedule (EventBridge,
    cron, or manually) instead of relying on Jira webhooks.

    No request body needed.

    Response:
      {
        "polled":    int   — number of linked rows checked
        "synced":    int   — number successfully resolved
        "skipped":   int   — number not yet Done in Jira
        "failed":    int   — number that errored during sync
        "details":   list  — per-issue breakdown
      }
    """
    # Authentication is optional for poll-sync — it can be called by a scheduler
    # with no session. Only require auth if a real session is present.
    user_id = None
    try:
        session = _get_session()
        if session:
            user_id = session.get("userId")
    except Exception:
        pass

    logger.info("[Jira PollSync] Starting poll-sync user_id=%s", user_id)

    try:
        from db import query as _q
        # Find all log rows that have a jira_issue_key but are NOT yet resolved
        linked_rows = _q(
            "SELECT id, project_name, error, error_hash, error_status, "
            "       metadata::jsonb->>'jira_issue_key' AS issue_key "
            "FROM projects_data "
            "WHERE row_type = 'log' "
            "  AND metadata::jsonb ? 'jira_issue_key' "
            "  AND metadata::jsonb->>'jira_issue_key' IS NOT NULL "
            "  AND metadata::jsonb->>'jira_issue_key' != '' "
            "  AND (error_status IS NULL OR error_status NOT IN ('resolved')) "
            "ORDER BY created_at DESC"
        )
    except Exception as exc:
        logger.exception("[Jira PollSync] DB query failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    if not linked_rows:
        logger.info("[Jira PollSync] No unresolved linked rows found")
        return jsonify({"polled": 0, "synced": 0, "skipped": 0, "failed": 0, "details": []})

    # Get a valid Jira token for API calls
    from .jira_sync import find_airbrake_token_for_webhook, fetch_full_issue
    token_pair = find_airbrake_token_for_webhook()
    if not token_pair:
        return jsonify({
            "error": "No Jira token available. Please connect your Jira account in Settings.",
            "polled": 0, "synced": 0, "skipped": 0, "failed": 0, "details": [],
        }), 401

    access_token, cloud_id = token_pair

    # Deduplicate by issue_key — one API call per ticket, not per row
    issue_keys = list({row["issue_key"] for row in linked_rows if row.get("issue_key")})
    logger.info("[Jira PollSync] Checking %d unique tickets for %d rows", len(issue_keys), len(linked_rows))

    # Fetch current status for each unique issue
    issue_statuses: dict[str, dict] = {}
    for key in issue_keys:
        try:
            issue = fetch_full_issue(key, access_token, cloud_id)
            issue_statuses[key] = issue
            logger.info(
                "[Jira PollSync] Fetched %s status=%s",
                key, issue.get("status", "unknown"),
            )
        except Exception as exc:
            logger.error("[Jira PollSync] Failed to fetch %s: %s", key, exc)
            issue_statuses[key] = {"status": "fetch_failed", "key": key, "error": str(exc)}

    # Run sync pipeline for each issue that is Done
    from .webhook_handler import TERMINAL_STATUSES
    from .sync_pipeline import run_sync_pipeline

    polled = len(issue_keys)
    synced = skipped = failed = 0
    details = []

    for key, issue in issue_statuses.items():
        status_name = (issue.get("status") or "").lower()
        is_done = status_name in TERMINAL_STATUSES

        if issue.get("error"):
            failed += 1
            details.append({"issue_key": key, "result": "error", "detail": issue.get("error", "")})
            continue

        if not is_done:
            skipped += 1
            details.append({"issue_key": key, "result": "skipped", "status": status_name})
            continue

        # Build a synthetic event matching what parse_webhook would produce
        synthetic_event = {
            "action":          "resolve",
            "issue_key":       key,
            "issue_id":        issue.get("key", key),
            "status":          status_name,
            "is_terminal":     True,
            "is_reopen":       False,
            "assignee":        issue.get("assignee"),
            "resolution":      issue.get("resolution"),
            "summary":         issue.get("summary", ""),
            "description":     issue.get("description"),
            "comment_body":    None,
            "reporter":        issue.get("reporter"),
            "updated_by":      None,
            "transition_name": "Done",
            "raw":             issue,
        }

        try:
            result = run_sync_pipeline(synthetic_event)
            if result.get("success"):
                synced += 1
                details.append({
                    "issue_key": key,
                    "result":    "synced",
                    "log_ids":   result.get("log_ids", []),
                    "detail":    result.get("detail", ""),
                })
            else:
                failed += 1
                details.append({
                    "issue_key": key,
                    "result":    "failed",
                    "detail":    result.get("detail", ""),
                })
        except Exception as exc:
            logger.exception("[Jira PollSync] Pipeline failed for %s: %s", key, exc)
            failed += 1
            details.append({"issue_key": key, "result": "error", "detail": str(exc)})

    logger.info(
        "[Jira PollSync] Done — polled=%d synced=%d skipped=%d failed=%d",
        polled, synced, skipped, failed,
    )
    return jsonify({
        "polled":  polled,
        "synced":  synced,
        "skipped": skipped,
        "failed":  failed,
        "details": details,
    })
