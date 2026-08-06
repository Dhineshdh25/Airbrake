import unittest
from unittest import mock

from jira import jira_sync, routes as jira_routes
from jira import webhook_handler


class JiraAutoReopenTests(unittest.TestCase):
    def test_parse_webhook_marks_terminal_to_reopen_transition(self):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": "ABC-123",
                "id": "42",
                "fields": {
                    "summary": "Example issue",
                    "status": {"name": "In Progress"},
                    "description": None,
                },
            },
            "changelog": {
                "items": [
                    {"field": "status", "fromString": "Done", "toString": "In Progress"},
                ]
            },
        }

        event = webhook_handler.parse_webhook(payload)

        self.assertIsNotNone(event)
        self.assertEqual(event["action"], "reopen")
        self.assertTrue(event["is_reopen"])
        self.assertEqual(event["status"], "in progress")

    def test_reopen_transition_updates_linked_log_rows_only_for_reopen_fields(self):
        linked_rows = [{"id": "log-1", "error_status": "resolved"}]

        with mock.patch.object(jira_sync, "find_log_rows_by_jira_key", return_value=linked_rows), \
             mock.patch("db.execute", return_value=1) as mock_execute:
            result = jira_sync.reopen_linked_airbrake_errors("ABC-123", "In Progress")

        self.assertEqual(result["reopened"], 1)
        self.assertEqual(result["issue_key"], "ABC-123")
        self.assertEqual(mock_execute.call_count, 1)

        sql, params = mock_execute.call_args.args
        self.assertIn("error_status = 'reopened'", sql)
        self.assertIn("reopened_at = NOW()", sql)
        self.assertIn("resolved_at = NULL", sql)
        self.assertIn("jira_status", sql)
        self.assertIn("jira_last_sync", sql)
        self.assertEqual(params[0], "In Progress")
        self.assertEqual(params[1], "log-1")


if __name__ == "__main__":
    unittest.main()
