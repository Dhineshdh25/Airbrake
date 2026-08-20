"""
Global pytest configuration.

Patches the db layer at every import site so no test can accidentally hit
Aurora DSQL without an explicit mock override. All patches return safe empty
results by default.

Individual tests that need specific DB behaviour override these with their
own patch() context managers.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# ── Env must be set before any app import ────────────────────────────────────
os.environ.setdefault("DEV_AUTH", "1")
os.environ.setdefault("APP_ENV", "development")


@pytest.fixture(autouse=True, scope="session")
def block_real_db():
    """
    Session-scoped fixture that stubs out the DB layer across every module
    that imported db.query / db.execute / db.execute_returning.

    For auth.session_store.query, we return a fake session for the token
    "fake-session" so that CSRF tests (which send that cookie) get a valid
    session object back and can reach the CSRF gate.
    """
    import json as _json

    def _session_store_query(sql, params=None):
        """Return a fake session row for known test tokens."""
        p = list(params or [])
        token_val = p[0] if p else None
        if token_val == "fake-session":
            return [{
                "id": "fake-row-id",
                "metadata": _json.dumps({
                    "token": "fake-session",
                    "user_id": "dev-admin",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                }),
            }]
        return []

    def _user_store_query(sql, params=None):
        """Return a fake user row for known dev user IDs."""
        p = list(params or [])
        uid = p[0] if p else None
        known = {
            "dev-admin": {"id": "dev-admin", "email": "dev-admin@dev.local",
                          "role": "admin", "oauth_provider": "dev", "oauth_subject": "dev-admin"},
            "dev-developer": {"id": "dev-developer", "email": "dev-developer@dev.local",
                              "role": "developer", "oauth_provider": "dev", "oauth_subject": "dev-developer"},
            "dev-viewer": {"id": "dev-viewer", "email": "dev-viewer@dev.local",
                           "role": "viewer", "oauth_provider": "dev", "oauth_subject": "dev-viewer"},
        }
        if uid and uid in known:
            u = known[uid]
            return [{"id": u["id"], "email": u["email"], "role": u["role"],
                     "oauth_provider": u["oauth_provider"], "oauth_subject": u["oauth_subject"],
                     "created_at": None}]
        return []

    with patch("db.query", return_value=[]), \
         patch("db.execute", return_value=0), \
         patch("db.execute_returning", return_value=None), \
         patch("auth.session_store.query", side_effect=_session_store_query), \
         patch("auth.user_store.query", side_effect=_user_store_query), \
         patch("auth.middleware.find_by_id", side_effect=lambda uid: {
             "dev-admin": {"id": "dev-admin", "email": "dev-admin@dev.local", "role": "admin",
                           "oauth_provider": "dev", "oauth_subject": "dev-admin"},
             "dev-developer": {"id": "dev-developer", "email": "dev-developer@dev.local", "role": "developer",
                               "oauth_provider": "dev", "oauth_subject": "dev-developer"},
             "dev-viewer": {"id": "dev-viewer", "email": "dev-viewer@dev.local", "role": "viewer",
                            "oauth_provider": "dev", "oauth_subject": "dev-viewer"},
         }.get(uid)), \
         patch("jira.token_store.query", return_value=[]), \
         patch("jira.token_store.execute", return_value=0):
        yield
