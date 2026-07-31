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


def _extract_group_candidates(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reduce Pinecone matches to unique group candidates by best score."""
    groups: dict[str, Dict[str, Any]] = {}
    for m in matches:
        score = float(m.get("score") or 0.0)
        meta = m.get("metadata") or {}
        if not isinstance(meta, dict):
            continue
        gid = meta.get("group_id")
        if not gid:
            continue
        entry = groups.get(gid)
        if entry is None or score > entry["score"]:
            groups[gid] = {
                "group_id": gid,
                "score": score,
                "group_name": meta.get("group_name") or None,
                "example_error": (meta.get("error_message") or "")[:300],
            }
    candidates = sorted(groups.values(), key=lambda item: item["score"], reverse=True)
    return candidates


def _enrich_group_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add group_name and occurrence count for each candidate group."""
    if not candidates:
        return candidates

    group_ids = [c["group_id"] for c in candidates]
    placeholders = ", ".join(["%s"] * len(group_ids))
    rows = query(
        f"SELECT error_group_id, MAX(error_group_name) AS error_group_name, COUNT(*) AS group_count "
        f"FROM {TABLE} "
        f"WHERE row_type = 'log' AND error_group_id IN ({placeholders}) "
        f"GROUP BY error_group_id",
        tuple(group_ids),
    )
    counts: dict[str, Dict[str, Any]] = {
        row["error_group_id"]: row for row in rows if row.get("error_group_id")
    }

    for candidate in candidates:
        group_id = candidate["group_id"]
        info = counts.get(group_id)
        candidate["group_name"] = candidate["group_name"] or (info.get("error_group_name") if info else None)
        candidate["group_count"] = int(info.get("group_count", 0)) if info else 0
    return candidates


def _build_nova_group_decision_prompt(error_message: str, candidates: List[Dict[str, Any]]) -> str:
    """Ask Nova whether the incoming error belongs to one of the existing groups."""
    group_lines = []
    for i, candidate in enumerate(candidates[:6]):
        group_name = candidate.get("group_name") or "Unknown Group"
        example = candidate.get("example_error") or ""
        group_lines.append(
            f'{i + 1}. GROUP_ID={candidate["group_id"]} | GROUP_NAME={group_name} | COUNT={candidate.get("group_count", 0)}\n'
            f'   EXAMPLE: {example}'
        )

    return (
        "You are a software error classification assistant.\n\n"
        "INCOMING ERROR:\n"
        f"{error_message}\n\n"
        "EXISTING SEMANTIC GROUP CANDIDATES:\n"
        f"{chr(10).join(group_lines)}\n\n"
        "TASK:\n"
        "Decide whether the INCOMING ERROR belongs to one of the EXISTING SEMANTIC GROUPS above. "
        "Focus only on the root cause, not file names, paths, line numbers, UUIDs, timestamps, or variable values.\n\n"
        "If the error clearly belongs to one of the existing groups, reply with ONLY the exact GROUP_ID of the best matching group.\n"
        "If it does not belong to any existing group, reply with EXACTLY NO_MATCH.\n"
        "Do not add any extra explanation or text.\n\n"
        "YOUR ANSWER:" 
    )


def _build_nova_same_group_prompt(error_message: str, error_detail: Optional[str], candidate: Dict[str, Any]) -> str:
    """Ask Nova whether the incoming error belongs to the candidate's semantic group."""
    context = error_message.strip()
    if error_detail:
        context += f"\n\nDetail:\n{error_detail.strip()[:300]}"

    candidate_name = candidate.get("group_name") or "Unknown Group"
    candidate_example = candidate.get("example_error") or ""
    candidate_count = candidate.get("group_count", 0)

    return (
        "You are a software error classification assistant.\n\n"
        "Decide whether the INCOMING ERROR below belongs to the SAME SEMANTIC GROUP as the CANDIDATE example. "
        "Ignore differences in file paths, line numbers, UUIDs, timestamps, and variable names. "
        "Focus only on the root cause and error type.\n\n"
        "INCOMING ERROR:\n"
        f"{context[:500]}\n\n"
        f"CANDIDATE GROUP NAME: {candidate_name}\n"
        f"CANDIDATE GROUP COUNT: {candidate_count}\n\n"
        "CANDIDATE EXAMPLE ERROR:\n"
        f"{candidate_example[:500]}\n\n"
        "Answer with EXACTLY one word: YES or NO.\n"
        "If the errors are the same root cause, answer YES. Otherwise answer NO."
    )


def _nova_confirm_same_group(error_message: str, error_detail: Optional[str], candidate: Dict[str, Any]) -> bool:
    """Ask Nova whether the incoming error belongs to the candidate's semantic group."""
    if not candidate or not candidate.get("group_id"):
        return False
    try:
        from ai.bedrock_llm import _call_nova
        prompt = _build_nova_same_group_prompt(error_message, error_detail, candidate)
        raw = _call_nova(prompt, max_tokens=40)
        answer = (raw or "").strip().upper()
        result = answer.startswith("YES")
        logger.info(
            "[ErrorGrouper] Nova confirm_same_group answer=%r group_id=%r score=%.4f",
            answer, candidate["group_id"], float(candidate.get("score", 0.0)),
        )
        return result
    except Exception as exc:
        logger.exception("[ErrorGrouper] Nova confirm_same_group failed: %s", exc)
        return False


def _nova_choose_existing_group(error_message: str, candidates: List[Dict[str, Any]]) -> Optional[str]:
    """Ask Nova to choose the best existing group or return NO_MATCH."""
    if not candidates:
        return None
    try:
        from ai.bedrock_llm import _call_nova
        prompt = _build_nova_group_decision_prompt(error_message, candidates)
        raw = _call_nova(prompt, max_tokens=80)
        if not raw:
            return None
        answer = raw.strip()
        if "NO_MATCH" in answer.upper():
            return None
        md5_match = re.search(r"\b([0-9a-f]{32})\b", answer.lower())
        if md5_match:
            selected = md5_match.group(1)
            valid_ids = {candidate["group_id"] for candidate in candidates}
            if selected in valid_ids:
                logger.info("[ErrorGrouper] Nova selected existing group_id=%r", selected)
                return selected
            logger.warning(
                "[ErrorGrouper] Nova returned unknown group_id=%r — treating as NO_MATCH",
                selected,
            )
        logger.warning("[ErrorGrouper] Nova returned unexpected response=%r", answer[:200])
    except Exception as exc:
        logger.exception("[ErrorGrouper] Nova choose existing group failed: %s", exc)
    return None


def _build_new_group_name_prompt(error_message: str, error_detail: Optional[str]) -> str:
    context = error_message.strip()
    if error_detail:
        context += f"\n{error_detail.strip()[:300]}"
    return (
        "Give a short 2-4 word group name for this software error.\n"
        "The name should describe the ROOT CAUSE category only, not the specific file, function, or variable.\n"
        "Keep the label concise and generic, for example: 'File not found', 'Permission denied', 'JSON validation error'.\n"
        "Output ONLY the group name, nothing else.\n\n"
        f"Error:\n{context[:500]}\n\n"
        "YOUR GROUP NAME:" 
    )


def _nova_name_group(error_message: str, error_detail: Optional[str] = None) -> str:
    """Ask Nova for a short (3–6 word) group name for this error. Falls back to truncated error text."""
    try:
        from ai.bedrock_llm import _call_nova
        context = error_message.strip()
        if error_detail:
            context += f"\n{error_detail.strip()[:300]}"

        # Enrich prompt with similar recent occurrences from the DB so Nova can
        # derive a more robust group name based on multiple examples.
        try:
            from ai.error_matching import build_error_hash_candidates
            candidates = build_error_hash_candidates(error_message, error_detail)
            if candidates:
                # Query recent rows that match any candidate hash (MD5 variants)
                placeholders = ", ".join(["%s"] * len(candidates))
                rows = query(
                    f"SELECT error, error_detail FROM {TABLE} WHERE row_type = 'log' AND (MD5(LOWER(TRIM(error))) IN ({placeholders}) OR error_hash IN ({placeholders})) LIMIT 5",
                    tuple(candidates + candidates),
                )
                if rows:
                    examples = []
                    for r in rows:
                        e = (r.get('error') or '').strip()
                        d = (r.get('error_detail') or '').strip()
                        combined = (e + "\n" + d).strip()
                        if combined:
                            examples.append(combined[:500])
                    if examples:
                        context += "\n\nOther examples:\n" + "\n---\n".join(examples[:5])
        except Exception as _exc:
            logger.exception("[ErrorGrouper] Could not enrich Nova prompt from DB: %s", _exc)
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
    dry_run: bool = False,
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
        if not dry_run:
            _write_group_to_row(log_id, group_id, group_name)
        logger.info("[ErrorGrouper] RESULT no-embedding fallback group_id=%r", group_id)
        return {"group_id": group_id, "group_name": group_name, "reason": "new_group", "similarity": None}

    logger.info("[ErrorGrouper] Embedding generated dim=%d", len(embedding))

    # ── STEP 2: Pinecone approximate nearest-neighbour ────────────────────────
    matches = _pinecone_query_errors(embedding)
    candidates = _extract_group_candidates(matches)
    candidates = _enrich_group_candidates(candidates)

    logger.info(
        "[ErrorGrouper] Pinecone candidate groups=%d",
        len(candidates),
    )
    for candidate in candidates[:6]:
        logger.info(
            "[ErrorGrouper] Candidate score=%.4f group_id=%r group_count=%d name=%r example=%r",
            candidate["score"], candidate["group_id"], candidate.get("group_count", 0),
            candidate.get("group_name"), candidate.get("example_error")[:80],
        )

    diagnostics: Dict[str, Any] = {
        "pinecone_matches": [
            {
                "group_id":      c["group_id"],
                "group_name":    c.get("group_name"),
                "group_count":   c.get("group_count"),
                "score":         c["score"],
                "example_error": c.get("example_error"),
            }
            for c in candidates[:8]
        ],
        "chosen_group_id": None,
        "chosen_group_name": None,
        "nova_decision": None,
        "provisional": False,
    }

    chosen_group_id: Optional[str] = None
    chosen_group_name: Optional[str] = None
    reason = "new_group"
    similarity = candidates[0]["score"] if candidates else None

    if candidates:
        best_candidate = candidates[0]
        if best_candidate["score"] >= PINECONE_AUTO_THRESHOLD:
            chosen_group_id = best_candidate["group_id"]
            chosen_group_name = best_candidate["group_name"] or _get_group_name_for_id(chosen_group_id) or error_message[:60]
            reason = "pinecone_auto"
            logger.info(
                "[ErrorGrouper] RESULT pinecone_auto group_id=%r name=%r similarity=%.4f",
                chosen_group_id, chosen_group_name, best_candidate["score"],
            )
        elif best_candidate["score"] >= PINECONE_FUZZY_LOW:
            logger.info(
                "[ErrorGrouper] Fuzzy Pinecone score %.4f: asking Nova to confirm same group",
                best_candidate["score"],
            )
            confirmed = _nova_confirm_same_group(error_message, error_detail, best_candidate)
            diagnostics["nova_decision"] = "confirmed" if confirmed else "rejected"
            if confirmed:
                chosen_group_id = best_candidate["group_id"]
                chosen_group_name = best_candidate["group_name"] or _get_group_name_for_id(chosen_group_id) or error_message[:60]
                reason = "nova_confirmed"
                logger.info(
                    "[ErrorGrouper] RESULT nova_confirmed group_id=%r name=%r similarity=%.4f",
                    chosen_group_id, chosen_group_name, best_candidate["score"],
                )
            else:
                logger.info(
                    "[ErrorGrouper] Nova rejected same-group match — creating new provisional group"
                )
        else:
            logger.info(
                "[ErrorGrouper] Best Pinecone score %.4f below fuzzy threshold; creating new group without Nova",
                best_candidate["score"],
            )

    if chosen_group_id:
        if not dry_run:
            _write_group_to_row(log_id, chosen_group_id, chosen_group_name or error_message[:60])
            _pinecone_upsert_error(log_id, embedding, chosen_group_id, error_message, project_name)
        diagnostics["chosen_group_id"] = chosen_group_id
        diagnostics["chosen_group_name"] = chosen_group_name
        diagnostics["provisional"] = False
        return {
            "group_id":   chosen_group_id,
            "group_name": chosen_group_name,
            "reason":     reason,
            "similarity": similarity,
            "diagnostics": diagnostics,
        }

    # 3c — No existing semantic group was selected. Create a provisional new group.
    new_group_id = str(uuid.uuid4())
    new_group_name = _nova_name_group(error_message, error_detail)
    if not dry_run:
        _write_group_to_row(log_id, new_group_id, new_group_name)
        _pinecone_upsert_error_with_group_name(
            log_id, embedding, new_group_id, new_group_name, error_message, project_name
        )
    logger.info(
        "[ErrorGrouper] RESULT provisional_new_group group_id=%r name=%r",
        new_group_id, new_group_name,
    )
    diagnostics["chosen_group_id"] = new_group_id
    diagnostics["chosen_group_name"] = new_group_name
    diagnostics["provisional"] = True
    return {
        "group_id":   new_group_id,
        "group_name": new_group_name,
        "reason":     "provisional_new_group",
        "similarity": similarity,
        "diagnostics": diagnostics,
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

def reclassify_all(
    batch_size: int = 30,
    max_batches: int = 20,
    project_name: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Merge existing semantic groups by re-running AI classification on group representatives.

    Algorithm
    ─────────
    1. Load all distinct existing groups (each with a representative error text).
    2. For each group, embed the representative error and query Pinecone for similar groups.
    3. If a high-similarity candidate group is found:
       a. Auto-merge at >= PINECONE_AUTO_THRESHOLD
       b. Ask Nova to confirm at >= PINECONE_FUZZY_LOW
    4. When two groups merge, update ALL rows pointing to the old group_id to
       use the canonical group_id and group_name.
    5. Repeat until no more merges happen in a batch (convergence).

    This is a group-level operation, not row-level — one LLM call per group
    comparison, not one per row.  Much cheaper and much faster.

    Returns a summary dict.
    """
    processed  = 0   # groups considered
    merged     = 0   # groups collapsed into another
    rows_updated = 0
    errors_hit = 0
    batches_done = 0

    logger.info(
        "[ErrorGrouper] reclassify_all START batch_size=%d max_batches=%d project=%r dry_run=%s",
        batch_size, max_batches, project_name, dry_run,
    )

    for batch_num in range(max_batches):
        # Load distinct groups ordered by size DESC so large groups act as
        # canonical targets and small fragmentary groups collapse into them.
        conditions = [
            "row_type = 'log'",
            "error_group_id IS NOT NULL",
            "error IS NOT NULL",
            "error <> ''",
        ]
        params: List[Any] = []
        if project_name:
            conditions.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)

        group_rows = query(
            f"SELECT error_group_id, MAX(error_group_name) AS error_group_name, "
            f"  COUNT(*) AS group_count, "
            f"  MAX(error) AS representative_error, "
            f"  MAX(error_detail) AS representative_detail "
            f"FROM {TABLE} "
            f"WHERE {' AND '.join(conditions)} "
            f"GROUP BY error_group_id "
            f"ORDER BY group_count DESC "
            f"LIMIT %s",
            tuple(params + [batch_size]),
        )

        if not group_rows:
            logger.info("[ErrorGrouper] reclassify_all: no groups found")
            break

        batches_done += 1
        batch_merged = 0

        logger.info(
            "[ErrorGrouper] reclassify_all batch=%d groups=%d",
            batch_num + 1, len(group_rows),
        )

        # Build a set of canonical group ids in this batch (largest first).
        # Once a group is used as canonical it won't be merged away.
        canonical_ids: set = {group_rows[0]["error_group_id"]} if group_rows else set()

        for group_row in group_rows:
            source_group_id   = group_row.get("error_group_id")
            source_group_name = group_row.get("error_group_name") or ""
            rep_error         = (group_row.get("representative_error") or "").strip()
            rep_detail        = group_row.get("representative_detail") or None
            group_count       = int(group_row.get("group_count") or 0)

            if not source_group_id or not rep_error:
                continue

            processed += 1

            # Don't try to merge the largest group into itself
            if source_group_id in canonical_ids and group_count == (group_rows[0].get("group_count") or 0):
                continue

            # Generate embedding for the representative error
            query_text = _build_query_text(rep_error, rep_detail)
            embedding  = _get_embedding(query_text)

            if embedding is None:
                logger.warning(
                    "[ErrorGrouper] reclassify_all: no embedding for group_id=%r — skipping",
                    source_group_id,
                )
                continue

            # Query Pinecone for similar error vectors
            matches   = _pinecone_query_errors(embedding)
            candidates = _extract_group_candidates(matches)
            candidates = _enrich_group_candidates(candidates)

            # Filter out the source group itself
            candidates = [c for c in candidates if c["group_id"] != source_group_id]

            if not candidates:
                logger.info(
                    "[ErrorGrouper] reclassify_all: no candidates for group_id=%r",
                    source_group_id,
                )
                continue

            best = candidates[0]
            logger.info(
                "[ErrorGrouper] reclassify_all group=%r (%d rows) vs candidate=%r score=%.4f",
                source_group_name, group_count, best.get("group_name"), best["score"],
            )

            target_group_id   = None
            target_group_name = None
            merge_reason      = None

            if best["score"] >= PINECONE_AUTO_THRESHOLD:
                target_group_id   = best["group_id"]
                target_group_name = best.get("group_name") or _get_group_name_for_id(best["group_id"]) or source_group_name
                merge_reason      = "pinecone_auto"
            elif best["score"] >= PINECONE_FUZZY_LOW:
                confirmed = _nova_confirm_same_group(rep_error, rep_detail, best)
                if confirmed:
                    target_group_id   = best["group_id"]
                    target_group_name = best.get("group_name") or _get_group_name_for_id(best["group_id"]) or source_group_name
                    merge_reason      = "nova_confirmed"
                else:
                    logger.info(
                        "[ErrorGrouper] reclassify_all Nova rejected merge for group_id=%r",
                        source_group_id,
                    )

            if not target_group_id:
                # No merge — keep this group as a canonical anchor
                canonical_ids.add(source_group_id)
                continue

            # Perform the merge: update all rows in source group to target group
            logger.info(
                "[ErrorGrouper] reclassify_all MERGE source=%r (%r) → target=%r (%r) reason=%s score=%.4f",
                source_group_id, source_group_name,
                target_group_id, target_group_name,
                merge_reason, best["score"],
            )

            try:
                if not dry_run:
                    update_conditions = ["row_type = 'log'", "error_group_id = %s",
                                         "(manual_group_override IS NULL OR manual_group_override = FALSE)"]
                    update_params = [target_group_id, target_group_name, source_group_id]
                    if project_name:
                        update_conditions.append("LOWER(project_name) = LOWER(%s)")
                        update_params.append(project_name)

                    count = execute(
                        f"UPDATE {TABLE} "
                        f"SET error_group_id = %s, error_group_name = %s "
                        f"WHERE {' AND '.join(update_conditions)}",
                        tuple(update_params),
                    )
                    rows_updated += (count or group_count)
                else:
                    rows_updated += group_count

                merged += 1
                batch_merged += 1
                canonical_ids.add(target_group_id)
                logger.info(
                    "[ErrorGrouper] reclassify_all merged %d rows from %r → %r",
                    group_count, source_group_id, target_group_id,
                )

            except Exception as exc:
                errors_hit += 1
                logger.exception(
                    "[ErrorGrouper] reclassify_all merge failed source=%r: %s",
                    source_group_id, exc,
                )

        # If no merges happened in this batch, we've converged — stop early
        if batch_merged == 0:
            logger.info("[ErrorGrouper] reclassify_all: no merges in batch %d — converged", batch_num + 1)
            break

    summary = {
        "processed":    processed,
        "merged":       merged,
        "rows_updated": rows_updated,
        "errors":       errors_hit,
        "batches_done": batches_done,
        "done":         True,
        "dry_run":      dry_run,
    }
    logger.info("[ErrorGrouper] reclassify_all summary: %s", summary)
    return summary


def backfill_unclassified(
    batch_size: int = BACKFILL_BATCH,
    max_batches: int = 20,
    project_name: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Classify all existing log rows that have error_group_id IS NULL.

    Safe to call repeatedly — rows already classified are skipped.
    Processes at most  batch_size * max_batches  rows per call to avoid
    Lambda timeouts.  Call again to continue.

    To RECLASSIFY and MERGE already-classified rows use reclassify_all() instead.

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
                log_id = row.get("id")
                err = row.get("error") or ""
                detail = row.get("error_detail") or None
                result = classify_error(
                    log_id=log_id,
                    error_message=err,
                    project_name=row.get("project_name"),
                    error_detail=detail,
                    dry_run=dry_run,
                )
                if result and result.get("reason") != "skipped":
                    classified += 1
            except Exception as _exc:
                errors_hit += 1
                logger.exception("[ErrorGrouper] backfill classify failed for %r: %s", row.get("id"), _exc)
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
