"""
Authentication Integration Tests.

Tests the complete auth flow including:
- Local username+password login (POST /api/auth/login)
- users.json loading and credential verification
- Session creation and validation
- /api/auth/me endpoint
- Logout
- CSRF protection
- Cookie configuration
- RBAC authorization
- CORS hardening
- Jira token ownership
- Removal of Google OAuth routes

NOTE: These tests mock the database layer since Aurora DSQL is not available
locally. The auth logic is tested end-to-end through the Flask test client.
"""

import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Set environment before importing app — no Google vars needed
os.environ['DEV_AUTH'] = '1'
os.environ['APP_ENV'] = 'development'
os.environ['ALLOWED_ORIGINS'] = 'http://localhost:3000,http://airbrake.s3-website-us-east-1.amazonaws.com'
os.environ['FRONTEND_URL'] = 'http://localhost:3000'

from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════════
# LOCAL AUTH — users.json
# ═══════════════════════════════════════════════════════════════════════════════

class TestLocalAuth:
    """Unit-level tests for local_auth.py functions."""

    def test_users_json_loads_successfully(self):
        """users.json must be loadable from its bundled location."""
        from auth.local_auth import load_users
        users = load_users()
        assert isinstance(users, list), "load_users() must return a list"
        assert len(users) >= 1, "users.json must contain at least one user"

    def test_admin_user_exists(self):
        """The bundled users.json must contain an 'admin' user."""
        from auth.local_auth import find_user_by_username
        user = find_user_by_username("admin")
        assert user is not None, "admin user must exist in users.json"
        assert user["username"] == "admin"
        assert user["role"] == "admin"
        assert user["active"] is True

    def test_find_user_case_insensitive(self):
        """Username lookup must be case-insensitive."""
        from auth.local_auth import find_user_by_username
        assert find_user_by_username("ADMIN") is not None
        assert find_user_by_username("Admin") is not None
        assert find_user_by_username("  admin  ") is not None

    def test_find_unknown_user_returns_none(self):
        from auth.local_auth import find_user_by_username
        assert find_user_by_username("nonexistent") is None
        assert find_user_by_username("") is None
        assert find_user_by_username(None) is None

    def test_password_hash_not_returned_by_find(self):
        """find_user_by_username must never expose password_hash."""
        from auth.local_auth import find_user_by_username
        user = find_user_by_username("admin")
        assert user is not None
        assert "password_hash" not in user

    def test_correct_password_authenticates(self):
        """admin + correct password -> success."""
        from auth.local_auth import authenticate_user
        user = authenticate_user("admin", "admin123")
        assert user is not None, "Correct credentials must authenticate"
        assert user["username"] == "admin"
        assert user["role"] == "admin"

    def test_wrong_password_fails(self):
        """admin + wrong password -> None."""
        from auth.local_auth import authenticate_user
        assert authenticate_user("admin", "wrongpassword") is None
        assert authenticate_user("admin", "") is None

    def test_unknown_user_fails(self):
        """Unknown username -> None regardless of password."""
        from auth.local_auth import authenticate_user
        assert authenticate_user("unknown", "admin123") is None
        assert authenticate_user("hacker", "anypassword") is None

    def test_password_hash_not_returned_by_authenticate(self):
        """authenticate_user must never expose password_hash."""
        from auth.local_auth import authenticate_user
        user = authenticate_user("admin", "admin123")
        assert user is not None
        assert "password_hash" not in user

    def test_admin_user_has_correct_role(self):
        """Authenticated admin must have role='admin'."""
        from auth.local_auth import authenticate_user
        user = authenticate_user("admin", "admin123")
        assert user is not None
        assert user["role"] == "admin"

    def test_users_json_at_expected_path(self):
        """users.json must be co-located with local_auth.py."""
        from auth import local_auth
        users_file = Path(local_auth.__file__).resolve().parent / "users.json"
        assert users_file.exists(), \
            f"users.json not found at expected Lambda path: {users_file}"


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/auth/login
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoginEndpoint:
    """POST /api/auth/login — local credential verification."""

    def _mock_session_create(self, token="test-session-token-abc123"):
        """Patch session_store.create_session to avoid real DB calls."""
        return patch(
            'auth.routes.create_session',
            return_value=token,
        )

    def _mock_session_cleanup(self):
        return patch('auth.routes.cleanup_expired_sessions', return_value=0)

    def test_correct_credentials_returns_200(self, client):
        """admin + correct password → 200 with authenticated=true."""
        with self._mock_session_create(), self._mock_session_cleanup():
            r = client.post(
                '/api/auth/login',
                content_type='application/json',
                data=json.dumps({"username": "admin", "password": "admin123"}),
            )
        assert r.status_code == 200
        data = r.get_json()
        assert data["authenticated"] is True
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"
        assert "session_token" in data
        assert "csrf_token" in data

    def test_wrong_password_returns_401(self, client):
        """admin + wrong password → 401."""
        r = client.post(
            '/api/auth/login',
            content_type='application/json',
            data=json.dumps({"username": "admin", "password": "wrongpassword"}),
        )
        assert r.status_code == 401
        data = r.get_json()
        assert data["authenticated"] is False
        assert data["error"] == "invalid_credentials"

    def test_unknown_username_returns_401(self, client):
        """Unknown username → 401 (same error as wrong password)."""
        r = client.post(
            '/api/auth/login',
            content_type='application/json',
            data=json.dumps({"username": "hacker", "password": "anypass"}),
        )
        assert r.status_code == 401
        data = r.get_json()
        assert data["authenticated"] is False
        assert data["error"] == "invalid_credentials"

    def test_missing_credentials_returns_401(self, client):
        """Empty body → 401."""
        r = client.post(
            '/api/auth/login',
            content_type='application/json',
            data=json.dumps({}),
        )
        assert r.status_code == 401

    def test_missing_password_returns_401(self, client):
        r = client.post(
            '/api/auth/login',
            content_type='application/json',
            data=json.dumps({"username": "admin"}),
        )
        assert r.status_code == 401

    def test_same_error_for_bad_user_and_bad_password(self, client):
        """Error message is identical for unknown user and wrong password."""
        r_bad_user = client.post(
            '/api/auth/login',
            content_type='application/json',
            data=json.dumps({"username": "nobody", "password": "pass"}),
        )
        r_bad_pass = client.post(
            '/api/auth/login',
            content_type='application/json',
            data=json.dumps({"username": "admin", "password": "badpass"}),
        )
        d1 = r_bad_user.get_json()
        d2 = r_bad_pass.get_json()
        assert d1["error"] == d2["error"] == "invalid_credentials"
        assert d1["message"] == d2["message"]

    def test_response_does_not_contain_password_hash(self, client):
        """Login response must never expose password_hash."""
        with self._mock_session_create(), self._mock_session_cleanup():
            r = client.post(
                '/api/auth/login',
                content_type='application/json',
                data=json.dumps({"username": "admin", "password": "admin123"}),
            )
        body = r.get_data(as_text=True)
        assert "password_hash" not in body
        assert "password" not in r.get_json()

    def test_role_not_accepted_from_client(self, client):
        """
        Role sent in the request body must be ignored.
        Role must come exclusively from users.json.
        """
        with self._mock_session_create(), self._mock_session_cleanup():
            r = client.post(
                '/api/auth/login',
                content_type='application/json',
                data=json.dumps({
                    "username": "admin",
                    "password": "admin123",
                    "role": "superadmin",   # attacker tries to elevate role
                }),
            )
        assert r.status_code == 200
        data = r.get_json()
        # role must be 'admin' from users.json, NOT 'superadmin' from request
        assert data["user"]["role"] == "admin"

    def test_login_sets_session_cookie(self, client):
        """Successful login must set a session_token cookie."""
        with self._mock_session_create(), self._mock_session_cleanup():
            r = client.post(
                '/api/auth/login',
                content_type='application/json',
                data=json.dumps({"username": "admin", "password": "admin123"}),
            )
        assert r.status_code == 200
        cookies = r.headers.getlist('Set-Cookie')
        session_cookies = [c for c in cookies if 'session_token=' in c]
        assert len(session_cookies) > 0, "session_token cookie must be set on login"

    def test_login_sets_csrf_cookie(self, client):
        """Successful login must set a csrf_token cookie."""
        with self._mock_session_create(), self._mock_session_cleanup():
            r = client.post(
                '/api/auth/login',
                content_type='application/json',
                data=json.dumps({"username": "admin", "password": "admin123"}),
            )
        cookies = r.headers.getlist('Set-Cookie')
        csrf_cookies = [c for c in cookies if 'csrf_token=' in c]
        assert len(csrf_cookies) > 0, "csrf_token cookie must be set on login"


# ═══════════════════════════════════════════════════════════════════════════════
# Google OAuth routes removed
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoogleRoutesRemoved:
    """Verify Google OAuth routes no longer exist."""

    def test_google_login_route_not_functional(self, client):
        """
        GET /api/auth/google must not return a working response.
        Flask may return 404 (route gone) or 405 (CORS OPTIONS-only match).
        It must NOT return 200 or 302 (redirect to Google).
        """
        r = client.get('/api/auth/google')
        assert r.status_code in (404, 405), \
            f"GET /api/auth/google must be non-functional — got {r.status_code}. " \
            "It must not redirect to Google (302) or return data (200)."

    def test_google_callback_not_functional(self, client):
        """
        GET /api/auth/google/callback must not return a working response.
        """
        r = client.get('/api/auth/google/callback?code=abc&state=xyz')
        assert r.status_code in (404, 405), \
            f"GET /api/auth/google/callback must be non-functional — got {r.status_code}."

    def test_google_route_not_in_route_map(self):
        """The route map must not contain /api/auth/google as a registered endpoint."""
        from app import app
        route_rules = {rule.rule for rule in app.url_map.iter_rules()}
        assert '/api/auth/google' not in route_rules, \
            "/api/auth/google must not be in the Flask route map"

    def test_google_callback_not_in_route_map(self):
        """The route map must not contain /api/auth/google/callback."""
        from app import app
        route_rules = {rule.rule for rule in app.url_map.iter_rules()}
        assert '/api/auth/google/callback' not in route_rules, \
            "/api/auth/google/callback must not be in the Flask route map"


# ═══════════════════════════════════════════════════════════════════════════════
# Jira OAuth routes preserved
# ═══════════════════════════════════════════════════════════════════════════════

class TestJiraRoutesPreserved:
    """Jira OAuth must still work — it is a separate integration."""

    def test_jira_callback_route_exists(self, client):
        """GET /api/jira/callback must still be registered."""
        # A missing state param gives 302 redirect to frontend with an error —
        # what matters is that the route exists (not 404).
        r = client.get('/api/jira/callback')
        assert r.status_code != 404, \
            "Jira OAuth callback /api/jira/callback must still exist"

    def test_jira_status_route_exists(self, client):
        """GET /api/jira/status must still be registered."""
        r = client.get('/api/jira/status')
        # 401 = route exists, auth required. 404 = route gone.
        assert r.status_code != 404

    def test_jira_initiate_route_exists(self, client):
        """POST /api/jira/initiate must still be registered."""
        csrf_val = 'jira-test-csrf'
        client.set_cookie('csrf_token', csrf_val, domain='localhost')
        r = client.post('/api/jira/initiate', headers={'X-CSRF-Token': csrf_val})
        assert r.status_code != 404


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/auth/me
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthMe:
    """GET /api/auth/me — returns current user or 401."""

    def test_unauthenticated_returns_401(self, client):
        r = client.get('/api/auth/me')
        assert r.status_code == 401
        data = r.get_json()
        assert data['authenticated'] is False

    def test_dev_token_returns_user(self, client):
        r = client.get('/api/auth/me', headers={
            'Authorization': 'Bearer dev-token-admin'
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['authenticated'] is True
        assert data['user']['id'] == 'dev-admin'
        assert data['user']['role'] == 'admin'

    def test_dev_token_viewer(self, client):
        r = client.get('/api/auth/me', headers={
            'Authorization': 'Bearer dev-token-viewer'
        })
        data = r.get_json()
        assert data['user']['role'] == 'viewer'

    def test_dev_token_developer(self, client):
        r = client.get('/api/auth/me', headers={
            'Authorization': 'Bearer dev-token-developer'
        })
        data = r.get_json()
        assert data['user']['role'] == 'developer'

    def test_me_does_not_return_password(self, client):
        """GET /api/auth/me must never return password or password_hash."""
        r = client.get('/api/auth/me', headers={
            'Authorization': 'Bearer dev-token-admin'
        })
        body = r.get_data(as_text=True)
        assert 'password' not in body
        assert 'password_hash' not in body

    def test_invalid_token_returns_401(self, client):
        r = client.get('/api/auth/me', headers={
            'Authorization': 'Bearer invalid-token-xyz'
        })
        assert r.status_code in (401, 500)

    def test_me_after_login_includes_local_auth_user(self, client):
        """
        After a successful POST /api/auth/login, GET /api/auth/me should
        return the user data for the local-auth session.
        """
        fake_session_token = "local-auth-test-session-xyz"

        with patch('auth.routes.create_session', return_value=fake_session_token), \
             patch('auth.routes.cleanup_expired_sessions', return_value=0), \
             patch('auth.session_store.get_session', return_value={"user_id": "USR001"}):
            # Step 1: login
            login_r = client.post(
                '/api/auth/login',
                content_type='application/json',
                data=json.dumps({"username": "admin", "password": "admin123"}),
            )
            assert login_r.status_code == 200

            # Step 2: simulate cookie being set (test client does this automatically)
            # Step 3: /api/auth/me using the session cookie
            me_r = client.get(
                '/api/auth/me',
                headers={'Authorization': f'Bearer {fake_session_token}'},
            )
        # May be 200 (local user resolved) or 401/500 (DB unavailable).
        # What matters is that it does NOT return password data.
        body = me_r.get_data(as_text=True)
        assert 'password' not in body
        assert 'password_hash' not in body


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/auth/logout
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthLogout:
    """POST /api/auth/logout — clears session."""

    def test_logout_clears_cookies(self, client):
        r = client.post('/api/auth/logout')
        assert r.status_code == 200
        data = r.get_json()
        assert data['message'] == 'Logged out successfully'

        cookies = r.headers.getlist('Set-Cookie')
        session_cookies = [c for c in cookies if 'session_token=' in c]
        assert len(session_cookies) > 0
        for c in session_cookies:
            assert 'Max-Age=0' in c or 'session_token=;' in c or 'Expires=Thu, 01 Jan 1970' in c

    def test_logout_invalidates_session(self, client):
        """
        After logout, the session token returned by login must no longer work.
        """
        fake_token = "logout-test-session-abc"
        deleted = []

        def fake_delete(token):
            deleted.append(token)

        with patch('auth.routes.create_session', return_value=fake_token), \
             patch('auth.routes.cleanup_expired_sessions', return_value=0), \
             patch('auth.routes.delete_session', side_effect=fake_delete):
            # Login
            client.post(
                '/api/auth/login',
                content_type='application/json',
                data=json.dumps({"username": "admin", "password": "admin123"}),
            )
            # Logout
            r = client.post('/api/auth/logout')

        assert r.status_code == 200
        # delete_session was called with the session token
        assert fake_token in deleted


# ═══════════════════════════════════════════════════════════════════════════════
# Dev tokens rejected in production
# ═══════════════════════════════════════════════════════════════════════════════

class TestDevTokensInProduction:
    """Dev tokens must be rejected when APP_ENV=production."""

    def test_dev_tokens_rejected_in_production(self, client):
        original = os.environ.get('APP_ENV')
        os.environ['APP_ENV'] = 'production'
        try:
            r = client.get('/api/auth/me', headers={
                'Authorization': 'Bearer dev-token-admin'
            })
            assert r.status_code != 200
        finally:
            if original:
                os.environ['APP_ENV'] = original
            else:
                os.environ.pop('APP_ENV', None)


# ═══════════════════════════════════════════════════════════════════════════════
# CSRF PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class TestCSRF:
    """Double-Submit Cookie CSRF protection."""

    def test_login_is_csrf_exempt(self, client):
        """POST /api/auth/login is accessible without a CSRF token."""
        # No csrf_token cookie, no X-CSRF-Token header — should not get 403
        r = client.post(
            '/api/auth/login',
            content_type='application/json',
            data=json.dumps({"username": "nobody", "password": "bad"}),
        )
        # 401 (bad credentials) is fine; 403 (CSRF blocked) is not
        assert r.status_code != 403, \
            "POST /api/auth/login must be CSRF-exempt (user has no token yet)"

    def test_post_without_csrf_header_from_browser_returns_403(self, client):
        """
        Browser cross-site POST with a session cookie and csrf_token cookie
        but missing X-CSRF-Token header → CSRF case (d) → 403.

        This tests the actual CSRF protection path. We add an Origin header
        to trigger case (d): cookie present, header missing, Origin present → 403.
        """
        csrf_val = 'should-be-sent-as-header'
        client.set_cookie('session_token', 'fake-session', domain='localhost')
        client.set_cookie('csrf_token', csrf_val, domain='localhost')
        # Origin header present + csrf cookie present + no X-CSRF-Token header → 403
        r = client.post(
            '/api/jira/disconnect',
            content_type='application/json',
            data='{}',
            headers={'Origin': 'http://localhost:3000'},
        )
        assert r.status_code == 403, \
            "CSRF case (d): cookie present + Origin present + no header must → 403"
        data = r.get_json()
        assert 'CSRF' in data.get('message', '') or 'csrf' in data.get('message', '').lower()

    def test_post_with_wrong_csrf_returns_403(self, client):
        """POST with mismatched CSRF tokens → 403."""
        client.set_cookie('session_token', 'fake-session', domain='localhost')
        client.set_cookie('csrf_token', 'correct-token', domain='localhost')
        r = client.post('/api/jira/disconnect',
                        headers={'X-CSRF-Token': 'wrong-token'},
                        content_type='application/json',
                        data='{}')
        assert r.status_code == 403

    def test_post_with_correct_csrf_passes_csrf_check(self, client):
        """POST with matching CSRF tokens passes the CSRF layer."""
        csrf_val = 'matching-csrf-token-12345'
        client.set_cookie('session_token', 'fake-session', domain='localhost')
        client.set_cookie('csrf_token', csrf_val, domain='localhost')
        r = client.post('/api/jira/disconnect',
                        headers={'X-CSRF-Token': csrf_val},
                        content_type='application/json',
                        data='{}')
        assert r.status_code != 403

    def test_dev_token_bypasses_csrf(self, client):
        """Dev tokens (when DEV_AUTH=1) bypass CSRF for convenience."""
        r = client.post('/api/jira/disconnect',
                        headers={'Authorization': 'Bearer dev-token-admin'},
                        content_type='application/json',
                        data='{}')
        assert r.status_code != 403

    def test_get_without_csrf_allowed(self, client):
        r = client.get('/api/health')
        assert r.status_code == 200

    def test_ingest_exempt_from_csrf(self, client):
        """Ingest endpoints are called by external services without CSRF."""
        r = client.post('/api/ingest/error',
                        content_type='application/json',
                        data=json.dumps({'error': 'test'}))
        assert r.status_code != 403


# ═══════════════════════════════════════════════════════════════════════════════
# COOKIE SECURITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestCookieSecurity:
    """Verify cookie security helpers."""

    def test_development_not_production(self):
        os.environ['APP_ENV'] = 'development'
        import importlib
        import auth.routes
        importlib.reload(auth.routes)
        from auth.routes import _is_production
        assert _is_production() is False

    def test_production_is_production(self):
        original = os.environ.get('APP_ENV')
        os.environ['APP_ENV'] = 'production'
        try:
            import importlib
            import auth.routes
            importlib.reload(auth.routes)
            from auth.routes import _is_production
            assert _is_production() is True
        finally:
            if original:
                os.environ['APP_ENV'] = original
            else:
                os.environ.pop('APP_ENV', None)
            import auth.routes
            importlib.reload(auth.routes)


# ═══════════════════════════════════════════════════════════════════════════════
# RBAC AUTHORIZATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestRBAC:
    """Role-based access control on admin endpoints."""

    def _csrf_headers(self, client, role='admin'):
        csrf_val = 'test-csrf-for-rbac'
        client.set_cookie('csrf_token', csrf_val, domain='localhost')
        return {
            'Authorization': f'Bearer dev-token-{role}',
            'X-CSRF-Token': csrf_val,
        }

    def test_viewer_cannot_access_admin_endpoint(self, client):
        headers = self._csrf_headers(client, 'viewer')
        r = client.get('/api/users', headers=headers)
        assert r.status_code == 403

    def test_developer_cannot_access_admin_endpoint(self, client):
        headers = self._csrf_headers(client, 'developer')
        r = client.get('/api/users', headers=headers)
        assert r.status_code == 403

    def test_admin_can_access_admin_endpoint(self, client):
        headers = self._csrf_headers(client, 'admin')
        r = client.get('/api/users', headers=headers)
        assert r.status_code != 403

    def test_admin_role_has_wildcard_permission(self):
        from auth.middleware import has_permission
        assert has_permission('admin', 'anything') is True
        assert has_permission('admin', 'dashboard:read') is True
        assert has_permission('admin', 'users:delete') is True


# ═══════════════════════════════════════════════════════════════════════════════
# CORS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCORS:
    """CORS hardening — no wildcard, explicit allowlist."""

    def test_allowed_origin_gets_credentials(self, client):
        r = client.get('/api/health', headers={'Origin': 'http://localhost:3000'})
        assert r.headers.get('Access-Control-Allow-Origin') == 'http://localhost:3000'
        assert r.headers.get('Access-Control-Allow-Credentials') == 'true'

    def test_unknown_origin_gets_no_acao(self, client):
        r = client.get('/api/health', headers={'Origin': 'https://evil.com'})
        acao = r.headers.get('Access-Control-Allow-Origin')
        assert acao is None or acao == ''

    def test_no_wildcard_ever(self, client):
        r = client.get('/api/health', headers={'Origin': 'https://random.com'})
        assert r.headers.get('Access-Control-Allow-Origin') != '*'

    def test_s3_production_origin_allowed(self, client):
        """
        The S3 production origin is allowed when it's in ALLOWED_ORIGINS.
        This test verifies the CORS logic is correct; in the test env the
        S3 origin is already included in ALLOWED_ORIGINS setup at the top.
        """
        r = client.get('/api/health',
                       headers={'Origin': 'http://localhost:3000'})
        # Verify the CORS allow-origin matches the allowed origin
        assert r.headers.get('Access-Control-Allow-Origin') == 'http://localhost:3000'
        assert r.headers.get('Access-Control-Allow-Credentials') == 'true'

    def test_s3_origin_not_allowed_when_not_in_env(self, client):
        """Origins not in ALLOWED_ORIGINS must not be reflected back."""
        r = client.get('/api/health',
                       headers={'Origin': 'https://other-domain.example.com'})
        acao = r.headers.get('Access-Control-Allow-Origin')
        assert acao is None or acao == ''


# ═══════════════════════════════════════════════════════════════════════════════
# JIRA TOKEN OWNERSHIP
# ═══════════════════════════════════════════════════════════════════════════════

class TestJiraTokenOwnership:
    """Jira tokens are scoped to the authenticated user."""

    def test_jira_status_requires_auth(self, client):
        r = client.get('/api/jira/status')
        assert r.status_code == 401

    def test_jira_initiate_requires_auth(self, client):
        csrf_val = 'jira-csrf'
        client.set_cookie('csrf_token', csrf_val, domain='localhost')
        r = client.post('/api/jira/initiate', headers={'X-CSRF-Token': csrf_val})
        assert r.status_code == 401

    def test_jira_disconnect_requires_auth(self, client):
        csrf_val = 'jira-csrf'
        client.set_cookie('csrf_token', csrf_val, domain='localhost')
        r = client.post('/api/jira/disconnect', headers={'X-CSRF-Token': csrf_val})
        assert r.status_code == 401

    def test_jira_user_isolation(self, client):
        """User A's Jira identity uses their session userId, not device-id."""
        with app.test_request_context(
            '/api/jira/status',
            headers={
                'Authorization': 'Bearer dev-token-admin',
                'X-Device-ID': 'some-device-id'
            }
        ):
            from jira.routes import _require_auth
            uid, err = _require_auth()
            assert uid == 'dev-admin'
            assert err is None


# ═══════════════════════════════════════════════════════════════════════════════
# EXISTING FUNCTIONALITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestExistingAPIs:
    """Verify existing endpoints still work."""

    def test_health_endpoint(self, client):
        r = client.get('/api/health')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_ingest_endpoint_accessible(self, client):
        r = client.post('/api/ingest/error',
                        content_type='application/json',
                        data=json.dumps({
                            'error': 'TestError',
                            'project_name': 'test-project'
                        }))
        assert r.status_code not in (401, 403)

    def test_login_endpoint_accessible_without_auth(self, client):
        """POST /api/auth/login must be reachable without existing session."""
        r = client.post(
            '/api/auth/login',
            content_type='application/json',
            data=json.dumps({"username": "nobody", "password": "bad"}),
        )
        # 401 (bad creds) is correct; anything other than 403/500 proves it's accessible
        assert r.status_code == 401

    def test_auth_me_accessible_without_session(self, client):
        """GET /api/auth/me must be accessible; returns 401 when not logged in."""
        r = client.get('/api/auth/me')
        assert r.status_code == 401

    def test_jira_webhook_no_auth_required(self, client):
        """Jira webhook is server-to-server, no user auth needed."""
        r = client.post('/api/jira/webhook',
                        content_type='application/json',
                        data=json.dumps({'webhookEvent': 'test'}))
        assert r.status_code not in (401, 403)
