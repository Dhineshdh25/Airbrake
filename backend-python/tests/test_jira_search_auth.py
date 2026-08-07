import unittest
from unittest.mock import patch

import app as app_module
from jira import routes as jira_routes


class JiraSearchAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_search_returns_not_connected_error_when_jira_token_missing(self):
        with patch.object(jira_routes, "_get_session", return_value={"userId": "device-123", "role": "admin"}), \
             patch.object(jira_routes, "get_token", return_value=None):
            response = self.client.get(
                "/api/jira/search?jql=project%20%3D%20ABC&maxResults=10",
                headers={
                    "Authorization": "Bearer dev-token-admin",
                    "X-Device-ID": "123",
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "Jira account not connected")

    def test_search_returns_401_for_invalid_auth(self):
        with patch.object(jira_routes, "_get_session", return_value=None):
            response = self.client.get(
                "/api/jira/search?jql=project%20%3D%20ABC&maxResults=10",
                headers={"Authorization": "Bearer invalid-token"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Unauthorized")

    def test_dev_tokens_are_rejected_in_production(self):
        with patch.dict("os.environ", {"NODE_ENV": "production"}, clear=False):
            with patch.object(jira_routes, "_get_session", wraps=jira_routes._get_session) as wrapped:
                response = self.client.get(
                    "/api/jira/search?jql=project%20%3D%20ABC&maxResults=10",
                    headers={"Authorization": "Bearer dev-token-admin"},
                )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Unauthorized")
        wrapped.assert_called_once()


if __name__ == "__main__":
    unittest.main()
