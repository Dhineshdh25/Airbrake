"""
Jira → Airbrake solution sync pipeline.

When a Jira issue is resolved this module:
  1. Fetches the full issue + comments from Jira
  2. Uses Nova to extract the final technical solution
  3. Runs that solution through the EXACT SAME pipeline as Save Solution:
       normalize → embedding → pinecone → duplicate detection → nova validation
       → knowledge base insert → confidence update
  4. Marks the Airbrake log row as resolved (only on successful ingestion)
  5. Records resolved_from=jira, resolved_by=<display_name>, jira_resolver_account_id

NEVER bypasses insert_solution(). Jira is just another solution source.
If ingestion fails the log row is left unresolved and marked sync_failed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TABLE = "projects_data"

# ── Import pipeline functions (same pattern as app.py) ───────────────────────
try:
    from ai.knowledge_base import insert_solution
except Exception as _kb_exc:
    logger.error("[SyncPipeline] knowledge_base import failed: %s", _kb_exc)
    def insert_solution(*a, **kw):
        raise RuntimeError(f"Knowledge Base unavailable: {_kb_exc}")

try:
    from db import execute, query
except Exception as _db_exc:
    logger.error("[SyncPipeline] db import failed: %s", _db_exc)
    def execute(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def query(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")

try:
    from .jira_sync import (
        fetch_full_issue,
        find_airbrake_token_for_webhook,
        find_log_rows_by_jira_key,
        mark_sync_status,
    )
    from .nova_extractor import extract_solution_from_issue, build_solution_text
    _JIRA_HELPERS_OK = True
except Exception as _exc:
    _JIRA_HELPERS_OK = False
    # Capture into a module-level variable so the stubs can reference it
    # after the except block exits (Python drops the 'as' name on exit).
    _JIRA_HELPERS_ERR = str(_exc)
    logger.error("[SyncPipeline] jira helper import failed: %s", _exc)

    def fetch_full_issue(*a, **kw):
        raise RuntimeError(f"Jira helper unavailable: {_JIRA_HELPERS_ERR}")
    def find_airbrake_token_for_webhook(*a, **kw):
        raise RuntimeError(f"Jira helper unavailable: {_JIRA_HELPERS_ERR}")
    def find_log_rows_by_jira_key(*a, **kw):
        raise RuntimeError(f"Jira helper unavailable: {_JIRA_HELPERS_ERR}")
    def mark_sync_status(*a, **kw):
        raise RuntimeError(f"Jira helper unavailable: {_JIRA_HELPERS_ERR}")
    def extract_solution_from_issue(*a, **kw):
        raise RuntimeError(f"Jira helper unavailable: {_JIRA_HELPERS_ERR}")
    def build_solution_text(*a, **kw):
        raise RuntimeError(f"Jira helper unavailable: {_JIRA_HELPERS_ERR}")


def run_sync_pipeline(event: dict[str, Any]) -> dict[str, Any]:
    """Run a Jira sync pipeline for a webhook event or manual retry."""
    issue_key = (event.get("issue_key") or "").strip()
    if not issue_key:
        raise ValueError("Missing issue_key")

    token_pair = find_airbrake_token_for_webhook()
    if not token_pair:
        return {
            "success": False,
            "detail": "No Jira token available to fetch issue details.",
            "issue_key": issue_key,
            "log_ids": [],
        }

    access_token, cloud_id = token_pair

    try:
        issue = fetch_full_issue(issue_key, access_token, cloud_id)
    except Exception as exc:
        logger.exception("[SyncPipeline] Failed to fetch Jira issue %s: %s", issue_key, exc)
        return {
            "success": False,
            "detail": f"Failed to fetch Jira issue {issue_key}: {exc}",
            "issue_key": issue_key,
            "log_ids": [],
        }

    linked_rows = find_log_rows_by_jira_key(issue_key)
    log_ids = [row.get("id") for row in linked_rows if row.get("id")]
    if not log_ids:
        return {
            "success": False,
            "detail": "No linked Airbrake log rows found for this Jira issue.",
            "issue_key": issue_key,
            "log_ids": [],
        }

    overall_success = True
    details: list[str] = []

    for linked_row in linked_rows:
        log_id = linked_row.get("id")
        if not log_id:
            continue

        error_hash = linked_row.get("error_hash") or ""
        project_name = linked_row.get("project_name") or None
        error_message = linked_row.get("error") or issue.get("summary") or ""
        jira_status = issue.get("status", "") or ""

        extraction = extract_solution_from_issue(issue)
        solution_text = build_solution_text(extraction)

        # Fallback: if Nova found nothing, use the last comment directly.
        # A human wrote it to explain the fix — it's better than nothing.
        if not solution_text:
            comments = issue.get("comments") or []
            for c in reversed(comments):
                body = (c.get("body") or "").strip()
                if body and len(body) > 10:
                    solution_text = body
                    logger.info(
                        "[SyncPipeline] Nova found nothing — using last comment as solution for %s",
                        issue_key,
                    )
                    break

        if not solution_text:
            overall_success = False
            detail = "No extractable solution found for Jira issue."
        else:
            solution_ok = False
            try:
                sol_result = insert_solution(
                    error_hash=error_hash,
                    solution=solution_text,
                    created_by=f"jira:{(issue or {}).get('reporter', {}).get('displayName') or (issue or {}).get('assignee', {}).get('displayName') or 'sync'}",
                    project_name=project_name,
                    error_message=error_message,
                )
                solution_ok = True
                detail = "Solution extracted and inserted from Jira issue."
            except Exception as exc:
                exc_str = str(exc)
                if "unique constraint" in exc_str.lower() or "duplicate key" in exc_str.lower():
                    # Solution already in KB — still resolve the error
                    solution_ok = True
                    detail = "Solution already in knowledge base; resolving error."
                    logger.info("[SyncPipeline] Duplicate solution for error_hash=%s — resolving anyway", error_hash)
                else:
                    overall_success = False
                    detail = f"Solution insertion failed: {exc}"

            # Resolve ONLY the specific log row linked to this Jira ticket.
            # Do NOT bulk-resolve by error_hash — other occurrences with the
            # same error message may be separate issues with different causes,
            # or may have their own Jira tickets in progress.
            if solution_ok:
                try:
                    execute(
                        "UPDATE projects_data "
                        "SET error_status = 'resolved', resolved_at = NOW() "
                        "WHERE row_type = 'log' AND id = %s "
                        "  AND (error_status IS NULL OR error_status NOT IN ('resolved'))",
                        (log_id,),
                    )
                    logger.info(
                        "[SyncPipeline] Resolved log_id=%s via Jira issue=%s",
                        log_id, issue_key,
                    )
                except Exception as exc:
                    logger.exception(
                        "[SyncPipeline] Failed to resolve log_id=%s: %s", log_id, exc
                    )
                    overall_success = False
                    detail += f" (resolve step failed: {exc})"

        details.append(detail)

        try:
            mark_sync_status(log_id, "synced" if solution_text else "sync_failed", detail)
            execute(
                "UPDATE projects_data "
                "SET metadata = COALESCE(metadata::jsonb, '{}'::jsonb) "
                "           || jsonb_build_object('jira_status', %s, 'jira_last_sync', NOW()) "
                "WHERE row_type = 'log' AND id = %s",
                (jira_status, log_id),
            )
        except Exception as exc:
            logger.exception("[SyncPipeline] Failed to update log metadata for %s: %s", log_id, exc)
            overall_success = False
            details.append(f"Metadata update failed for {log_id}: {exc}")

    return {
        "success": overall_success,
        "detail": "; ".join(details),
        "issue_key": issue_key,
        "log_ids": log_ids,
    }
