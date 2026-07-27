"""Knowledge base helpers — solution versioning, metrics, and Bedrock embeddings.

Grouping key
────────────
Solutions are grouped by a  group_key  that is resolved in this order:

  1. AI semantic match  — find_matching_solution_group() asks Nova Lite whether
     the incoming error belongs to any existing solution group in this project,
     matching by root cause regardless of wording differences.
  2. Normalized text    — derive_solution_group_key(error_message), the MD5 of
     normalize_error_for_lookup(error_message).  Catches identical errors after
     stripping timestamps, paths, IDs etc.
  3. Legacy hash        — occurrence-specific error_hash used as a last resort
     so callers that haven't been updated yet continue to work.

The group_key is stored in the solution row's existing  error_hash  column.
No schema change is required.

Duplicate detection order (cheapest first):
  1. Exact-text normalization  — pure Python + one SQL query, zero Bedrock cost
  2. Semantic similarity        — Bedrock embedding + Pinecone query
  3. LLM confirmation           — Nova Lite, only at the 0.90–0.95 boundary

Atomic operations
  increment_usage() uses a single UPDATE SET usage_count = usage_count + 1
  to eliminate the read-then-write race condition under concurrent load.
  Version assignment uses COALESCE(MAX(version),0)+1 with a retry loop
  (MAX_VERSION_RETRIES) to handle serialization conflicts from Aurora DSQL's
  optimistic concurrency.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ai.error_matching import (
    build_error_hash_candidates,
    derive_solution_group_key,
    normalize_project_name,
)
from ai.pinecone_service import delete_vector, query_similar, upsert_vector
from db import execute, execute_returning, query

logger = logging.getLogger(__name__)

TABLE = "projects_data"
MAX_VERSION_RETRIES = 5


# ── Internal helpers ──────────────────────────────────────────────────────────

def _create_embedding_safe(text: str) -> Optional[str]:
    """Generate a Titan embedding, returning it as a JSON string for the TEXT column.
    Returns None (not raises) on any failure so saves always succeed without embeddings.
    """
    logger.info(
        "[KnowledgeBase][Embedding] START — generating Titan embedding for %d chars",
        len(text),
    )
    try:
        from ai.embeddings import create_embedding
        vec = create_embedding(text)
        if vec and any(v != 0.0 for v in vec):
            emb_json = json.dumps(vec)
            logger.info(
                "[KnowledgeBase][Embedding] SUCCESS — length=%d, json_bytes=%d",
                len(vec), len(emb_json),
            )
            return emb_json
        logger.warning(
            "[KnowledgeBase][Embedding] FAILED — Bedrock returned zero vector or empty list"
            " (vec type=%s, len=%s) — embedding skipped",
            type(vec).__name__,
            len(vec) if isinstance(vec, list) else "n/a",
        )
        return None
    except Exception as exc:
        logger.exception(
            "[KnowledgeBase][Embedding] FAILED — exception during create_embedding: %s", exc
        )
        return None


def calculate_confidence(usage_count: int) -> float:
    return round(min(100.0, 50.0 + float(usage_count) * 2.0), 2)


def classify_duplicate_solution(
    similarity: Optional[float],
    confirmation: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return a structured decision dict for a given Pinecone similarity score."""
    if similarity is None:
        return {"is_duplicate": False, "decision": "new",       "severity": "none",   "confidence": 0.0}
    if similarity >= 0.95:
        return {"is_duplicate": True,  "decision": "duplicate", "severity": "high",   "confidence": float(similarity)}
    if similarity >= 0.90:
        return {"is_duplicate": False, "decision": "warn",      "severity": "medium", "confidence": float(similarity)}
    return     {"is_duplicate": False, "decision": "new",       "severity": "low",    "confidence": float(similarity)}


def _normalize_solution_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


# ── Group-key helpers ─────────────────────────────────────────────────────────

def _group_key_conditions(
    group_key: str,
    project_name: Optional[str],
) -> Tuple[List[str], List[Any]]:
    """Return (conditions, params) that filter solution rows to a single group.

    The group key is stored in the error_hash column of solution rows.
    A project filter is always applied when project_name is supplied.
    """
    conditions: List[str] = ["row_type = 'solution'", "error_hash = %s"]
    params: List[Any] = [group_key]
    if project_name:
        conditions.append("LOWER(project_name) = LOWER(%s)")
        params.append(project_name)
    return conditions, params


# ── Tier 1: Exact-text duplicate search (no Bedrock call) ────────────────────

def _find_duplicate_solution(
    group_key: str,
    solution_text: str,
    project_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Exact-text duplicate search within the solution group — zero Bedrock cost.

    Scans all solution rows that share the same group_key (project + normalized
    error message) and returns one whose normalized text matches solution_text.
    """
    normalized = _normalize_solution_text(solution_text)
    if not normalized:
        return None

    conditions, params = _group_key_conditions(group_key, project_name)
    try:
        rows = query(
            f"SELECT id, usage_count, confidence_score, version, solution, "
            f"created_by, created_at "
            f"FROM {TABLE} "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY confidence_score DESC, usage_count DESC, created_at DESC",
            tuple(params),
        )
        for row in rows:
            if _normalize_solution_text(row.get("solution")) == normalized:
                logger.info(
                    "[KnowledgeBase] Exact duplicate found in group — solution_id=%s",
                    row.get("id"),
                )
                return row
    except Exception as exc:
        logger.exception("[KnowledgeBase] Exact duplicate query failed: %s", exc)

    return None


# ── Tier 2: Semantic duplicate search (Bedrock + Pinecone) ───────────────────

def detect_duplicate_solution(
    solution_text: str,
    group_key: str,
    project_name: Optional[str] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    """Project-scoped semantic duplicate detection.

    Only called after exact-text (Tier 1) found nothing.
    Pinecone is queried with project_name filter only (no error_hash/group_key)
    so semantically equivalent solutions are caught across the whole project.

    Thresholds:
      >= 0.95  → duplicate, no LLM needed
      0.90–0.95 → warn, ask Nova Lite for confirmation
      < 0.90   → new

    Fails open: any exception returns is_duplicate=False so saves are never
    silently blocked.
    """
    try:
        from ai.embeddings import create_embedding

        embedding = create_embedding(solution_text)
        if not embedding:
            logger.warning("[KnowledgeBase] Duplicate detection skipped — embedding unavailable")
            return {"is_duplicate": False, "decision": "new",
                    "reason": "embedding_unavailable", "duplicate_prompt": False}

        matches = query_similar(None, embedding, project_name, limit=limit, error_hash=None)
        if not matches:
            return {"is_duplicate": False, "decision": "new",
                    "reason": "no_matches", "duplicate_prompt": False}

        candidate       = None
        best_similarity = 0.0
        for match in matches:
            metadata   = match.get("metadata") or {}
            if not metadata.get("solution_id"):
                continue
            similarity = max(float(match.get("score") or 0.0), 0.0)
            if similarity > best_similarity:
                best_similarity = similarity
                candidate = match

        if not candidate:
            return {"is_duplicate": False, "decision": "new",
                    "reason": "no_valid_candidate", "duplicate_prompt": False}

        existing_solution = _get_solution_metadata(candidate.get("id"))
        if not existing_solution and candidate.get("metadata"):
            meta = candidate.get("metadata", {})
            existing_solution = {
                "id":               candidate.get("id"),
                "solution":         meta.get("solution"),
                "created_by":       meta.get("created_by"),
                "created_at":       meta.get("created_at"),
                "version":          meta.get("version"),
                "confidence_score": meta.get("confidence_score"),
                "usage_count":      meta.get("usage_count"),
            }

        classification = classify_duplicate_solution(best_similarity)

        # Tier 3: LLM confirmation at the 0.90–0.95 boundary
        if classification["decision"] == "warn":
            try:
                from ai.llm import generate_ai_response
                nova_prompt = (
                    "Are these two solutions functionally the same? "
                    "Ignore wording differences. Answer only YES or NO.\n\n"
                    f"Solution A: {solution_text}\n\n"
                    f"Solution B: {existing_solution.get('solution') if existing_solution else ''}"
                )
                nova_reply = (generate_ai_response(nova_prompt, max_tokens=64) or "").strip().lower()
                if "yes" in nova_reply:
                    classification = {
                        "is_duplicate": True, "decision": "duplicate",
                        "severity": "high", "confidence": float(best_similarity),
                    }
            except Exception as exc:
                logger.exception("[KnowledgeBase] Nova Lite confirmation failed: %s", exc)

        if classification["is_duplicate"]:
            return {
                "is_duplicate":      True,
                "decision":          classification["decision"],
                "reason":            "similarity",
                "similarity":        best_similarity,
                "solution_id":       candidate.get("id"),
                "metadata":          candidate.get("metadata") or {},
                "existing_solution": existing_solution,
                "duplicate_prompt":  True,
            }

        if best_similarity >= 0.90:
            return {
                "is_duplicate":      False,
                "decision":          "warn",
                "reason":            "similarity",
                "similarity":        best_similarity,
                "solution_id":       candidate.get("id"),
                "metadata":          candidate.get("metadata") or {},
                "existing_solution": existing_solution,
                "duplicate_prompt":  True,
            }

        return {
            "is_duplicate":  False,
            "decision":      "new",
            "reason":        "below_threshold",
            "similarity":    best_similarity,
            "duplicate_prompt": False,
        }

    except Exception as exc:
        logger.exception("[KnowledgeBase] Duplicate detection failed: %s", exc)
        return {"is_duplicate": False, "decision": "new",
                "reason": "error", "error": str(exc), "duplicate_prompt": False}


# ── Row lookups ───────────────────────────────────────────────────────────────

def _get_solution_metadata(solution_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not solution_id:
        return None
    row = _find_solution(solution_id)
    if not row:
        return None
    return {
        "id":               row.get("id"),
        "solution":         row.get("solution"),
        "created_by":       row.get("created_by"),
        "created_at":       row.get("created_at"),
        "version":          row.get("version"),
        "confidence_score": row.get("confidence_score"),
        "usage_count":      row.get("usage_count"),
    }


def _get_log_row(
    error_message: str,
    project_name: Optional[str] = None,
    occurrence_error_hash: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find a representative log row by error message text (primary) or hash (fallback).

    We select the most recent log row for this project+error so we can read the
    canonical project_name casing.  The specific log row ID is no longer used
    for solution grouping — only project_name and the group_key matter.
    """
    conditions = ["row_type = 'log'", "error IS NOT NULL"]
    params: List[Any] = []

    if project_name:
        conditions.insert(0, "LOWER(project_name) = LOWER(%s)")
        params.insert(0, project_name)

    # Primary: match by normalised error text
    if error_message:
        conditions.append(
            "(LOWER(TRIM(error)) = LOWER(TRIM(%s)) "
            " OR MD5(LOWER(TRIM(error))) = MD5(LOWER(TRIM(%s))))"
        )
        params.extend([error_message, error_message])
    elif occurrence_error_hash:
        # Fallback: match by the occurrence-specific hash when text is unavailable
        hash_candidates = build_error_hash_candidates(occurrence_error_hash, None)
        if hash_candidates:
            conditions.append(f"({' OR '.join(['error_hash = %s'] * len(hash_candidates))})")
            params.extend(hash_candidates)
        else:
            conditions.append("error_hash = %s")
            params.append(occurrence_error_hash)

    rows = query(
        f"SELECT id, project_name, error, error_hash FROM {TABLE} "
        f"WHERE {' AND '.join(conditions)} ORDER BY timestamp DESC LIMIT 1",
        tuple(params),
    )
    return rows[0] if rows else None


def _find_solution(solution_id: str) -> Optional[Dict[str, Any]]:
    rows = query(
        f"SELECT * FROM {TABLE} WHERE row_type = 'solution' AND id = %s",
        (solution_id,),
    )
    return rows[0] if rows else None


# ── Public API ────────────────────────────────────────────────────────────────

def insert_solution(
    error_hash: str,
    solution: str,
    created_by: str = "developer",
    project_name: Optional[str] = None,
    base_solution_id: Optional[str] = None,
    force_create: bool = False,
    check_only: bool = False,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a new solution or return an existing duplicate.

    The solution group is identified by  project_name + normalize_error_for_lookup(error_message).
    error_hash is used only as a fallback when error_message is not supplied.

    Duplicate detection order (cheapest first):
      1. Exact-text match  — no Bedrock call, no Pinecone call
      2. Semantic match    — Bedrock embedding + Pinecone
      (3. LLM confirmation — inside detect_duplicate_solution at 0.90–0.95)

    check_only=True: run duplicate detection and return the result without
      inserting.  If a duplicate is found, return it.  If no duplicate, return
      {"duplicate": False}.

    force_create=True: bypass all duplicate checks (intentional user override).
    """
    # Resolve the log row so we can read canonical project_name
    log_row = _get_log_row(
        error_message or "",
        project_name,
        occurrence_error_hash=error_hash,
    )
    if not log_row:
        raise ValueError("No matching log row found")

    canonical_project = log_row.get("project_name") or project_name or ""

    # ── Resolve the group key (first match wins) ──────────────────────────────
    # Priority:
    #   1. AI semantic match — finds the correct group even when wording differs
    #   2. Normalized text   — exact same error after normalization
    #   3. Legacy hash       — occurrence hash as last resort
    raw_error_text = error_message or log_row.get("error") or ""
    group_key: Optional[str] = None

    # Step 1: AI semantic match
    if raw_error_text and canonical_project:
        try:
            from ai.semantic_group_matcher import find_matching_solution_group
            ai_key = find_matching_solution_group(raw_error_text, canonical_project)
            if ai_key:
                group_key = ai_key
                logger.info(
                    "[KnowledgeBase] insert_solution group resolved via AI match: "
                    "group_key=%r project=%r", group_key, canonical_project,
                )
        except Exception as exc:
            logger.exception(
                "[KnowledgeBase] insert_solution AI match failed — falling back: %s", exc
            )

    # Step 2: normalized text key
    if not group_key and raw_error_text:
        group_key = derive_solution_group_key(raw_error_text)

    # Step 3: occurrence hash fallback
    if not group_key:
        group_key = error_hash
        logger.warning(
            "[KnowledgeBase] Could not derive group_key from error text — "
            "falling back to occurrence hash=%r", error_hash
        )

    logger.info(
        "[KnowledgeBase] insert_solution group_key=%r project=%r",
        group_key, canonical_project,
    )

    if not force_create:
        # Tier 1: exact-text (zero Bedrock cost) ─────────────────────────────
        exact_duplicate = _find_duplicate_solution(group_key, solution, canonical_project)
        if exact_duplicate:
            payload = {
                "duplicate":        True,
                "duplicate_prompt": True,
                "decision":         "duplicate",
                "similarity":       1.0,
                "solution_id":      exact_duplicate.get("id"),
                "solution":         exact_duplicate.get("solution"),
                "created_by":       exact_duplicate.get("created_by"),
                "created_at":       exact_duplicate.get("created_at"),
                "version":          exact_duplicate.get("version"),
                "confidence_score": exact_duplicate.get("confidence_score"),
                "usage_count":      exact_duplicate.get("usage_count"),
            }
            logger.info("[Duplicate] Exact duplicate found — solution_id=%s", exact_duplicate.get("id"))
            return payload

        # Tier 2: semantic (Bedrock + Pinecone) ───────────────────────────────
        duplicate_check = detect_duplicate_solution(solution, group_key, canonical_project)
        if duplicate_check.get("duplicate_prompt"):
            es = duplicate_check.get("existing_solution") or {}
            payload = {
                "duplicate":        True,
                "duplicate_prompt": True,
                "decision":         duplicate_check.get("decision"),
                "similarity":       duplicate_check.get("similarity"),
                "solution_id":      duplicate_check.get("solution_id"),
                "solution":         es.get("solution"),
                "created_by":       es.get("created_by"),
                "created_at":       es.get("created_at"),
                "version":          es.get("version"),
                "confidence_score": es.get("confidence_score"),
                "usage_count":      es.get("usage_count"),
            }
            logger.info(
                "[Duplicate] Semantic duplicate found — solution_id=%s score=%.3f",
                duplicate_check.get("solution_id"),
                duplicate_check.get("similarity") or 0.0,
            )
            return payload

    # check_only with no duplicate found — return preview without inserting
    if check_only:
        return {"duplicate": False, "duplicate_prompt": False}

    # ── Resolve the version family ────────────────────────────────────────────
    # A solution family is identified by a family_id stored in the log_ref_id
    # column.  The family_id is the ID of the first (root) version in the chain.
    #
    # Create New  (base_solution_id is None):
    #   → Always a new independent root.  version=1, family_id = own new UUID.
    #
    # Improve  (base_solution_id is set by the frontend):
    #   → New version appended to the parent's family.
    #     family_id = parent's log_ref_id (which is already the root ID).
    #     version  = MAX(version in that family) + 1.

    is_improve = bool(base_solution_id)

    if is_improve:
        # Resolve the family_id from the parent solution's log_ref_id
        parent_row = _find_solution(base_solution_id)
        if not parent_row:
            logger.warning(
                "[KnowledgeBase] insert_solution: base_solution_id=%r not found — "
                "treating as Create New", base_solution_id
            )
            is_improve = False

    if is_improve and parent_row:
        # The family is identified by the parent's log_ref_id (which is the root ID)
        family_id = parent_row.get("log_ref_id") or base_solution_id
    else:
        # New root: the family_id will be set to the solution's own UUID after insert
        family_id = None  # filled in during the insert loop below

    # ── Insert the new solution row ───────────────────────────────────────────
    usage_count = 1
    confidence  = calculate_confidence(usage_count)

    logger.info(
        "[KnowledgeBase][Pinecone] STAGE 1 — calling _create_embedding_safe "
        "for solution (len=%d chars)", len(solution)
    )
    embedding = _create_embedding_safe(solution)

    if embedding is None:
        logger.warning(
            "[KnowledgeBase][Pinecone] STAGE 1 RESULT — embedding=None "
            "-- solution will be saved to Aurora WITHOUT a Pinecone vector. "
            "Check [KnowledgeBase][Embedding] lines above for root cause."
        )
    else:
        try:
            _emb_len = len(json.loads(embedding))
        except Exception:
            _emb_len = "parse-error"
        logger.info(
            "[KnowledgeBase][Pinecone] STAGE 1 RESULT — embedding=JSON string "
            "(dim=%s) -- Pinecone upsert WILL be attempted after Aurora insert.",
            _emb_len,
        )

    last_exc: Optional[Exception] = None
    for attempt in range(MAX_VERSION_RETRIES):
        try:
            # Assign a new UUID for this solution row
            new_id = str(uuid.uuid4())

            # For a new root (Create New), family_id == own ID.
            # For an Improve, family_id was resolved above from the parent.
            effective_family_id = family_id if family_id else new_id

            if is_improve:
                # Version number is scoped to the solution family (same log_ref_id),
                # not to the entire error group. This is correct: two independent
                # solutions for the same error each maintain their own v1, v2, v3...
                version_rows = query(
                    f"SELECT COALESCE(MAX(version), 0) AS max_version FROM {TABLE} "
                    f"WHERE row_type = 'solution' AND log_ref_id = %s",
                    (effective_family_id,),
                )
                version = int((version_rows[0]["max_version"] or 0)) + 1
            else:
                # Create New always starts at version 1
                version = 1

            row = execute_returning(
                f"INSERT INTO {TABLE} "
                f"(id, row_type, project_name, error_hash, log_ref_id, solution, "
                f"created_by, created_at, usage_count, version, confidence_score, embedding) "
                f"VALUES (%s,'solution',%s,%s,%s,%s,%s,NOW(),%s,%s,%s,%s) "
                f"RETURNING *",
                (
                    new_id,
                    canonical_project,
                    group_key,             # error group key for retrieval/Pinecone
                    effective_family_id,   # solution family key for versioning
                    solution,
                    created_by,
                    usage_count,
                    version,
                    confidence,
                    embedding,
                ),
            )
            if row:
                row["duplicate"] = False
                logger.info(
                    "[Solution] %s — solution_id=%s version=%d "
                    "family_id=%r group_key=%r project=%r",
                    "Improve (new version)" if is_improve else "Create New (root)",
                    row.get("id"), version, effective_family_id,
                    group_key, canonical_project,
                )
                if embedding is not None:
                    logger.info(
                        "[KnowledgeBase][Pinecone] STAGE 2 — calling upsert_vector "
                        "solution_id=%r version=%d project=%r group_key=%r",
                        row.get("id"), version, canonical_project, group_key,
                    )
                    try:
                        upsert_result = upsert_vector(
                            row["id"],
                            json.loads(embedding),
                            canonical_project,
                            group_key,
                            version,
                        )
                        if upsert_result:
                            logger.info(
                                "[KnowledgeBase][Pinecone] STAGE 2 SUCCESS — "
                                "vector upserted solution_id=%r", row.get("id")
                            )
                        else:
                            logger.error(
                                "[KnowledgeBase][Pinecone] STAGE 2 FAILED — "
                                "upsert_vector returned False for solution_id=%r. "
                                "See [Pinecone] FAILED lines above.", row.get("id")
                            )
                    except Exception as exc:
                        logger.exception(
                            "[KnowledgeBase][Pinecone] STAGE 2 FAILED — "
                            "upsert_vector raised for solution_id=%r: %s",
                            row.get("id"), exc,
                        )
                else:
                    logger.warning(
                        "[KnowledgeBase][Pinecone] STAGE 2 SKIPPED — "
                        "embedding is None, upsert_vector NOT called for solution_id=%r. "
                        "Bedrock embedding failed — check STAGE 1 logs above.",
                        row.get("id"),
                    )
            return row

        except Exception as exc:
            last_exc = exc
            err_str  = str(exc).lower()
            if attempt < MAX_VERSION_RETRIES - 1 and (
                "unique" in err_str or "duplicate" in err_str or "serializ" in err_str
            ):
                logger.warning(
                    "[KnowledgeBase] Version conflict on attempt %d — retrying: %s",
                    attempt + 1, exc,
                )
                continue
            raise

    raise RuntimeError(
        f"[KnowledgeBase] insert_solution failed after {MAX_VERSION_RETRIES} attempts: {last_exc}"
    )


def increment_usage(solution_id: str) -> Dict[str, Any]:
    """Atomically increment usage_count and recompute confidence_score.

    Single UPDATE eliminates the read-then-write race condition.
    """
    incremented = execute_returning(
        f"UPDATE {TABLE} "
        f"SET usage_count = usage_count + 1 "
        f"WHERE row_type = 'solution' AND id = %s "
        f"RETURNING id, usage_count, version, confidence_score",
        (solution_id,),
    )
    if not incremented:
        raise ValueError("Solution not found")

    new_usage      = int(incremented.get("usage_count") or 1)
    new_confidence = calculate_confidence(new_usage)

    row = execute_returning(
        f"UPDATE {TABLE} SET confidence_score = %s "
        f"WHERE row_type = 'solution' AND id = %s RETURNING *",
        (new_confidence, solution_id),
    )
    if not row:
        raise ValueError("Solution not found after confidence update")
    return row


def delete_solution_version(solution_id: str) -> int:
    """Delete a single solution version and its Pinecone vector."""
    count = execute(
        f"DELETE FROM {TABLE} WHERE row_type = 'solution' AND id = %s",
        (solution_id,),
    )
    if count > 0:
        try:
            delete_vector(solution_id)
        except Exception as exc:
            logger.exception("[KnowledgeBase] Pinecone delete failed: %s", exc)
    return count


def get_top_solutions(
    error_message: str,
    project_name: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
    # Legacy param accepted but ignored — kept for call-site compatibility
    error_hash: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return paginated solutions for a project + error message group.

    Group key resolution order (first match wins):
      1. AI semantic match — find_matching_solution_group() asks Nova Lite to
         identify the correct group by meaning, not exact wording.
      2. Normalized text key — derive_solution_group_key(error_message).
      3. Legacy fallback — error_hash treated as the group key directly.

    All occurrences that resolve to the same group_key see identical results.
    """
    group_key: Optional[str] = None

    # ── Step 1: AI semantic match ─────────────────────────────────────────────
    if error_message and error_message.strip() and project_name:
        try:
            from ai.semantic_group_matcher import find_matching_solution_group
            ai_key = find_matching_solution_group(error_message.strip(), project_name)
            if ai_key:
                group_key = ai_key
                logger.info(
                    "[KnowledgeBase] get_top_solutions resolved via AI match: "
                    "group_key=%r project=%r", group_key, project_name,
                )
        except Exception as exc:
            logger.exception(
                "[KnowledgeBase] get_top_solutions AI match failed — falling back: %s", exc
            )

    # ── Step 2: normalized text key ───────────────────────────────────────────
    if not group_key and error_message and error_message.strip():
        group_key = derive_solution_group_key(error_message)

    # ── Step 3: legacy hash fallback ──────────────────────────────────────────
    if not group_key and error_hash:
        group_key = error_hash
        logger.warning(
            "[KnowledgeBase] get_top_solutions: no error_message supplied, "
            "falling back to error_hash=%r", error_hash
        )

    if not group_key:
        return [], 0

    conditions, params = _group_key_conditions(group_key, project_name)
    where = " AND ".join(conditions)

    rows = query(
        f"SELECT id, solution, created_by, created_at, usage_count, "
        f"confidence_score, version, log_ref_id "
        f"FROM {TABLE} WHERE {where} "
        f"ORDER BY confidence_score DESC, usage_count DESC, created_at DESC "
        f"LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    )
    total_rows = query(
        f"SELECT COUNT(*) AS total FROM {TABLE} WHERE {where}",
        tuple(params),
    )
    total = int(total_rows[0]["total"]) if total_rows else 0

    logger.info(
        "[KnowledgeBase] get_top_solutions group_key=%r project=%r total=%d",
        group_key, project_name, total,
    )
    return rows, total


def get_solution_versions(solution_id: str) -> List[Dict[str, Any]]:
    """Return all versions in the same solution family as solution_id.

    A solution family is identified by log_ref_id, which equals the ID of the
    root (first) version in the Improve chain.  All versions created via
    Improve share the same log_ref_id.  Solutions created via Create New each
    have a unique log_ref_id (their own ID) and are never returned as versions
    of each other.

    The error_hash (group_key) is intentionally NOT used here — that key is for
    retrieval/recommendation only and must not drive version grouping.
    """
    row = _find_solution(solution_id)
    if not row:
        return []

    # The family key is the log_ref_id stored on the solution row.
    # For a root solution it equals its own ID; for improved versions it equals
    # the root's ID.
    family_id    = row.get("log_ref_id") or solution_id
    project_name = row.get("project_name")

    conditions: List[str] = ["row_type = 'solution'", "log_ref_id = %s"]
    params: List[Any]     = [family_id]
    if project_name:
        conditions.append("LOWER(project_name) = LOWER(%s)")
        params.append(project_name)

    return query(
        f"SELECT id, solution, created_by, created_at, usage_count, confidence_score, version "
        f"FROM {TABLE} WHERE {' AND '.join(conditions)} "
        f"ORDER BY version DESC",
        tuple(params),
    )


def get_solution_by_id(solution_id: str) -> Optional[Dict[str, Any]]:
    return _find_solution(solution_id)
