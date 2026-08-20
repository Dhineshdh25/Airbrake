"""
Jira REST API fetcher for webhook sync.

When a webhook fires we have the basic payload, but we need to fetch
the full issue (including all comments, resolution, assignee, and
final status) to give Nova enough context for solution extraction.

Uses the OAuth token of whoever connected their Jira account to
Airbrake from the same project. Falls back to the most recently
connected token if no per-project mapping exists.

DO NOT log access_token values.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 15


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_full_issue(
    issue_key: str,
    access_token: str,
    cloud_id: str,
) -> dict[str, Any]:
    """
    Fetch the full Jira issue including fields, comments, and changelog.

    Returns a dict with:
      {
        "key":         str,
        "summary":     str,
        "description": str | None,
        "status":      str,
        "resolution":  str | None,
        "assignee":    { account_id, display_name, email } | None,
        "reporter":    { account_id, display_name, email } | None,
        "comments":    [ { author, body, created } ],
        "created":     str (ISO),
        "updated":     str (ISO),
      }
    """
    base   = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json",
    }

    # Expand comments and changelog in one call
    url = f"{base}/issue/{issue_key}?expand=renderedFields,names,changelog"
    logger.info("[JiraSync] Fetching issue %s", issue_key)

    resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json()

    fields  = raw.get("fields") or {}
    comments_container = fields.get("comment") or {}
    raw_comments = comments_container.get("comments") or []

    # Also fetch comments separately if the issue has more than 5
    # (Jira sometimes truncates in the main response)
    total_comments = comments_container.get("total", len(raw_comments))
    if total_comments > len(raw_comments):
        raw_comments = _fetch_all_comments(issue_key, base, headers)

    comments = [_normalise_comment(c) for c in raw_comments]

    # Resolution
    res_obj    = fields.get("resolution") or {}
    resolution = res_obj.get("name") or None

    # Status
    status_obj = fields.get("status") or {}
    status     = (status_obj.get("name") or "").strip().lower()

    # Description (ADF or plain)
    from .webhook_handler import _extract_description, _extract_user
    description = _extract_description(fields.get("description"))

    logger.info(
        "[JiraSync] Issue %s fetched — status=%s comments=%d resolution=%s",
        issue_key, status, len(comments), resolution,
    )

    return {
        "key":         issue_key,
        "summary":     fields.get("summary", ""),
        "description": description,
        "status":      status,
        "resolution":  resolution,
        "assignee":    _extract_user(fields.get("assignee")),
        "reporter":    _extract_user(fields.get("reporter")),
        "comments":    comments,
        "created":     fields.get("created", ""),
        "updated":     fields.get("updated", ""),
    }


def find_airbrake_token_for_webhook() -> Optional[tuple[str, str]]:
    """
    Return (access_token, cloud_id) for ANY connected Airbrake user.

    Webhooks are not tied to a specific Airbrake user — they come from Jira.
    We use any available token to fetch issue details; the token is only used
    for READ operations (fetching issue + comments), never for write.

    Returns None if no tokens exist (Jira not yet connected by anyone).
    DO NOT log the access_token.
    """
    try:
        from db import query
        rows = query(
            "SELECT metadata FROM projects_data "
            "WHERE row_type = 'jira_token' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if not rows:
            logger.warning("[JiraSync] No Jira tokens available for webhook fetch")
            return None

        import json
        raw = rows[0].get("metadata")
        token_data = json.loads(raw) if isinstance(raw, str) else raw
        if not token_data:
            return None

        access_token = token_data.get("access_token", "")
        cloud_id     = token_data.get("cloud_id", "")
        if not access_token or not cloud_id:
            return None

        # Validate token is not expired; refresh if needed
        from .token_store import is_token_expired
        from .oauth import refresh_access_token

        if is_token_expired(token_data):
            refresh_tok = token_data.get("refresh_token", "")
            if refresh_tok:
                try:
                    refreshed    = refresh_access_token(refresh_tok)
                    access_token = refreshed["access_token"]
                    cloud_id     = token_data["cloud_id"]
                    logger.info("[JiraSync] Webhook token refreshed successfully")
                except Exception as exc:
                    logger.error("[JiraSync] Webhook token refresh failed: %s", exc)
                    # Fall through and try with the existing token anyway —
                    # Atlassian tokens often remain valid past their declared expiry.
                    logger.warning("[JiraSync] Attempting webhook fetch with potentially expired token")
            else:
                # No refresh token — try the access token anyway, it may still be valid.
                logger.warning("[JiraSync] Token flagged expired but no refresh token — trying anyway")

        return access_token, cloud_id

    except Exception as exc:
        logger.exception("[JiraSync] find_airbrake_token_for_webhook failed: %s", exc)
        return None


def find_log_rows_by_jira_key(issue_key: str) -> list[dict]:
    """
    Find all Airbrake log rows linked to a Jira issue key.

    Looks in the metadata JSON column for jira_issue_key = issue_key.
    Also falls back to matching jira_issue_url containing the issue key
    so rows linked via the URL field are never missed.
    Returns list of { id, project_name, error, error_hash, error_status }.
    """
    try:
        from db import query
        # Primary lookup: exact jira_issue_key match
        rows = query(
            "SELECT id, project_name, error, error_hash, error_status "
            "FROM projects_data "
            "WHERE row_type = 'log' "
            "  AND metadata::jsonb->>'jira_issue_key' = %s",
            (issue_key,),
        )

        # Secondary: rows where jira_issue_key is missing but jira_issue_url
        # contains the issue key (e.g. stored as .../browse/ARGUS-36).
        # Avoids missing rows when /link stored the URL but not the key.
        fallback_rows = query(
            "SELECT id, project_name, error, error_hash, error_status "
            "FROM projects_data "
            "WHERE row_type = 'log' "
            "  AND (metadata::jsonb->>'jira_issue_key' IS NULL "
            "       OR metadata::jsonb->>'jira_issue_key' = '') "
            "  AND metadata::jsonb->>'jira_issue_url' LIKE %s",
            (f"%/{issue_key}",),
        )

        # Merge, deduplicating by id
        seen: set[str] = {r["id"] for r in rows if r.get("id")}
        for r in fallback_rows:
            if r.get("id") and r["id"] not in seen:
                rows.append(r)
                seen.add(r["id"])

        logger.info(
            "[JiraSync] Found %d log rows for issue_key=%s (primary=%d fallback=%d)",
            len(rows), issue_key, len(rows) - len(fallback_rows), len(fallback_rows),
        )
        return rows
    except Exception as exc:
        logger.exception("[JiraSync] find_log_rows_by_jira_key failed: %s", exc)
        return []


def mark_log_jira_key(
    log_id: str,
    issue_key: str,
    issue_url: str = "",
    created_by_user_id: str = "",
) -> None:
    """
    Store the Jira issue key (and URL) on a log row's metadata so we can
    look it up later via the global ticket-status endpoint.

    Also stamps jira_created_by = the Airbrake user_id who created the ticket
    so GET /api/jira/my-tickets can filter server-side per user.

    Uses a JSON merge so existing metadata is preserved.
    """
    try:
        from db import execute
        extra = {}
        if created_by_user_id:
            extra["jira_created_by"] = created_by_user_id
        # Build the jsonb_build_object call dynamically — always include
        # jira_issue_key and jira_issue_url; optionally include jira_created_by.
        if extra:
            execute(
                "UPDATE projects_data "
                "SET metadata = COALESCE(metadata::jsonb, '{}'::jsonb) "
                "           || jsonb_build_object("
                "               'jira_issue_key',  %s::text,"
                "               'jira_issue_url',  %s::text,"
                "               'jira_created_by', %s::text"
                "             ) "
                "WHERE row_type = 'log' AND id = %s",
                (issue_key, issue_url, created_by_user_id, log_id),
            )
        else:
            execute(
                "UPDATE projects_data "
                "SET metadata = COALESCE(metadata::jsonb, '{}'::jsonb) "
                "           || jsonb_build_object("
                "               'jira_issue_key', %s::text,"
                "               'jira_issue_url', %s::text"
                "             ) "
                "WHERE row_type = 'log' AND id = %s",
                (issue_key, issue_url, log_id),
            )
        logger.info(
            "[JiraSync] Linked log_id=%s → jira_issue_key=%s created_by=%s",
            log_id, issue_key, created_by_user_id or "(none)",
        )
    except Exception as exc:
        logger.exception("[JiraSync] mark_log_jira_key failed: %s", exc)


def mark_sync_status(log_id: str, status: str, detail: str = "") -> None:
    """
    Update the jira_sync_status on a log row.

    status values: 'synced' | 'sync_failed' | 'skipped'
    """
    try:
        from db import execute
        execute(
            "UPDATE projects_data "
            "SET metadata = COALESCE(metadata::jsonb, '{}'::jsonb) "
            "           || jsonb_build_object("
            "               'jira_sync_status', %s::text,"
            "               'jira_sync_detail', %s::text"
            "             ) "
            "WHERE row_type = 'log' AND id = %s",
            (status, detail[:500], log_id),
        )
    except Exception as exc:
        logger.exception("[JiraSync] mark_sync_status failed: %s", exc)


def reopen_linked_airbrake_errors(issue_key: str, jira_status: str) -> dict[str, Any]:
    """Reopen linked Airbrake log rows when a Jira issue moves back to an open state."""
    try:
        linked_rows = find_log_rows_by_jira_key(issue_key)
        if not linked_rows:
            return {"reopened": 0, "issue_key": issue_key, "status": jira_status}

        updated = 0
        for row in linked_rows:
            log_id = row.get("id")
            if not log_id:
                continue
            from db import execute
            count = execute(
                "UPDATE projects_data "
                "SET error_status = 'reopened', "
                "reopened_at = NOW(), resolved_at = NULL, "
                "jira_status = %s, jira_last_sync = NOW() "
                "WHERE row_type = 'log' AND id = %s "
                "AND error_status IN ('resolved', 'reopened')",
                (jira_status, log_id),
            )
            updated += int(count or 0)

        return {"reopened": updated, "issue_key": issue_key, "status": jira_status}
    except Exception as exc:
        logger.exception("[JiraSync] reopen_linked_airbrake_errors failed: %s", exc)
        return {"reopened": 0, "issue_key": issue_key, "status": jira_status, "error": str(exc)}


# ── Private helpers ───────────────────────────────────────────────────────────

def _fetch_all_comments(
    issue_key: str,
    base_url: str,
    headers: dict,
    max_results: int = 200,
) -> list[dict]:
    """Paginated comment fetch for issues with many comments."""
    all_comments: list[dict] = []
    start_at = 0

    while True:
        url  = f"{base_url}/issue/{issue_key}/comment?startAt={start_at}&maxResults=50"
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
        if not resp.ok:
            break
        data     = resp.json()
        comments = data.get("comments") or []
        all_comments.extend(comments)

        if len(all_comments) >= data.get("total", 0) or len(comments) == 0:
            break
        if len(all_comments) >= max_results:
            break
        start_at += len(comments)

    return all_comments


def _normalise_comment(c: dict) -> dict:
    """Extract the fields we need from a raw Jira comment object."""
    from .webhook_handler import _extract_description, _extract_user
    return {
        "author":  _extract_user(c.get("author")),
        "body":    _extract_description(c.get("body")) or "",
        "created": c.get("created", ""),
        "updated": c.get("updated", ""),
        "id":      c.get("id", ""),
    }
