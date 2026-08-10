"""
Jira OAuth token persistence.

Tokens are stored as rows in the existing 'projects_data' Aurora DSQL table
using row_type = 'jira_token'.  One row per Airbrake user_id.

Schema used (all columns are existing columns in projects_data):
  id            UUID primary key
  row_type      = 'jira_token'
  created_at    TIMESTAMPTZ
  -- payload stored as JSON in the metadata column:
  --   {
  --     "user_id":           str   ← Airbrake userId from session
  --     "access_token":      str   ← NEVER logged
  --     "refresh_token":     str   ← NEVER logged
  --     "expires_at":        str   ← ISO timestamp (may be None if absent)
  --     "cloud_id":          str
  --     "atlassian_account_id": str
  --     "atlassian_email":   str
  --   }
  metadata      TEXT / JSONB   ← stores the full token payload

DO NOT log access_token, refresh_token, or client_secret values.
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Import db helpers (same pattern as the rest of app.py) ────────────────────
try:
    from db import query, execute, execute_returning
except Exception as _db_exc:  # pragma: no cover
    import traceback
    print(f"[jira.token_store] WARNING: db import failed: {_db_exc}")
    print(traceback.format_exc())

    def query(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def execute(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def execute_returning(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")

TABLE = "projects_data"


# ── Public API ────────────────────────────────────────────────────────────────

def save_token(
    user_id: str,
    access_token: str,
    refresh_token: str,
    expires_in: Optional[int],
    cloud_id: str,
    atlassian_account_id: str,
    atlassian_email: str,
    site_url: str = "",
) -> None:
    """
    Upsert the Jira OAuth token for the given Airbrake user_id.

    Deletes any existing token row for this user then inserts a fresh one.
    DO NOT log token values.
    """
    if not user_id:
        raise ValueError("user_id is required to save a Jira token")

    expires_at = None
    if expires_in:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        ).isoformat()

    payload = {
        "user_id":               user_id,
        "access_token":          access_token,
        "refresh_token":         refresh_token,
        "expires_at":            expires_at,
        "cloud_id":              cloud_id,
        "atlassian_account_id":  atlassian_account_id,
        "atlassian_email":       atlassian_email,
        "site_url":              site_url,
    }

    # Remove any existing token row for this user first
    _delete_token_row(user_id)

    row_id = str(uuid.uuid4())
    execute(
        f"INSERT INTO {TABLE} (id, row_type, metadata, created_at) "
        f"VALUES (%s, 'jira_token', %s, NOW())",
        (row_id, json.dumps(payload)),
    )
    logger.info(
        "[Jira TokenStore] Saved token for user_id=%s account_id=%s email=%s",
        user_id, atlassian_account_id, atlassian_email,
    )


def get_token(user_id: str) -> Optional[dict]:
    """
    Return the stored token payload dict for this user, or None.

    The returned dict contains: access_token, refresh_token, expires_at,
    cloud_id, atlassian_account_id, atlassian_email.
    DO NOT log token values from the returned dict.
    """
    if not user_id:
        return None

    rows = query(
        f"SELECT metadata FROM {TABLE} "
        f"WHERE row_type = 'jira_token' AND metadata::jsonb->>'user_id' = %s "
        f"ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    if not rows:
        return None

    raw = rows[0].get("metadata")
    if not raw:
        return None

    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        logger.warning("[Jira TokenStore] Could not parse metadata for user_id=%s", user_id)
        return None


def delete_token(user_id: str) -> None:
    """Remove the stored Jira token for this user (disconnect)."""
    _delete_token_row(user_id)
    logger.info("[Jira TokenStore] Deleted token for user_id=%s", user_id)


def is_token_expired(token: dict) -> bool:
    """Return True if the token's expires_at is in the past (or missing)."""
    expires_at = token.get("expires_at")
    if not expires_at:
        return False  # treat tokens with no expiry as valid
    try:
        exp = datetime.fromisoformat(expires_at)
        # Refresh 60 s before actual expiry to avoid edge cases
        return datetime.now(timezone.utc) >= (exp - timedelta(seconds=60))
    except (ValueError, TypeError):
        return False


# ── Private helpers ───────────────────────────────────────────────────────────

def _delete_token_row(user_id: str) -> None:
    execute(
        f"DELETE FROM {TABLE} "
        f"WHERE row_type = 'jira_token' AND metadata::jsonb->>'user_id' = %s",
        (user_id,),
    )
