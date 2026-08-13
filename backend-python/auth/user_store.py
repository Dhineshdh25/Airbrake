"""
User lookup and creation using Aurora DSQL.

Users are stored in the 'projects_data' table with row_type = 'user'.
This matches the existing implementation in app.py for the admin user
management routes (GET/POST/DELETE /api/users).

Columns used:
  id              UUID
  row_type        = 'user'
  email           TEXT
  role            TEXT  ('admin', 'developer', 'viewer')
  oauth_provider  TEXT  (e.g. 'google')
  oauth_subject   TEXT  (the OIDC 'sub' claim — stable user identifier)
  created_at      TIMESTAMPTZ
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from db import query, execute, execute_returning
except Exception as _db_exc:
    import traceback
    print(f"[auth.user_store] WARNING: db import failed: {_db_exc}")
    print(traceback.format_exc())

    def query(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")

    def execute(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")

    def execute_returning(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")


TABLE = "projects_data"


def find_by_oauth_subject(provider: str, subject: str) -> Optional[dict]:
    """
    Look up a user by OAuth provider + subject (the OIDC 'sub' claim).

    Returns a dict with {id, email, role, oauth_provider, oauth_subject}
    or None if not found.
    """
    if not provider or not subject:
        return None

    rows = query(
        f"SELECT id, email, role, oauth_provider, oauth_subject, created_at "
        f"FROM {TABLE} "
        f"WHERE row_type = 'user' "
        f"  AND oauth_provider = %s "
        f"  AND oauth_subject = %s "
        f"LIMIT 1",
        (provider, subject),
    )
    if not rows:
        return None

    row = rows[0]
    return {
        "id": str(row["id"]),
        "email": row.get("email", ""),
        "role": row.get("role", "viewer"),
        "oauth_provider": row.get("oauth_provider", ""),
        "oauth_subject": row.get("oauth_subject", ""),
    }


def find_by_id(user_id: str) -> Optional[dict]:
    """Look up a user by their internal UUID."""
    if not user_id:
        return None

    rows = query(
        f"SELECT id, email, role, oauth_provider, oauth_subject, created_at "
        f"FROM {TABLE} "
        f"WHERE row_type = 'user' AND id = %s "
        f"LIMIT 1",
        (user_id,),
    )
    if not rows:
        return None

    row = rows[0]
    return {
        "id": str(row["id"]),
        "email": row.get("email", ""),
        "role": row.get("role", "viewer"),
        "oauth_provider": row.get("oauth_provider", ""),
        "oauth_subject": row.get("oauth_subject", ""),
    }


def find_by_email(email: str) -> Optional[dict]:
    """Look up a user by email. Used for debugging only."""
    if not email:
        return None

    rows = query(
        f"SELECT id, email, role, oauth_provider, oauth_subject, created_at "
        f"FROM {TABLE} "
        f"WHERE row_type = 'user' AND email = %s "
        f"LIMIT 1",
        (email,),
    )
    if not rows:
        return None

    row = rows[0]
    return {
        "id": str(row["id"]),
        "email": row.get("email", ""),
        "role": row.get("role", "viewer"),
        "oauth_provider": row.get("oauth_provider", ""),
        "oauth_subject": row.get("oauth_subject", ""),
    }


def create_user(email: str, provider: str, subject: str, role: str = "viewer") -> Optional[dict]:
    """
    Create a new user record in the database.

    Used for auto-registration on first Google OAuth login.
    The first user ever created gets 'admin' role; subsequent users get 'viewer'.

    Returns the created user dict or None on failure.
    """
    import uuid

    if not email or not provider or not subject:
        logger.error("[user_store] create_user called with missing fields")
        return None

    # Check if this is the first user — if so, make them admin
    existing_users = query(
        f"SELECT id FROM {TABLE} WHERE row_type = 'user' LIMIT 1"
    )
    if not existing_users:
        role = "admin"
        logger.info("[user_store] First user — assigning admin role to %s", email)

    user_id = str(uuid.uuid4())
    try:
        execute(
            f"INSERT INTO {TABLE} (id, row_type, email, role, oauth_provider, oauth_subject, created_at) "
            f"VALUES (%s, 'user', %s, %s, %s, %s, NOW())",
            (user_id, email, role, provider, subject),
        )
        logger.info("[user_store] Created user: id=%s email=%s role=%s", user_id, email, role)
        return {
            "id": user_id,
            "email": email,
            "role": role,
            "oauth_provider": provider,
            "oauth_subject": subject,
        }
    except Exception as exc:
        logger.error("[user_store] Failed to create user: %s", exc)
        return None
