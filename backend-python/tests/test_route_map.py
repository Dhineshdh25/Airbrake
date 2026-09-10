"""
Route map tests — verifies Flask registers the expected auth routes
and that wrong methods return proper 405 responses (not 500).

Google OAuth routes (/api/auth/google, /api/auth/google/callback) have been
removed and replaced with POST /api/auth/login (local username+password auth).
"""

import os

# Set environment before importing app
os.environ['DEV_AUTH'] = '1'
os.environ['APP_ENV'] = 'development'
os.environ['ALLOWED_ORIGINS'] = 'http://localhost:3000'
os.environ['FRONTEND_URL'] = 'http://localhost:3000'

import pytest
from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE MAP ASSERTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthRouteMapRegistration:
    """Verify the Flask route map contains the expected auth routes."""

    def _get_route_map(self):
        """Return dict of {rule_string: set_of_methods}."""
        route_map = {}
        for rule in app.url_map.iter_rules():
            # Exclude OPTIONS and HEAD (auto-added by Flask)
            methods = rule.methods - {'OPTIONS', 'HEAD'}
            route_map[rule.rule] = methods
        return route_map

    def test_login_route_exists(self):
        """POST /api/auth/login must be registered."""
        route_map = self._get_route_map()
        assert '/api/auth/login' in route_map, \
            "POST /api/auth/login route is missing from the route map"
        assert 'POST' in route_map['/api/auth/login'], \
            "/api/auth/login must accept POST"

    def test_auth_me_route_exists(self):
        route_map = self._get_route_map()
        assert '/api/auth/me' in route_map
        assert 'GET' in route_map['/api/auth/me']

    def test_auth_logout_route_exists(self):
        route_map = self._get_route_map()
        assert '/api/auth/logout' in route_map
        assert 'POST' in route_map['/api/auth/logout']

    def test_auth_csrf_route_exists(self):
        route_map = self._get_route_map()
        assert '/api/auth/csrf' in route_map
        assert 'GET' in route_map['/api/auth/csrf']

    def test_google_login_route_removed(self):
        """GET /api/auth/google must NOT be registered — Google auth removed."""
        route_map = self._get_route_map()
        assert '/api/auth/google' not in route_map, \
            "Google OAuth route /api/auth/google must be removed"

    def test_google_callback_route_removed(self):
        """GET /api/auth/google/callback must NOT be registered."""
        route_map = self._get_route_map()
        assert '/api/auth/google/callback' not in route_map, \
            "Google OAuth callback /api/auth/google/callback must be removed"

    def test_jira_oauth_routes_present(self):
        """Jira OAuth routes must still exist."""
        route_map = self._get_route_map()
        assert '/api/jira/callback' in route_map, \
            "Jira OAuth callback /api/jira/callback must still be registered"


# ═══════════════════════════════════════════════════════════════════════════════
# 405 METHOD NOT ALLOWED — PROPER STATUS CODE (NOT 500)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMethodNotAllowedReturns405:
    """Verify that wrong HTTP methods return 405, not 500."""

    def test_get_to_login_returns_405(self, client):
        """GET /api/auth/login should return 405 (route only accepts POST)."""
        r = client.get('/api/auth/login')
        assert r.status_code == 405
        data = r.get_json()
        assert data['error'] == 'Method Not Allowed'
        assert 'traceback' not in data
        assert 'exception' not in data

    def test_post_to_auth_me_returns_405(self, client):
        """POST /api/auth/me should return 405 (route only accepts GET)."""
        r = client.post('/api/auth/me')
        assert r.status_code == 405
        data = r.get_json()
        assert data['error'] == 'Method Not Allowed'
        assert 'traceback' not in data

    def test_get_to_auth_logout_returns_405(self, client):
        """GET /api/auth/logout should return 405 (route only accepts POST)."""
        r = client.get('/api/auth/logout')
        assert r.status_code == 405
        data = r.get_json()
        assert data['error'] == 'Method Not Allowed'
        assert 'traceback' not in data

    def test_put_to_auth_me_returns_405(self, client):
        """PUT /api/auth/me should return 405."""
        r = client.put('/api/auth/me')
        assert r.status_code == 405
        data = r.get_json()
        assert data['error'] == 'Method Not Allowed'
        assert 'traceback' not in data

    def test_google_route_is_not_functional(self, client):
        """
        GET /api/auth/google must not work — no Google OAuth handler exists.
        Flask may return 404 (no match) or 405 (OPTIONS-only match from CORS).
        Both mean the Google login route is absent.
        """
        r = client.get('/api/auth/google')
        assert r.status_code in (404, 405), \
            f"Expected 404 or 405 for removed Google route, got {r.status_code}"

    def test_google_callback_is_not_functional(self, client):
        """GET /api/auth/google/callback must not work."""
        r = client.get('/api/auth/google/callback')
        assert r.status_code in (404, 405), \
            f"Expected 404 or 405 for removed Google callback, got {r.status_code}"


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR RESPONSE FORMAT — NO TRACEBACK IN PRODUCTION
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorResponseSafety:
    """Verify error responses do not leak internal details."""

    def test_405_response_is_safe_json(self, client):
        """405 response must be clean JSON without traceback."""
        r = client.patch('/api/auth/me')
        assert r.status_code == 405
        data = r.get_json()
        assert set(data.keys()) == {'error'}
        assert data['error'] == 'Method Not Allowed'

    def test_404_response_is_safe_json(self, client):
        """404 response for unknown endpoint must be clean JSON."""
        r = client.get('/nonexistent-endpoint')
        assert r.status_code == 404
        data = r.get_json()
        assert 'traceback' not in data
        assert 'exception' not in data
        assert data['error'] == 'Not Found'
