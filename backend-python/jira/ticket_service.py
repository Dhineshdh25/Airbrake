"""
Jira ticket creation service.

Builds a structured, Airbrake-rich Jira ticket from the error data passed
by the frontend (everything already visible in the Error Details modal).

Uses Atlassian Document Format (ADF) for the description so formatting
is preserved in Jira's rich-text editor.
"""

from __future__ import annotations
import logging
import os
import requests
from typing import Optional

from .client import JiraClient
from .oauth import refresh_access_token
from .token_store import get_token, save_token, is_token_expired
import json
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────────────

def create_jira_ticket(user_id: str, error_data: dict) -> dict:
    """
    Create a Jira ticket using the OAuth token of the given Airbrake user.

    error_data keys (all optional except error_message):
      project_name, error_group, error_message, error_detail, error_hash,
      occurrence_count, status, solution, ai_recommendation,
      timestamp, file_name, airbrake_url

    Returns { key, id, url }.
    Raises RuntimeError if the user has no connected Jira account.
    Raises requests.HTTPError on Jira API failure.
    """
    token = _get_valid_token(user_id)

    project_key = (
        error_data.get("jira_project_key")
        or os.environ.get("JIRA_PROJECT_KEY", "")
    )
    if not project_key:
        raise ValueError(
            "JIRA_PROJECT_KEY is not configured.  "
            "Set it in your .env or pass jira_project_key in the request."
        )

    summary = _build_summary(error_data)
    description_adf = _build_description_adf(error_data)

    client = JiraClient(
        access_token=token["access_token"],
        cloud_id=token["cloud_id"],
    )

    # Deduplication: check if THIS SPECIFIC OCCURRENCE already has a ticket.
    # We check by log_id (specific row UUID), NOT by error_hash.
    # Two different occurrences of the same error can each have their own ticket.
    log_id = error_data.get("log_id")
    project_name = error_data.get("project_name")
    error_hash = error_data.get("error_hash")

    if log_id:
        try:
            from db import query as _q
            rows = _q(
                "SELECT metadata FROM projects_data "
                "WHERE row_type = 'log' AND id = %s "
                "  AND metadata::jsonb ? 'jira_issue_key' "
                "  AND metadata::jsonb->>'jira_issue_key' IS NOT NULL "
                "  AND metadata::jsonb->>'jira_issue_key' != '' ",
                (log_id,),
            )
            if rows:
                import json as _j
                raw  = rows[0].get("metadata")
                meta = _j.loads(raw) if isinstance(raw, str) else (raw or {})
                existing_key = meta.get("jira_issue_key", "")
                if existing_key:
                    logger.info(
                        "[Jira TicketService] Occurrence already has ticket log_id=%s key=%s",
                        log_id, existing_key,
                    )
                    return {
                        "key": existing_key,
                        "id":  meta.get("jira_issue_id", ""),
                        "url": meta.get("jira_issue_url", ""),
                    }
        except Exception as exc:
            logger.warning("[Jira TicketService] log_id dedup check failed: %s", exc)

    try:
        result = client.create_issue(project_key, summary, description_adf)
    except requests.HTTPError as exc:
        # If Jira returns 401, the token was revoked externally (user removed
        # app access from Atlassian account settings).  Attempt one refresh
        # then retry.  If refresh also fails, raise RuntimeError so routes.py
        # returns 401 + needs_auth=True and the frontend prompts reconnect.
        if exc.response is not None and exc.response.status_code == 401:
            logger.warning(
                "[Jira TicketService] Got 401 from Jira, attempting token refresh for user_id=%s",
                user_id,
            )
            if not token.get("refresh_token"):
                raise RuntimeError(
                    "Your Jira session was revoked.  Please reconnect your Jira account."
                ) from exc
            try:
                refreshed = refresh_access_token(token["refresh_token"])
                save_token(
                    user_id              = user_id,
                    access_token         = refreshed["access_token"],
                    refresh_token        = refreshed.get("refresh_token", token["refresh_token"]),
                    expires_in           = refreshed.get("expires_in"),
                    cloud_id             = token["cloud_id"],
                    atlassian_account_id = token["atlassian_account_id"],
                    atlassian_email      = token["atlassian_email"],
                )
                fresh_token = get_token(user_id)
                logger.info(
                    "[Jira TicketService] Token refreshed after 401, retrying for user_id=%s",
                    user_id,
                )
                client2 = JiraClient(
                    access_token=fresh_token["access_token"],
                    cloud_id=fresh_token["cloud_id"],
                )
                result = client2.create_issue(project_key, summary, description_adf)
            except RuntimeError:
                raise
            except Exception as refresh_exc:
                logger.error(
                    "[Jira TicketService] Refresh-and-retry failed for user_id=%s: %s",
                    user_id, refresh_exc,
                )
                raise RuntimeError(
                    "Your Jira session was revoked and could not be refreshed.  "
                    "Please reconnect your Jira account."
                ) from refresh_exc
        else:
            raise  # non-401 Jira errors propagate normally

    logger.info(
        "[Jira TicketService] Ticket created user_id=%s key=%s",
        user_id, result.get("key"),
    )

    # Save ticket to database - if this fails, log prominently but don't fail
    # the request since the Jira ticket was already created successfully
    if error_hash:
        payload = {
            "error_hash": error_hash,
            "project_name": project_name,
            "jira_key": result.get("key"),
            "jira_id": result.get("id"),
            "jira_url": result.get("url"),
            # Also store the canonical Jira response keys for compatibility
            "key": result.get("key"),
            "id": result.get("id"),
            "url": result.get("url"),
            "created_by": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            # Try to insert the ticket directly (simpler than claim/update pattern)
            inserted = try_claim_jira_ticket(error_hash, project_name, payload)
            if inserted:
                logger.info(
                    "[Jira TicketService] SUCCESS: Ticket metadata saved to database key=%s hash=%s",
                    result.get("key"),
                    error_hash
                )
            else:
                # Unique constraint violation - ticket already exists
                logger.warning(
                    "[Jira TicketService] WARNING: Ticket already exists in database (unique constraint) key=%s",
                    result.get("key")
                )
        except Exception as db_error:
            # Database save failed - log prominently so we can investigate
            logger.exception(
                "[Jira TicketService] CRITICAL ERROR: Failed to save ticket metadata to database"
            )
            logger.error(
                "ORPHANED TICKET ALERT: Ticket %s (id=%s) was created in Jira but NOT saved to database. "
                "Error: %s. Manual backfill required. Ticket payload: error_hash=%s, project=%s, url=%s",
                result.get("key"),
                result.get("id"),
                str(db_error),
                error_hash,
                project_name,
                result.get("url")
            )
            # Don't raise - Jira ticket creation was successful, that's what matters most
    
    return result


def search_jira_tickets(user_id: str, jql: str, max_results: int = 100) -> dict:
    """
    Search Jira tickets using JQL via the new /rest/api/3/search/jql endpoint.

    Args:
        user_id: Airbrake user ID to use for OAuth token lookup
        jql: JQL query string (e.g., "project = AIRBRAKE AND status = Open")
        max_results: Maximum number of results to return (default: 100)

    Returns:
        {
            "issues": [...],
            "isLast": bool,
            "nextPageToken": str or None,
            "total": int
        }

    Raises RuntimeError if the user has no connected Jira account.
    Raises requests.HTTPError on Jira API failure.
    """
    token = _get_valid_token(user_id)

    client = JiraClient(
        access_token=token["access_token"],
        cloud_id=token["cloud_id"],
    )

    try:
        result = client.search_issues(
            jql=jql,
            fields=["summary", "status", "created", "updated", "assignee", "reporter"],
            max_results=max_results
        )
        
        logger.info(
            "[Jira TicketService] Search completed user_id=%s results=%d",
            user_id, len(result.get("issues", []))
        )
        
        return result
    except requests.HTTPError as exc:
        # Handle 401 the same way as create_jira_ticket
        if exc.response is not None and exc.response.status_code == 401:
            logger.warning(
                "[Jira TicketService] Got 401 from Jira search, attempting token refresh for user_id=%s",
                user_id,
            )
            if not token.get("refresh_token"):
                raise RuntimeError(
                    "Your Jira session was revoked.  Please reconnect your Jira account."
                ) from exc
            try:
                refreshed = refresh_access_token(token["refresh_token"])
                save_token(
                    user_id              = user_id,
                    access_token         = refreshed["access_token"],
                    refresh_token        = refreshed.get("refresh_token", token["refresh_token"]),
                    expires_in           = refreshed.get("expires_in"),
                    cloud_id             = token["cloud_id"],
                    atlassian_account_id = token["atlassian_account_id"],
                    atlassian_email      = token["atlassian_email"],
                )
                fresh_token = get_token(user_id)
                logger.info(
                    "[Jira TicketService] Token refreshed after 401, retrying search for user_id=%s",
                    user_id,
                )
                client2 = JiraClient(
                    access_token=fresh_token["access_token"],
                    cloud_id=fresh_token["cloud_id"],
                )
                result = client2.search_issues(
                    jql=jql,
                    fields=["summary", "status", "created", "updated", "assignee", "reporter"],
                    max_results=max_results
                )
                return result
            except RuntimeError:
                raise
            except Exception as refresh_exc:
                logger.error(
                    "[Jira TicketService] Refresh-and-retry failed for search user_id=%s: %s",
                    user_id, refresh_exc,
                )
                raise RuntimeError(
                    "Your Jira session was revoked and could not be refreshed.  "
                    "Please reconnect your Jira account."
                ) from refresh_exc
        else:
            raise  # non-401 Jira errors propagate normally


# ── DB helpers for ticket metadata ───────────────────────────────────────────
try:
    from db import query, execute, execute_returning, try_claim_jira_ticket, update_claimed_jira_ticket, find_jira_ticket_by_hash
except Exception as _db_exc:  # pragma: no cover
    def query(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def execute(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def execute_returning(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def try_claim_jira_ticket(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def update_claimed_jira_ticket(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def find_jira_ticket_by_hash(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")


# ── Token helpers ─────────────────────────────────────────────────────────────

def _get_valid_token(user_id: str) -> dict:
    """
    Return a valid (refreshed if necessary) token dict for the user.

    Raises RuntimeError if no token is found.
    """
    token = get_token(user_id)
    if not token:
        raise RuntimeError(
            "No Jira connection found for this user.  "
            "Please connect your Jira account first."
        )

    if is_token_expired(token) and token.get("refresh_token"):
        logger.info("[Jira TicketService] Token expired, refreshing for user_id=%s", user_id)
        try:
            refreshed = refresh_access_token(token["refresh_token"])
            # Persist the updated token while preserving the cloud/account metadata
            save_token(
                user_id              = user_id,
                access_token         = refreshed["access_token"],
                refresh_token        = refreshed.get("refresh_token", token["refresh_token"]),
                expires_in           = refreshed.get("expires_in"),
                cloud_id             = token["cloud_id"],
                atlassian_account_id = token["atlassian_account_id"],
                atlassian_email      = token["atlassian_email"],
            )
            token = get_token(user_id)
            logger.info("[Jira TicketService] Token refreshed for user_id=%s", user_id)
        except Exception as exc:
            logger.error(
                "[Jira TicketService] Token refresh failed for user_id=%s: %s",
                user_id, exc,
            )
            raise RuntimeError(
                "Your Jira session has expired and could not be refreshed.  "
                "Please reconnect your Jira account."
            ) from exc

    return token


# ── Ticket formatting ─────────────────────────────────────────────────────────

def _build_summary(error_data: dict) -> str:
    """Return a concise Jira summary line (≤ 200 chars)."""
    msg = (error_data.get("error_message") or "Unknown error").strip()
    return msg[:200]


def _build_description_adf(error_data: dict) -> dict:
    """
    Build an Atlassian Document Format (ADF) description block.

    Populates every field that is available in the Error Details modal.
    Fields that are None / empty are skipped.
    """
    content = []

    def _heading(text: str, level: int = 3):
        return {
            "type": "heading",
            "attrs": {"level": level},
            "content": [{"type": "text", "text": text}],
        }

    def _para(*parts):
        """parts = alternating (text, marks?) tuples or plain strings."""
        nodes = []
        for part in parts:
            if isinstance(part, str):
                nodes.append({"type": "text", "text": part})
            elif isinstance(part, tuple):
                text, marks = part
                nodes.append({"type": "text", "text": text, "marks": marks})
        return {"type": "paragraph", "content": nodes}

    def _code_block(text: str, language: str = ""):
        return {
            "type": "codeBlock",
            "attrs": {"language": language},
            "content": [{"type": "text", "text": text}],
        }

    def _rule():
        return {"type": "rule"}

    # ── Error overview ────────────────────────────────────────────────────────
    content.append(_heading("Error Overview", 2))

    fields = [
        ("Project",        error_data.get("project_name")),
        ("Error Group",    error_data.get("error_group")),
        ("Error Hash",     error_data.get("error_hash")),
        ("File",           error_data.get("file_name")),
        ("Occurrences",    str(error_data["occurrence_count"]) if error_data.get("occurrence_count") else None),
        ("Status",         error_data.get("status")),
        ("First Seen",     error_data.get("timestamp")),
    ]
    for label, value in fields:
        if value:
            content.append(_para(
                (f"{label}: ", [{"type": "strong"}]),
                value,
            ))

    # ── Error message ─────────────────────────────────────────────────────────
    if error_data.get("error_message"):
        content.append(_rule())
        content.append(_heading("Error Message", 3))
        content.append(_code_block(error_data["error_message"]))

    # ── Stack trace / error detail ────────────────────────────────────────────
    if error_data.get("error_detail"):
        content.append(_rule())
        content.append(_heading("Stack Trace", 3))
        content.append(_code_block(error_data["error_detail"]))

    # ── Suggested solution ────────────────────────────────────────────────────
    if error_data.get("solution"):
        content.append(_rule())
        content.append(_heading("Suggested Solution", 3))
        content.append(_para(error_data["solution"]))

    # ── AI recommendation ─────────────────────────────────────────────────────
    if error_data.get("ai_recommendation"):
        content.append(_rule())
        content.append(_heading("AI Recommendation", 3))
        content.append(_para(error_data["ai_recommendation"]))

    # ── Footer ────────────────────────────────────────────────────────────────
    content.append(_rule())

    # Airbrake deep-link back to this error (if caller provides it)
    airbrake_url = error_data.get("airbrake_url")
    if airbrake_url:
        content.append({
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "View in Airbrake: "},
                {
                    "type": "text",
                    "text": airbrake_url,
                    "marks": [{"type": "link", "attrs": {"href": airbrake_url}}],
                },
            ],
        })

    content.append(_para(
        "Created automatically by ",
        ("Airbrake", [{"type": "strong"}]),
        " via Jira integration.",
    ))

    return {"type": "doc", "version": 1, "content": content}
