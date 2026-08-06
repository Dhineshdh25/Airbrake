import importlib.util
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / 'app.py'

spec = importlib.util.spec_from_file_location('airbrake_app', MODULE_PATH)
app_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_module)


class JiraSummaryRouteTests(unittest.TestCase):
    def test_jira_summary_returns_ticket_count_and_statuses(self):
        rows = [
            {
                'metadata': {
                    'error_hash': 'hash-a',
                    'project_name': 'ProjectX',
                    'jira_key': 'ABC-1',
                    'jira_url': 'https://jira.example/ABC-1',
                    'created_by': 'alice@example.com',
                    'created_at': '2024-01-01T00:00:00Z',
                }
            },
            {
                'metadata': {
                    'error_hash': 'hash-b',
                    'project_name': 'ProjectX',
                    'jira_key': 'ABC-2',
                    'jira_url': 'https://jira.example/ABC-2',
                    'created_by': 'bob@example.com',
                    'created_at': '2024-01-02T00:00:00Z',
                }
            },
        ]

        log_rows = [
            {'error_status': 'resolved', 'error': 'Resolved error'},
            {'error_status': 'open', 'error': 'Open error'},
        ]

        with mock.patch('db.query', side_effect=[rows, log_rows[:1], log_rows[1:]]):
            client = app_module.app.test_client()
            response = client.get('/api/jira/summary')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['total'], 2)
        self.assertEqual(payload['resolved'], 1)
        self.assertEqual(payload['todo'], 1)
        self.assertEqual(payload['tickets'][0]['created_by'], 'alice@example.com')
        self.assertEqual(payload['tickets'][0]['status'], 'Resolved')
        self.assertEqual(payload['tickets'][1]['status'], 'Todo')


if __name__ == '__main__':
    unittest.main()
