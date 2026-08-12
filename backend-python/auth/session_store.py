"""
Server-side session store backed by Aurora DSQL.

Sessions are stored in the existing 'projects_data' table using
row_type = 'auth_session'.  One row per active session.

Schema (uses existing projects_data columns):
  id          UUID primary key (the session token — opaque, random)
  row_type    = 'auth_session'
  metadata    JSONB: { "user_id": str, "expires_at": ISO timestamp }
  created_at  TIMESTAMPTZ

Sessions expire after SESSION_TTL_SECONDS (default 24 hours).
Expired rows are deleted on lookup (lazy cleanup).
"""

import json
import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from db import query, execute, execute_returning
except Exception as _db_exc:
    import traceback
    print(f"[auth.session_store] WARNING: db import failed: {_db_exc}")
    print(traceback.format_exc())

    def query(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")

    def execute(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")

    def execute_returning(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")


TABLE = "projects_data"
SESSION_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def generate_session_token() -> str:
    """Generate a cryptographically random opaque session token."""
    return secrets.token_urlsafe(48)


def create_session(user_id: str) -> str:
    """
    Create a new server-side session for the given user_id.

    Returns the opaque session token (to be set in the cookie).
    """
    if not user_id:
        raise ValueError("user_id is required to create a session")

    token = generate_session_token()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)
    ).isoformat()

    payload = {
        "user_id": user_id,
        "expires_at": expires_at,
    }

    row_id = str(uuid.uuid4())
    execute(
        f"INSERT INTO {TABLE} (id, row_type, metadata, created_at) "
        f"VALUES (%s, 'auth_session', %s, NOW())",
        (row_id, json.dumps({"token": token, **payload})),
    )
    logger.info("[Auth Session] Created session for user_id=%s", user_id)
    return token


def get_session(token: str) -> Optional[dict]:
    """
    Look up a session by token.

    Returns {"user_id": str, "expires_at": str} or None if
    the session is missing or expired.
    """
    if not token:
        return None

    rows = query(
        f"SELECT id, metadata FROM {TABLE} "
        f"WHERE row_type = 'auth_session' AND metadata::jsonb->>'token' = %s "
        f"ORDER BY created_at DESC LIMIT 1",
        (token,),
    )
    if not rows:
        return None

    raw = rows[0].get("metadata")
    if not raw:
        return None

    try:
        meta = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None

    # Check expiry
    expires_at = meta.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) >= exp:
                # Expired — delete and return None
                _delete_session_row(rows[0]["id"])
                logger.info("[Auth Session] Session expired, deleted row_id=%s", rows[0]["id"])
                return None
        except (ValueError, TypeError):
            pass

    return {
        "user_id": meta.get("user_id"),
        "expires_at": meta.get("expires_at"),
    }


def delete_session(token: str) -> None:
    """Delete (invalidate) a session by token."""
    if not token:
        return
    execute(
        f"DELETE FROM {TABLE} "
        f"WHERE row_type = 'auth_session' AND metadata::jsonb->>'token' = %s",
        (token,),
    )
    logger.info("[Auth Session] Session deleted")


def cleanup_expired_sessions() -> int:
    """
    Delete all expired sessions. Returns number of rows deleted.

    Call periodically (e.g. on each login) to keep the table clean.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    count = execute(
        f"DELETE FROM {TABLE} "
        f"WHERE row_type = 'auth_session' "
        f"AND (metadata::jsonb->>'expires_at')::timestamptz < %s",
        (now_iso,),
    )
    if count > 0:
        logger.info("[Auth Session] Cleaned up %d expired sessions", count)
    return count


def _delete_session_row(row_id: str) -> None:
    execute(f"DELETE FROM {TABLE} WHERE id = %s", (row_id,))
