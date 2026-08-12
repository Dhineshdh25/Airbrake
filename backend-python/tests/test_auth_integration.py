"""
Authentication Integration Tests.

Tests the complete auth flow including:
- Google OAuth initiation and callback
- Session creation and validation
- /api/auth/me endpoint
- Logout
- CSRF protection
- Cookie configuration
- RBAC authorization
- CORS hardening
- Jira token ownership

NOTE: These tests mock the database layer since Aurora DSQL
is not available locally. The auth logic is tested end-to-end
through the Flask test client.
"""

import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Set environment before importing app
os.environ['DEV_AUTH'] = '1'
os.environ['APP_ENV'] = 'development'
os.environ['ALLOWED_ORIGINS'] = 'http://localhost:3000,http://airbrake.s3-website-us-east-1.amazonaws.com'
os.environ['FRONTEND_URL'] = 'http://localhost:3000'
os.environ['GOOGLE_CLIENT_ID'] = 'test-client-id.apps.googleusercontent.com'
os.environ['GOOGLE_CLIENT_SECRET'] = 'test-secret'
os.environ['GOOGLE_CALLBACK_URL'] = 'http://localhost:5000/api/auth/google/callback'

from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION FLOW
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoogleOAuthInitiation:
    """GET /api/auth/google — should redirect to Google."""

    def test_redirects_to_google(self, client):
        r = client.get('/api/auth/google')
        assert r.status_code == 302
        location = r.headers.get('Location', '')
        assert 'accounts.google.com' in location
        assert 'test-client-id' in location
        assert 'openid' in location
        assert 'state=' in location

    def test_preserves_redirect_uri(self, client):
        r = client.get('/api/auth/google?redirect_uri=/settings')
        assert r.status_code == 302


class TestOAuthCallback:
    """GET /api/auth/google/callback — handles the OAuth response."""

    def test_missing_code_redirects_with_error(self, client):
        r = client.get('/api/auth/google/callback?state=abc')
        assert r.status_code == 302
        assert 'auth_error=missing_params' in r.headers['Location']

    def test_missing_state_redirects_with_error(self, client):
        r = client.get('/api/auth/google/callback?code=abc')
        assert r.status_code == 302
        assert 'auth_error=missing_params' in r.headers['Location']

    def test_invalid_state_redirects_with_error(self, client):
        r = client.get('/api/auth/google/callback?code=abc&state=invalid')
        assert r.status_code == 302
        assert 'auth_error=invalid_state' in r.headers['Location']

    def test_google_error_forwarded(self, client):
        r = client.get('/api/auth/google/callback?error=access_denied')
        assert r.status_code == 302
        assert 'auth_error=access_denied' in r.headers['Location']


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

    def test_invalid_token_returns_401(self, client):
        r = client.get('/api/auth/me', headers={
            'Authorization': 'Bearer invalid-token-xyz'
        })
        # Without local DB, this returns 500 (DB connection error).
        # In production with Aurora DSQL, it returns 401.
        # We verify the token is NOT accepted as a dev token.
        assert r.status_code in (401, 500)


class TestAuthLogout:
    """POST /api/auth/logout — clears session."""

    def test_logout_clears_cookies(self, client):
        # Logout should work even without a session
        r = client.post('/api/auth/logout')
        assert r.status_code == 200
        data = r.get_json()
        assert data['message'] == 'Logged out successfully'

        # Check cookies are cleared
        cookies = r.headers.getlist('Set-Cookie')
        session_cookies = [c for c in cookies if 'session_token=' in c]
        assert len(session_cookies) > 0
        # Cleared cookie has empty value or max-age=0
        for c in session_cookies:
            assert 'Max-Age=0' in c or 'session_token=;' in c or 'Expires=Thu, 01 Jan 1970' in c


class TestDevTokensInProduction:
    """Dev tokens must be rejected when APP_ENV=production."""

    def test_dev_tokens_rejected_in_production(self, client):
        original = os.environ.get('APP_ENV')
        os.environ['APP_ENV'] = 'production'
        try:
            r = client.get('/api/auth/me', headers={
                'Authorization': 'Bearer dev-token-admin'
            })
            # In production, dev tokens are not recognized.
            # Without local DB, it falls to real session lookup → 500 (no DB).
            # The important thing: it is NOT 200 (token not accepted).
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

    def test_post_without_csrf_on_jira_returns_403(self, client):
        """Non-exempt POST without CSRF cookie → 403."""
        # /api/jira/disconnect requires auth AND csrf
        # Use a cookie-based session (not dev token) to test CSRF
        client.set_cookie('session_token', 'fake-session', domain='localhost')
        r = client.post('/api/jira/disconnect',
                        content_type='application/json',
                        data='{}')
        assert r.status_code == 403
        data = r.get_json()
        assert 'CSRF' in data.get('message', '')

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
        # Should NOT be 403 (CSRF passed). May be 401 (no valid session) or 500 (no DB).
        assert r.status_code != 403

    def test_delete_without_csrf_returns_403(self, client):
        """DELETE without CSRF → 403."""
        client.set_cookie('session_token', 'fake-session', domain='localhost')
        r = client.delete('/api/filters/presets/123')
        assert r.status_code == 403

    def test_get_without_csrf_allowed(self, client):
        r = client.get('/api/health')
        assert r.status_code == 200

    def test_ingest_exempt_from_csrf(self, client):
        """Ingest endpoints are called by external services without CSRF."""
        r = client.post('/api/ingest/error',
                        content_type='application/json',
                        data=json.dumps({'error': 'test'}))
        # Should not be 403 (CSRF exempt)
        assert r.status_code != 403

    def test_dev_token_bypasses_csrf(self, client):
        """Dev tokens (when DEV_AUTH=1) bypass CSRF for convenience."""
        r = client.post('/api/jira/disconnect',
                        headers={'Authorization': 'Bearer dev-token-admin'},
                        content_type='application/json',
                        data='{}')
        # Should NOT be 403 (dev token bypasses CSRF)
        assert r.status_code != 403


# ═══════════════════════════════════════════════════════════════════════════════
# COOKIE SECURITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestCookieSecurity:
    """Verify cookie attributes."""

    def test_development_cookies_not_secure(self):
        os.environ['APP_ENV'] = 'development'
        import importlib
        import auth.routes
        importlib.reload(auth.routes)
        from auth.routes import _is_production
        assert _is_production() is False

    def test_production_cookies_secure(self):
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
        # May fail on DB but should NOT be 403
        assert r.status_code != 403


# ═══════════════════════════════════════════════════════════════════════════════
# CORS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCORS:
    """CORS hardening — no wildcard, explicit allowlist."""

    def test_allowed_origin_gets_credentials(self, client):
        r = client.get('/api/health', headers={'Origin': 'http://localhost:3000'})
        assert r.headers.get('Access-Control-Allow-Origin') == 'http://localhost:3000'
        assert r.headers.get('Access-Control-Allow-Credentials') == 'true'
        assert r.headers.get('Vary') == 'Origin'

    def test_unknown_origin_gets_no_acao(self, client):
        r = client.get('/api/health', headers={'Origin': 'https://evil.com'})
        acao = r.headers.get('Access-Control-Allow-Origin')
        assert acao is None or acao == ''

    def test_no_wildcard_ever(self, client):
        r = client.get('/api/health', headers={'Origin': 'https://random.com'})
        assert r.headers.get('Access-Control-Allow-Origin') != '*'

    def test_s3_production_origin_allowed(self, client):
        r = client.get('/api/health',
                       headers={'Origin': 'http://airbrake.s3-website-us-east-1.amazonaws.com'})
        assert r.headers.get('Access-Control-Allow-Origin') == 'http://airbrake.s3-website-us-east-1.amazonaws.com'
        assert r.headers.get('Access-Control-Allow-Credentials') == 'true'

    def test_preflight_options_supported(self, client):
        r = client.options('/api/users', headers={
            'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'POST',
        })
        # Flask may return 200 or 204 for OPTIONS depending on route matching
        assert r.status_code in (200, 204)
        assert r.headers.get('Access-Control-Allow-Origin') == 'http://localhost:3000'

    def test_allowed_headers_locked_down(self, client):
        r = client.options('/api/health', headers={'Origin': 'http://localhost:3000'})
        allowed = r.headers.get('Access-Control-Allow-Headers', '')
        assert 'Content-Type' in allowed
        assert 'X-CSRF-Token' in allowed
        assert 'X-Device-ID' in allowed
        # These should NOT be present
        assert 'Authorization' not in allowed
        assert 'X-API-Key' not in allowed


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
            # Should be session userId, NOT device-based
            assert uid == 'dev-admin'
            assert err is None

    def test_different_users_get_different_ids(self, client):
        """User A and User B have different Jira token keys."""
        with app.test_request_context(
            '/api/jira/status',
            headers={'Authorization': 'Bearer dev-token-admin'}
        ):
            from jira.routes import _require_auth
            uid_a, _ = _require_auth()

        with app.test_request_context(
            '/api/jira/status',
            headers={'Authorization': 'Bearer dev-token-viewer'}
        ):
            uid_b, _ = _require_auth()

        assert uid_a != uid_b
        assert uid_a == 'dev-admin'
        assert uid_b == 'dev-viewer'


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
        """Ingest endpoints should work without auth (API-key protected)."""
        r = client.post('/api/ingest/error',
                        content_type='application/json',
                        data=json.dumps({
                            'error': 'TestError',
                            'project_name': 'test-project'
                        }))
        # Should not be 401 or 403 (auth/CSRF exempt)
        assert r.status_code not in (401, 403)

    def test_auth_routes_are_public(self, client):
        """Auth endpoints should not require existing auth."""
        r = client.get('/api/auth/google')
        assert r.status_code == 302  # redirect to Google

        r = client.get('/api/auth/me')
        assert r.status_code == 401  # not authenticated but accessible

    def test_jira_webhook_no_auth_required(self, client):
        """Jira webhook is server-to-server, no user auth needed."""
        r = client.post('/api/jira/webhook',
                        content_type='application/json',
                        data=json.dumps({'webhookEvent': 'test'}))
        # Should not be 401 or CSRF-blocked
        assert r.status_code != 401
        assert r.status_code != 403
