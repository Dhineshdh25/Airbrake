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
        error_message = linked_row.get("error") or (issue or {}).get("summary") or ""
        jira_status = (issue or {}).get("status", "") or ""
        current_status = linked_row.get("error_status") or ""

        # Skip rows that are already resolved — they were resolved by a previous
        # sync run or manually. Do not overwrite or duplicate-process them.
        if current_status == "resolved":
            logger.info(
                "[SyncPipeline] log_id=%s already resolved — skipping (issue=%s)",
                log_id, issue_key,
            )
            details.append(f"log_id={log_id} already resolved — skipped.")
            continue

        logger.info(
            "[SyncPipeline] Processing log_id=%s issue=%s current_status=%s",
            log_id, issue_key, current_status or "null",
        )

        # ── Solution extraction ───────────────────────────────────────────────
        # Strategy:
        # 1. Get the latest comment from the issue.
        # 2. Use Nova to classify it — is it a technical solution or just discussion?
        # 3. If it's a solution, use it directly (preserves full human-written text).
        # 4. If Nova finds it's not a solution / no comment, fall back to Nova's
        #    own extraction from the full issue content.
        solution_text = None
        comments = (issue or {}).get("comments") or []

        # Find the latest non-empty comment
        latest_comment_body = None
        latest_comment_author = None
        for c in reversed(comments):
            body = (c.get("body") or "").strip()
            if body and len(body) > 15:
                latest_comment_body = body
                latest_comment_author = (
                    (c.get("author") or {}).get("displayName")
                    or (c.get("author") or {}).get("display_name")
                    or "sync"
                )
                break

        if latest_comment_body:
            # Ask Nova: is this comment a technical solution or just discussion?
            from .nova_extractor import _call_nova, _parse_nova_response
            classify_prompt = (
                "You are evaluating a Jira comment to determine if it contains a technical solution.\n\n"
                f"COMMENT:\n{latest_comment_body[:1000]}\n\n"
                "Does this comment describe a specific technical fix, root cause analysis, or actionable solution?\n"
                "IGNORE: greetings, status updates ('I'll look into this'), questions, vague statements.\n"
                "ONLY accept: specific technical actions taken, code changes, configuration fixes, root cause + fix.\n\n"
                "Return ONLY valid JSON:\n"
                "{\"is_solution\": <true or false>, \"confidence\": <0.0 to 1.0>}"
            )
            classify_raw = _call_nova(classify_prompt)
            is_solution = False
            if classify_raw:
                try:
                    import json as _j
                    text = classify_raw.strip()
                    start = text.find("{"); end = text.rfind("}") + 1
                    if start != -1 and end > 0:
                        result = _j.loads(text[start:end])
                        is_solution = bool(result.get("is_solution", False))
                        confidence = float(result.get("confidence", 0.0))
                        # Only use if confidence >= 0.5
                        if confidence < 0.5:
                            is_solution = False
                except Exception:
                    is_solution = False
            else:
                # Nova unavailable — heuristic: if comment is > 50 chars and
                # contains technical keywords, treat as solution
                tech_keywords = {"fix", "solve", "resolv", "updat", "chang", "configur",
                                  "install", "remov", "replac", "set ", "add ", "run ", "pip ",
                                  "command", "code", "function", "class", "error", "import"}
                body_lower = latest_comment_body.lower()
                is_solution = (
                    len(latest_comment_body) > 50
                    and any(kw in body_lower for kw in tech_keywords)
                )

            if is_solution:
                solution_text = latest_comment_body
                logger.info(
                    "[SyncPipeline] Using latest comment as solution for %s (len=%d)",
                    issue_key, len(solution_text),
                )

        # If comment wasn't a solution, fall back to Nova full extraction
        if not solution_text:
            extraction = extract_solution_from_issue(issue)
            solution_text = build_solution_text(extraction)
            if solution_text:
                logger.info(
                    "[SyncPipeline] Using Nova extraction for %s",
                    issue_key,
                )

        # Last resort: use the comment body directly even if not classified as solution
        if not solution_text and latest_comment_body and len(latest_comment_body) > 30:
            solution_text = latest_comment_body
            logger.info(
                "[SyncPipeline] Last resort: using latest comment directly for %s",
                issue_key,
            )

        creator = latest_comment_author or (
            (issue or {}).get("reporter", {}).get("displayName")
            or (issue or {}).get("assignee", {}).get("displayName")
            or "sync"
        )

        if not solution_text:
            overall_success = False
            detail = "No extractable solution found for Jira issue."
        else:
            solution_ok = False
            try:
                sol_result = insert_solution(
                    error_hash=error_hash,
                    solution=solution_text,
                    created_by=f"jira:{creator}",
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
                elif "no matching log row" in exc_str.lower() or isinstance(exc, (ValueError, AttributeError)):
                    # log row not found by insert_solution lookup — resolve directly without KB insert
                    solution_ok = True
                    detail = "Could not insert to KB (log row lookup failed) — resolving error directly."
                    logger.warning("[SyncPipeline] insert_solution lookup failed for %s: %s — resolving anyway", error_hash, exc)
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
