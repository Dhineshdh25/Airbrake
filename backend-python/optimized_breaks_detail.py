"""
Optimized breaks detail endpoint - separates fast and slow operations.

This module provides:
1. A fast endpoint that returns basic error data immediately
2. Separate endpoints for expensive operations (AI, solutions) that can be called lazily
3. Proper database indexing recommendations

Performance targets:
- Main endpoint: < 500ms (basic error details)
- AI endpoint: < 3s (async/lazy load)
- Solution endpoint: < 1s (cached/lazy load)
"""

import time
import json
from typing import Optional, Dict, Any
from flask import request, jsonify, g
import logging

logger = logging.getLogger(__name__)

TABLE = "projects_data"


def get_break_detail_optimized(error_hash: str, query_func, serialize_row, serialize_rows, 
                                build_error_hash_candidates, parse_and_enhance_stacktrace,
                                STACKTRACE_PARSER_AVAILABLE, DEBUG_BREAK_DETAIL):
    """
    Optimized version of get_break_detail endpoint.
    
    Returns ONLY essential data immediately:
    - Error message and details
    - Occurrences list
    - Status
    - Parsed stacktrace (if fast enough)
    
    DEFERRED operations (loaded separately by frontend):
    - AI recommendations (slow LLM call)
    - Solution lookup (complex multi-tier search)
    - Jira ticket (can be cached)
    """
    request_id = g.get("request_id", "unknown")
    request_start = time.perf_counter()
    print(f"[PERF] [req:{request_id}] === OPTIMIZED REQUEST START === error_hash={error_hash}")
    
    try:
        # Parse parameters
        parse_params_start = time.perf_counter()
        project_name = (request.args.get('project_name') or '').strip() or None
        log_id_param = request.args.get('log_id', '').strip() or None
        parse_params_elapsed = (time.perf_counter() - parse_params_start) * 1000
        print(f"[PERF] [req:{request_id}] Parse params: {parse_params_elapsed:.3f}ms")
        
        debug_info = {
            "error_hash": error_hash,
            "project_name": project_name,
            "optimized": True,
        }
        
        # Generate hash candidates
        hash_gen_start = time.perf_counter()
        hash_candidates = build_error_hash_candidates(error_hash, None)
        hash_gen_elapsed = (time.perf_counter() - hash_gen_start) * 1000
        print(f"[PERF] [req:{request_id}] Hash generation: {hash_gen_elapsed:.3f}ms")
        
        # Build primary query - OPTIMIZED with proper WHERE clause ordering
        primary_params = []
        primary_conditions = ["row_type = 'log'", "error IS NOT NULL", "error <> ''"]
        
        if error_hash and hash_candidates:
            hash_clauses = []
            for candidate in hash_candidates:
                hash_clauses.append("error_hash = %s")
                primary_params.append(candidate)
            if hash_clauses:
                primary_conditions.append(f"({' OR '.join(hash_clauses)})")
        
        if project_name:
            primary_conditions.insert(0, "LOWER(project_name) = LOWER(%s)")
            primary_params.insert(0, project_name)
        
        primary_where = ' AND '.join(primary_conditions)
        
        # Execute PRIMARY query - should be FAST with proper indexes
        query_start = time.perf_counter()
        log_query = (
            "SELECT id, project_name, error AS error_message, error_detail, error_hash, "
            "failure_count, timestamp, error_status, reopened_at, file_name, "
            "error_group_name "
            f"FROM {TABLE} "
            f"WHERE {primary_where} "
            "ORDER BY timestamp DESC"
        )
        error_rows = query_func(log_query, tuple(primary_params))
        query_elapsed = (time.perf_counter() - query_start) * 1000
        print(f"[PERF] [req:{request_id}] Primary query: {query_elapsed:.3f}ms (returned {len(error_rows) if error_rows else 0} rows)")
        
        # Fallback to MD5 if needed
        if not error_rows:
            fallback_start = time.perf_counter()
            fallback_params = []
            fallback_conditions = ["row_type = 'log'", "error IS NOT NULL", "error <> ''"]
            if project_name:
                fallback_conditions.insert(0, "LOWER(project_name) = LOWER(%s)")
                fallback_params.append(project_name)
            fallback_conditions.append("MD5(LOWER(TRIM(error))) = %s")
            fallback_params.append(error_hash)
            fallback_where = ' AND '.join(fallback_conditions)
            fallback_sql = (
                "SELECT id, project_name, error AS error_message, error_detail, error_hash, "
                "failure_count, timestamp, error_status, reopened_at, file_name, "
                "error_group_name "
                f"FROM {TABLE} "
                f"WHERE {fallback_where} "
                "ORDER BY timestamp DESC"
            )
            error_rows = query_func(fallback_sql, tuple(fallback_params))
            fallback_elapsed = (time.perf_counter() - fallback_start) * 1000
            print(f"[PERF] [req:{request_id}] Fallback query: {fallback_elapsed:.3f}ms")
        
        if not error_rows:
            return jsonify({"error": "Not Found", "message": "Error not found."}), 404
        
        first = error_rows[0]
        
        # Calculate basic aggregates
        occurrence_count = sum(int(r.get("failure_count", 1) or 0) for r in error_rows)
        timestamps = [r.get("timestamp") for r in error_rows if r.get("timestamp") is not None]
        first_seen = min(timestamps) if timestamps else None
        last_seen = max(timestamps) if timestamps else None
        file_name = next((r.get("file_name") for r in error_rows if r.get("file_name")), first.get("file_name"))
        
        # Status calculation
        status_calc_start = time.perf_counter()
        specific_row = None
        if log_id_param:
            specific_row = next((r for r in error_rows if r.get("id") == log_id_param), None)
        
        if specific_row:
            row_status = specific_row.get("error_status") or "open"
            if row_status == "resolved":
                status = "resolved"
            elif row_status == "reopened":
                status = "regression"
            elif occurrence_count == 1:
                status = "new"
            else:
                status = "existing"
            first = specific_row
        else:
            has_resolved = any(r.get("error_status") == "resolved" for r in error_rows)
            has_reopened = any(r.get("error_status") == "reopened" for r in error_rows)
            if has_resolved:
                status = "resolved"
            elif has_reopened:
                status = "regression"
            elif occurrence_count == 1:
                status = "new"
            else:
                status = "existing"
        status_calc_elapsed = (time.perf_counter() - status_calc_start) * 1000
        print(f"[PERF] [req:{request_id}] Status calculation: {status_calc_elapsed:.3f}ms")
        
        # Occurrence numbering
        occur_num_start = time.perf_counter()
        asc = sorted(error_rows, key=lambda x: x.get("timestamp") or "")
        cumulative = 0
        occurrence_map = {}
        for row in asc:
            fc = int(row.get("failure_count", 1) or 0)
            occurrence_map[row.get("id")] = cumulative + 1
            cumulative += fc
        
        occurrences = []
        for r in error_rows:
            occurrences.append({
                "id": r.get("id"),
                "file_name": r.get("file_name"),
                "timestamp": r.get("timestamp"),
                "failure_count": int(r.get("failure_count", 1) or 0),
                "occurrence_number": occurrence_map.get(r.get("id")),
            })
        occur_num_elapsed = (time.perf_counter() - occur_num_start) * 1000
        print(f"[PERF] [req:{request_id}] Occurrence numbering: {occur_num_elapsed:.3f}ms")
        
        # OPTIONAL: Parse stacktrace ONLY if it's fast (< 100ms typical)
        # If slow, move this to a separate endpoint too
        parsed_stacktrace = None
        if STACKTRACE_PARSER_AVAILABLE:
            stacktrace_start = time.perf_counter()
            try:
                # Parse WITHOUT source code enhancement for speed
                parsed_stacktrace = parse_and_enhance_stacktrace(
                    first["error_message"],
                    first.get("error_detail"),
                    enhance_with_source=False,  # DISABLED for speed
                )
                stacktrace_elapsed = (time.perf_counter() - stacktrace_start) * 1000
                print(f"[PERF] [req:{request_id}] Stacktrace parsing (no source): {stacktrace_elapsed:.3f}ms")
            except Exception as e:
                print(f"[req:{request_id}] Stacktrace parsing failed: {e}")
        
        # Build result with ONLY essential data
        result = {
            "project_name": first["project_name"],
            "file_name": file_name,
            "error_message": first["error_message"],
            "error_detail": first.get("error_detail"),
            "parsed_stacktrace": parsed_stacktrace,
            "error_hash": error_hash,
            "error_group_name": first.get("error_group_name") or None,
            "occurrence_count": occurrence_count,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "status": status,
            "error_status": first.get("error_status"),
            "occurrences": serialize_rows(occurrences),
            # DEFERRED FIELDS - loaded separately by frontend:
            "solution": None,  # Use /api/breaks/detail/:hash/solution
            "solution_error": None,
            "ai_recommendation": None,  # Use /api/breaks/detail/:hash/ai
            "jira_ticket": None,  # Use /api/breaks/detail/:hash/jira
            "_optimized": True,
            "_endpoints": {
                "solution": f"/api/breaks/detail/{error_hash}/solution?project_name={project_name}",
                "ai": f"/api/breaks/detail/{error_hash}/ai?project_name={project_name}",
                "jira": f"/api/breaks/detail/{error_hash}/jira?project_name={project_name}",
            }
        }
        
        request_elapsed = (time.perf_counter() - request_start) * 1000
        print(f"[PERF] [req:{request_id}] === OPTIMIZED REQUEST END === Total: {request_elapsed:.3f}ms")
        
        if DEBUG_BREAK_DETAIL:
            debug_info['request_elapsed_ms'] = round(request_elapsed, 3)
            result["debug"] = debug_info
        
        return jsonify(serialize_row(result))
        
    except Exception as e:
        import traceback as _tb
        tb_str = _tb.format_exc()
        request_elapsed = (time.perf_counter() - request_start) * 1000
        print(f"[PERF] [req:{request_id}] ERROR after {request_elapsed:.3f}ms: {type(e).__name__}: {e}")
        print(f"[req:{request_id}] Traceback:\n{tb_str}")
        return jsonify({
            "error": "Internal Server Error",
            "message": "Error detail failed to load.",
            "trace_id": request_id,
        }), 500


def get_break_detail_solution(error_hash: str, query_func, serialize_row,
                               build_error_hash_candidates, TABLE):
    """
    Separate endpoint for solution lookup - can be called lazily by frontend.
    This operation is expensive due to embeddings and Pinecone lookups.
    """
    request_id = g.get("request_id", "unknown")
    solution_start = time.perf_counter()
    print(f"[PERF] [req:{request_id}] === SOLUTION REQUEST START === error_hash={error_hash}")
    
    try:
        project_name = (request.args.get('project_name') or '').strip() or None
        
        # Import solution lookup logic
        from ai.recommendations import get_similar_solutions
        
        # Get the error details for context
        hash_candidates = build_error_hash_candidates(error_hash, None)
        params = []
        conditions = ["row_type = 'log'"]
        if hash_candidates:
            hash_clauses = []
            for candidate in hash_candidates:
                hash_clauses.append("error_hash = %s")
                params.append(candidate)
            conditions.append(f"({' OR '.join(hash_clauses)})")
        if project_name:
            conditions.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        error_rows = query_func(
            f"SELECT error AS error_message, error_detail FROM {TABLE} "
            f"WHERE {' AND '.join(conditions)} LIMIT 1",
            tuple(params)
        )
        
        if not error_rows:
            return jsonify({"solution": None}), 404
        
        error_message = error_rows[0].get("error_message")
        error_detail = error_rows[0].get("error_detail")
        
        # Use semantic solution search
        solutions = get_similar_solutions(
            error_hash,
            project_name,
            limit=5,
            error_message=error_message,
        )
        
        solution_data = None
        if solutions:
            # Return the best solution
            best = solutions[0]
            solution_data = {
                "id": best.get("id"),
                "solution": best.get("solution"),
                "created_at": best.get("created_at").isoformat() if best.get("created_at") else None,
                "created_by": best.get("created_by"),
                "version": best.get("version"),
                "confidence_score": best.get("confidence_score"),
                "usage_count": best.get("usage_count"),
            }
        
        solution_elapsed = (time.perf_counter() - solution_start) * 1000
        print(f"[PERF] [req:{request_id}] === SOLUTION REQUEST END === {solution_elapsed:.3f}ms")
        
        return jsonify({"solution": solution_data})
        
    except Exception as e:
        import traceback as _tb
        solution_elapsed = (time.perf_counter() - solution_start) * 1000
        print(f"[PERF] [req:{request_id}] SOLUTION ERROR after {solution_elapsed:.3f}ms: {e}")
        print(_tb.format_exc())
        return jsonify({"solution": None, "error": str(e)}), 500


def get_break_detail_ai(error_hash: str, get_ai_recommendations, query_func, 
                        build_error_hash_candidates, TABLE):
    """
    Separate endpoint for AI recommendations - VERY expensive (LLM calls).
    Should be called lazily by frontend or cached aggressively.
    """
    request_id = g.get("request_id", "unknown")
    ai_start = time.perf_counter()
    print(f"[PERF] [req:{request_id}] === AI REQUEST START === error_hash={error_hash}")
    
    try:
        project_name = (request.args.get('project_name') or '').strip() or None
        
        # Get error message for AI context
        hash_candidates = build_error_hash_candidates(error_hash, None)
        params = []
        conditions = ["row_type = 'log'"]
        if hash_candidates:
            hash_clauses = []
            for candidate in hash_candidates:
                hash_clauses.append("error_hash = %s")
                params.append(candidate)
            conditions.append(f"({' OR '.join(hash_clauses)})")
        if project_name:
            conditions.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        error_rows = query_func(
            f"SELECT error AS error_message FROM {TABLE} "
            f"WHERE {' AND '.join(conditions)} LIMIT 1",
            tuple(params)
        )
        
        error_message = error_rows[0].get("error_message") if error_rows else None
        
        ai_recommendation = get_ai_recommendations(
            error_hash,
            project_name,
            error_message=error_message,
        )
        
        ai_elapsed = (time.perf_counter() - ai_start) * 1000
        print(f"[PERF] [req:{request_id}] === AI REQUEST END === {ai_elapsed:.3f}ms")
        
        return jsonify({"ai_recommendation": ai_recommendation})
        
    except Exception as e:
        import traceback as _tb
        ai_elapsed = (time.perf_counter() - ai_start) * 1000
        print(f"[PERF] [req:{request_id}] AI ERROR after {ai_elapsed:.3f}ms: {e}")
        print(_tb.format_exc())
        return jsonify({"ai_recommendation": None, "error": str(e)}), 500


def get_break_detail_jira(error_hash: str, query_func, build_error_hash_candidates, TABLE):
    """
    Separate endpoint for Jira ticket lookup - can be cached.
    """
    request_id = g.get("request_id", "unknown")
    jira_start = time.perf_counter()
    
    try:
        project_name = (request.args.get('project_name') or '').strip() or None
        hash_candidates = build_error_hash_candidates(error_hash, None)
        
        jt_params = list(hash_candidates) if hash_candidates else [error_hash]
        jt_where = ' OR '.join(["metadata::jsonb->>'error_hash' = %s"] * len(jt_params))
        jt_sql = f"SELECT metadata FROM {TABLE} WHERE row_type = 'jira_ticket' AND ({jt_where})"
        if project_name:
            jt_sql += " AND LOWER(metadata::jsonb->>'project_name') = LOWER(%s)"
            jt_params.append(project_name)
        jt_sql += " ORDER BY created_at DESC LIMIT 1"
        
        jt_rows = query_func(jt_sql, tuple(jt_params))
        jira_ticket = None
        
        if jt_rows:
            raw = jt_rows[0].get('metadata')
            if raw:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    jira_ticket = {
                        'key': parsed.get('jira_key') or parsed.get('key'),
                        'url': parsed.get('jira_url') or parsed.get('url'),
                    }
                except Exception:
                    pass
        
        jira_elapsed = (time.perf_counter() - jira_start) * 1000
        print(f"[PERF] [req:{request_id}] Jira lookup: {jira_elapsed:.3f}ms")
        
        return jsonify({"jira_ticket": jira_ticket})
        
    except Exception as e:
        jira_elapsed = (time.perf_counter() - jira_start) * 1000
        print(f"[PERF] [req:{request_id}] Jira ERROR after {jira_elapsed:.3f}ms: {e}")
        return jsonify({"jira_ticket": None, "error": str(e)}), 500
