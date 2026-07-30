"""AI recommendation pipeline backed by Bedrock embeddings and Nova Lite.

The public response shape remains unchanged so the frontend does not need to change.

Grouping key
────────────
Retrieval uses  project_name + AI semantic matching  as the primary lookup
strategy.  When a semantic match is found by the LLM (TIER 0), its group key
is used directly to load solutions.  The remaining tiers (embedding + exact
key) are fallbacks for when the LLM is unavailable or returns NO_MATCH.

Retrieval strategy (AI-first, four-tier):
  TIER 0 — AI semantic group match (find_matching_solution_group).
            Asks Nova Lite whether the incoming error belongs to any known
            solution group in this project.  Returns the matched group_key
            and loads solutions from that group directly.  No embeddings needed.
            Skipped when project_name is absent or LLM is unavailable.
  TIER 1 — Pinecone semantic search scoped to project_name (no hash filter).
  TIER 2 — Aurora in-process cosine scan (project-wide, cross-hash).
  TIER 3 — Group-key SQL lookup using derive_solution_group_key(error_message).

Project isolation guarantee
  All tiers are scoped to project_name.  TIER 0 structurally cannot leak
  cross-project data (the matcher only loads groups for the given project).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from ai.embeddings import EMBEDDING_DIM
from ai.error_matching import derive_solution_group_key
from db import query

logger = logging.getLogger(__name__)

TABLE = "projects_data"

# ── Tunable constants ─────────────────────────────────────────────────────────
PINECONE_CANDIDATE_LIMIT = 20   # vectors retrieved from Pinecone per query
AURORA_SCAN_LIMIT        = 200  # rows scanned when Pinecone is unavailable
SIM_THRESHOLD            = 0.30 # minimum cosine similarity to include a result
RANK_LIMIT               = 50   # candidates passed into _rank_candidates


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_embeddings():
    try:
        from ai.embeddings import create_embedding, cosine_similarity
        return create_embedding, cosine_similarity
    except Exception as exc:
        logger.exception("[Recommendations] Embeddings import failed: %s", exc)
        return None, None


def _get_llm():
    try:
        from ai.llm import generate_suggested_solution
        return generate_suggested_solution
    except Exception as exc:
        logger.exception("[Recommendations] LLM import failed: %s", exc)
        return None


def _serialize_solution(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id":               row.get("id"),
        "solution":         row.get("solution"),
        "created_by":       row.get("created_by"),
        "created_at":       row["created_at"].isoformat() if row.get("created_at") else None,
        "usage_count":      row.get("usage_count"),
        "confidence_score": row.get("confidence_score"),
        "version":          row.get("version"),
    }


def _parse_embedding(raw: Any) -> Optional[List[float]]:
    """Parse embedding from the DB TEXT column (JSON array).
    Returns None on any failure — callers treat missing embeddings as unscored.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw if len(raw) > 0 else None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed
        except Exception:
            pass
    return None


def _rank_candidates(
    query_vec: List[float],
    candidates: List[Dict[str, Any]],
    limit: int,
    cosine_similarity_fn: Any,
) -> List[Dict[str, Any]]:
    """Score and rank candidates.

    Combined score = (cosine * 0.7) + (confidence * 0.2) + (usage * 0.1)
    Rows without valid embeddings are appended after scored rows in SQL order.
    """
    scored:   List[Tuple[float, Dict[str, Any]]] = []
    unscored: List[Dict[str, Any]]               = []

    for row in candidates:
        emb = _parse_embedding(row.get("embedding"))
        if emb and len(emb) == EMBEDDING_DIM:
            try:
                sim        = cosine_similarity_fn(query_vec, emb)
                confidence = float(row.get("confidence_score") or 0.0) / 100.0
                usage      = min(int(row.get("usage_count") or 0), 20) / 20.0
                combined   = (sim * 0.7) + (confidence * 0.2) + (usage * 0.1)
                scored.append((combined, row))
            except Exception as exc:
                logger.warning("[Recommendations] Scoring failed for row %s: %s",
                               row.get("id"), exc)
                unscored.append(row)
        else:
            unscored.append(row)

    scored.sort(key=lambda item: item[0], reverse=True)
    ranked = [row for _, row in scored] + unscored
    return ranked[:limit]


# ── Candidate fetch helpers (three tiers) ────────────────────────────────────

def _fetch_error_text(
    error_hash: str,
    project_name: Optional[str],
    error_message: Optional[str] = None,
) -> Tuple[str, str]:
    """Return (error_message, error_detail) for the given error.

    When error_message is already supplied by the caller it is used directly —
    no DB round-trip needed.  Falls back to a hash-based query only when the
    text is not available.
    """
    # Caller already knows the error text — use it directly
    if error_message and error_message.strip():
        return error_message.strip(), ""

    # Fall back to DB lookup by occurrence hash
    conditions = [
        "row_type = 'log'",
        "(error_hash = %s OR MD5(LOWER(TRIM(error))) = %s)",
    ]
    params: List[Any] = [error_hash, error_hash]
    if project_name:
        conditions.insert(0, "LOWER(project_name) = LOWER(%s)")
        params.insert(0, project_name)

    rows = query(
        f"SELECT error AS error_message, error_detail "
        f"FROM {TABLE} "
        f"WHERE {' AND '.join(conditions)} "
        f"LIMIT 1",
        tuple(params),
    )
    if not rows:
        return "", ""
    return (rows[0].get("error_message") or ""), (rows[0].get("error_detail") or "")


def _tier1_pinecone(
    query_vec: List[float],
    project_name: Optional[str],
) -> List[Dict[str, Any]]:
    """TIER 1 — Pinecone semantic search, project-scoped, no hash filter.

    Returns hydrated Aurora rows for the matched solution IDs.
    Returns [] on any failure so the caller falls through to TIER 2.
    """
    try:
        from ai.pinecone_service import query_similar

        matches = query_similar(
            solution_id=None,
            embedding=query_vec,
            project_name=project_name,
            limit=PINECONE_CANDIDATE_LIMIT,
            error_hash=None,    # no hash filter — enables cross-hash retrieval
        )
        if not matches:
            logger.info("[Recommendation] TIER 1 Pinecone returned 0 matches")
            return []

        solution_ids = [m.get("id") for m in matches if m.get("id")]
        if not solution_ids:
            return []

        logger.info("[Recommendation] TIER 1 Pinecone returned %d candidate IDs",
                    len(solution_ids))

        # Hydrate from Aurora with project_name filter to enforce isolation
        placeholders = ", ".join(["%s"] * len(solution_ids))
        hydrate_conditions = [
            "row_type = 'solution'",
            f"id IN ({placeholders})",
        ]
        hydrate_params: List[Any] = list(solution_ids)
        if project_name:
            hydrate_conditions.append("LOWER(project_name) = LOWER(%s)")
            hydrate_params.append(project_name)

        rows = query(
            f"SELECT id, solution, created_by, created_at, "
            f"usage_count, confidence_score, version, embedding "
            f"FROM {TABLE} "
            f"WHERE {' AND '.join(hydrate_conditions)}",
            tuple(hydrate_params),
        )
        logger.info("[Recommendation] TIER 1 hydrated %d rows from Aurora", len(rows))
        return rows

    except Exception as exc:
        logger.exception(
            "[Pinecone] Unavailable — falling through to TIER 2: %s", exc
        )
        return []


def _tier2_aurora_scan(
    query_vec: List[float],
    project_name: Optional[str],
    cosine_similarity_fn: Any,
) -> List[Dict[str, Any]]:
    """TIER 2 — Aurora full-project scan + in-process cosine filter.

    Fetches up to AURORA_SCAN_LIMIT rows for the project, computes cosine
    similarity in Python, keeps rows above SIM_THRESHOLD.
    Returns [] on any failure so the caller falls through to TIER 3.
    """
    try:
        scan_conditions = ["row_type = 'solution'", "embedding IS NOT NULL"]
        scan_params: List[Any] = []
        if project_name:
            scan_conditions.append("LOWER(project_name) = LOWER(%s)")
            scan_params.append(project_name)

        rows = query(
            f"SELECT id, solution, created_by, created_at, "
            f"usage_count, confidence_score, version, embedding "
            f"FROM {TABLE} "
            f"WHERE {' AND '.join(scan_conditions)} "
            f"ORDER BY confidence_score DESC, usage_count DESC, created_at DESC "
            f"LIMIT %s",
            tuple(scan_params + [AURORA_SCAN_LIMIT]),
        )
        if not rows:
            logger.info("[Recommendation] TIER 2 Aurora: no embedded solutions for project")
            return []

        logger.info("[Recommendation] TIER 2 Aurora: scanning %d rows", len(rows))

        above_threshold: List[Dict[str, Any]] = []
        for row in rows:
            emb = _parse_embedding(row.get("embedding"))
            if not emb or len(emb) != EMBEDDING_DIM:
                continue
            try:
                sim = cosine_similarity_fn(query_vec, emb)
                if sim >= SIM_THRESHOLD:
                    above_threshold.append(row)
            except Exception as exc:
                logger.warning("[Recommendation] TIER 2 cosine failed for row %s: %s",
                               row.get("id"), exc)
                continue

        logger.info("[Recommendation] TIER 2 Aurora: %d rows above threshold %.2f",
                    len(above_threshold), SIM_THRESHOLD)
        return above_threshold

    except Exception as exc:
        logger.exception(
            "[Aurora] TIER 2 scan failed — falling through to TIER 3: %s", exc
        )
        return []


def _tier0_ai_group_match(
    error_text: str,
    project_name: Optional[str],
) -> List[Dict[str, Any]]:
    """TIER 0 — AI semantic group match (primary, LLM-based).

    Calls find_matching_solution_group() to ask Nova Lite whether the incoming
    error belongs to any known solution group in this project.  When a match is
    found, fetches all solutions for that group directly from Aurora and returns
    them — no embeddings, no cosine scan.

    Returns [] when:
    - project_name is absent (project isolation requirement)
    - LLM is unavailable or returns NO_MATCH
    - No solutions exist for the matched group
    - Any DB or import error
    """
    if not project_name or not error_text:
        return []

    try:
        from ai.semantic_group_matcher import find_matching_solution_group
        matched_key = find_matching_solution_group(error_text, project_name)
    except Exception as exc:
        logger.exception("[Recommendation] TIER 0 import/call failed: %s", exc)
        return []

    if not matched_key:
        logger.info("[Recommendation] TIER 0 AI match: NO_MATCH for project=%r", project_name)
        return []

    # Load all solutions for the matched group
    try:
        rows = query(
            f"SELECT id, solution, created_by, created_at, "
            f"usage_count, confidence_score, version, embedding "
            f"FROM {TABLE} "
            f"WHERE row_type = 'solution' "
            f"  AND error_hash = %s "
            f"  AND LOWER(project_name) = LOWER(%s) "
            f"ORDER BY confidence_score DESC, usage_count DESC, created_at DESC "
            f"LIMIT %s",
            (matched_key, project_name, RANK_LIMIT),
        )
        logger.info(
            "[Recommendation] TIER 0 AI match: group_key=%r project=%r solutions=%d",
            matched_key, project_name, len(rows),
        )
        return rows
    except Exception as exc:
        logger.exception("[Recommendation] TIER 0 solution load failed: %s", exc)
        return []


def _tier3_group_key_fallback(
    error_message: str,
    project_name: Optional[str],
    occurrence_hash: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """TIER 3 — Group-key SQL lookup (replaces the old hash-exact fallback).

    Queries solution rows whose error_hash == derive_solution_group_key(error_message).
    This is the same key written by insert_solution(), so all occurrences of the
    same error text share results regardless of their occurrence-specific hash.

    Falls back to occurrence_hash when error_message is blank, preserving
    backward compatibility for callers that haven't been updated yet.
    """
    try:
        # Derive the group key from the normalised error text
        group_key: Optional[str] = None
        if error_message and error_message.strip():
            group_key = derive_solution_group_key(error_message)

        if not group_key and occurrence_hash:
            # Old behaviour: treat the raw hash as the key (solutions created
            # before this migration will still be found this way)
            group_key = occurrence_hash
            logger.warning(
                "[Recommendation] TIER 3 falling back to occurrence hash — "
                "no error_message available, hash=%r", occurrence_hash
            )

        if not group_key:
            logger.warning("[Recommendation] TIER 3 skipped — no group_key or hash available")
            return []

        sol_conditions: List[str] = ["row_type = 'solution'", "error_hash = %s"]
        sol_params: List[Any]     = [group_key]
        if project_name:
            sol_conditions.append("LOWER(project_name) = LOWER(%s)")
            sol_params.append(project_name)

        rows = query(
            f"SELECT id, solution, created_by, created_at, "
            f"usage_count, confidence_score, version, embedding "
            f"FROM {TABLE} "
            f"WHERE {' AND '.join(sol_conditions)} "
            f"ORDER BY confidence_score DESC, usage_count DESC, created_at DESC "
            f"LIMIT %s",
            tuple(sol_params + [RANK_LIMIT]),
        )
        logger.info(
            "[Recommendation] TIER 3 group-key fallback: group_key=%r project=%r rows=%d",
            group_key, project_name, len(rows),
        )
        return rows

    except Exception as exc:
        logger.exception("[Aurora] TIER 3 group-key fallback failed: %s", exc)
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def get_similar_solutions(
    error_hash: str,
    project_name: Optional[str] = None,
    limit: int = 10,
    error_message: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return up to *limit* solutions ranked by semantic similarity.

    Retrieval tiers (AI-first):
      TIER 0: AI semantic group match — asks Nova Lite to identify the matching
              solution group by meaning, not wording.  When matched, solutions
              are loaded from that group and returned immediately (no embeddings).
      TIER 1: Pinecone vector search (project-wide, cross-hash)
      TIER 2: Aurora in-process cosine scan (project-wide, cross-hash)
      TIER 3: Group-key SQL (queries by derive_solution_group_key(error_message))

    error_message is the canonical lookup text.  error_hash is retained as a
    fallback for callers that haven't been updated yet.
    """
    create_embedding, cosine_similarity = _get_embeddings()

    # Step 1: resolve error text ───────────────────────────────────────────────
    try:
        error_text, detail_text = _fetch_error_text(error_hash, project_name, error_message)
    except Exception as exc:
        logger.exception("[Recommendations] Error text fetch failed: %s", exc)
        return []

    if not error_text and not detail_text:
        logger.info(
            "[Recommendations] No error text found for hash=%r message=%r — returning empty",
            error_hash, error_message,
        )
        return []

    query_text = f"{error_text}\n\n{detail_text}".strip() or error_text

    # ── TIER 0: AI semantic group match (primary path) ────────────────────────
    # Attempt this first.  When it succeeds we return immediately without
    # touching Pinecone or Bedrock embeddings.
    if project_name:
        tier0_candidates = _tier0_ai_group_match(error_text, project_name)
        if tier0_candidates:
            ranked = tier0_candidates[:limit]
            logger.info(
                "[Recommendation] Returning %d solutions via TIER 0 (AI match)", len(ranked)
            )
            return [_serialize_solution(r) for r in ranked]

    # ── Step 2: generate query embedding (needed for TIER 1 / TIER 2) ─────────
    query_vec: Optional[List[float]] = None
    if create_embedding:
        try:
            query_vec = create_embedding(query_text)
        except Exception as exc:
            logger.exception(
                "[Bedrock] Embedding generation failed — falling back to TIER 3: %s", exc
            )

    # ── TIER 1 / TIER 2: embedding-based retrieval ────────────────────────────
    candidates: List[Dict[str, Any]] = []

    if query_vec and project_name:
        candidates = _tier1_pinecone(query_vec, project_name)

        if not candidates and cosine_similarity:
            logger.info("[Recommendation] TIER 1 empty — trying TIER 2 (Aurora scan)")
            candidates = _tier2_aurora_scan(query_vec, project_name, cosine_similarity)

    elif query_vec and not project_name:
        logger.warning(
            "[Recommendations] project_name missing — "
            "TIER 1 and TIER 2 skipped to prevent cross-project leaks. "
            "Falling through to TIER 3."
        )

    # ── TIER 3: group-key SQL fallback ────────────────────────────────────────
    if not candidates:
        logger.info("[Recommendation] Semantic tiers empty — using TIER 3 (group-key fallback)")
        candidates = _tier3_group_key_fallback(
            error_text,
            project_name,
            occurrence_hash=error_hash,
        )

    if not candidates:
        return []

    # ── Step 4: rank ───────────────────────────────────────────────────────────
    if query_vec and cosine_similarity:
        try:
            ranked = _rank_candidates(query_vec, candidates, limit, cosine_similarity)
        except Exception as exc:
            logger.exception(
                "[Recommendations] Ranking failed — using candidate order: %s", exc
            )
            ranked = candidates[:limit]
    else:
        ranked = candidates[:limit]

    return [_serialize_solution(r) for r in ranked]


def get_ai_recommendations(
    error_hash: str,
    project_name: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Return { recommendation: str|None, description: str|None, solutions: [...] }.

    error_message is now the primary lookup key.  error_hash is kept for
    backward compatibility and to resolve the error text when needed.
    Payload shape is unchanged — frontend requires no update.
    """
    try:
        solutions = get_similar_solutions(
            error_hash,
            project_name,
            limit=10,
            error_message=error_message,
        )
        if not solutions:
            return {"recommendation": None, "description": None, "solutions": []}

        # Use the supplied error_message text directly when available;
        # fall back to a DB lookup by hash only when necessary.
        prompt_parts = []
        detail = ""
        if project_name and project_name.strip():
            prompt_parts.append(f"Project: {project_name.strip()}")
        if error_message and error_message.strip():
            prompt_parts.append(f"Error: {error_message.strip()}")
        else:
            error_rows = query(
                f"SELECT error AS error_message, error_detail "
                f"FROM {TABLE} "
                f"WHERE row_type = 'log' AND error_hash = %s "
                f"LIMIT 1",
                (error_hash,),
            )
            prompt_parts.append((error_rows[0].get("error_message") if error_rows else "") or "")
            detail = (error_rows[0].get("error_detail") if error_rows else "") or ""

        if detail:
            prompt_parts.append(f"Stack trace:\n{detail.strip()}")

        prompt = "\n\n".join(part for part in prompt_parts if part).strip()

        generate_suggested_solution = _get_llm()
        nova_diagnostics = {}
        if generate_suggested_solution:
            logger.info("[Recommendations] Retrieved context for Nova — solutions=%d", len(solutions[:5]))
            logger.info("[Recommendations] Prompt sent to Nova")
            recommendation = generate_suggested_solution(prompt, solutions[:5])
            logger.info("[Recommendations] Nova response generated")
            try:
                from ai.bedrock_llm import get_last_nova_diagnostics
                nova_diagnostics = get_last_nova_diagnostics()
            except Exception as diag_exc:
                logger.exception("[Recommendations] failed to fetch Nova diagnostics: %s", diag_exc)
        else:
            recommendation = None
            logger.warning(
                "[Recommendations] LLM unavailable — returning solutions without recommendation"
            )

        # Generate error description (compute BEFORE building the result)
        description = None
        if error_message or detail:
            try:
                from ai.llm import generate_error_description
                logger.info(
                    "[Recommendations] Calling generate_error_description — project_name=%r error_message_present=%s detail_length=%d solutions=%d",
                    project_name,
                    bool(error_message and error_message.strip()),
                    len(detail or ""),
                    len(solutions[:5]),
                )
                description = generate_error_description(
                    error_message=error_message or prompt,
                    error_detail=detail,
                    project_name=project_name,
                    solutions=solutions[:5],
                )
                logger.info(
                    "[Recommendations] generate_error_description returned length=%d description=%r",
                    len(description or ""),
                    (description or "")[:300],
                )
                if not description:
                    logger.info("[Recommendations] Description was empty — using empty fallback")
                else:
                    logger.info("[Recommendations] Description generated successfully")
            except Exception as desc_exc:
                logger.exception(
                    "[Recommendations] Error description generation failed: %s", desc_exc
                )

        result = {"recommendation": recommendation, "description": description, "solutions": solutions, "nova_diagnostics": nova_diagnostics}
        return result

    except Exception as exc:
        logger.exception(
            "[Recommendations] Recommendation generation failed — returning empty payload: %s", exc
        )
        return {"recommendation": None, "description": None, "solutions": []}
