"""
Jira REST API client.

Wraps the Atlassian REST API v3 calls needed for Phase 1:
  - Creating an issue
  - Resolving the site URL for building browse links

The client always uses the token belonging to the requesting Airbrake user so
every ticket is created under that user's Jira identity (not a shared bot).

DO NOT log access_token values.
"""

import json
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
        # Build the request payload
        payload = {
            "jql": jql,
            "maxResults": max_results,
        }

        if fields:
            payload["fields"] = fields

        if next_page_token:
            payload["nextPageToken"] = next_page_token

        # Use the new Jira Cloud REST API v3 endpoint: /rest/api/3/search/jql (POST with body)
        url = f"{self._base}/search/jql"

        # Explicitly serialize the payload so the outgoing body is logged exactly.
        request_body = json.dumps(payload)
        masked_headers = {k: ("Bearer ***" if k == "Authorization" else v) for k, v in self._headers.items()}

        logger.info(
            "[Jira Client] Request START\n"
            "  URL: %s\n"
            "  Method: POST\n"
            "  Headers: %s\n"
            "  Body: %s",
            url,
            masked_headers,
            request_body,
        )

        import time
        start_time = time.time()

        try:
            resp = requests.post(
                url,
                data=request_body,
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            
            elapsed = time.time() - start_time
            
            logger.info(
                "[Jira Client] Response received status=%d elapsed=%.2fs",
                resp.status_code, elapsed
            )
            
            if not resp.ok:
                # Log the full error response from Jira
                error_body = resp.text[:1000]
                logger.error(
                    "[Jira Client] search_issues FAILED\n"
                    "  Status: %s\n"
                    "  Response body: %s\n"
                    "  JQL: %s\n"
                    "  Payload: %s",
                    resp.status_code, error_body, jql, payload
                )
                resp.raise_for_status()
            
            data = resp.json()
            total = data.get("total", 0)
            returned = len(data.get("issues", []))
            start_at = data.get("startAt", 0)
            
            # Calculate if this is the last page
            is_last = (start_at + returned) >= total
            
            # Calculate next page token (startAt for next page)
            next_token = None
            if not is_last:
                next_token = str(start_at + returned)
            
            logger.info(
                "[Jira Client] Search SUCCESS: returned %d issues, total=%d, startAt=%d, isLast=%s, nextPageToken=%s",
                returned, total, start_at, is_last, next_token
            )
            
            return {
                "issues": data.get("issues", []),
                "total": total,
                "isLast": is_last,
                "nextPageToken": next_token
            }
            
        except requests.exceptions.RequestException as exc:
            elapsed = time.time() - start_time
            logger.exception(
                "[Jira Client] Request exception elapsed=%.2fs: %s",
                elapsed, exc
            )
            raise

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
