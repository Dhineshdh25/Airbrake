"""Intelligent semantic error grouping.

Every log row gets three new columns (already added via ALTER TABLE):
    error_group_id       TEXT     — stable UUID identifying the semantic group
    error_group_name     TEXT     — human-readable group label
    manual_group_override BOOLEAN — TRUE means a developer chose the group; AI never overwrites

Architecture
────────────
classify_error() is the single entry point. Call it after inserting any log row.

Grouping pipeline (cheapest first):
  STEP 1 — Embedding                    Titan embed (error + detail)
  STEP 2 — Pinecone approximate-search  find existing group vectors, threshold >= 0.82
  STEP 3 — Nova Lite confirmation        only when Pinecone score is in 0.82–0.92 "fuzzy" band
  STEP 4 — New group creation            when no match found; Nova names the group

Cross-project
  Pinecone is queried WITHOUT a project_name filter, so semantically identical
  errors from different projects land in the same group.  Project metadata is
  preserved on each log row unchanged.

Manual override
  When manual_group_override = TRUE the row is never reclassified.
  Developers update the three columns via PATCH /api/error-groups/override.

Backfill
  backfill_unclassified(batch_size, max_batches) processes existing rows that
  have error_group_id IS NULL.  Safe to call repeatedly; idempotent.

Taxonomy (auto-assigned group names)
  Nova Lite derives a short group name like "File not found" or "Permission denied".
  The name is the same for all rows that belong to the group.

Logging
  Every classification decision is logged at INFO level with:
    incoming_error, project, embedding_dim, pinecone_matches,
    similarity_scores, nova_used, chosen_group_id, chosen_group_name,
    reason (new_group | pinecone_match | nova_confirmed | manual_override)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from db import execute, query

logger = logging.getLogger(__name__)

TABLE = "projects_data"

# ── Tuning constants ──────────────────────────────────────────────────────────
PINECONE_MATCH_LIMIT   = 8      # how many Pinecone neighbours to retrieve
PINECONE_AUTO_THRESHOLD  = 0.92  # >= this  → automatically same group (no Nova)
PINECONE_FUZZY_LOW       = 0.82  # >= this  → ask Nova to confirm
# below 0.82 → new group
NOVA_MAX_TOKENS          = 80    # token budget for group-name generation
BACKFILL_BATCH           = 50    # rows per backfill iteration


# ── Pinecone namespace for error vectors ─────────────────────────────────────
# We use a dedicated "errors" namespace so error vectors don't collide with
# solution vectors that live in the same index.
_ERROR_NAMESPACE = "errors"


# ─────────────────────────────────────────────────────────────────────────────
# Embedding
# ─────────────────────────────────────────────────────────────────────────────

def _build_query_text(error_message: str, error_detail: Optional[str]) -> str:
    """Combine error + detail into the text that will be embedded."""
    parts = [error_message.strip()]
    if error_detail:
        # Keep the first 500 chars of the stack trace — enough signal, not too long
        parts.append(error_detail.strip()[:500])
    return "\n\n".join(parts)


def _get_embedding(text: str) -> Optional[List[float]]:
    """Generate a Titan embedding. Returns None on any failure (never raises)."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Pinecone — error-namespace helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pinecone_upsert_error(log_id: str, embedding: List[float],
                            group_id: str, error_message: str,
                            project_name: str) -> None:
    """Upsert the error vector into the 'errors' namespace. Never raises."""
    try:
        from ai.pinecone_service import _get_index
        index = _get_index()
        index.upsert(
            vectors=[{
                "id":       log_id,
                "values":   embedding,
                "metadata": {
                    "log_id":        log_id,
                    "group_id":      group_id,
                    "error_message": error_message[:200],
                    "project_name":  project_name,
                },
            }],
            namespace=_ERROR_NAMESPACE,
        )
        logger.info("[ErrorGrouper] Pinecone upsert OK log_id=%r group_id=%r", log_id, group_id)
    except Exception as exc:
        logger.exception("[ErrorGrouper] Pinecone upsert failed (non-fatal): %s", exc)


def _pinecone_query_errors(embedding: List[float], top_k: int = PINECONE_MATCH_LIMIT
                           ) -> List[Dict[str, Any]]:
    """Query the errors namespace — NO project filter (cross-project grouping)."""
    try:
        from ai.pinecone_service import _get_index
        index = _get_index()
        results = index.query(
            vector=embedding,
            top_k=top_k,
            include_metadata=True,
            namespace=_ERROR_NAMESPACE,
        )
        matches = (
            results.get("matches", [])
            if isinstance(results, dict)
            else getattr(results, "matches", []) or []
        )
        logger.info("[ErrorGrouper] Pinecone query returned %d matches", len(matches))
        return matches
    except Exception as exc:
        logger.exception("[ErrorGrouper] Pinecone query failed (non-fatal): %s", exc)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Nova Lite helpers
# ─────────────────────────────────────────────────────────────────────────────

def _nova_confirm_same_group(error_a: str, error_b: str) -> bool:
    """Ask Nova whether two errors represent the same root cause. Defaults False on failure."""
    try:
        from ai.bedrock_llm import _call_nova
        prompt = (
            "Do these two software errors represent the same underlying root cause?\n"
            "Ignore differences in file paths, variable names, timestamps, and IDs.\n"
            "Focus only on the error type and cause.\n\n"
            f"Error A: {error_a[:300]}\n\n"
            f"Error B: {error_b[:300]}\n\n"
            "Answer with exactly one word: YES or NO"
        )
        raw = _call_nova(prompt, max_tokens=10)
        answer = (raw or "").strip().upper()
        result = answer.startswith("YES")
        logger.info("[ErrorGrouper] Nova confirm_same_group: %r -> %s", answer, result)
        return result
    except Exception as exc:
        logger.exception("[ErrorGrouper] Nova confirmation failed — defaulting to False: %s", exc)
        return False


def _nova_name_group(error_message: str, error_detail: Optional[str] = None) -> str:
    """Ask Nova for a short (3–6 word) group name for this error. Falls back to truncated error text."""
    try:
        from ai.bedrock_llm import _call_nova
        context = error_message.strip()
        if error_detail:
            context += f"\n{error_detail.strip()[:300]}"
        prompt = (
            "Give a short 3-6 word group name for this software error.\n"
            "The name should describe the ROOT CAUSE category, not the specific file or variable.\n"
            "Examples: 'File not found', 'Permission denied', 'Invalid input format', "
            "'NoneType attribute error', 'XML parse failure', 'Missing config key'\n\n"
            f"Error: {context[:400]}\n\n"
            "Output ONLY the group name, nothing else."
        )
        raw = _call_nova(prompt, max_tokens=NOVA_MAX_TOKENS)
        name = (raw or "").strip()
        # Sanitise: strip quotes, trim to 80 chars
        name = re.sub(r'^["\']|["\']$', '', name).strip()[:80]
        if name:
            logger.info("[ErrorGrouper] Nova group name: %r", name)
            return name
    except Exception as exc:
        logger.exception("[ErrorGrouper] Nova group naming failed — using fallback: %s", exc)

    # Fallback: use first 60 chars of error message
    fallback = error_message.strip()[:60]
    logger.info("[ErrorGrouper] Group name fallback: %r", fallback)
    return fallback


# ─────────────────────────────────────────────────────────────────────────────
# Aurora helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write_group_to_row(log_id: str, group_id: str, group_name: str) -> None:
    """Persist error_group_id and error_group_name on the log row. Never raises."""
    try:
        execute(
            f"UPDATE {TABLE} "
            f"SET error_group_id = %s, error_group_name = %s "
            f"WHERE id = %s AND (manual_group_override IS NULL OR manual_group_override = FALSE)",
            (group_id, group_name, log_id),
        )
    except Exception as exc:
        logger.exception("[ErrorGrouper] Aurora write failed log_id=%r: %s", log_id, exc)


def _resolve_group_from_pinecone_match(match: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Extract (group_id, group_name) from a Pinecone match's metadata."""
    metadata = match.get("metadata") or {}
    if isinstance(metadata, dict):
        gid   = metadata.get("group_id")
        gname = metadata.get("group_name")  # may be absent in older vectors
        return gid, gname
    return None, None


def _get_group_name_for_id(group_id: str) -> Optional[str]:
    """Fetch the group name for an existing group_id from any log row that has it."""
    try:
        rows = query(
            f"SELECT error_group_name FROM {TABLE} "
            f"WHERE row_type = 'log' AND error_group_id = %s "
            f"AND error_group_name IS NOT NULL LIMIT 1",
            (group_id,),
        )
        if rows:
            return rows[0].get("error_group_name")
    except Exception as exc:
        logger.exception("[ErrorGrouper] _get_group_name_for_id failed: %s", exc)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Core classifier
# ─────────────────────────────────────────────────────────────────────────────

def classify_error(
    log_id: str,
    error_message: str,
    project_name: str,
    error_detail: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify one log row into a semantic error group.

    Returns:
        {
            "group_id":   str,
            "group_name": str,
            "reason":     "new_group" | "pinecone_auto" | "nova_confirmed" | "skipped",
            "similarity": float | None,
        }

    Never raises. On any failure, a new UUID group is created so the row is
    always classified and the pipeline never blocks ingest.
    """
    logger.info(
        "[ErrorGrouper] START classify log_id=%r project=%r error=%r",
        log_id, project_name, error_message[:120],
    )

    # ── Guard: already classified and not overrideable ────────────────────────
    try:
        rows = query(
            f"SELECT error_group_id, manual_group_override FROM {TABLE} "
            f"WHERE id = %s",
            (log_id,),
        )
        if rows:
            row = rows[0]
            if row.get("manual_group_override"):
                gid = row.get("error_group_id") or ""
                logger.info("[ErrorGrouper] SKIP manual_group_override=TRUE log_id=%r group=%r", log_id, gid)
                return {"group_id": gid, "group_name": "", "reason": "skipped", "similarity": None}
            if row.get("error_group_id"):
                # Already classified; re-classify to allow backfill to fix old rows
                logger.info("[ErrorGrouper] Re-classifying existing log_id=%r", log_id)
    except Exception as exc:
        logger.exception("[ErrorGrouper] Guard query failed: %s", exc)

    # ── STEP 1: embedding ─────────────────────────────────────────────────────
    query_text = _build_query_text(error_message, error_detail)
    embedding  = _get_embedding(query_text)

    if embedding is None:
        # No embedding available — fall back to a deterministic group based on
        # the normalized error text so identical messages still cluster together.
        from ai.error_matching import normalize_error_for_lookup
        normalized = normalize_error_for_lookup(error_message)
        group_id   = hashlib.md5(normalized.encode()).hexdigest() if normalized else str(uuid.uuid4())
        group_name = error_message.strip()[:60]
        _write_group_to_row(log_id, group_id, group_name)
        logger.info("[ErrorGrouper] RESULT no-embedding fallback group_id=%r", group_id)
        return {"group_id": group_id, "group_name": group_name, "reason": "new_group", "similarity": None}

    logger.info("[ErrorGrouper] Embedding generated dim=%d", len(embedding))

    # ── STEP 2: Pinecone approximate nearest-neighbour ────────────────────────
    matches = _pinecone_query_errors(embedding)

    best_score: float = 0.0
    best_group_id: Optional[str] = None
    best_group_name: Optional[str] = None
    best_match_error: Optional[str] = None

    for m in matches:
        score = float(m.get("score") or 0.0)
        meta  = m.get("metadata") or {}
        gid   = meta.get("group_id") if isinstance(meta, dict) else None
        if not gid:
            continue
        logger.info(
            "[ErrorGrouper] Pinecone match score=%.4f group_id=%r error=%r",
            score, gid, (meta.get("error_message") or "")[:80],
        )
        if score > best_score:
            best_score      = score
            best_group_id   = gid
            best_group_name = meta.get("group_name") if isinstance(meta, dict) else None
            best_match_error = meta.get("error_message", "") if isinstance(meta, dict) else ""

    logger.info(
        "[ErrorGrouper] Best Pinecone score=%.4f group_id=%r",
        best_score, best_group_id,
    )

    # ── STEP 3: decision tree ─────────────────────────────────────────────────

    # 3a — High-confidence automatic match
    if best_group_id and best_score >= PINECONE_AUTO_THRESHOLD:
        group_name = best_group_name or _get_group_name_for_id(best_group_id) or error_message[:60]
        _write_group_to_row(log_id, best_group_id, group_name)
        _pinecone_upsert_error(log_id, embedding, best_group_id, error_message, project_name)
        logger.info(
            "[ErrorGrouper] RESULT pinecone_auto group_id=%r name=%r similarity=%.4f",
            best_group_id, group_name, best_score,
        )
        return {
            "group_id":   best_group_id,
            "group_name": group_name,
            "reason":     "pinecone_auto",
            "similarity": best_score,
        }

    # 3b — Fuzzy band: ask Nova to confirm
    if best_group_id and best_score >= PINECONE_FUZZY_LOW:
        logger.info(
            "[ErrorGrouper] Fuzzy band — asking Nova to confirm score=%.4f", best_score
        )
        confirmed = _nova_confirm_same_group(error_message, best_match_error or "")
        if confirmed:
            group_name = best_group_name or _get_group_name_for_id(best_group_id) or error_message[:60]
            _write_group_to_row(log_id, best_group_id, group_name)
            _pinecone_upsert_error(log_id, embedding, best_group_id, error_message, project_name)
            logger.info(
                "[ErrorGrouper] RESULT nova_confirmed group_id=%r name=%r similarity=%.4f",
                best_group_id, group_name, best_score,
            )
            return {
                "group_id":   best_group_id,
                "group_name": group_name,
                "reason":     "nova_confirmed",
                "similarity": best_score,
            }
        logger.info("[ErrorGrouper] Nova said NOT same group — creating new group")

    # 3c — No match: create a new group
    new_group_id   = str(uuid.uuid4())
    new_group_name = _nova_name_group(error_message, error_detail)
    _write_group_to_row(log_id, new_group_id, new_group_name)
    # Store the group name in the Pinecone metadata too so future lookups can read it
    _pinecone_upsert_error_with_group_name(
        log_id, embedding, new_group_id, new_group_name, error_message, project_name
    )
    logger.info(
        "[ErrorGrouper] RESULT new_group group_id=%r name=%r",
        new_group_id, new_group_name,
    )
    return {
        "group_id":   new_group_id,
        "group_name": new_group_name,
        "reason":     "new_group",
        "similarity": best_score if best_score > 0 else None,
    }


def _pinecone_upsert_error_with_group_name(
    log_id: str, embedding: List[float], group_id: str,
    group_name: str, error_message: str, project_name: str,
) -> None:
    """Upsert with group_name included in metadata. Never raises."""
    try:
        from ai.pinecone_service import _get_index
        index = _get_index()
        index.upsert(
            vectors=[{
                "id":       log_id,
                "values":   embedding,
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
        logger.info("[ErrorGrouper] Pinecone upsert (new group) OK log_id=%r group_id=%r name=%r",
                    log_id, group_id, group_name)
    except Exception as exc:
        logger.exception("[ErrorGrouper] Pinecone upsert (new group) failed (non-fatal): %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Backfill
# ─────────────────────────────────────────────────────────────────────────────

def backfill_unclassified(
    batch_size: int = BACKFILL_BATCH,
    max_batches: int = 20,
    project_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify all existing log rows that have error_group_id IS NULL.

    Safe to call repeatedly — rows already classified are skipped.
    Processes at most  batch_size * max_batches  rows per call to avoid
    Lambda timeouts.  Call again to continue.

    Returns a summary dict suitable for a JSON API response.
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
            logger.info("[ErrorGrouper] Backfill complete — no more unclassified rows")
            break

        batches_done += 1
        logger.info(
            "[ErrorGrouper] Backfill batch=%d rows=%d", batch_num + 1, len(rows)
        )

        for row in rows:
            processed += 1
            try:
                classify_error(
                    log_id       = row["id"],
                    error_message= row["error"],
                    project_name = row["project_name"],
                    error_detail = row.get("error_detail"),
                )
                classified += 1
            except Exception as exc:
                errors_hit += 1
                logger.exception(
                    "[ErrorGrouper] Backfill classify failed log_id=%r: %s",
                    row.get("id"), exc,
                )

    summary = {
        "processed":    processed,
        "classified":   classified,
        "errors":       errors_hit,
        "batches_done": batches_done,
        "done":         batches_done < max_batches or processed < batch_size,
    }
    logger.info("[ErrorGrouper] Backfill summary: %s", summary)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Manual override
# ─────────────────────────────────────────────────────────────────────────────

def apply_manual_override(
    log_id: str,
    group_id: str,
    group_name: str,
) -> bool:
    """Set a manual group on a log row. Returns True on success."""
    try:
        execute(
            f"UPDATE {TABLE} "
            f"SET error_group_id = %s, error_group_name = %s, manual_group_override = TRUE "
            f"WHERE id = %s AND row_type = 'log'",
            (group_id, group_name, log_id),
        )
        logger.info(
            "[ErrorGrouper] Manual override applied log_id=%r group_id=%r name=%r",
            log_id, group_id, group_name,
        )
        return True
    except Exception as exc:
        logger.exception("[ErrorGrouper] Manual override failed: %s", exc)
        return False


def list_groups(project_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all distinct error groups with counts.

    Cross-project unless project_name is given.
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
            f"ORDER BY last_seen DESC NULLS LAST",
            tuple(params) if params else None,
        )
        return rows
    except Exception as exc:
        logger.exception("[ErrorGrouper] list_groups failed: %s", exc)
        return []
