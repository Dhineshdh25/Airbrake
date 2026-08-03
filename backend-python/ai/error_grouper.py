"""Intelligent semantic error grouping — fixed taxonomy edition.

Every log row gets three columns (added via ALTER TABLE):
    error_group_id       TEXT     — deterministic MD5 of the category name
    error_group_name     TEXT     — exactly one of the 18 PRIMARY_GROUPS below
    manual_group_override BOOLEAN — TRUE means a developer chose the group; AI never overwrites

Design
──────
The AI NEVER invents group names.  It classifies every error into exactly one
of the 18 predefined PRIMARY_GROUPS.  group_id = MD5(group_name), so it is
stable, deterministic, and collision-free across the whole system.

This eliminates fragmentation entirely.  "File not found", "File access conflict",
and "File existence conflict" all become "File Errors" with the same group_id.

Pipeline (per error row)
  1. Ask Nova Lite: "Which category does this error belong to?"
     Nova must return exactly one name from PRIMARY_GROUPS.
  2. Validate the response against PRIMARY_GROUPS.  If invalid → "Unknown".
  3. group_id  = MD5(group_name)
  4. Persist group_id + group_name on the log row.
  5. (Optional) Upsert error vector to Pinecone for solution recommendations.

Manual override
  When manual_group_override = TRUE the row is never reclassified.
  Developers update via PATCH /api/error-groups/override.

Backfill
  backfill_unclassified() processes rows where error_group_id IS NULL.
  reclassify_all() reprocesses ALL existing rows to apply the new taxonomy
  and collapse old fragmented group names into the canonical set.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from db import execute, query

logger = logging.getLogger(__name__)

TABLE = "projects_data"

# ── Tuning ────────────────────────────────────────────────────────────────────
BACKFILL_BATCH   = 50    # rows per backfill iteration
NOVA_MAX_TOKENS  = 20    # the answer is just the category name — keep it very tight

# ── Pinecone namespace for error embeddings ───────────────────────────────────
# Still used for solution recommendations; NOT used for group classification.
_ERROR_NAMESPACE = "errors"


# ═════════════════════════════════════════════════════════════════════════════
# FIXED TAXONOMY — the ONLY allowed group names
# ═════════════════════════════════════════════════════════════════════════════

PRIMARY_GROUPS: List[str] = [
    "File Errors",
    "Input Validation",
    "JSON / Serialization",
    "Authentication",
    "Authorization / Permission",
    "Database",
    "Network",
    "API / External Service",
    "Resource Limits",
    "Configuration",
    "Programming Errors",
    "Syntax & Parsing",
    "Dependency & Package",
    "Workflow / Business Logic",
    "Data Integrity",
    "AI / ML",
    "System / Infrastructure",
    "Unknown",
]

# Stable group_id = MD5(group_name) — deterministic and cross-project consistent
_TAXONOMY_IDS: Dict[str, str] = {
    name: hashlib.md5(name.encode("utf-8")).hexdigest()
    for name in PRIMARY_GROUPS
}

_TAXONOMY_NAMES_LOWER: Dict[str, str] = {
    name.lower(): name for name in PRIMARY_GROUPS
}


def _canonical_group(name: str) -> tuple[str, str]:
    """Return (group_id, canonical_name) for a taxonomy entry.
    Falls back to Unknown if name is not in the taxonomy.
    """
    clean = name.strip()
    canonical = _TAXONOMY_NAMES_LOWER.get(clean.lower())
    if canonical is None:
        canonical = "Unknown"
    group_id = _TAXONOMY_IDS[canonical]
    return group_id, canonical


# ═════════════════════════════════════════════════════════════════════════════
# Nova classification prompt
# ═════════════════════════════════════════════════════════════════════════════

_TAXONOMY_LIST = "\n".join(f"- {name}" for name in PRIMARY_GROUPS)

_CLASSIFICATION_PROMPT_TEMPLATE = """\
You are a software error classification assistant.

Your task: choose the SINGLE best matching category from the list below.

RULES:
- Return ONLY the exact category name from the list.
- Do not add any explanation, punctuation, or extra words.
- Do not invent new categories.
- Use semantic reasoning about the root cause, not just keyword matching.

CATEGORIES:
{taxonomy}

ERROR TO CLASSIFY:
{error}

YOUR ANSWER (one category name only):"""

CLASSIFICATION_GUIDELINES = """\

CLASSIFICATION GUIDELINES:
- File Errors: missing file, empty file, unreadable file, invalid path, file permissions, upload/download issues
- Input Validation: invalid user input, missing required field, invalid argument, bad format from user
- JSON / Serialization: JSONDecodeError, malformed JSON, serialization/deserialization failures
- Authentication: invalid credentials, expired token, JWT invalid, login failed
- Authorization / Permission: 403 Forbidden, access denied, insufficient privileges, RBAC failure
- Database: SQL errors, database timeout, constraint violation, deadlock, connection refused
- Network: connection reset, DNS failure, socket closed, host unreachable, TLS/SSL failure
- API / External Service: HTTP 4xx/5xx from external service, third-party API unavailable, rate limiting
- Resource Limits: memory exceeded, disk full, buffer overflow, max retries exceeded, storage quota
- Configuration: missing env variable, invalid config file, incorrect deployment configuration
- Programming Errors: AttributeError, TypeError, ValueError, KeyError, IndexError, NoneType errors, RuntimeError
- Syntax & Parsing: SyntaxError, IndentationError, parser error, compiler error, lexer error
- Dependency & Package: ModuleNotFoundError, ImportError, missing package, dependency conflict
- Workflow / Business Logic: invalid workflow state, missing relationship, business rule violation
- Data Integrity: CRC mismatch, checksum failure, duplicate record, corrupted data, schema mismatch
- AI / ML: embedding failed, LLM timeout, vector search failure, model unavailable, Pinecone/Bedrock errors
- System / Infrastructure: internal server error, worker crashed, container failure, service unavailable
- Unknown: use ONLY if none of the above fit"""


def _build_classification_prompt(error_message: str, error_detail: Optional[str]) -> str:
    """Build the Nova classification prompt."""
    context = error_message.strip()
    if error_detail:
        # Include first 400 chars of detail for context
        detail_snippet = error_detail.strip()[:400]
        context = f"{context}\n\nDetail:\n{detail_snippet}"

    return (
        _CLASSIFICATION_PROMPT_TEMPLATE.format(
            taxonomy=_TAXONOMY_LIST + CLASSIFICATION_GUIDELINES,
            error=context[:800],
        )
    )


def _call_nova_classify(error_message: str, error_detail: Optional[str]) -> str:
    """Call Nova and return a canonical category name. Falls back to 'Unknown'."""
    try:
        from ai.bedrock_llm import _call_nova
        prompt = _build_classification_prompt(error_message, error_detail)
        raw    = _call_nova(prompt, max_tokens=NOVA_MAX_TOKENS)
        if not raw:
            logger.warning("[ErrorGrouper] Nova returned empty response — defaulting to Unknown")
            return "Unknown"

        answer = raw.strip()

        # Try exact match first (case-insensitive)
        canonical_match = _TAXONOMY_NAMES_LOWER.get(answer.lower())
        if canonical_match:
            logger.info("[ErrorGrouper] Nova classified: %r -> %r", answer, canonical_match)
            return canonical_match

        # Try partial match — Nova sometimes adds punctuation or quotes
        answer_clean = re.sub(r'[^a-z /&]', '', answer.lower()).strip()
        for lower_name, canon_name in _TAXONOMY_NAMES_LOWER.items():
            if lower_name in answer_clean or answer_clean in lower_name:
                logger.info(
                    "[ErrorGrouper] Nova partial match: %r -> %r", answer, canon_name
                )
                return canon_name

        logger.warning(
            "[ErrorGrouper] Nova returned unrecognised category=%r — defaulting to Unknown",
            answer[:120],
        )
        return "Unknown"

    except Exception as exc:
        logger.exception("[ErrorGrouper] Nova classification failed: %s", exc)
        return "Unknown"


# ═════════════════════════════════════════════════════════════════════════════
# Pinecone helpers (for embedding upsert only — not used for classification)
# ═════════════════════════════════════════════════════════════════════════════

def _build_query_text(error_message: str, error_detail: Optional[str]) -> str:
    parts = [error_message.strip()]
    if error_detail:
        parts.append(error_detail.strip()[:500])
    return "\n\n".join(parts)


def _get_embedding(text: str) -> Optional[List[float]]:
    try:
        from ai.embeddings import create_embedding
        vec = create_embedding(text)
        if vec and len(vec) == 1024 and any(v != 0.0 for v in vec):
            return vec
        logger.warning("[ErrorGrouper] Embedding returned zero/empty vector")
        return None
    except Exception as exc:
        logger.exception("[ErrorGrouper] Embedding failed: %s", exc)
        return None


def _pinecone_upsert_error(
    log_id: str, embedding: List[float],
    group_id: str, group_name: str,
    error_message: str, project_name: str,
) -> None:
    """Store the error vector in Pinecone for solution recommendation lookups. Never raises."""
    try:
        from ai.pinecone_service import _get_index
        index = _get_index()
        index.upsert(
            vectors=[{
                "id":     log_id,
                "values": embedding,
                "metadata": {
                    "log_id":        log_id,
                    "group_id":      group_id,
                    "group_name":    group_name,
                    "error_message": error_message[:200],
                    "project_name":  project_name,
                },
            }],
            namespace=_ERROR_NAMESPACE,
        )
        logger.info("[ErrorGrouper] Pinecone upsert OK log_id=%r group=%r", log_id, group_name)
    except Exception as exc:
        logger.exception("[ErrorGrouper] Pinecone upsert failed (non-fatal): %s", exc)


# ═════════════════════════════════════════════════════════════════════════════
# Aurora helpers
# ═════════════════════════════════════════════════════════════════════════════

def _write_group_to_row(log_id: str, group_id: str, group_name: str) -> None:
    """Persist group_id and group_name on the log row. Never raises."""
    try:
        execute(
            f"UPDATE {TABLE} "
            f"SET error_group_id = %s, error_group_name = %s "
            f"WHERE id = %s "
            f"AND (manual_group_override IS NULL OR manual_group_override = FALSE)",
            (group_id, group_name, log_id),
        )
    except Exception as exc:
        logger.exception("[ErrorGrouper] Aurora write failed log_id=%r: %s", log_id, exc)


# ═════════════════════════════════════════════════════════════════════════════
# Core classifier — public entry point
# ═════════════════════════════════════════════════════════════════════════════

def classify_error(
    log_id: str,
    error_message: str,
    project_name: str,
    error_detail: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Classify one log row into a fixed taxonomy category.

    Returns:
        {
            "group_id":   str,   # MD5 of the category name — stable and deterministic
            "group_name": str,   # exactly one of PRIMARY_GROUPS
            "reason":     str,   # "nova_classified" | "skipped" | "nova_unavailable"
        }

    Never raises. On any failure the row is classified as "Unknown".
    """
    logger.info(
        "[ErrorGrouper] START classify log_id=%r project=%r error=%r",
        log_id, project_name, error_message[:120],
    )

    # ── Guard: manual override — never reclassify ─────────────────────────────
    try:
        rows = query(
            f"SELECT error_group_id, manual_group_override FROM {TABLE} WHERE id = %s",
            (log_id,),
        )
        if rows and rows[0].get("manual_group_override"):
            gid = rows[0].get("error_group_id") or ""
            logger.info("[ErrorGrouper] SKIP manual_group_override=TRUE log_id=%r", log_id)
            return {"group_id": gid, "group_name": "", "reason": "skipped"}
    except Exception as exc:
        logger.exception("[ErrorGrouper] Guard query failed: %s", exc)

    # ── Classify via Nova ─────────────────────────────────────────────────────
    logger.info("[ErrorGrouper] Calling Nova to classify error")
    group_name = _call_nova_classify(error_message, error_detail)
    group_id, group_name = _canonical_group(group_name)

    logger.info(
        "[ErrorGrouper] RESULT log_id=%r -> group=%r id=%r",
        log_id, group_name, group_id,
    )

    if not dry_run:
        _write_group_to_row(log_id, group_id, group_name)

        # Best-effort Pinecone upsert for solution recommendations
        try:
            query_text = _build_query_text(error_message, error_detail)
            embedding  = _get_embedding(query_text)
            if embedding:
                _pinecone_upsert_error(
                    log_id, embedding, group_id, group_name,
                    error_message, project_name,
                )
        except Exception as exc:
            logger.exception("[ErrorGrouper] Pinecone upsert failed (non-fatal): %s", exc)

    return {
        "group_id":   group_id,
        "group_name": group_name,
        "reason":     "nova_classified",
    }


# ═════════════════════════════════════════════════════════════════════════════
# Backfill — process unclassified rows
# ═════════════════════════════════════════════════════════════════════════════

def backfill_unclassified(
    batch_size: int = BACKFILL_BATCH,
    max_batches: int = 20,
    project_name: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Classify all existing log rows that have error_group_id IS NULL.

    Safe to call repeatedly — rows already classified are skipped.
    """
    processed  = 0
    classified = 0
    errors_hit = 0
    batches_done = 0

    for batch_num in range(max_batches):
        conditions = [
            "row_type = 'log'",
            "error IS NOT NULL",
            "error <> ''",
            "error_group_id IS NULL",
        ]
        params: List[Any] = []
        if project_name:
            conditions.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)

        rows = query(
            f"SELECT id, project_name, error, error_detail "
            f"FROM {TABLE} "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY timestamp DESC "
            f"LIMIT %s",
            tuple(params + [batch_size]),
        )

        if not rows:
            logger.info("[ErrorGrouper] backfill_unclassified: no more NULL rows")
            break

        batches_done += 1
        logger.info("[ErrorGrouper] backfill batch=%d rows=%d", batch_num + 1, len(rows))

        for row in rows:
            processed += 1
            try:
                classify_error(
                    log_id        = row["id"],
                    error_message = row["error"],
                    project_name  = row["project_name"],
                    error_detail  = row.get("error_detail"),
                    dry_run       = dry_run,
                )
                classified += 1
            except Exception as exc:
                errors_hit += 1
                logger.exception(
                    "[ErrorGrouper] backfill classify failed log_id=%r: %s",
                    row.get("id"), exc,
                )

    summary = {
        "processed":    processed,
        "classified":   classified,
        "errors":       errors_hit,
        "batches_done": batches_done,
        "done":         processed < batch_size or batches_done < max_batches,
        "dry_run":      dry_run,
    }
    logger.info("[ErrorGrouper] backfill_unclassified summary: %s", summary)
    return summary


# ═════════════════════════════════════════════════════════════════════════════
# Reclassify — overwrite existing groups with fixed taxonomy
# ═════════════════════════════════════════════════════════════════════════════

def reclassify_all(
    batch_size: int = 100,
    max_batches: int = 50,
    project_name: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Reclassify ALL existing log rows using the fixed taxonomy.

    This replaces every arbitrary AI-generated group name with exactly one of
    the 18 predefined PRIMARY_GROUPS.  Run this once after deploying the new
    taxonomy to collapse all fragmented group names.

    Because group_id = MD5(group_name) and all taxonomy names are fixed,
    rows that belong to the same category will automatically share the same
    group_id — merging is implicit, no separate merge step needed.

    manual_group_override = TRUE rows are always skipped.
    """
    processed  = 0
    reclassified = 0
    skipped    = 0
    errors_hit = 0
    batches_done = 0

    logger.info(
        "[ErrorGrouper] reclassify_all START taxonomy=%d categories batch_size=%d max_batches=%d project=%r dry_run=%s",
        len(PRIMARY_GROUPS), batch_size, max_batches, project_name, dry_run,
    )

    for batch_num in range(max_batches):
        conditions = [
            "row_type = 'log'",
            "error IS NOT NULL",
            "error <> ''",
            "(manual_group_override IS NULL OR manual_group_override = FALSE)",
        ]
        params: List[Any] = []
        if project_name:
            conditions.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)

        # Fetch the next batch ordered by timestamp — consistent pagination
        rows = query(
            f"SELECT id, project_name, error, error_detail, error_group_name "
            f"FROM {TABLE} "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY timestamp DESC "
            f"LIMIT %s OFFSET %s",
            tuple(params + [batch_size, batch_num * batch_size]),
        )

        if not rows:
            logger.info("[ErrorGrouper] reclassify_all: no more rows at batch %d", batch_num + 1)
            break

        batches_done += 1
        logger.info(
            "[ErrorGrouper] reclassify_all batch=%d rows=%d",
            batch_num + 1, len(rows),
        )

        for row in rows:
            processed += 1
            old_name = row.get("error_group_name") or "(none)"
            try:
                result = classify_error(
                    log_id        = row["id"],
                    error_message = row["error"],
                    project_name  = row["project_name"],
                    error_detail  = row.get("error_detail"),
                    dry_run       = dry_run,
                )
                new_name = result.get("group_name", "")
                if result.get("reason") == "skipped":
                    skipped += 1
                else:
                    reclassified += 1
                    if old_name != new_name:
                        logger.info(
                            "[ErrorGrouper] reclassify_all log_id=%r  %r -> %r",
                            row["id"], old_name, new_name,
                        )
            except Exception as exc:
                errors_hit += 1
                logger.exception(
                    "[ErrorGrouper] reclassify_all classify failed log_id=%r: %s",
                    row.get("id"), exc,
                )

    summary = {
        "processed":     processed,
        "reclassified":  reclassified,
        "skipped":       skipped,
        "errors":        errors_hit,
        "batches_done":  batches_done,
        "done":          True,
        "dry_run":       dry_run,
        "taxonomy_size": len(PRIMARY_GROUPS),
    }
    logger.info("[ErrorGrouper] reclassify_all summary: %s", summary)
    return summary


# ═════════════════════════════════════════════════════════════════════════════
# Manual override and group listing
# ═════════════════════════════════════════════════════════════════════════════

def apply_manual_override(
    log_id: str,
    group_id: str,
    group_name: str,
) -> bool:
    """Set a manual group on a log row. Returns True on success."""
    # Validate: group_name must be one of the taxonomy names OR a custom override
    # We allow custom names for manual overrides (developer's decision).
    try:
        execute(
            f"UPDATE {TABLE} "
            f"SET error_group_id = %s, error_group_name = %s, manual_group_override = TRUE "
            f"WHERE id = %s AND row_type = 'log'",
            (group_id, group_name, log_id),
        )
        logger.info(
            "[ErrorGrouper] Manual override applied log_id=%r group=%r",
            log_id, group_name,
        )
        return True
    except Exception as exc:
        logger.exception("[ErrorGrouper] Manual override failed: %s", exc)
        return False


def list_groups(project_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all distinct error groups with counts.

    Cross-project unless project_name is given.
    Results are ordered by occurrence count DESC.
    """
    conditions = [
        "row_type = 'log'",
        "error_group_id IS NOT NULL",
    ]
    params: List[Any] = []
    if project_name:
        conditions.append("LOWER(project_name) = LOWER(%s)")
        params.append(project_name)

    try:
        rows = query(
            f"SELECT "
            f"  error_group_id, "
            f"  MAX(error_group_name) AS error_group_name, "
            f"  COUNT(*) AS occurrence_count, "
            f"  MIN(timestamp) AS first_seen, "
            f"  MAX(timestamp) AS last_seen "
            f"FROM {TABLE} "
            f"WHERE {' AND '.join(conditions)} "
            f"GROUP BY error_group_id "
            f"ORDER BY occurrence_count DESC",
            tuple(params) if params else None,
        )
        return rows
    except Exception as exc:
        logger.exception("[ErrorGrouper] list_groups failed: %s", exc)
        return []


def get_taxonomy() -> List[Dict[str, str]]:
    """Return the full fixed taxonomy list with stable group_ids."""
    return [
        {"group_id": _TAXONOMY_IDS[name], "group_name": name}
        for name in PRIMARY_GROUPS
    ]
