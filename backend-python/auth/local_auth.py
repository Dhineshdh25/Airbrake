"""
Local JSON-backed authentication service.

Loads users from auth/users.json bundled with the Lambda deployment.
Never queries a remote database for credential verification — auth is
entirely local to the Lambda package.

Public API:
  load_users()                          -> list[dict]
  find_user_by_username(username)       -> dict | None
  authenticate_user(username, password) -> dict | None

Security rules enforced here:
  - Username comparison is case-insensitive and whitespace-stripped.
  - Password verification uses werkzeug check_password_hash() (constant-time).
  - Passwords and password_hash values are NEVER logged.
  - password_hash is NEVER included in returned user dicts.
  - Only active == true users are returned.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from werkzeug.security import check_password_hash

logger = logging.getLogger(__name__)

# Absolute path relative to this file — works correctly inside Lambda zip
USERS_FILE = Path(__file__).resolve().parent / "users.json"

# ── Safe public user fields returned to callers ───────────────────────────────
# password_hash is explicitly excluded from all returned dicts.
_PUBLIC_FIELDS = {"id", "username", "role", "active"}


def load_users() -> list:
    """
    Load and return the raw user list from users.json.

    Returns an empty list if the file cannot be read or parsed.
    Never raises — callers can always assume a list is returned.
    """
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        users = data.get("users", [])
        if not isinstance(users, list):
            logger.error("[LocalAuth] users.json 'users' key is not a list")
            return []
        logger.debug("[LocalAuth] Loaded %d user(s) from users.json", len(users))
        return users
    except FileNotFoundError:
        logger.error("[LocalAuth] users.json not found at %s", USERS_FILE)
        return []
    except json.JSONDecodeError as exc:
        logger.error("[LocalAuth] users.json is not valid JSON: %s", exc)
        return []
    except Exception as exc:
        logger.error("[LocalAuth] Unexpected error loading users.json: %s", exc)
        return []


def find_user_by_username(username: str) -> Optional[dict]:
    """
    Look up a user by username (case-insensitive, whitespace-stripped).

    Returns a dict with public fields only:
      { "id", "username", "role", "active" }

    Returns None if:
      - username is empty / None
      - no matching user is found
      - matched user is inactive (active != true)

    password_hash is NEVER included in the returned dict.
    """
    if not username:
        return None

    normalised = username.strip().lower()
    users = load_users()

    for user in users:
        stored = (user.get("username") or "").strip().lower()
        if stored == normalised:
            if not user.get("active", False):
                logger.info("[LocalAuth] User '%s' found but is inactive", normalised)
                return None
            # Return only safe public fields — never expose password_hash
            return {
                "id": user.get("id", ""),
                "username": user.get("username", ""),
                "role": user.get("role", "viewer"),
                "active": user.get("active", False),
            }

    return None


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    Verify a username + password combination against users.json.

    Returns a safe public user dict on success:
      { "id", "username", "role" }

    Returns None on any failure:
      - empty / missing credentials
      - unknown username
      - inactive user
      - wrong password

    Uses the same error path for all failure modes to prevent
    username enumeration through timing differences.

    NEVER logs the password or password_hash.
    """
    if not username or not password:
        return None

    normalised = username.strip().lower()
    users = load_users()

    # Find the matching raw user record (includes password_hash for verification)
    matched_user = None
    for user in users:
        stored = (user.get("username") or "").strip().lower()
        if stored == normalised:
            matched_user = user
            break

    # Always run password check — avoids timing side-channel on username miss.
    # If no user was found we check against a dummy hash (which always fails).
    _DUMMY_HASH = "scrypt:32768:8:1$dummy$" + "0" * 64
    candidate_hash = (matched_user or {}).get("password_hash", _DUMMY_HASH)

    try:
        password_ok = check_password_hash(candidate_hash, password)
    except Exception as exc:
        # Malformed hash in users.json — treat as auth failure, log hash issue
        logger.error("[LocalAuth] Password hash verification error for user '%s': %s", normalised, exc)
        password_ok = False

    if matched_user is None or not password_ok:
        # Generic failure — do not distinguish "wrong user" from "wrong password"
        logger.info("[LocalAuth] Authentication failed for username='%s'", normalised)
        return None

    if not matched_user.get("active", False):
        logger.info("[LocalAuth] Authentication rejected — user '%s' is inactive", normalised)
        return None

    logger.info(
        "[LocalAuth] Authentication successful: id=%s username=%s role=%s",
        matched_user.get("id"),
        matched_user.get("username"),
        matched_user.get("role"),
    )

    # Return only safe public fields — password_hash is never returned
    return {
        "id": matched_user.get("id", ""),
        "username": matched_user.get("username", ""),
        "role": matched_user.get("role", "viewer"),
    }
