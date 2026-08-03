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


import hashlib


# ── Solution text normalization & fingerprinting ──────────────────────────────

def _normalize_solution_text(value: Optional[str]) -> str:
    """Full normalization for duplicate detection.

    Two solutions that represent the same fix must produce the same output
    regardless of:
    - capitalization
    - whitespace / line endings
    - repeated / trailing punctuation
    - markdown formatting (**, __, #, >, -, `)
    - HTML tags
    - emojis and non-ASCII symbols
    - unicode variants
    - repeated symbols
    """
    import unicodedata

    if not value:
        return ""

    s = value

    # Normalize unicode to NFC (composed form), then strip non-ASCII control chars
    s = unicodedata.normalize("NFC", s)

    # Remove HTML tags
    s = re.sub(r"<[^>]+>", " ", s)

    # Remove markdown formatting characters (bold, italic, headers, code, blockquote, lists)
    s = re.sub(r"[*_~`#>]", " ", s)

    # Remove emojis and other symbol/pictograph unicode blocks
    # (matches most emoji ranges without external libraries)
    s = re.sub(
        r"[\U0001F300-\U0001F9FF"   # Misc symbols, dingbats, emoticons, transport
        r"\U00002600-\U000027BF"   # Misc symbols
        r"\U0001FA00-\U0001FA9F"   # Chess, hand, misc symbols
        r"\U0000200B-\U0000200F"   # Zero-width spaces
        r"\U0000FE00-\U0000FE0F"   # Variation selectors
        r"]+",
        " ", s, flags=re.UNICODE,
    )

    # Collapse sequences of the same punctuation char (e.g. "......." → ".")
    # Handles: . , ! ? - _ = + ~ ^ | / \\ : ; @ % & * ( ) [ ] { } < >
    s = re.sub(r"([.!?,;:@%&\-_=+~^|/\\*()\[\]{}<>])\1+", r"\1", s)

    # Strip all remaining punctuation that doesn't change meaning
    # Keep alphanumeric, spaces, and single meaningful punctuation
    s = re.sub(r"[^\w\s]", " ", s)

    # Collapse whitespace (including newlines, tabs)
    s = re.sub(r"\s+", " ", s)

    # Lowercase and strip
    s = s.strip().lower()

    return s


def _solution_fingerprint(solution_text: str) -> str:
    """Return a stable MD5 fingerprint of the normalized solution text.

    Two solutions with the same fingerprint are considered identical regardless
    of formatting, punctuation, or whitespace differences.
    """
    normalized = _normalize_solution_text(solution_text)
    if not normalized:
        return ""
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _nova_same_fix_check(
    candidate_text: str,
    existing_text: str,
    error_context: Optional[str] = None,
) -> Optional[str]:
    """Ask Nova whether two solutions represent the same underlying fix.

    Returns 'SAME_FIX', 'DIFFERENT_FIX', or None if Nova is unavailable.
    Nova is the FINAL authority — it ignores formatting and evaluates only
    whether the technical resolution is the same.
    """
    try:
        from ai.bedrock_llm import _call_nova
        error_ctx = f"\n\nError context: {error_context.strip()[:300]}" if error_context else ""
        prompt = (
            "You are a technical solution validator.\n\n"
            "Compare these two solutions and determine if they describe the SAME underlying technical fix.\n"
            "Ignore: punctuation, capitalization, whitespace, formatting, markdown, wording differences.\n"
            "Evaluate ONLY whether the technical resolution is identical.\n"
            f"{error_ctx}\n\n"
            f"EXISTING SOLUTION:\n{existing_text.strip()[:500]}\n\n"
            f"CANDIDATE SOLUTION:\n{candidate_text.strip()[:500]}\n\n"
            "Reply with ONLY one of:\n"
            "SAME_FIX\n"
            "DIFFERENT_FIX"
        )
        raw = _call_nova(prompt, max_tokens=20)
        answer = (raw or "").strip().upper()
        if "SAME_FIX" in answer:
            logger.info("[KnowledgeBase] Nova final verdict: SAME_FIX")
            return "SAME_FIX"
        if "DIFFERENT_FIX" in answer:
            logger.info("[KnowledgeBase] Nova final verdict: DIFFERENT_FIX")
            return "DIFFERENT_FIX"
        logger.warning("[KnowledgeBase] Nova returned unexpected answer=%r — treating as DIFFERENT_FIX", answer[:80])
        return "DIFFERENT_FIX"
    except Exception as exc:
        logger.exception("[KnowledgeBase] Nova same-fix check failed: %s", exc)
        return None


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
    """Fingerprint-based duplicate search within the solution group — zero Bedrock cost.

    Computes the normalized fingerprint of solution_text, then scans all
    solution rows in the group and returns one whose fingerprint matches.
    This catches "User uploaded an incorrect file." vs
    "User uploaded an incorrect file................." as identical.
    """
    candidate_fp = _solution_fingerprint(solution_text)
    if not candidate_fp:
        return None

    logger.info(
        "[KnowledgeBase] Fingerprint search — candidate_fp=%r group_key=%r",
        candidate_fp, group_key,
    )

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
            if _solution_fingerprint(row.get("solution")) == candidate_fp:
                logger.info(
                    "[KnowledgeBase] Fingerprint duplicate found — solution_id=%s",
                    row.get("id"),
                )
                return row
    except Exception as exc:
        logger.exception("[KnowledgeBase] Fingerprint duplicate query failed: %s", exc)

    return None


# ── Tier 2: Semantic duplicate search (Bedrock + Pinecone) ───────────────────

def detect_duplicate_solution(
    solution_text: str,
    group_key: str,
    project_name: Optional[str] = None,
    limit: int = 5,
    error_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Four-stage semantic duplicate detection.

    Stage 1 (fingerprint)  — already handled by _find_duplicate_solution().
                             Caller passes solution_text ONLY when fingerprint
                             check found nothing.

    Stage 2 (embedding)    — embed the NORMALIZED solution text and query
                             Pinecone for similar vectors.

    Stage 3 (thresholds)   — >= 0.97 → automatic duplicate, no Nova needed.
                             0.90–0.97 → ask Nova for SAME_FIX / DIFFERENT_FIX.
                             < 0.90 → new solution.

    Stage 4 (Nova)         — final authority on ambiguous cases.

    Fails open: any exception returns is_duplicate=False so saves are never
    silently blocked.
    """
    # Embed the NORMALIZED text so trivial formatting differences (dots, spaces,
    # markdown) don't push the vector far from the canonical solution vector.
    normalized_text = _normalize_solution_text(solution_text)
    if not normalized_text:
        logger.warning("[KnowledgeBase] Normalized solution text is empty — skipping semantic search")
        return {"is_duplicate": False, "decision": "new", "reason": "empty_normalized", "duplicate_prompt": False}

    try:
        logger.info(
            "[KnowledgeBase] Semantic duplicate detection — project=%r group_key=%r",
            project_name, group_key,
        )
        from ai.embeddings import create_embedding

        embedding = create_embedding(normalized_text)
        if embedding is None:
            logger.warning("[KnowledgeBase] Duplicate detection skipped — embedding unavailable")
            return {"is_duplicate": False, "decision": "new",
                    "reason": "embedding_unavailable", "duplicate_prompt": False}

        logger.info("[KnowledgeBase] Embedding generated — length=%d", len(embedding))
        matches = query_similar(None, embedding, project_name, limit=limit, error_hash=None)
        logger.info("[KnowledgeBase] Pinecone returned %d matches", len(matches))

        for idx, match in enumerate(matches[:5], start=1):
            metadata = match.get("metadata") or {}
            score = max(float(match.get("score") or 0.0), 0.0)
            logger.info(
                "[KnowledgeBase] Match %d: solution_id=%s score=%.4f",
                idx, metadata.get("solution_id") or match.get("id"), score,
            )

        if not matches:
            return {"is_duplicate": False, "decision": "new",
                    "reason": "no_matches", "duplicate_prompt": False}

        # Find best candidate
        candidate = None
        best_similarity = 0.0
        for match in matches:
            metadata = match.get("metadata") or {}
            if not metadata.get("solution_id"):
                continue
            sim = max(float(match.get("score") or 0.0), 0.0)
            if sim > best_similarity:
                best_similarity = sim
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

        logger.info(
            "[KnowledgeBase] Best candidate: solution_id=%r similarity=%.4f",
            candidate.get("id"), best_similarity,
        )

        # ── Stage 3: similarity thresholds ───────────────────────────────────

        # Auto-duplicate at >= 0.97 (tighter than before — eliminates near-identical vectors)
        if best_similarity >= 0.97:
            logger.info("[KnowledgeBase] Decision: AUTO_DUPLICATE (sim=%.4f >= 0.97)", best_similarity)
            return {
                "is_duplicate":      True,
                "decision":          "duplicate",
                "reason":            "high_similarity",
                "similarity":        best_similarity,
                "solution_id":       candidate.get("id"),
                "metadata":          candidate.get("metadata") or {},
                "existing_solution": existing_solution,
                "duplicate_prompt":  True,
            }

        # ── Stage 4: Nova final validation at 0.90–0.97 ──────────────────────
        if best_similarity >= 0.90:
            logger.info(
                "[KnowledgeBase] Ambiguous zone (%.4f) — asking Nova for SAME_FIX / DIFFERENT_FIX",
                best_similarity,
            )
            existing_text = (existing_solution or {}).get("solution") or ""
            nova_verdict = _nova_same_fix_check(
                candidate_text  = solution_text,
                existing_text   = existing_text,
                error_context   = error_context,
            )

            if nova_verdict == "SAME_FIX":
                logger.info("[KnowledgeBase] Nova: SAME_FIX → duplicate")
                return {
                    "is_duplicate":      True,
                    "decision":          "duplicate",
                    "reason":            "nova_same_fix",
                    "similarity":        best_similarity,
                    "solution_id":       candidate.get("id"),
                    "metadata":          candidate.get("metadata") or {},
                    "existing_solution": existing_solution,
                    "duplicate_prompt":  True,
                }
            elif nova_verdict is None:
                # Nova unavailable — surface as a warning prompt for the developer
                logger.warning(
                    "[KnowledgeBase] Nova unavailable — surfacing duplicate_prompt for developer decision"
                )
                return {
                    "is_duplicate":      False,
                    "decision":          "warn",
                    "reason":            "nova_unavailable",
                    "similarity":        best_similarity,
                    "solution_id":       candidate.get("id"),
                    "metadata":          candidate.get("metadata") or {},
                    "existing_solution": existing_solution,
                    "duplicate_prompt":  True,
                }
            else:
                # DIFFERENT_FIX — new solution allowed
                logger.info("[KnowledgeBase] Nova: DIFFERENT_FIX → new solution")

        logger.info(
            "[KnowledgeBase] Decision: NEW (similarity=%.4f below all thresholds)", best_similarity
        )
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

        # Tier 2: semantic + Nova four-stage pipeline ────────────────────────
        duplicate_check = detect_duplicate_solution(
            solution,
            group_key,
            canonical_project,
            error_context=raw_error_text or None,
        )
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
    error_hash: Optional[str] = None,
    error_group_name: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return paginated solutions using three retrieval tiers.

    TIER 1 — Exact group match
        Resolves the solution group_key from the error message (AI semantic →
        normalized text → legacy hash) and returns the best version per family.
        match_source = "exact_match"

    TIER 2 — Semantic group fallback (only when TIER 1 returns nothing)
        Finds all solution group_keys that were ever written for log rows sharing
        the same taxonomy group (error_group_name).  Returns the top solutions
        from those groups, ranked by confidence DESC / usage DESC.
        match_source = "same_semantic_group"

    TIER 3 — Cross-project Pinecone similarity (only when TIER 2 also returns nothing)
        Embeds the error message and queries Pinecone for similar solution vectors,
        project-scoped.  Falls back to an Aurora cosine scan when Pinecone is
        unavailable.
        match_source = "semantic_similarity"

    Every returned row carries a `match_source` field so the frontend can display
    "✓ Exact Match", "✓ Same Group (Programming Errors)", or "✓ Similar Error".

    Returns ONE card per solution family (best version per log_ref_id).
    """

    def _best_per_family(rows: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
        """Deduplicate to one best row per solution family and stamp match_source."""
        seen: set = set()
        result: List[Dict[str, Any]] = []
        for r in rows:
            fid = r.get("log_ref_id") or r.get("id")
            if fid not in seen:
                seen.add(fid)
                stamped = dict(r)
                stamped["match_source"] = source
                result.append(stamped)
        return result

    # ── TIER 1: exact group match ─────────────────────────────────────────────
    group_key: Optional[str] = None

    if error_message and error_message.strip() and project_name:
        try:
            from ai.semantic_group_matcher import find_matching_solution_group
            ai_key = find_matching_solution_group(error_message.strip(), project_name)
            if ai_key:
                group_key = ai_key
                logger.info(
                    "[KnowledgeBase] get_top_solutions TIER1 AI match: "
                    "group_key=%r project=%r", group_key, project_name,
                )
        except Exception as exc:
            logger.exception(
                "[KnowledgeBase] get_top_solutions AI match failed: %s", exc
            )

    if not group_key and error_message and error_message.strip():
        group_key = derive_solution_group_key(error_message)

    if not group_key and error_hash:
        group_key = error_hash
        logger.warning(
            "[KnowledgeBase] get_top_solutions TIER1: no error_message, "
            "falling back to error_hash=%r", error_hash
        )

    tier1_rows: List[Dict[str, Any]] = []
    if group_key:
        conditions, params = _group_key_conditions(group_key, project_name)
        where = " AND ".join(conditions)
        raw = query(
            f"SELECT id, solution, created_by, created_at, usage_count, "
            f"confidence_score, version, log_ref_id "
            f"FROM {TABLE} WHERE {where} "
            f"ORDER BY usage_count DESC NULLS LAST, "
            f"         confidence_score DESC NULLS LAST, "
            f"         created_at DESC NULLS LAST",
            tuple(params),
        )
        tier1_rows = _best_per_family(raw, "exact_match")

    if tier1_rows:
        total = len(tier1_rows)
        paginated = tier1_rows[offset: offset + limit]
        logger.info(
            "[KnowledgeBase] get_top_solutions TIER1 returning %d/%d families",
            len(paginated), total,
        )
        return paginated, total

    # ── TIER 2: same taxonomy group ───────────────────────────────────────────
    # When no exact group_key match exists, search for solutions that were saved
    # for any error in the same taxonomy category (error_group_name).
    tier2_rows: List[Dict[str, Any]] = []
    if error_group_name and project_name:
        try:
            # Find all solution group_keys that belong to log rows in this
            # taxonomy category.  Solutions are stored with
            # error_hash = group_key — which is the MD5 of the normalized error
            # text, not the taxonomy category.  We find group_keys indirectly:
            # look at log rows in the same category, get their distinct
            # error_hash values (= the group_keys the solutions were saved under).
            group_key_rows = query(
                f"SELECT DISTINCT error_hash AS gk "
                f"FROM {TABLE} "
                f"WHERE row_type = 'log' "
                f"  AND error_group_name = %s "
                f"  AND error_hash IS NOT NULL "
                f"  AND LOWER(project_name) = LOWER(%s) "
                f"LIMIT 50",
                (error_group_name, project_name),
            )
            candidate_keys = [r["gk"] for r in group_key_rows if r.get("gk")]

            if candidate_keys:
                placeholders = ", ".join(["%s"] * len(candidate_keys))
                t2_raw = query(
                    f"SELECT id, solution, created_by, created_at, usage_count, "
                    f"confidence_score, version, log_ref_id "
                    f"FROM {TABLE} "
                    f"WHERE row_type = 'solution' "
                    f"  AND error_hash IN ({placeholders}) "
                    f"  AND LOWER(project_name) = LOWER(%s) "
                    f"ORDER BY confidence_score DESC NULLS LAST, "
                    f"         usage_count DESC NULLS LAST, "
                    f"         created_at DESC NULLS LAST",
                    tuple(candidate_keys + [project_name]),
                )
                group_label = error_group_name
                tier2_rows = _best_per_family(
                    t2_raw, f"same_group:{group_label}"
                )
                logger.info(
                    "[KnowledgeBase] get_top_solutions TIER2 group=%r "
                    "candidate_keys=%d families=%d",
                    error_group_name, len(candidate_keys), len(tier2_rows),
                )
        except Exception as exc:
            logger.exception(
                "[KnowledgeBase] get_top_solutions TIER2 failed: %s", exc
            )

    if tier2_rows:
        total = len(tier2_rows)
        paginated = tier2_rows[offset: offset + limit]
        logger.info(
            "[KnowledgeBase] get_top_solutions TIER2 returning %d/%d families",
            len(paginated), total,
        )
        return paginated, total

    # ── TIER 3: Pinecone semantic similarity ──────────────────────────────────
    # Last resort: embed the error message and find similar solutions via Pinecone
    # or Aurora cosine scan.  Project-scoped.
    tier3_rows: List[Dict[str, Any]] = []
    if error_message and error_message.strip() and project_name:
        try:
            from ai.embeddings import create_embedding, cosine_similarity as _cos
            from ai.embeddings import EMBEDDING_DIM
            query_vec = create_embedding(error_message.strip())
            if query_vec:
                # Try Pinecone first
                try:
                    from ai.pinecone_service import query_similar
                    matches = query_similar(
                        solution_id=None,
                        embedding=query_vec,
                        project_name=project_name,
                        limit=20,
                        error_hash=None,
                    )
                    if matches:
                        sol_ids = [m.get("id") for m in matches if m.get("id")]
                        if sol_ids:
                            ph = ", ".join(["%s"] * len(sol_ids))
                            t3_raw = query(
                                f"SELECT id, solution, created_by, created_at, usage_count, "
                                f"confidence_score, version, log_ref_id "
                                f"FROM {TABLE} "
                                f"WHERE row_type = 'solution' "
                                f"  AND id IN ({ph}) "
                                f"  AND LOWER(project_name) = LOWER(%s)",
                                tuple(sol_ids + [project_name]),
                            )
                            # Attach similarity scores then sort
                            score_map = {
                                m.get("id"): float(m.get("score") or 0.0)
                                for m in matches if m.get("id")
                            }
                            t3_raw_sorted = sorted(
                                t3_raw,
                                key=lambda r: score_map.get(r.get("id"), 0.0),
                                reverse=True,
                            )
                            for r in t3_raw_sorted:
                                r["_similarity"] = score_map.get(r.get("id"), 0.0)
                            tier3_rows = _best_per_family(t3_raw_sorted, "semantic_similarity")
                            logger.info(
                                "[KnowledgeBase] get_top_solutions TIER3 Pinecone: %d families",
                                len(tier3_rows),
                            )
                except Exception as _pexc:
                    logger.warning(
                        "[KnowledgeBase] get_top_solutions TIER3 Pinecone failed — "
                        "trying Aurora scan: %s", _pexc,
                    )

                # Aurora cosine scan fallback when Pinecone returned nothing
                if not tier3_rows:
                    try:
                        scan_rows = query(
                            f"SELECT id, solution, created_by, created_at, usage_count, "
                            f"confidence_score, version, log_ref_id, embedding "
                            f"FROM {TABLE} "
                            f"WHERE row_type = 'solution' "
                            f"  AND embedding IS NOT NULL "
                            f"  AND LOWER(project_name) = LOWER(%s) "
                            f"ORDER BY confidence_score DESC NULLS LAST "
                            f"LIMIT 200",
                            (project_name,),
                        )
                        import json as _json
                        scored = []
                        for r in scan_rows:
                            raw_emb = r.get("embedding")
                            emb = None
                            if isinstance(raw_emb, str):
                                try:
                                    emb = _json.loads(raw_emb)
                                except Exception:
                                    pass
                            elif isinstance(raw_emb, list):
                                emb = raw_emb
                            if emb and len(emb) == EMBEDDING_DIM:
                                sim = _cos(query_vec, emb)
                                if sim >= 0.30:
                                    scored.append((sim, r))
                        scored.sort(key=lambda x: x[0], reverse=True)
                        t3_aurora = [r for _, r in scored[:limit * 3]]
                        for i, (sim, r) in enumerate(scored[:limit * 3]):
                            t3_aurora[i]["_similarity"] = sim
                        tier3_rows = _best_per_family(t3_aurora, "semantic_similarity")
                        logger.info(
                            "[KnowledgeBase] get_top_solutions TIER3 Aurora: %d families",
                            len(tier3_rows),
                        )
                    except Exception as _aexc:
                        logger.exception(
                            "[KnowledgeBase] get_top_solutions TIER3 Aurora failed: %s", _aexc,
                        )
        except Exception as exc:
            logger.exception(
                "[KnowledgeBase] get_top_solutions TIER3 failed: %s", exc
            )

    total = len(tier3_rows)
    paginated = tier3_rows[offset: offset + limit]
    logger.info(
        "[KnowledgeBase] get_top_solutions TIER3 returning %d/%d (or 0 if no results)",
        len(paginated), total,
    )
    return paginated, total


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
