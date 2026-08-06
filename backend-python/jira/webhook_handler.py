"""
Jira webhook event parser and router.

Receives raw Jira webhook payloads and decides whether to trigger
the sync pipeline based on event type and issue status.

Jira sends webhooks for every issue event. We only care about events
that indicate an issue has reached a terminal state (Done / Closed /
Resolved) because that is when a meaningful solution exists to extract.

We also track issue updates to keep jira_issue_key linkage current.

Supported event types (webhookEvent field in payload):
  jira:issue_updated      — covers transitions, field edits, comments
  jira:issue_created      — ignored (no solution yet)
  comment_created         — triggers re-extraction if issue is already resolved
  comment_updated         — same
  jira:issue_deleted      — marks sync row as deleted
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Terminal statuses that trigger solution extraction ────────────────────────
# Jira status names are case-insensitive. We normalise before comparing.
TERMINAL_STATUSES = {"done", "closed", "resolved", "fixed", "complete", "completed"}

# Transition event types that carry a new status
_TRANSITION_EVENTS = {
    "jira:issue_updated",
    "jira:issue_transitioned",   # some Jira Cloud versions use this
}

_REOPEN_STATUSES = {"todo", "in progress", "reopened", "open"}

_COMMENT_EVENTS = {
    "comment_created",
    "comment_updated",
}

_DELETE_EVENTS = {
    "jira:issue_deleted",
}


def parse_webhook(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Parse a raw Jira webhook payload into a structured event dict.

    Returns None if the event should be ignored (e.g. issue opened,
    status not terminal, no issue key present).

    Returns a dict with:
      {
        "action":          str  — "resolve" | "update" | "comment" | "delete"
        "issue_key":       str  — e.g. "ARGUS-123"
        "issue_id":        str  — Jira numeric issue ID
        "status":          str  — current status name (lower)
        "is_terminal":     bool — True if status is Done/Closed/Resolved
        "assignee":        dict | None
        "resolution":      dict | None
        "summary":         str
        "description":     str | None
        "comment_body":    str | None  — set for comment events
        "reporter":        dict | None
        "updated_by":      dict | None — user who triggered the event
        "transition_name": str | None  — the transition that just happened
        "raw":             dict        — full payload for downstream use
      }
    """
    webhook_event = payload.get("webhookEvent", "")
    issue         = payload.get("issue") or {}
    fields        = issue.get("fields") or {}

    issue_key = issue.get("key", "")
    issue_id  = str(issue.get("id", ""))

    if not issue_key:
        logger.debug("[Webhook] Ignoring event with no issue key: %s", webhook_event)
        return None

    # ── Deleted ───────────────────────────────────────────────────────────────
    if webhook_event in _DELETE_EVENTS:
        logger.info("[Webhook] Issue deleted: %s", issue_key)
        return {
            "action":          "delete",
            "issue_key":       issue_key,
            "issue_id":        issue_id,
            "status":          "",
            "is_terminal":     False,
            "assignee":        None,
            "resolution":      None,
            "summary":         fields.get("summary", ""),
            "description":     None,
            "comment_body":    None,
            "reporter":        None,
            "updated_by":      _extract_user(payload.get("user")),
            "transition_name": None,
            "raw":             payload,
        }

    # ── Extract status ────────────────────────────────────────────────────────
    status_obj  = fields.get("status") or {}
    status_name = (status_obj.get("name") or "").strip().lower()
    is_terminal = status_name in TERMINAL_STATUSES

    # ── Comment events ────────────────────────────────────────────────────────
    if webhook_event in _COMMENT_EVENTS:
        comment = payload.get("comment") or {}
        body    = comment.get("body") or ""
        logger.info(
            "[Webhook] Comment event issue=%s status=%s is_terminal=%s",
            issue_key, status_name, is_terminal,
        )
        return {
            "action":          "comment",
            "issue_key":       issue_key,
            "issue_id":        issue_id,
            "status":          status_name,
            "is_terminal":     is_terminal,
            "assignee":        _extract_user(fields.get("assignee")),
            "resolution":      fields.get("resolution"),
            "summary":         fields.get("summary", ""),
            "description":     _extract_description(fields.get("description")),
            "comment_body":    body,
            "reporter":        _extract_user(fields.get("reporter")),
            "updated_by":      _extract_user(payload.get("user")),
            "transition_name": None,
            "raw":             payload,
        }

    # ── Update / transition events ────────────────────────────────────────────
    if webhook_event in _TRANSITION_EVENTS or webhook_event.startswith("jira:"):
        # Extract which transition just fired (if any)
        changelog      = payload.get("changelog") or {}
        transition_name = _extract_transition_name(changelog)

        logger.info(
            "[Webhook] Update event issue=%s status=%s is_terminal=%s transition=%s",
            issue_key, status_name, is_terminal, transition_name,
        )

        action = "resolve" if is_terminal else "update"
        is_reopen = bool(transition_name and transition_name.lower() in {"reopened", "todo", "in progress", "inprogress"})
        if not is_reopen and status_name in _REOPEN_STATUSES:
            is_reopen = True

        if is_reopen:
            action = "reopen"

        return {
            "action":          action,
            "issue_key":       issue_key,
            "issue_id":        issue_id,
            "status":          status_name,
            "is_terminal":     is_terminal,
            "is_reopen":       is_reopen,
            "assignee":        _extract_user(fields.get("assignee")),
            "resolution":      fields.get("resolution"),
            "summary":         fields.get("summary", ""),
            "description":     _extract_description(fields.get("description")),
            "comment_body":    None,
            "reporter":        _extract_user(fields.get("reporter")),
            "updated_by":      _extract_user(payload.get("user")),
            "transition_name": transition_name,
            "raw":             payload,
        }

    logger.debug("[Webhook] Unhandled event type: %s", webhook_event)
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_user(user_obj: Any) -> Optional[dict]:
    """Normalise a Jira user object to { account_id, display_name, email }."""
    if not user_obj or not isinstance(user_obj, dict):
        return None
    return {
        "account_id":   user_obj.get("accountId", ""),
        "display_name": user_obj.get("displayName", ""),
        "email":        user_obj.get("emailAddress", ""),
    }


def _extract_description(desc: Any) -> Optional[str]:
    """
    Jira description can be plain text (Server) or Atlassian Document Format (Cloud).
    Return plain text in both cases.
    """
    if not desc:
        return None
    if isinstance(desc, str):
        return desc.strip() or None
    # ADF: {"type":"doc","content":[...]}
    if isinstance(desc, dict):
        return _adf_to_text(desc).strip() or None
    return None


def _adf_to_text(node: dict, depth: int = 0) -> str:
    """Recursively extract plain text from an ADF document node."""
    if depth > 20:
        return ""  # guard against pathological nesting
    node_type = node.get("type", "")
    text = node.get("text", "")

    if node_type == "text":
        return text

    parts = []
    for child in node.get("content") or []:
        parts.append(_adf_to_text(child, depth + 1))

    joined = " ".join(p for p in parts if p)

    # Add newlines for block elements
    if node_type in ("paragraph", "heading", "listItem", "bulletList", "orderedList", "codeBlock"):
        return joined + "\n"
    return joined


def _extract_transition_name(changelog: dict) -> Optional[str]:
    """Pull the 'status' field change from a Jira changelog block."""
    for item in changelog.get("items") or []:
        if item.get("field") == "status":
            return item.get("toString") or item.get("to") or None
    return None
