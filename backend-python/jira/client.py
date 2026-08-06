"""
Jira REST API client.

Wraps the Atlassian REST API v3 calls needed for Phase 1:
  - Creating an issue
  - Resolving the site URL for building browse links

The client always uses the token belonging to the requesting Airbrake user so
every ticket is created under that user's Jira identity (not a shared bot).

DO NOT log access_token values.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds


class JiraClient:
    """Thin wrapper around the Atlassian REST API using an OAuth access token."""

    def __init__(self, access_token: str, cloud_id: str):
        self._access_token = access_token
        self._cloud_id     = cloud_id
        self._base          = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept":        "application/json",
            "Content-Type":  "application/json",
        }

    # ── Issue creation ────────────────────────────────────────────────────────

    def create_issue(self, project_key: str, summary: str, description_adf: dict) -> dict:
        """
        Create a Jira issue and return { key, id, url }.

        summary          — plain text (≤ 255 chars)
        description_adf  — Atlassian Document Format dict
        """
        payload = {
            "fields": {
                "project":     {"key": project_key},
                "summary":     summary[:255],
                "description": description_adf,
                "issuetype":   {"name": "Bug"},
            }
        }
        url = f"{self._base}/issue"
        logger.info(
            "[Jira Client] Creating issue project=%s summary=%s",
            project_key, summary[:80],
        )
        resp = requests.post(url, json=payload, headers=self._headers, timeout=_TIMEOUT)

        if not resp.ok:
            logger.error(
                "[Jira Client] create_issue failed status=%s body=%s",
                resp.status_code, resp.text[:500],
            )
            resp.raise_for_status()

        data       = resp.json()
        ticket_key = data.get("key", "")
        ticket_id  = data.get("id", "")

        # Build browse URL using the cloud site URL
        browse_url = self._build_browse_url(ticket_key)

        logger.info(
            "[Jira Client] Issue created key=%s id=%s url=%s",
            ticket_key, ticket_id, browse_url,
        )
        return {"key": ticket_key, "id": ticket_id, "url": browse_url}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def search_issues(self, jql: str, fields: list = None, max_results: int = 100, next_page_token: str = None) -> dict:
        """
        Search Jira issues using JQL (POST /rest/api/3/search/jql).
        
        Args:
            jql: JQL query string (e.g., "project = AIRBRAKE AND status = Open")
            fields: List of fields to return (default: all standard fields)
            max_results: Max results per page (default: 100)
            next_page_token: Token for pagination (optional)
        
        Returns:
            {
                "issues": [...],
                "isLast": bool,
                "nextPageToken": str or None
            }
        
        Raises:
            requests.HTTPError: If the API call fails
        """
        payload = {
            "jql": jql,
            "maxResults": max_results
        }
        
        if fields:
            payload["fields"] = fields
        
        if next_page_token:
            payload["nextPageToken"] = next_page_token
        
        url = f"{self._base}/search/jql"
        logger.info("[Jira Client] Searching issues jql=%s maxResults=%d", jql[:100], max_results)
        
        resp = requests.post(
            url, 
            json=payload, 
            headers=self._headers, 
            timeout=_TIMEOUT
        )
        
        if not resp.ok:
            logger.error(
                "[Jira Client] search_issues failed status=%s body=%s",
                resp.status_code, resp.text[:500]
            )
            resp.raise_for_status()
        
        data = resp.json()
        logger.info(
            "[Jira Client] Search returned %d issues, isLast=%s",
            len(data.get("issues", [])), data.get("isLast", True)
        )
        return data

    def get_issue(self, issue_key: str, fields: list = None) -> dict:
        """
        Get a single Jira issue by key.
        
        Args:
            issue_key: Issue key (e.g., "PROJ-123")
            fields: List of fields to return (default: all)
        
        Returns:
            Issue data dict with fields
        
        Raises:
            requests.HTTPError: If the issue doesn't exist or API call fails
        """
        url = f"{self._base}/issue/{issue_key}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        
        logger.info("[Jira Client] Getting issue key=%s", issue_key)
        
        resp = requests.get(
            url,
            params=params,
            headers=self._headers,
            timeout=_TIMEOUT
        )
        
        if not resp.ok:
            logger.error(
                "[Jira Client] get_issue failed status=%s body=%s",
                resp.status_code, resp.text[:500]
            )
            resp.raise_for_status()
        
        return resp.json()

    def _build_browse_url(self, ticket_key: str) -> str:
        """Build the human-readable browse URL for a ticket key."""
        try:
            resp = requests.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"},
                timeout=_TIMEOUT,
            )
            if resp.ok:
                resources = resp.json()
                if resources:
                    site_url = resources[0].get("url", "")
                    if site_url:
                        return f"{site_url}/browse/{ticket_key}"
        except Exception as exc:
            logger.warning("[Jira Client] Could not resolve site URL: %s", exc)

        # Fallback: use configured cloud ID in a generic URL pattern
        return f"https://your-domain.atlassian.net/browse/{ticket_key}"
