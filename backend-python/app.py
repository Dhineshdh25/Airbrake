"""
Flask application — all API routes.
Shared between the Lambda handler (lambda_function.py) and local dev.

Architecture: Single-table design using DSQL table 'projects_data'
  - row_type = 'project'  → project metadata (name, category, is_live)
  - row_type = 'log'      → all logs/errors/results from ALL projects
  - row_type = 'solution' → AI knowledge base (solution versioning)
  - row_type = 'user'     → user accounts
"""

import os
import uuid
import hashlib
import logging
import re
import json
import time
import random
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from flask import Flask, request, jsonify, make_response, g, has_request_context

logger = logging.getLogger(__name__)

try:
    from db import query, execute, execute_returning
except Exception as _db_exc:  # pragma: no cover - import safety
    import traceback as _db_tb_mod
    _db_import_error = _db_exc
    _db_import_tb = _db_tb_mod.format_exc()
    print(f"[app] WARNING: db import failed — using degraded stubs: {type(_db_exc).__name__}: {_db_exc}")
    print(_db_import_tb)

    def query(*args, **kwargs):
        raise RuntimeError(f"Database unavailable — component=db error={type(_db_import_error).__name__}: {_db_import_error}")

    def execute(*args, **kwargs):
        raise RuntimeError(f"Database unavailable — component=db error={type(_db_import_error).__name__}: {_db_import_error}")

    def execute_returning(*args, **kwargs):
        raise RuntimeError(f"Database unavailable — component=db error={type(_db_import_error).__name__}: {_db_import_error}")
else:
    _db_import_error = None
    _db_import_tb = ""

try:
    from ai.diagnostics import get_ai_diagnostics
except Exception as exc:  # pragma: no cover - import safety
    def get_ai_diagnostics():
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

_error_matching_import_err = None
try:
    from ai.error_matching import build_error_hash_candidates, build_lookup_hash_candidates, derive_error_hash, normalize_project_name
except Exception as exc:  # pragma: no cover - import safety
    _error_matching_import_err = exc
    print(f"[app] WARNING: ai.error_matching import failed: {type(exc).__name__}: {exc}")
    
    def derive_error_hash(error_text, error_detail=None):
        return hashlib.md5((error_detail or error_text or '').strip().lower().encode('utf-8')).hexdigest()

    def normalize_project_name(project_name):
        return (project_name or '').strip().lower().replace('_', ' ')
    
    def build_error_hash_candidates(error_text, error_detail=None):
        """Fallback stub if ai.error_matching import fails."""
        if isinstance(error_text, str) and re.fullmatch(r"[0-9a-fA-F]{32}", error_text.strip()):
            return [error_text.strip().lower()]
        primary = derive_error_hash(error_text, error_detail)
        return [primary] if primary else []

# ── Stack trace parsing (embedded below) ──────────────────────────────────────
# Parser is embedded directly in this file - no separate import needed
STACKTRACE_PARSER_AVAILABLE = True

# Stack trace parser — extracts file paths, line numbers, and source code context
class StackFrame:
    """Represents a single frame in a stack trace with source code context."""
    
    def __init__(
        self,
        file_path: str,
        line_number: int,
        function_name: Optional[str] = None,
        code_line: Optional[str] = None,
        column: Optional[int] = None,
    ):
        self.file_path = file_path
        self.line_number = line_number
        self.function_name = function_name
        self.code_line = code_line
        self.column = column
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "function_name": self.function_name,
            "code_line": self.code_line,
            "column": self.column,
        }


class ParsedStackTrace:
    """Container for parsed stack trace with structured frames."""
    
    def __init__(self, frames: List[StackFrame], raw_trace: str):
        self.frames = frames
        self.raw_trace = raw_trace
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "frames": [f.to_dict() for f in self.frames],
            "raw_trace": self.raw_trace,
        }


def parse_python_traceback(traceback_text: str) -> List[StackFrame]:
    """Parse Python traceback format."""
    frames = []
    file_pattern = re.compile(
        r'^\s*File\s+"([^"]+)",\s+line\s+(\d+)(?:,\s+in\s+(.+))?$',
        re.MULTILINE
    )
    
    lines = traceback_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i]
        match = file_pattern.match(line)
        
        if match:
            file_path = match.group(1)
            line_number = int(match.group(2))
            function_name = match.group(3) if match.group(3) else None
            
            code_line = None
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                stripped = next_line.strip()
                if stripped and not stripped.startswith('File ') and not re.match(r'^[A-Z]\w+Error:', stripped):
                    code_line = stripped
                    
            column = None
            if i + 2 < len(lines) and '^' in lines[i + 2]:
                caret_line = lines[i + 2]
                column = caret_line.index('^') if '^' in caret_line else None
            
            frames.append(StackFrame(
                file_path=file_path,
                line_number=line_number,
                function_name=function_name,
                code_line=code_line,
                column=column,
            ))
        
        i += 1
    
    return frames


def parse_javascript_stacktrace(stacktrace_text: str) -> List[StackFrame]:
    """Parse JavaScript/Node.js V8 stack trace format."""
    frames = []
    
    patterns = [
        re.compile(r'^\s*at\s+([^\s(]+)\s+\(([^:]+):(\d+):(\d+)\)'),
        re.compile(r'^\s*at\s+([^:]+):(\d+):(\d+)'),
        re.compile(r'^\s*at\s+([^:]+):(\d+)'),
    ]
    
    for line in stacktrace_text.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        match = patterns[0].match(line)
        if match:
            function_name = match.group(1)
            file_path = match.group(2)
            line_number = int(match.group(3))
            column = int(match.group(4)) if match.lastindex >= 4 else None
            
            frames.append(StackFrame(
                file_path=file_path,
                line_number=line_number,
                function_name=function_name,
                column=column,
            ))
            continue
        
        match = patterns[1].match(line)
        if match:
            file_path = match.group(1)
            line_number = int(match.group(2))
            column = int(match.group(3)) if match.lastindex >= 3 else None
            
            frames.append(StackFrame(
                file_path=file_path,
                line_number=line_number,
                column=column,
            ))
            continue
        
        match = patterns[2].match(line)
        if match:
            file_path = match.group(1)
            line_number = int(match.group(2))
            
            frames.append(StackFrame(
                file_path=file_path,
                line_number=line_number,
            ))
    
    return frames


def parse_generic_error(error_text: str) -> List[StackFrame]:
    """Parse generic error messages that mention file paths and line numbers."""
    frames = []
    lines = error_text.split('\n')
    
    patterns = [
        re.compile(r'\(([^,)]+),\s+line\s+(\d+)\)'),
        re.compile(r'([a-zA-Z0-9_./\\-]+\.[a-zA-Z]{1,5}):(\d+)(?::(\d+))?'),
        re.compile(r'(?:at\s+)?line\s+(\d+)', re.IGNORECASE),
    ]
    
    for idx, line in enumerate(lines):
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                groups = match.groups()
                
                if len(groups) >= 2 and groups[0] and groups[1]:
                    file_path = groups[0]
                    line_number = int(groups[1])
                    column = int(groups[2]) if len(groups) > 2 and groups[2] else None
                    
                    code_line = None
                    if idx + 1 < len(lines):
                        next_line = lines[idx + 1].strip()
                        if next_line and not re.match(r'^(File|at|Traceback)', next_line):
                            code_line = next_line
                    
                    if idx + 2 < len(lines) and lines[idx + 2].strip().startswith('^'):
                        if idx + 1 < len(lines):
                            code_line = lines[idx + 1].strip()
                    
                    frames.append(StackFrame(
                        file_path=file_path,
                        line_number=line_number,
                        code_line=code_line,
                        column=column,
                    ))
                    break
                elif len(groups) == 1 and groups[0]:
                    line_number = int(groups[0])
                    code_line = None
                    if idx + 1 < len(lines):
                        next_line = lines[idx + 1].strip()
                        if next_line and not re.match(r'^(File|at|Traceback|Error)', next_line):
                            code_line = next_line
                    
                    frames.append(StackFrame(
                        file_path="<unknown>",
                        line_number=line_number,
                        code_line=code_line,
                    ))
                    break
    
    return frames


def parse_stacktrace(error_text: str, error_detail: Optional[str] = None) -> ParsedStackTrace:
    """Parse stack trace from error text and detail, extracting structured frame information."""
    source = (error_detail or error_text or '').strip()
    
    if not source:
        return ParsedStackTrace(frames=[], raw_trace='')
    
    frames = []
    
    if 'Traceback' in source or 'File "' in source:
        frames = parse_python_traceback(source)
    
    if not frames and (' at ' in source or 'at Object.' in source):
        frames = parse_javascript_stacktrace(source)
    
    if not frames:
        frames = parse_generic_error(source)
    
    return ParsedStackTrace(frames=frames, raw_trace=source)


def enhance_frame_with_source(frame: StackFrame, max_context_lines: int = 3) -> StackFrame:
    """Attempt to read source code from the file system for a given frame."""
    import os
    
    if frame.code_line:
        return frame
    
    try:
        file_path = frame.file_path
        
        if file_path in ('<unknown>', '<string>', '<stdin>'):
            return frame
        
        if not os.path.isfile(file_path):
            return frame
        
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            
            if 1 <= frame.line_number <= len(lines):
                code_line = lines[frame.line_number - 1].rstrip()
                frame.code_line = code_line
    
    except Exception as e:
        print(f"[StackTraceParser] Could not read source for {frame.file_path}:{frame.line_number}: {e}")
    
    return frame


def parse_and_enhance_stacktrace(
    error_text: str,
    error_detail: Optional[str] = None,
    enhance_with_source: bool = True,
) -> Dict[str, Any]:
    """Parse stack trace and optionally enhance with source code context."""
    parsed = parse_stacktrace(error_text, error_detail)
    
    if enhance_with_source:
        parsed.frames = [enhance_frame_with_source(frame) for frame in parsed.frames]
    
    return parsed.to_dict()

# ── Knowledge base functions (DB only, no AI runtime required) ────────────────
# These are always imported directly — they handle AI runtime failures internally.
KB_AVAILABLE = False
_kb_import_err = None          # always defined — stubs reference this safely
_kb_import_tb  = ""

try:
    from ai.knowledge_base import (
        delete_solution_version,
        get_solution_versions,
        get_top_solutions,
        increment_usage,
        insert_solution,
    )
    KB_AVAILABLE = True
except Exception as _e:
    import traceback as _tb_mod
    _kb_import_err = _e
    _kb_import_tb  = _tb_mod.format_exc()
    print(f"[app] CRITICAL: knowledge_base import failed — {type(_e).__name__}: {_e}")
    print(_kb_import_tb)

    def insert_solution(*a, **kw):
        raise RuntimeError(
            f"Knowledge Base unavailable — {type(_kb_import_err).__name__}: {_kb_import_err}"
        )
    def increment_usage(*a, **kw):
        raise RuntimeError(
            f"Knowledge Base unavailable — {type(_kb_import_err).__name__}: {_kb_import_err}"
        )
    def get_top_solutions(*a, **kw): return [], 0
    def get_solution_versions(*a, **kw): return []
    def delete_solution_version(*a, **kw): return 0

# ── AI recommendation (requires Bedrock/LLM at runtime, gracefully disabled) ───
AI_RECOMMENDATIONS_AVAILABLE = False
try:
    from ai.recommendations import get_ai_recommendations
    AI_RECOMMENDATIONS_AVAILABLE = True
except Exception as exc:
    _ai_import_err = exc
    print(f"[app] WARNING: AI recommendations import failed — recommendations disabled: {_ai_import_err}")
    def get_ai_recommendations(*a, **kw):
        return {"recommendation": None, "solutions": [], "error": str(_ai_import_err)}

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.before_request
def attach_request_context():
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.request_id = request_id
    g.request_started_at = time.monotonic()
    print(f"[req:{request_id}] {request.method} {request.path}")


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    import traceback as _tb_mod
    tb_str = _tb_mod.format_exc()
    print(f"[app] Unhandled exception — {type(exc).__name__}: {exc}")
    print(tb_str)
    return jsonify({
        "error": "Internal server error",
        "exception": type(exc).__name__,
        "message": str(exc),
        "traceback": tb_str,
    }), 500

# The single DSQL table used for ALL data
TABLE = "projects_data"
DEBUG_BREAK_DETAIL = str(os.getenv("DEBUG_BREAK_DETAIL", "true")).strip().lower() in ("1", "true", "yes", "on")


class _RequestIdFilter(logging.Filter):
    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, "request_id", "n/a")
        else:
            record.request_id = "n/a"
        return True


def _configure_debug_logging() -> None:
    if not DEBUG_BREAK_DETAIL:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    handler_exists = any(
        isinstance(h, logging.StreamHandler) for h in root_logger.handlers
    )
    if not handler_exists:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("[req:%(request_id)s] %(message)s")
        )
        handler.addFilter(_RequestIdFilter())
        root_logger.addHandler(handler)


_configure_debug_logging()

# ── CORS ──────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = {
    "http://airbrake.s3-website-us-east-1.amazonaws.com",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:3003",
    "http://localhost:3004",
    "http://localhost:3005",
}


#new version check
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    allow_origin = origin if origin in ALLOWED_ORIGINS else "*"
    response.headers["Access-Control-Allow-Origin"] = allow_origin
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
    response.headers["Access-Control-Max-Age"] = "86400"
    if origin in ALLOWED_ORIGINS:
        response.headers["Vary"] = "Origin"
    if hasattr(g, "request_started_at"):
        elapsed_ms = (time.monotonic() - g.request_started_at) * 1000
        print(f"[req:{getattr(g, 'request_id', 'n/a')}] completed status={response.status_code} elapsed_ms={elapsed_ms:.2f}")
    return response


@app.route("/api/<path:p>", methods=["OPTIONS"])
@app.route("/api/", methods=["OPTIONS"])
def options_handler(p=""):
    return make_response("", 204)


# ── Auth helpers ──────────────────────────────────────────────────────────────
DEV_SESSIONS = {
    "dev-token-admin":     {"userId": "dev-admin",     "role": "admin"},
    "dev-token-developer": {"userId": "dev-developer", "role": "developer"},
    "dev-token-viewer":    {"userId": "dev-viewer",    "role": "viewer"},
}


def get_session():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return DEV_SESSIONS.get(token)
    return None


def require_role(*roles):
    """Return (session, error_response). If error_response is not None, return it."""
    session = get_session()
    if not session:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    if session["role"] not in roles:
        return None, (jsonify({"error": "Forbidden"}), 403)
    return session, None


# ── Serialization helper ──────────────────────────────────────────────────────
import decimal as _decimal


def _safe_value(v):
    """Convert non-JSON-serializable DB values to safe Python primitives."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, _decimal.Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, dict)):
        return v
    return str(v)


def serialize_row(row):
    """Convert DB row values to JSON-serializable Python primitives."""
    return {k: _safe_value(v) for k, v in row.items()}


def serialize_rows(rows):
    return [serialize_row(r) for r in rows]


def _resolve_project_name(project_name):
    if not project_name:
        return None
    candidate = str(project_name).strip()
    if not candidate:
        return None
    rows = query(
        f"SELECT project_name AS name FROM {TABLE} WHERE row_type = 'project' ORDER BY project_name"
    )
    for row in rows:
        if normalize_project_name(row.get("name")) == normalize_project_name(candidate):
            return row.get("name")
    return candidate


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})


@app.route("/api/debug/project-tables")
def debug_project_tables():
    """Debug endpoint — lists all projects from project_data."""
    rows = query(
        f"SELECT project_name AS name FROM {TABLE} WHERE row_type = 'project' ORDER BY project_name"
    )
    names = [r["name"] for r in rows]
    return jsonify({"tables": names, "count": len(names)})


@app.route("/api/debug/columns")
def debug_columns():
    """Debug endpoint — lists all columns in projects_data."""
    rows = query("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'projects_data'
        ORDER BY ordinal_position
    """)
    return jsonify({"columns": [r["column_name"] for r in rows], "count": len(rows)})


@app.route("/api/debug/kb-status")
def debug_kb_status():
    """Debug endpoint — shows Knowledge Base and AI import status.
    Visible directly in browser: GET /api/debug/kb-status
    """
    return jsonify({
        "kb_available": KB_AVAILABLE,
        "ai_recommendations_available": AI_RECOMMENDATIONS_AVAILABLE,
        "kb_import_error": str(_kb_import_err) if _kb_import_err else None,
        "kb_import_traceback": _kb_import_tb if _kb_import_tb else None,
        "db_import_error": str(_db_import_error) if _db_import_error else None,
        "db_import_traceback": _db_import_tb if _db_import_tb else None,
        "ai_health": get_ai_diagnostics(),
    })


@app.route("/api/debug/ai-health")
def debug_ai_health():
    """Lightweight diagnostic endpoint for Bedrock, Pinecone, Aurora, and imports."""
    try:
        return jsonify(get_ai_diagnostics())
    except Exception as exc:
        import traceback as _tb_mod
        return jsonify({
            "status": "error",
            "bedrock": {"connected": False, "model": None, "embedding_dimension": None},
            "pinecone": {"connected": False, "index": None, "namespace": None, "record_count": None, "last_error": f"{type(exc).__name__}: {exc}"},
            "aurora": {"connected": False},
            "environment": {"region": None, "embedding_model": None, "nova_model": None, "pinecone_index": None},
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": _tb_mod.format_exc(),
        })


@app.route("/api/debug/nova-direct")
def debug_nova_direct():
    events = []
    try:
        import traceback as _tb_mod
        from ai import bedrock_llm

        events.append({"stage": "starting"})
        events.append({"stage": "import_bedrock_wrapper"})

        client = bedrock_llm._get_runtime_client()
        events.append({"stage": "client_initialized"})

        model_id = bedrock_llm._get_nova_model_id()
        events.append({"stage": "model_identified", "model_id": model_id})

        prompt = (
            "You are analyzing application errors for an automated error-monitoring system.\n\n"
            "Below are errors that may be different in wording but represent the same underlying problem.\n\n"
            "Errors:\n\n"
            "1. \"400: Input file does not exist or is not a file\"\n"
            "2. \"400: Input file is empty\"\n"
            "3. \"400: Unable to read the uploaded file\"\n"
            "4. \"FileNotFoundError: requested input document could not be located\"\n"
            "5. \"Permission denied while accessing input file\"\n"
            "6. \"JSONDecodeError: Invalid JSON payload\"\n"
            "7. \"ValueError: Malformed request body\"\n"
            "8. \"400: Request payload has an invalid format\"\n"
            "9. \"TimeoutError: Database connection timed out\"\n"
            "10. \"Database connection could not be established within the timeout period\"\n"
            "11. \"Connection refused by PostgreSQL server\"\n"
            "12. \"Authentication failed for database user\"\n\n"
            "Your task is NOT to simply repeat the error messages.\n\n"
            "Perform high-level semantic analysis:\n"
            "1. Identify which errors belong to the same underlying problem/domain.\n"
            "2. Group semantically related errors together even when their exact wording is different.\n"
            "3. Do NOT group errors merely because they have the same HTTP status code.\n"
            "4. Give each group a concise, generalized group name that describes the underlying problem rather than copying an error message.\n"
            "5. The group name should be useful to a developer looking at an error dashboard.\n\n"
            "For each error, return:\n"
            "- original_error\n"
            "- group_name\n"
            "- reason_for_grouping\n\n"
            "Also identify errors that should NOT be grouped together and explain why.\n\n"
            "Finally, explain the general rule you used to determine whether two errors are semantically related.\n\n"
            "Do not rely on exact string matching, error hashes, or HTTP status codes. The goal is to test whether you can understand the underlying meaning of different error messages and derive meaningful generalized categories."
        )
        body = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "maxTokens": 512,
            "temperature": 0.0,
        }
        events.append({"stage": "request_constructed", "request_payload": body})

        events.append({"stage": "invoking_bedrock"})
        response = client.invoke_model(modelId=model_id, body=json.dumps(body))
        events.append({"stage": "response_received", "response_keys": list(response.keys())})

        raw_body = response.get("body")
        if raw_body is None:
            events.append({"stage": "body_missing"})
            raise RuntimeError("Bedrock invoke_model returned no body")

        if isinstance(raw_body, (bytes, bytearray)):
            raw_bytes = bytes(raw_body)
        elif hasattr(raw_body, "read"):
            raw_bytes = raw_body.read()
        else:
            raw_bytes = str(raw_body).encode("utf-8")

        events.append({"stage": "body_decoded"})
        try:
            body_text = raw_bytes.decode("utf-8")
        except Exception as exc:
            events.append({
                "stage": "body_decode_failed",
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "traceback": _tb_mod.format_exc(),
            })
            raise

        events.append({"stage": "body_text_extracted", "body_text": body_text})
        events.append({"stage": "parsing_response"})
        try:
            payload = json.loads(body_text or "{}")
        except Exception as exc:
            events.append({
                "stage": "json_parse_failed",
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "traceback": _tb_mod.format_exc(),
            })
            raise

        parsed_text = bedrock_llm._extract_nova_text(payload)
        events.append({"stage": "parsed_response", "parsed_text": parsed_text})

        result = {
            "status": "success" if parsed_text.strip() == "NOVA_TEST_SUCCESS" else "failed",
            "model_id": model_id,
            "request_payload": body,
            "response_metadata": {
                "keys": list(response.keys()),
                "response_metadata": response.get("ResponseMetadata"),
            },
            "body_text": body_text,
            "payload": payload,
            "parsed_text": parsed_text,
            "events": events,
        }

        if parsed_text.strip() == "NOVA_TEST_SUCCESS":
            events.append({"stage": "success"})
            result["status"] = "success"
            return jsonify(result)

        events.append({"stage": "unexpected_text"})
        result["status"] = "failed"
        return jsonify(result), 502
    except Exception as exc:
        import traceback as _tb_mod
        tb_str = _tb_mod.format_exc()
        events.append({
            "stage": "exception",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": tb_str,
        })
        return jsonify({
            "status": "error",
            "error": str(exc),
            "exception_type": type(exc).__name__,
            "traceback": tb_str,
            "events": events,
        }), 500


# ═══════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/projects")
def list_projects():
    category = request.args.get("category")
    try:
        if category:
            rows = query(
                f"SELECT id, project_name AS name, category FROM {TABLE} "
                f"WHERE row_type = 'project' AND category = %s ORDER BY project_name",
                (category,),
            )
        else:
            rows = query(
                f"SELECT id, project_name AS name, category FROM {TABLE} "
                f"WHERE row_type = 'project' ORDER BY project_name"
            )
        return jsonify(serialize_rows(rows))
    except Exception as e:
        print(f"[Projects] error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects", methods=["POST"])
def create_project():
    """
    POST /api/projects
    Register a new project so it appears in AI Services.

    Body:
      {
        "name":     "my_new_project",   ← required
        "category": "Production",       ← optional, defaults to 'Production'
        "is_live":  true                ← optional, defaults to true
      }

    Returns the created project row.
    If the project already exists, returns the existing row.
    """
    body = request.get_json() or {}
    name = str(body.get("name") or body.get("project_name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    category = str(body.get("category") or "Production").strip()
    is_live  = body.get("is_live", True)
    if not isinstance(is_live, bool):
        is_live = True

    try:
        # Return existing project if it already exists
        existing = query(
            f"SELECT id, project_name AS name, category, is_live FROM {TABLE} "
            f"WHERE row_type = 'project' AND LOWER(project_name) = LOWER(%s)",
            (name,),
        )
        if existing:
            return jsonify(serialize_row(existing[0])), 200

        # Insert new project row
        row = execute_returning(
            f"INSERT INTO {TABLE} (id, row_type, project_name, category, is_live, created_at) "
            f"VALUES (%s, 'project', %s, %s, %s, NOW()) RETURNING id, project_name AS name, category, is_live",
            (str(uuid.uuid4()), name, category, is_live),
        )
        print(f"[Projects] New project registered: '{name}' category='{category}'")
        return jsonify(serialize_row(row)), 201
    except Exception as e:
        print(f"[Projects] create error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects/live")
def list_live_projects():
    try:
        rows = query(
            f"SELECT id, project_name AS name, category, is_live FROM {TABLE} "
            f"WHERE row_type = 'project' AND is_live = true ORDER BY project_name"
        )
        return jsonify(serialize_rows(rows))
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects/<path:name>/logs")
def project_logs(name):
    project_name = name
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    offset = (page - 1) * limit
    
    # Date filter parameters
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    
    print(f"[DEBUG] Date filter params - from: {from_date}, to: {to_date}")
    
    try:
        # Check if project exists
        proj = query(
            f"SELECT project_name AS name FROM {TABLE} "
            f"WHERE row_type = 'project' AND LOWER(project_name) = LOWER(%s)",
            (project_name,),
        )
        if not proj:
            return jsonify({
                "exists": False, "tableName": project_name.replace(" ", "_"),
                "total": 0, "filesProcessed": 0, "success": 0, "failure": 0, "resolved": 0,
                "totalCost": None, "errors": [], "logs": [],
                "pagination": {
                    "currentPage": 1, "totalPages": 0, "totalRecords": 0,
                    "limit": limit, "hasNextPage": False, "hasPreviousPage": False
                }
            })

        # Build date filter WHERE clause
        date_filter = ""
        count_params = [project_name]
        query_params = [project_name]
        
        if from_date:
            # Convert ISO string to timestamp for comparison
            # Remove timezone info if present and convert to date
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            date_filter += " AND DATE(timestamp) >= %s"
            count_params.append(from_date_clean)
            query_params.append(from_date_clean)
            print(f"[DEBUG] Adding from_date filter: DATE(timestamp) >= {from_date_clean}")
        if to_date:
            # Convert ISO string to timestamp for comparison
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            date_filter += " AND DATE(timestamp) <= %s"
            count_params.append(to_date_clean)
            query_params.append(to_date_clean)
            print(f"[DEBUG] Adding to_date filter: DATE(timestamp) <= {to_date_clean}")
        
        print(f"[DEBUG] Final date_filter clause: {date_filter}")
        print(f"[DEBUG] Count params: {count_params}")

        # Get total count first with date filter
        count_query = (
            f"SELECT COUNT(*) as total FROM {TABLE} "
            f"WHERE row_type = 'log' AND LOWER(project_name) = LOWER(%s){date_filter}"
        )
        print(f"[DEBUG] Count query: {count_query}")
        count_result = query(count_query, tuple(count_params))
        total_records = int(count_result[0].get("total", 0)) if count_result else 0
        print(f"[DEBUG] Total records after filter: {total_records}")
        total_pages = (total_records + limit - 1) // limit if limit > 0 else 0

        # Add limit and offset to query params
        query_params.extend([limit, offset])

        # Fetch paginated logs with date filter
        logs_query = (
            f"SELECT file_name, timestamp, success_count, failure_count, error, "
            f"llm_usage, input_tokens, output_tokens, calculated_cost, word_count, file_type, "
            f"error_status, resolved_at, reopened_at "
            f"FROM {TABLE} WHERE row_type = 'log' AND LOWER(project_name) = LOWER(%s){date_filter} "
            f"ORDER BY timestamp DESC LIMIT %s OFFSET %s"
        )
        print(f"[DEBUG] Logs query: {logs_query}")
        logs = query(logs_query, tuple(query_params))

        # Get TOTAL counts across all pages (not just current page)
        # Success: files with no error or empty error
        success_query = (
            f"SELECT COUNT(*) as total FROM {TABLE} "
            f"WHERE row_type = 'log' AND LOWER(project_name) = LOWER(%s){date_filter} "
            f"AND (error IS NULL OR error = '')"
        )
        success_result = query(success_query, tuple(count_params))
        success = int(success_result[0].get("total", 0)) if success_result else 0
        
        # Failure: files with errors that are not resolved
        failure_query = (
            f"SELECT COUNT(*) as total FROM {TABLE} "
            f"WHERE row_type = 'log' AND LOWER(project_name) = LOWER(%s){date_filter} "
            f"AND error IS NOT NULL AND error != '' AND (error_status IS NULL OR error_status != 'resolved')"
        )
        failure_result = query(failure_query, tuple(count_params))
        failure = int(failure_result[0].get("total", 0)) if failure_result else 0
        
        # Resolved: files with errors that have been resolved
        resolved_query = (
            f"SELECT COUNT(*) as total FROM {TABLE} "
            f"WHERE row_type = 'log' AND LOWER(project_name) = LOWER(%s){date_filter} "
            f"AND error IS NOT NULL AND error != '' AND error_status = 'resolved'"
        )
        resolved_result = query(resolved_query, tuple(count_params))
        resolved = int(resolved_result[0].get("total", 0)) if resolved_result else 0

        # Separate logs by status for the current page (for display purposes)
        resolved_logs = [r for r in logs if r.get("error") and r.get("error") != "" and r.get("error_status") == "resolved"]
        active_logs = [r for r in logs if r.get("error") and r.get("error") != "" and r.get("error_status") != "resolved"]
        successful_logs = [r for r in logs if not r.get("error") or r.get("error") == ""]
        
        print(f"[DEBUG] Project: {project_name}, Page: {page}/{total_pages}")
        print(f"  - Files processed (total): {total_records}")
        print(f"  - Success (total): {success}")
        print(f"  - Active errors (total): {failure}")
        print(f"  - Resolved errors (total): {resolved}")
        print(f"  - Success (current page): {len(successful_logs)}")
        print(f"  - Active errors (current page): {len(active_logs)}")
        print(f"  - Resolved errors (current page): {len(resolved_logs)}")

        raw_cost = sum(float(r.get("calculated_cost") or 0) for r in logs)
        total_cost = f"${raw_cost:.4f}" if raw_cost > 0 else None
        
        errors = [
            {"timestamp": str(r["timestamp"]), "message": r["error"]}
            for r in active_logs
        ]

        # Create visible logs with isResolved flag
        visible_logs = [
            {**r, "isResolved": r.get("error") and r.get("error") != "" and r.get("error_status") == "resolved"}
            for r in logs
        ]
        
        visible_logs = serialize_rows(visible_logs)
        errors = serialize_rows(errors)
        
        date_info = f", From: {from_date}" if from_date else ""
        date_info += f", To: {to_date}" if to_date else ""
        print(f"[DEBUG] Project: {project_name}, Page: {page}/{total_pages}{date_info}")
        print(f"  - Total records: {total_records}")
        print(f"  - Files with active errors (this page): {len(active_logs)}")
        print(f"  - Files with resolved errors (this page): {len(resolved_logs)}")
        
        return jsonify({
            "exists": True, "tableName": project_name.replace(" ", "_"),
            "total": total_records, "filesProcessed": total_records,
            "success": success, "failure": failure, "resolved": resolved,
            "totalCost": total_cost, "errors": errors, "logs": visible_logs,
            "pagination": {
                "currentPage": page,
                "totalPages": total_pages,
                "totalRecords": total_records,
                "limit": limit,
                "hasNextPage": page < total_pages,
                "hasPreviousPage": page > 1
            }
        })
    except Exception as e:
        import traceback as _tb
        tb_str = _tb.format_exc()
        request_id = g.get("request_id", "unknown")
        print(f"[req:{request_id}] [Projects:logs] ERROR: {type(e).__name__}: {e}")
        print(f"[req:{request_id}] [Projects:logs] Traceback:\n{tb_str}")
        return jsonify({
            "success": False,
            "exists": False,
            "error": "Failed to load logs",
            "data": [],
            "trace_id": request_id,
            "fallback": True,
        }), 200


@app.route("/api/projects/<path:name>/errors", methods=["POST"])
def upsert_project_error(name):
    project_name = name
    try:
        # Verify project exists
        actual_name = _resolve_project_name(project_name)
        if not actual_name:
            return jsonify({"error": f"No project found: {project_name}"}), 404

        body = request.get_json() or {}
        file_name = str(body.get("file_name", ""))
        error_detail = (body.get("error_detail") or "").strip() or None
        short_error = str(body.get("error", "")).strip()

        if error_detail:
            lines = [l.strip() for l in error_detail.split("\n") if l.strip()]
            if lines:
                derived = lines[-1].split(":")[0].strip()
                if derived:
                    short_error = derived

        if not short_error:
            return jsonify({"error": "error or error_detail is required"}), 400

        error_hash = derive_error_hash(short_error, error_detail)

        # Try to update existing row with same error_hash
        updated = execute_returning(
            f"UPDATE {TABLE} SET failure_count = failure_count + 1, file_name = %s, "
            f"timestamp = NOW(), error_detail = COALESCE(%s, error_detail), "
            f"error_status = CASE WHEN error_status = 'resolved' THEN 'reopened' ELSE error_status END, "
            f"reopened_at = CASE WHEN error_status = 'resolved' THEN NOW() ELSE reopened_at END, "
            f"resolved_at = CASE WHEN error_status = 'resolved' THEN NULL ELSE resolved_at END "
            f"WHERE row_type = 'log' AND error_hash = %s AND LOWER(project_name) = LOWER(%s) "
            f"RETURNING id, error_status, failure_count",
            (file_name, error_detail, error_hash, actual_name),
        )
        if updated:
            action = "reopened" if updated["error_status"] == "reopened" else "updated"
            return jsonify({"action": action, "error_status": updated["error_status"],
                            "failure_count": updated["failure_count"]})

        # Insert new error row
        inserted = execute_returning(
            f"INSERT INTO {TABLE} (id, row_type, project_name, file_name, timestamp, "
            f"success_count, failure_count, error, error_detail, error_hash, error_status) "
            f"VALUES (%s, 'log', %s, %s, NOW(), 0, 1, %s, %s, %s, 'open') "
            f"RETURNING id, error_status, failure_count",
            (str(uuid.uuid4()), actual_name, file_name, short_error, error_detail, error_hash),
        )
        return jsonify({"action": "inserted", "error_status": inserted["error_status"],
                        "failure_count": inserted["failure_count"]})
    except Exception as e:
        print(f"[Projects] upsert error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects/<path:name>/errors/<hash>/resolve", methods=["PATCH"])
def resolve_project_error(name, hash):
    try:
        actual_name = _resolve_project_name(name)
        if not actual_name:
            return jsonify({"error": f"No project found: {name}"}), 404
        execute(
            f"UPDATE {TABLE} SET error_status = %s, resolved_at = NOW(), "
            f"reopened_at = NULL WHERE row_type = 'log' AND error_hash = %s "
            f"AND LOWER(project_name) = LOWER(%s)",
            ("resolved", hash, actual_name),
        )
        return jsonify({"action": "resolved"})
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects/<path:name>/live", methods=["PATCH"])
def toggle_project_live(name):
    body = request.get_json() or {}
    is_live = body.get("is_live")
    if not isinstance(is_live, bool):
        return jsonify({"error": "Body must contain { is_live: true | false }"}), 400
    try:
        row = execute_returning(
            f"UPDATE {TABLE} SET is_live = %s "
            f"WHERE row_type = 'project' AND LOWER(project_name) = LOWER(%s) "
            f"RETURNING id, project_name AS name, category, is_live",
            (is_live, name),
        )
        if not row:
            return jsonify({"error": f"Project not found: {name}"}), 404
        return jsonify(serialize_row(row))
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# INGEST
# ═══════════════════════════════════════════════════════════════════════════════

def _insert_result(project_name, file_name, error, error_detail,
                   error_hash, error_status, success_count, failure_count,
                   word_count, file_type, input_tokens, output_tokens,
                   calculated_cost, llm_usage):
    """Insert a log row into project_data and return it."""
    row_id = str(uuid.uuid4())
    return execute_returning(
        f"INSERT INTO {TABLE} ("
        f"id, row_type, project_name, file_name, timestamp, "
        f"success_count, failure_count, error, error_detail, error_hash, error_status, "
        f"word_count, file_type, input_tokens, output_tokens, calculated_cost, llm_usage"
        f") VALUES (%s,'log',%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        f"RETURNING id, project_name, file_name, error, error_detail, "
        f"error_hash, error_status, success_count, failure_count, timestamp",
        (row_id, project_name, file_name,
         success_count, failure_count, error, error_detail,
         error_hash, error_status,
         word_count, file_type, input_tokens, output_tokens,
         calculated_cost, llm_usage),
    )


def _to_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _to_float(value):
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _lookup_usage_field(source, keys):
    if not isinstance(source, dict):
        return None
    for key in keys:
        if key in source:
            return source[key]
    return None


def _normalize_usage(source):
    if not isinstance(source, dict):
        return {}

    data = {}
    # Token counts
    data["input_tokens"] = _to_int(_lookup_usage_field(source, ["prompt_tokens", "input_tokens", "input", "input_token_count", "tokens_in", "promptTokenCount"]))
    data["output_tokens"] = _to_int(_lookup_usage_field(source, ["completion_tokens", "output_tokens", "output", "output_token_count", "tokens_out", "completionTokenCount"]))
    data["calculated_cost"] = _to_float(_lookup_usage_field(source, ["cost", "total_cost", "usd_cost", "price", "estimated_cost", "currency_cost"]))
    data["llm_usage"] = source.get("llm_usage") or source.get("provider") or source.get("model")
    return data


def _extract_usage(body):
    if not isinstance(body, dict):
        return {}

    extracted = {
        "input_tokens": None,
        "output_tokens": None,
        "calculated_cost": None,
        "llm_usage": None,
    }

    # Direct values first
    extracted["input_tokens"] = _to_int(body.get("input_tokens"))
    extracted["output_tokens"] = _to_int(body.get("output_tokens"))
    extracted["calculated_cost"] = _to_float(body.get("calculated_cost"))
    extracted["llm_usage"] = body.get("llm_usage") or body.get("model") or body.get("provider")

    candidates = []
    if isinstance(body.get("usage"), dict):
        candidates.append(body["usage"])
    elif isinstance(body.get("usage"), str):
        try:
            parsed = json.loads(body["usage"])
            if isinstance(parsed, dict):
                candidates.append(parsed)
        except Exception:
            pass

    for key in ("response", "result", "data", "metadata", "response_metadata", "output", "completion"):
        value = body.get(key)
        if isinstance(value, dict):
            candidates.append(value)
            if isinstance(value.get("usage"), dict):
                candidates.append(value["usage"])

    for source in candidates:
        if extracted["input_tokens"] is None:
            extracted["input_tokens"] = _normalize_usage(source).get("input_tokens")
        if extracted["output_tokens"] is None:
            extracted["output_tokens"] = _normalize_usage(source).get("output_tokens")
        if extracted["calculated_cost"] is None:
            extracted["calculated_cost"] = _normalize_usage(source).get("calculated_cost")
        if extracted["llm_usage"] is None:
            extracted["llm_usage"] = _normalize_usage(source).get("llm_usage")

    if extracted["input_tokens"] is None and extracted["output_tokens"] is None:
        total_tokens = _to_int(_lookup_usage_field(body, ["total_tokens", "tokens", "total"]))
        if total_tokens is not None:
            extracted["input_tokens"] = total_tokens

    return extracted


def _parse_optional(body):
    extracted = _extract_usage(body)
    return {
        "file_name":       body.get("file_name") or None,
        "error_detail":    body.get("error_detail") or None,
        "success_count":   body.get("success_count", 0),
        "failure_count":   body.get("failure_count", 1),
        "word_count":      body.get("word_count"),
        "file_type":       body.get("file_type"),
        "input_tokens":    body.get("input_tokens") if body.get("input_tokens") is not None else extracted.get("input_tokens"),
        "output_tokens":   body.get("output_tokens") if body.get("output_tokens") is not None else extracted.get("output_tokens"),
        "calculated_cost": body.get("calculated_cost") if body.get("calculated_cost") is not None else extracted.get("calculated_cost"),
        "llm_usage":       body.get("llm_usage") or extracted.get("llm_usage"),
    }


def _validate_project(project_name):
    """Return actual project name if found. Auto-registers it if it doesn't exist yet."""
    rows = query(
        f"SELECT project_name AS name FROM {TABLE} "
        f"WHERE row_type = 'project' AND LOWER(project_name) = LOWER(%s)",
        (project_name,),
    )
    if rows:
        return rows[0]["name"]

    # Project not found — auto-register it so it appears in AI Services
    print(f"[Projects] Auto-registering new project: '{project_name}'")
    execute_returning(
        f"INSERT INTO {TABLE} (id, row_type, project_name, category, is_live, created_at) "
        f"VALUES (%s, 'project', %s, 'Production', true, NOW()) "
        f"ON CONFLICT DO NOTHING RETURNING project_name",
        (str(uuid.uuid4()), project_name),
    )
    return project_name


def _smart_extract_error_detail(error_text):
    """
    Smart extraction: If error field contains a stack trace, extract it.
    
    Returns: (short_error, full_traceback)
    
    Handles patterns like:
    - "KeyError: 'user_id'\nTraceback (most recent call last)..."
    - "Traceback (most recent call last):\n  File...\nKeyError: 'user_id'"
    - Just "KeyError: 'user_id'" (no traceback)
    """
    if not error_text:
        return error_text, None
    
    # Check for common stack trace patterns
    traceback_indicators = [
        "Traceback (most recent call last)",
        "  File \"",
        "\n  at ",  # JavaScript
        "\n    at ",  # JavaScript with spaces
        "Stack trace:",
        "Call stack:",
    ]
    
    # If no traceback indicators, return as-is
    has_traceback = any(indicator in error_text for indicator in traceback_indicators)
    if not has_traceback:
        return error_text, None
    
    # Split into lines
    lines = error_text.split('\n')
    
    # Try to find where the actual error message is (usually first or last line)
    # Pattern 1: Error message at the end (Python style)
    # "Traceback...\n  File...\nKeyError: 'user_id'"
    if "Traceback" in lines[0]:
        # Last non-empty line is usually the error
        error_message = None
        for line in reversed(lines):
            if line.strip():
                error_message = line.strip()
                break
        return error_message or error_text, error_text
    
    # Pattern 2: Error message at the beginning
    # "KeyError: 'user_id'\nTraceback..."
    first_line = lines[0].strip()
    if first_line and not first_line.startswith(('Traceback', '  File', '  at', 'Stack')):
        return first_line, error_text
    
    # Pattern 3: Can't determine - return full text as both
    return error_text, error_text


@app.route("/api/ingest/error", methods=["POST"])
def ingest_error():
    body = request.get_json() or {}
    project_name = str(body.get("project_name", "")).strip()
    error = str(body.get("error", "")).strip()
    if not project_name:
        return jsonify({"error": "project_name is required"}), 400
    if not error:
        return jsonify({"error": "error is required"}), 400
    if error.startswith("{") and ("workflowId" in error or "workflowStatus" in error):
        return jsonify({"error": "Invalid error value — workflow/system response passed"}), 400

    actual_name = _validate_project(project_name)
    opt = _parse_optional(body)
    
    # ── SMART EXTRACTION: Auto-extract stack trace from error field ──────────
    error_detail = opt.get("error_detail")
    
    if not error_detail:
        # Try to extract stack trace from the error field itself
        short_error, extracted_trace = _smart_extract_error_detail(error)
        if extracted_trace:
            error_detail = extracted_trace
            error = short_error  # Use the short version for the error field
            print(f'[Ingest] 🔧 Auto-extracted stack trace from error field for project="{actual_name}"')
            print(f'[Ingest] ✅ error_detail now populated ({len(error_detail)} chars)')
        else:
            print(f'[Ingest] ⚠️  WARNING: No stack trace found in error field for project="{actual_name}"')
            print(f'[Ingest] ⚠️  Error: "{error[:100]}"')
            print(f'[Ingest] ⚠️  Stack trace parsing will NOT work without error_detail!')
    else:
        print(f'[Ingest] ✅ error_detail received ({len(error_detail)} chars) for project="{actual_name}"')
    
    error_hash = derive_error_hash(error, error_detail)

    try:
        inserted = _insert_result(
            actual_name, opt["file_name"], error, error_detail,
            error_hash, "open",
            opt.get("success_count", 0), opt.get("failure_count", 1),
            opt["word_count"], opt["file_type"], opt["input_tokens"],
            opt["output_tokens"], opt["calculated_cost"], opt["llm_usage"],
        )
        print(f'[Ingest] ❌ Error row → "{actual_name}" | {error}')
        row = serialize_row(inserted)
        # ── Async-style classification: best-effort, never blocks ingest ──────
        try:
            from ai.error_grouper import classify_error as _classify
            _classify(
                log_id        = inserted["id"],
                error_message = error,
                project_name  = actual_name,
                error_detail  = error_detail,
            )
        except Exception as _cexc:
            logger.warning("[Ingest] classify_error failed (non-fatal): %s", _cexc)
        return jsonify({"success": True, "type": "error", **row}), 201
    except Exception as e:
        print(f"[Ingest] error: {e}")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


@app.route("/api/ingest/log", methods=["POST"])
def ingest_log():
    body = request.get_json() or {}
    project_name = str(body.get("project_name", "")).strip()
    if not project_name:
        return jsonify({"error": "project_name is required"}), 400

    actual_name = _validate_project(project_name)
    opt = _parse_optional(body)
    error = str(body.get("error", "")).strip()
    is_workflow = error.startswith("{") and ("workflowId" in error or "workflowStatus" in error)
    is_error = bool(error) and not is_workflow
    
    # ── SMART EXTRACTION: Auto-extract stack trace from error field ──────────
    error_detail = opt.get("error_detail")
    if is_error and not error_detail:
        short_error, extracted_trace = _smart_extract_error_detail(error)
        if extracted_trace:
            error_detail = extracted_trace
            error = short_error
            print(f'[Ingest] 🔧 Auto-extracted stack trace from error field for project="{actual_name}"')

    error_hash = derive_error_hash(error, error_detail) if is_error else None
    success_count = body.get("success_count", 0 if is_error else 1)
    failure_count = body.get("failure_count", 1 if is_error else 0)

    try:
        inserted = _insert_result(
            actual_name, opt["file_name"],
            error if is_error else None, error_detail,
            error_hash, "open" if is_error else None,
            success_count, failure_count,
            opt["word_count"], opt["file_type"], opt["input_tokens"],
            opt["output_tokens"], opt["calculated_cost"], opt["llm_usage"],
        )
        t = "error" if is_error else "success"
        print(f'[Ingest] {"❌" if is_error else "✅"} {t} row → "{actual_name}"')
        if is_error:
            print(f'[Ingest] ❌ error row → "{actual_name}" | {error}')
        row = serialize_row(inserted)
        # ── Classification for error rows — best-effort, never blocks ────────
        if is_error:
            try:
                from ai.error_grouper import classify_error as _classify
                _classify(
                    log_id        = inserted["id"],
                    error_message = error,
                    project_name  = actual_name,
                    error_detail  = error_detail,
                )
            except Exception as _cexc:
                logger.warning("[Ingest] classify_error (log) failed (non-fatal): %s", _cexc)
        return jsonify({"success": True, "type": t, **row}), 201
    except Exception as e:
        print(f"[Ingest] log error: {e}")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


@app.route("/api/ingest/success", methods=["POST"])
def ingest_success():
    body = request.get_json() or {}
    project_name = str(body.get("project_name", "")).strip()
    if not project_name:
        return jsonify({"error": "project_name is required"}), 400

    actual_name = _validate_project(project_name)
    opt = _parse_optional(body)
    success_count = body.get("success_count", 1)

    try:
        inserted = _insert_result(
            actual_name, opt["file_name"],
            None, None, None, None,
            success_count, 0,
            opt["word_count"], opt["file_type"], opt["input_tokens"],
            opt["output_tokens"], opt["calculated_cost"], opt["llm_usage"],
        )
        row = serialize_row(inserted)
        return jsonify({"success": True, "type": "success", **row}), 201
    except Exception as e:
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/dashboard/top-projects")
def dashboard_top_projects():
    from_ts = request.args.get("from", "")
    to_ts = request.args.get("to", "")
    try:
        conditions = ["row_type = 'log'"]
        params = []
        if from_ts:
            conditions.append("timestamp >= %s")
            params.append(from_ts)
        if to_ts:
            conditions.append("timestamp <= %s")
            params.append(to_ts)
        where = "WHERE " + " AND ".join(conditions)
        rows = query(
            f"SELECT project_name, CAST(COUNT(*) AS int) AS total "
            f"FROM {TABLE} {where} "
            f"GROUP BY project_name ORDER BY total DESC LIMIT 10",
            params if params else None,
        )
        return jsonify({"projects": serialize_rows(rows)})
    except Exception as e:
        print(f"[Dashboard] top-projects: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/top-error-projects")
def dashboard_top_error_projects():
    from_ts = request.args.get("from", "")
    to_ts = request.args.get("to", "")
    try:
        conditions = [
            "row_type = 'log'",
            "error IS NOT NULL", "error <> ''",
        ]
        params = []
        if from_ts:
            conditions.append("timestamp >= %s")
            params.append(from_ts)
        if to_ts:
            conditions.append("timestamp <= %s")
            params.append(to_ts)
        where = "WHERE " + " AND ".join(conditions)
        rows = query(
            f"SELECT project_name, CAST(COUNT(*) AS int) AS total "
            f"FROM {TABLE} {where} "
            f"GROUP BY project_name HAVING COUNT(*) > 0 "
            f"ORDER BY total DESC LIMIT 10",
            params if params else None,
        )
        return jsonify({"projects": serialize_rows(rows)})
    except Exception as e:
        print(f"[Dashboard] top-error-projects: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/today-errors")
def dashboard_today_errors():
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = query(
            f"SELECT project_name AS project, file_name, error, "
            f"error_detail, error_hash, timestamp "
            f"FROM {TABLE} "
            f"WHERE row_type = 'log' AND error IS NOT NULL AND error <> '' "
            f"AND ("
            f"  (timestamp AT TIME ZONE 'UTC' >= CURRENT_DATE "
            f"   AND timestamp AT TIME ZONE 'UTC' < CURRENT_DATE + INTERVAL '1 day')"
            f"  OR"
            f"  (reopened_at IS NOT NULL "
            f"   AND reopened_at AT TIME ZONE 'UTC' >= CURRENT_DATE "
            f"   AND reopened_at AT TIME ZONE 'UTC' < CURRENT_DATE + INTERVAL '1 day')"
            f") ORDER BY timestamp DESC"
        )
        return jsonify({"date": date_str, "errors": serialize_rows(rows)})
    except Exception as e:
        print(f"[Dashboard] today-errors: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/errors")
def dashboard_errors():
    from_ts = request.args.get("from", "")
    to_ts = request.args.get("to", "")
    try:
        conditions = [
            "row_type = 'log'",
            "error IS NOT NULL", "error <> ''",
        ]
        params = []
        if from_ts:
            conditions.append("timestamp >= %s")
            params.append(from_ts)
        if to_ts:
            conditions.append("timestamp <= %s")
            params.append(to_ts)
        where = " AND ".join(conditions)
        rows = query(
            f"SELECT project_name AS project, file_name, error, "
            f"error_detail, error_hash, timestamp "
            f"FROM {TABLE} WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT 2000",
            params if params else None,
        )
        return jsonify({"errors": serialize_rows(rows)})
    except Exception as e:
        print(f"[Dashboard] errors: {e}")
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# BREAKS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/breaks/grouped")
def breaks_grouped():
    page = max(1, int(request.args.get("page", 1) or 1))
    limit = min(100, max(1, int(request.args.get("limit", 20) or 20)))
    offset = (page - 1) * limit
    status_f        = request.args.get("status", "")
    project_f       = request.args.get("project", "")
    semantic_group_f = request.args.get("semantic_group", "")   # NEW: filter by error_group_id
    from_ts = request.args.get("from", "")
    to_ts   = request.args.get("to", "")

    try:
        conditions = [
            "row_type = 'log'",
            "error IS NOT NULL", "error <> ''",
        ]
        params = []

        if from_ts:
            conditions.append("timestamp >= %s")
            params.append(from_ts)
        if to_ts:
            conditions.append("timestamp <= %s")
            params.append(to_ts)
        if project_f:
            conditions.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_f)
        if semantic_group_f:
            conditions.append("error_group_id = %s")
            params.append(semantic_group_f)

        where = " AND ".join(conditions)

        row_sql = (
            f"SELECT id AS representative_id, "
            f"project_name, "
            f"error AS error_message, "
            f"COALESCE(error_hash, MD5(LOWER(TRIM(error)))) AS error_hash, "
            f"COALESCE(error_group_id, '') AS error_group_id, "
            f"error_group_name, "
            f"failure_count::int AS occurrence_count, "
            f"timestamp AS first_seen, "
            f"GREATEST(COALESCE(reopened_at, timestamp), timestamp) AS last_seen, "
            f"CASE "
            f"  WHEN error_status = 'reopened' THEN 'regression' "
            f"  WHEN failure_count = 1 THEN 'new' "
            f"  ELSE 'existing' "
            f"END AS status "
            f"FROM {TABLE} WHERE {where}"
        )

        if status_f:
            count_sql = f"SELECT COUNT(*) AS cnt FROM ({row_sql}) AS g WHERE status = %s"
            total_rows = query(count_sql, tuple(params + [status_f]))
            total = total_rows[0].get("cnt", 0) if total_rows else 0
            data_sql = (
                f"SELECT * FROM ({row_sql}) AS g "
                f"WHERE status = %s "
                f"ORDER BY last_seen DESC NULLS LAST LIMIT %s OFFSET %s"
            )
            all_params = params + [status_f, limit, offset]
        else:
            count_sql = f"SELECT COUNT(*) AS cnt FROM ({row_sql}) AS g"
            total_rows = query(count_sql, tuple(params) if params else None)
            total = total_rows[0].get("cnt", 0) if total_rows else 0
            data_sql = (
                f"SELECT * FROM ({row_sql}) AS g "
                f"ORDER BY last_seen DESC NULLS LAST LIMIT %s OFFSET %s"
            )
            all_params = params + [limit, offset]

        data = query(data_sql, tuple(all_params))
        return jsonify({"data": serialize_rows(data), "total": total, "page": page, "limit": limit})
    except Exception as e:
        print(f"[Breaks] grouped error: {e}")
        return jsonify({
            "error": f"Failed to load grouped breaks: {str(e)}",
            "data": [],
            "total": 0,
            "page": page,
            "limit": limit,
        }), 500


@app.route("/api/breaks/<break_id>")
def get_break(break_id):
    """
    GET /api/breaks/:id — returns break detail with correlatedLogs: []
    """
    try:
        rows = query(
            f"SELECT * FROM {TABLE} WHERE row_type = 'log' AND id = %s",
            (break_id,),
        )
        if not rows:
            return jsonify({"error": "Not Found", "message": "Break not found."}), 404
        row = serialize_row(rows[0])
        row["correlatedLogs"] = []
        return jsonify(row)
    except Exception as exc:
        import traceback as _tb
        tb_str = _tb.format_exc()
        request_id = g.get("request_id", "unknown")
        print(f"[req:{request_id}] [Breaks] get_break error: {type(exc).__name__}: {exc}")
        print(f"[req:{request_id}] [Breaks] get_break Traceback:\n{tb_str}")
        return jsonify({"error": "Internal Server Error", "message": "Failed to load break.", "trace_id": request_id}), 500


@app.route("/api/breaks/detail/<error_hash>")
def get_break_detail(error_hash):
    """
    GET /api/breaks/detail/:error_hash
    Returns full error detail for the Error Details page.
    """
    request_id = g.get("request_id", "unknown")
    try:
        project_name = (request.args.get('project_name') or '').strip() or None
        stage = "route_entered"
        debug_info = {
            "error_hash": error_hash,
            "project_name": project_name,
            "debug_enabled": DEBUG_BREAK_DETAIL,
            "stage": stage,
        }

        print(f"[req:{request_id}] [Breaks:detail] TRACE START")
        print(f"[req:{request_id}] [Breaks:detail] URL error_hash={repr(error_hash)}")
        print(f"[req:{request_id}] [Breaks:detail] query_param project_name={repr(project_name)}")

        stage = "parsed_project"
        debug_info["stage"] = stage
        debug_info["project_name"] = project_name

        # Get grouped error info
        conditions = [
            "row_type = 'log'",
            "error IS NOT NULL",
            "error <> ''",
        ]
        params = []
        try:
            hash_candidates = build_error_hash_candidates(error_hash, None)
            debug_info["hash_candidates"] = hash_candidates
            debug_info["hash_helper_type"] = str(type(build_error_hash_candidates))
            debug_info["hash_helper_module"] = getattr(build_error_hash_candidates, "__module__", None)
            debug_info["hash_helper_callable"] = callable(build_error_hash_candidates)
            stage = "generated_hash_candidates"
            debug_info["stage"] = stage
        except Exception as exc:
            debug_info["stage"] = "hash_generation_failed"
            debug_info["hash_candidate_error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            raise

        print(f"[req:{request_id}] [Breaks:detail] hash_candidates={hash_candidates}")
        
        if hash_candidates is None:
            print(f"[req:{request_id}] [Breaks:detail] WARNING: build_error_hash_candidates returned None!")
            if _error_matching_import_err:
                print(f"[req:{request_id}] [Breaks:detail] Import error was: {type(_error_matching_import_err).__name__}: {_error_matching_import_err}")
            hash_candidates = []
        
        if error_hash:
            hash_clauses = []
            for idx, candidate in enumerate(hash_candidates):
                hash_clauses.append("error_hash = %s")
                params.append(candidate)
                print(f"[req:{request_id}] [Breaks:detail] Added hash candidate[{idx}]={repr(candidate)}")
            # Preserve compatibility with older rows that may not have an error_hash value
            # but still match via the normalized MD5 of the raw error text.
            hash_clauses.append("MD5(LOWER(TRIM(error))) = %s")
            params.append(error_hash)
            if hash_clauses:
                conditions.append(f"({' OR '.join(hash_clauses)})")
                print(f"[req:{request_id}] [Breaks:detail] Added hash condition with {len(hash_clauses)} candidates")

        if project_name:
            conditions.insert(0, "LOWER(project_name) = LOWER(%s)")
            params.insert(0, project_name)
            print(f"[req:{request_id}] [Breaks:detail] Inserted project_name at params[0]={repr(project_name)}")

        where_clause = ' AND '.join(conditions)
        debug_info["conditions"] = conditions
        debug_info["params"] = tuple(params)
        debug_info["param_count"] = len(params)
        stage = "built_sql"
        debug_info["stage"] = stage
        print(f"[req:{request_id}] [Breaks:detail] WHERE clause: {where_clause}")
        print(f"[req:{request_id}] [Breaks:detail] Parameters tuple: {tuple(params)}")
        print(f"[req:{request_id}] [Breaks:detail] Param count: {len(params)}")

        sql = (
            "SELECT project_name, error AS error_message, error_detail, error_hash, "
            "failure_count, timestamp, error_status, reopened_at, file_name "
            f"FROM {TABLE} "
            f"WHERE {where_clause} "
            "ORDER BY timestamp DESC"
        )
        debug_info["sql"] = sql
        print(f"[req:{request_id}] [Breaks:detail] Full SQL:\n{sql}")
        debug_info["stage"] = "executing_query"
        error_rows = query(sql, tuple(params))
        debug_info["row_count"] = len(error_rows) if error_rows else 0
        debug_info["first_row"] = serialize_row(error_rows[0]) if error_rows else None
        debug_info["first_row_keys"] = list(error_rows[0].keys()) if error_rows else []
        print(f"[req:{request_id}] [Breaks:detail] Query returned {len(error_rows) if error_rows else 0} rows")
        if error_rows:
            for i, row in enumerate(error_rows[:3]):
                print(f"[req:{request_id}] [Breaks:detail] Row[{i}]: error_hash={row.get('error_hash')}, project_name={row.get('project_name')}, error={row.get('error_message', '')[:50]}")
        
        if not error_rows:
            debug_info["stage"] = "query_returned_zero_rows"
            print(f"[req:{request_id}] [Breaks:detail] ZERO ROWS - Testing conditions individually")
            # Test each condition to find the culprit
            test_conditions = [
                ("row_type='log' only", ["row_type = 'log'"], []),
                ("no row_type filter", ["error IS NOT NULL", "error <> ''"], []),
                ("with error_hash candidates", conditions[:4] if len(conditions) > 4 else conditions, params[:1] if params else []),
            ]
            test_debug = []
            for test_name, test_conds, test_params in test_conditions:
                test_where = ' AND '.join(test_conds)
                test_sql = f"SELECT COUNT(*) as cnt FROM {TABLE} WHERE {test_where}"
                print(f"[req:{request_id}] [Breaks:detail] TEST[{test_name}]: {test_sql}")
                try:
                    result = query(test_sql, tuple(test_params))
                    cnt = result[0].get('cnt', 0) if result else 0
                    print(f"[req:{request_id}] [Breaks:detail] TEST[{test_name}] returned {cnt} rows")
                    test_debug.append({
                        "name": test_name,
                        "sql": test_sql,
                        "params": tuple(test_params),
                        "count": cnt,
                    })
                except Exception as e:
                    print(f"[req:{request_id}] [Breaks:detail] TEST[{test_name}] ERROR: {e}")
                    test_debug.append({
                        "name": test_name,
                        "sql": test_sql,
                        "params": tuple(test_params),
                        "error": str(e),
                    })
            debug_info["zero_row_tests"] = test_debug
            response_body = {"error": "Not Found", "message": "Error not found.", "reason": "query_returned_zero_rows"}
            if DEBUG_BREAK_DETAIL:
                response_body["debug"] = debug_info
            return jsonify(response_body), 404

        first = error_rows[0]
        occurrence_count = sum(r.get("failure_count", 1) for r in error_rows)
        timestamps = [r.get("timestamp") for r in error_rows if r.get("timestamp") is not None]
        first_seen = min(timestamps) if timestamps else None
        reopened_ts = [r.get("reopened_at") for r in error_rows if r.get("reopened_at") is not None]
        all_ts = timestamps + reopened_ts
        last_seen = max(all_ts) if all_ts else None
        file_name = next((r.get("file_name") for r in error_rows if r.get("file_name")), first.get("file_name"))

        has_reopened = any(r.get("error_status") == "reopened" for r in error_rows)
        if has_reopened:
            status = "regression"
        elif occurrence_count == 1:
            status = "new"
        else:
            status = "existing"

        occurrences = [
            {"file_name": r.get("file_name"), "timestamp": r["timestamp"],
             "failure_count": r.get("failure_count", 1)}
            for r in error_rows
        ]

        # ── Solution card — semantic-first, three-tier lookup ─────────────────
        # Retrieval is project-scoped at every tier. The frontend receives the
        # same solution_data dict shape regardless of which tier matched.
        #
        # TIER 1: Pinecone nearest-neighbour for the current error text
        #         (cross-hash, project-scoped). Best match hydrated from Aurora.
        # TIER 2: Aurora in-process cosine scan across the whole project.
        #         Used when Pinecone is unavailable or returns nothing.
        # TIER 3: Original hash-exact SQL.
        #         Used when embeddings are unavailable or tiers 1+2 empty.
        #
        # Isolated in a try/except so any failure falls back gracefully and
        # never prevents the rest of Error Details from loading.
        solution_data = None
        solution_error = None
        try:
            def _make_solution_data(s):
                """Convert a DB row dict into the solution_data shape."""
                sol_text = s.get("solution")
                if sol_text is None:
                    return None
                return {
                    "id":               s.get("id"),
                    "solution":         sol_text,
                    "created_at":       s.get("created_at").isoformat() if s.get("created_at") else None,
                    "created_by":       s.get("created_by"),
                    "version":          s.get("version"),
                    "confidence_score": float(s["confidence_score"]) if s.get("confidence_score") is not None else None,
                    "usage_count":      s.get("usage_count"),
                }

            _solution_found = False

            # ── TIER 1: Pinecone ──────────────────────────────────────────────
            if not _solution_found:
                try:
                    from ai.embeddings import create_embedding, cosine_similarity
                    from ai.pinecone_service import query_similar as _pinecone_query

                    # Build query text from the error we already have in memory
                    _err_text    = first.get("error_message") or ""
                    _detail_text = first.get("error_detail") or ""
                    _query_text  = f"{_err_text}\n\n{_detail_text}".strip() or _err_text

                    if _query_text:
                        _qvec = create_embedding(_query_text)
                        # Project-scoped, no hash filter — cross-hash semantic match
                        _matches = _pinecone_query(
                            solution_id=None,
                            embedding=_qvec,
                            project_name=project_name,
                            limit=5,
                            error_hash=None,
                        )
                        if _matches:
                            _ids = [m.get("id") for m in _matches if m.get("id")]
                            if _ids:
                                _placeholders = ", ".join(["%s"] * len(_ids))
                                _hydrate_conds = [
                                    "row_type = 'solution'",
                                    f"id IN ({_placeholders})",
                                ]
                                _hydrate_params = list(_ids)
                                if project_name:
                                    _hydrate_conds.append("LOWER(project_name) = LOWER(%s)")
                                    _hydrate_params.append(project_name)
                                _hydrate_rows = query(
                                    f"SELECT id, solution, created_at, created_by, version, "
                                    f"confidence_score, usage_count, embedding "
                                    f"FROM {TABLE} WHERE {' AND '.join(_hydrate_conds)}",
                                    tuple(_hydrate_params),
                                )
                                if _hydrate_rows:
                                    # Pick highest cosine match from hydrated rows
                                    _best_row  = None
                                    _best_sim  = -1.0
                                    for _hr in _hydrate_rows:
                                        _emb_raw = _hr.get("embedding")
                                        _emb = None
                                        if isinstance(_emb_raw, str):
                                            try:
                                                import json as _j
                                                _parsed = _j.loads(_emb_raw)
                                                _emb = _parsed if isinstance(_parsed, list) else None
                                            except Exception:
                                                pass
                                        elif isinstance(_emb_raw, list):
                                            _emb = _emb_raw
                                        if _emb:
                                            _sim = cosine_similarity(_qvec, _emb)
                                            if _sim > _best_sim:
                                                _best_sim = _sim
                                                _best_row = _hr
                                        elif _best_row is None:
                                            _best_row = _hr
                                    if _best_row:
                                        solution_data = _make_solution_data(_best_row)
                                        if solution_data:
                                            _solution_found = True
                                            debug_info["solution_tier"] = f"tier1_pinecone sim={_best_sim:.3f}"
                                            logger.info(
                                                "[req:%s] [Breaks:detail] Solution TIER 1 (Pinecone) sim=%.3f",
                                                request_id, _best_sim,
                                            )
                except Exception as _t1_exc:
                    logger.exception(
                        "[req:%s] [Breaks:detail] TIER 1 failed: %s",
                        request_id, _t1_exc,
                    )
                    debug_info["solution_tier1_error"] = str(_t1_exc)

            # ── TIER 2: Aurora in-process cosine scan ─────────────────────────
            if not _solution_found:
                try:
                    from ai.embeddings import create_embedding as _ce2, cosine_similarity as _cs2
                    _err_text2   = first.get("error_message") or ""
                    _detail2     = first.get("error_detail") or ""
                    _qtext2      = f"{_err_text2}\n\n{_detail2}".strip() or _err_text2

                    if _qtext2:
                        _qvec2 = _ce2(_qtext2)
                        _scan_conds  = ["row_type = 'solution'", "embedding IS NOT NULL"]
                        _scan_params = []
                        if project_name:
                            _scan_conds.append("LOWER(project_name) = LOWER(%s)")
                            _scan_params.append(project_name)
                        _scan_rows = query(
                            f"SELECT id, solution, created_at, created_by, version, "
                            f"confidence_score, usage_count, embedding "
                            f"FROM {TABLE} WHERE {' AND '.join(_scan_conds)} "
                            f"ORDER BY confidence_score DESC, usage_count DESC, created_at DESC "
                            f"LIMIT 200",
                            tuple(_scan_params),
                        )
                        _t2_best_row = None
                        _t2_best_sim = -1.0
                        for _sr in _scan_rows:
                            _emb_raw2 = _sr.get("embedding")
                            _emb2 = None
                            if isinstance(_emb_raw2, str):
                                try:
                                    import json as _j2
                                    _p2 = _j2.loads(_emb_raw2)
                                    _emb2 = _p2 if isinstance(_p2, list) else None
                                except Exception:
                                    pass
                            elif isinstance(_emb_raw2, list):
                                _emb2 = _emb_raw2
                            if _emb2 and len(_emb2) > 0:
                                _sim2 = _cs2(_qvec2, _emb2)
                                if _sim2 > _t2_best_sim:
                                    _t2_best_sim = _sim2
                                    _t2_best_row = _sr
                        if _t2_best_row and _t2_best_sim >= 0.30:
                            solution_data = _make_solution_data(_t2_best_row)
                            if solution_data:
                                _solution_found = True
                                debug_info["solution_tier"] = f"tier2_aurora_scan sim={_t2_best_sim:.3f}"
                                logger.info(
                                    "[req:%s] [Breaks:detail] Solution TIER 2 (Aurora scan) sim=%.3f",
                                    request_id, _t2_best_sim,
                                )
                except Exception as _t2_exc:
                    logger.exception(
                        "[req:%s] [Breaks:detail] TIER 2 failed: %s",
                        request_id, _t2_exc,
                    )
                    debug_info["solution_tier2_error"] = str(_t2_exc)

            # ── TIER 3: original hash-exact SQL (backward-compatible) ─────────
            if not _solution_found:
                logger.info(
                    "[req:%s] [Breaks:detail] Solution TIER 3 (hash fallback)",
                    request_id,
                )
                debug_info["solution_tier"] = "tier3_hash_fallback"
                solution_conditions = ["row_type = 'solution'"]
                solution_params = []
                if error_hash:
                    candidate_clauses = []
                    for candidate in build_error_hash_candidates(error_hash, None):
                        candidate_clauses.append("error_hash = %s")
                        solution_params.append(candidate)
                    if candidate_clauses:
                        fallback_clause = (
                            f"error_hash IN (SELECT error_hash FROM {TABLE} WHERE row_type = 'log' "
                            f"AND MD5(LOWER(TRIM(error))) = %s)"
                        )
                        solution_conditions.append(
                            f"({' OR '.join(candidate_clauses)} OR {fallback_clause})"
                        )
                        solution_params.append(error_hash)
                    else:
                        solution_conditions.append("error_hash = %s")
                        solution_params.append(error_hash)
                if project_name:
                    solution_conditions.append("LOWER(project_name) = LOWER(%s)")
                    solution_params.append(project_name)

                solution_rows = query(
                    f"SELECT id, solution, created_at, created_by, version, confidence_score, usage_count "
                    f"FROM {TABLE} WHERE {' AND '.join(solution_conditions)} "
                    f"ORDER BY created_at DESC LIMIT 1",
                    tuple(solution_params),
                )
                if solution_rows:
                    solution_data = _make_solution_data(solution_rows[0])

        except Exception as e:
            logger.exception("[Breaks:detail] Solution card lookup failed: %s", e)
            debug_info["solution_stage"] = "solution_query_failed"
            debug_info["solution_error"] = {"type": type(e).__name__, "message": str(e)}
            solution_error = f"Failed to load solution: {str(e)}"
            debug_info["solution_error"] = {"type": type(e).__name__, "message": str(e)}
            solution_error = f"Failed to load solution: {str(e)}"

        ai_recommendation = None
        try:
            debug_info["solution_stage"] = "loading_ai"
            ai_recommendation = get_ai_recommendations(
                error_hash,
                project_name,
                error_message=first["error_message"],
            )
            debug_info["ai_stage"] = "ai_executed"
            if isinstance(ai_recommendation, dict):
                debug_info["ai_recommendation"] = {
                    "recommendation": ai_recommendation.get("recommendation"),
                    "description": ai_recommendation.get("description"),
                    "solution_count": len(ai_recommendation.get("solutions") or []),
                    "nova_diagnostics": ai_recommendation.get("nova_diagnostics"),
                }
                try:
                    print(json.dumps({
                        "req": request_id,
                        "event": "ai_recommendation_result",
                        "recommendation": ai_recommendation.get("recommendation"),
                        "description": ai_recommendation.get("description"),
                        "solution_count": len(ai_recommendation.get("solutions") or []),
                        "nova_diagnostics": ai_recommendation.get("nova_diagnostics"),
                    }, default=str))
                except Exception:
                    print(f"[req:{request_id}] [Breaks] ai recommendation result: {ai_recommendation}")
        except Exception as e:
            print(f"[Breaks] ai recommendation error: {e}")
            debug_info["ai_stage"] = "ai_exception"
            debug_info["ai_error"] = {"type": type(e).__name__, "message": str(e)}
            try:
                print(json.dumps({
                    "req": request_id,
                    "event": "ai_recommendation_exception",
                    "error": {"type": type(e).__name__, "message": str(e)},
                }, default=str))
            except Exception:
                pass

        # Parse stack trace to extract structured frame information with source code lines
        parsed_stacktrace = None
        if STACKTRACE_PARSER_AVAILABLE:
            try:
                parsed_stacktrace = parse_and_enhance_stacktrace(
                    first["error_message"],
                    first.get("error_detail"),
                    enhance_with_source=True,
                )
                debug_info["stacktrace_parsed"] = True
                debug_info["frame_count"] = len(parsed_stacktrace.get("frames", []))
            except Exception as e:
                print(f"[req:{request_id}] [Breaks:detail] Stack trace parsing failed: {e}")
                debug_info["stacktrace_parse_error"] = str(e)

        result = {
            "project_name": first["project_name"],
            "file_name": file_name,
            "error_message": first["error_message"],
            "error_detail": first.get("error_detail"),
            "parsed_stacktrace": parsed_stacktrace,
            "error_hash": error_hash,
            "occurrence_count": occurrence_count,
            "first_seen": first_seen,
            "status": status,
            "error_status": first.get("error_status"),
            "occurrences": serialize_rows(occurrences),
            "solution": solution_data,
            "solution_error": solution_error,
            "ai_recommendation": ai_recommendation,
        }
        stage = "serializing_response"
        debug_info["stage"] = stage
        debug_info["returned_hashes"] = [r.get("error_hash") for r in error_rows[:3]]
        debug_info["returned_projects"] = [r.get("project_name") for r in error_rows[:3]]
        debug_info["returned_statuses"] = [r.get("error_status") for r in error_rows[:3]]
        response = jsonify(serialize_row(result))
        if DEBUG_BREAK_DETAIL:
            try:
                response_data = result.copy()
                response_data["debug"] = debug_info
                return jsonify(serialize_row(response_data))
            except Exception as e:
                debug_info["stage"] = "debug_serialization_failed"
                debug_info["debug_serialization_error"] = {"type": type(e).__name__, "message": str(e)}
                return jsonify(result)
        return response
    except Exception as e:
        import traceback as _tb
        tb_str = _tb.format_exc()
        request_id = g.get("request_id", "unknown")
        debug_info["stage"] = "unhandled_exception"
        debug_info["exception"] = {"type": type(e).__name__, "message": str(e)}
        debug_info["traceback"] = tb_str
        print(f"[req:{request_id}] [Breaks:detail] ERROR: {type(e).__name__}: {e}")
        print(f"[req:{request_id}] [Breaks:detail] error_hash={error_hash} project_name={project_name}")
        print(f"[req:{request_id}] [Breaks:detail] Traceback:\n{tb_str}")
        response_body = {
            "error": "Internal Server Error",
            "message": "Error detail failed to load.",
            "trace_id": request_id,
        }
        if DEBUG_BREAK_DETAIL:
            response_body["debug"] = debug_info
        return jsonify(response_body), 500


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY DASHBOARD (GET /api/dashboard — used by useDashboard.ts hook)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/dashboard")
def dashboard_legacy():
    """
    GET /api/dashboard — returns aggregated break counts, trend, etc.
    """
    try:
        def safe_count(sql):
            try:
                r = query(sql)
                return int(r[0]["count"]) if r else 0
            except Exception:
                return 0

        last24h = safe_count(
            f"SELECT COUNT(*) AS count FROM {TABLE} "
            f"WHERE row_type = 'log' AND error IS NOT NULL AND error <> '' "
            f"AND timestamp >= NOW() - INTERVAL '24 hours'"
        )
        last7d = safe_count(
            f"SELECT COUNT(*) AS count FROM {TABLE} "
            f"WHERE row_type = 'log' AND error IS NOT NULL AND error <> '' "
            f"AND timestamp >= NOW() - INTERVAL '7 days'"
        )

        return jsonify({
            "breakCounts": {"last24h": last24h, "last7d": last7d},
            "errorRateTrend": [],
            "topServices": [],
            "timeSeries": [],
            "severityBreakdown": [],
            "deploymentEvents": [],
            "airbrakeUnreachable": False,
        })
    except Exception:
        return jsonify({
            "breakCounts": {"last24h": 0, "last7d": 0},
            "errorRateTrend": [],
            "topServices": [],
            "timeSeries": [],
            "severityBreakdown": [],
            "deploymentEvents": [],
            "airbrakeUnreachable": True,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR SOLUTIONS / KNOWLEDGE BASE
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/knowledge_base/reopen", methods=["POST"])
def reopen_error_solution():
    body         = request.get_json() or {}
    error_hash   = body.get("error_hash")
    project_name = body.get("project_name")
    log_id       = body.get("log_id") or None

    if not error_hash or not project_name:
        return jsonify({"error": "error_hash and project_name are required"}), 400
    if not log_id:
        return jsonify({
            "error": "log_id is required",
            "detail": (
                "Reopen must target a specific log row by id to avoid "
                "reopening unrelated occurrences that share the same error_hash. "
                "The frontend supplies this from representative_id in breaks_grouped."
            ),
        }), 400

    try:
        count = execute(
            f"UPDATE {TABLE} "
            f"SET error_status = 'reopened', reopened_at = NOW(), resolved_at = NULL "
            f"WHERE row_type = 'log' "
            f"  AND id = %s "
            f"  AND error_status IN ('resolved', 'reopened')",
            (log_id,),
        )
        logger.info("[Reopen] log_id=%r error_hash=%r project=%r rows_updated=%d",
                    log_id, error_hash, project_name, count)
        return jsonify({"reopened": count, "project_name": project_name, "error_hash": error_hash})
    except Exception as e:
        logger.exception("[Reopen] Failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge_base/resolve", methods=["POST"])
def resolve_error_solution():
    body         = request.get_json() or {}
    error_hash   = body.get("error_hash")
    project_name = body.get("project_name")
    log_id       = body.get("log_id") or None

    if not error_hash or not project_name:
        return jsonify({"error": "error_hash and project_name are required"}), 400
    if not log_id:
        return jsonify({
            "error": "log_id is required",
            "detail": (
                "resolve must target a specific log row by id to avoid "
                "resolving unrelated occurrences that share the same error_hash."
            ),
        }), 400

    try:
        count = execute(
            f"UPDATE {TABLE} "
            f"SET error_status = 'resolved', resolved_at = NOW() "
            f"WHERE row_type = 'log' "
            f"  AND id = %s "
            f"  AND error_status IN ('open', 'reopened')",
            (log_id,),
        )
        logger.info("[Resolve] log_id=%r error_hash=%r project=%r rows_updated=%d",
                    log_id, error_hash, project_name, count)
        return jsonify({"resolved": count, "project_name": project_name, "error_hash": error_hash})
    except Exception as e:
        logger.exception("[Resolve] Failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge_base/use", methods=["POST"])
def use_solution():
    body         = request.get_json() or {}
    solution_id  = body.get("solution_id")
    error_hash   = body.get("error_hash")
    project_name = body.get("project_name")
    log_id       = body.get("log_id") or None

    if not solution_id or not error_hash or not project_name:
        return jsonify({"error": "solution_id, error_hash and project_name are required"}), 400
    if not log_id:
        return jsonify({
            "error": "log_id is required",
            "detail": (
                "use_solution must target a specific log row by id to avoid "
                "resolving unrelated occurrences that share the same error_hash. "
                "The frontend supplies this from representative_id in breaks_grouped."
            ),
        }), 400

    try:
        # Atomically increment usage and get the updated solution row
        updated_solution = increment_usage(solution_id)

        # Resolve exactly the one log row the user is looking at.
        execute(
            f"UPDATE {TABLE} "
            f"SET error_status = 'resolved', resolved_at = NOW() "
            f"WHERE row_type = 'log' "
            f"  AND id = %s "
            f"  AND error_status IN ('open', 'reopened')",
            (log_id,),
        )
        logger.info("[Solution] Resolved — solution_id=%s log_id=%r error_hash=%r",
                    solution_id, log_id, error_hash)

        sol = serialize_row(updated_solution) if updated_solution else {}
        return jsonify({
            "used":             True,
            "solution_id":      solution_id,
            "solution":         sol.get("solution"),
            "version":          sol.get("version"),
            "confidence_score": sol.get("confidence_score"),
            "usage_count":      sol.get("usage_count"),
            "created_by":       sol.get("created_by"),
            "created_at":       sol.get("created_at"),
        })
    except Exception as e:
        logger.exception("[use_solution] Failed: %s", e)
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


@app.route("/api/knowledge_base/<solution_id>/versions", methods=["GET"])
def get_solution_versions_route(solution_id):
    try:
        versions = get_solution_versions(solution_id)
        return jsonify({"versions": versions})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


@app.route("/api/knowledge_base/<solution_id>/versions/<version_id>", methods=["DELETE"])
def delete_solution_version_route(solution_id, version_id):
    try:
        count = delete_solution_version(version_id)
        return jsonify({"deleted": count > 0, "version_id": version_id})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


@app.route("/api/knowledge_base/top", methods=["GET"])
def get_top_solutions_route():
    # Primary key: error_message (normalized in get_top_solutions).
    # error_hash accepted for backward-compat but ignored when error_message is present.
    error_message = request.args.get("error_message", "").strip()
    error_hash    = request.args.get("error_hash", "").strip()
    project_name  = request.args.get("project_name")
    limit         = int(request.args.get("limit", "5"))
    offset        = int(request.args.get("offset", "0"))

    if not error_message and not error_hash:
        return jsonify({"error": "error_message or error_hash is required"}), 400
    try:
        rows, total = get_top_solutions(
            error_message=error_message,
            project_name=project_name,
            limit=limit,
            offset=offset,
            error_hash=error_hash or None,
        )
        return jsonify({"solutions": rows, "total": total})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


@app.route("/api/knowledge_base/<error_hash>", methods=["GET"])
def get_error_solution(error_hash):
    try:
        hash_candidates = build_error_hash_candidates(error_hash, None)
        params = list(hash_candidates) if hash_candidates else [error_hash]
        rows = query(
            f"SELECT solution, created_at "
            f"FROM {TABLE} WHERE row_type = 'solution' AND (" + " OR ".join(["error_hash = %s"] * len(params)) + ") "
            f"ORDER BY created_at DESC LIMIT 1",
            tuple(params),
        )
        if not rows:
            return jsonify({"solution": None})
        r = rows[0]
        return jsonify({
            "solution": r["solution"],
            "updated_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


@app.route("/api/knowledge_base", methods=["POST"])
def upsert_error_solution():
    body = request.get_json() or {}
    error_hash   = body.get("error_hash")
    solution     = body.get("solution")
    created_by   = body.get("created_by") or "developer"
    project_name = body.get("project_name")
    # error_message is the primary group-key lookup text — passed through to insert_solution
    error_message    = body.get("error_message") or None
    base_solution_id = body.get("base_solution_id")
    if not error_hash:
        return jsonify({"error": "error_hash is required"}), 400
    if not solution:
        return jsonify({"error": "solution is required"}), 400
    check_only   = bool(body.get("check_only"))
    force_create = bool(body.get("create_anyway") or body.get("force_create"))
    try:
        row = insert_solution(
            error_hash,
            solution,
            created_by=created_by,
            project_name=project_name,
            base_solution_id=base_solution_id,
            force_create=force_create,
            check_only=check_only,
            error_message=error_message,
        )
        status_code = 200 if check_only else 201
        return jsonify(serialize_row(row)), status_code
    except Exception as e:
        import traceback as _tb2
        tb_str = _tb2.format_exc()
        print(f"[KnowledgeBase] Save Solution FAILED — {type(e).__name__}: {e}")
        print(tb_str)
        return jsonify({
            "error": str(e),
            "exception": type(e).__name__,
            "traceback": tb_str,
            "kb_available": KB_AVAILABLE,
            "kb_import_error": str(_kb_import_err) if _kb_import_err else None,
            "kb_import_traceback": _kb_import_tb if _kb_import_tb else None,
        }), 500


@app.route("/api/knowledge_base/<error_hash>", methods=["DELETE"])
def delete_error_solution(error_hash):
    """Delete one solution family (all versions created via Improve from the same root).

    The frontend passes the solution_id of the specific solution card the user
    clicked Delete on.  We load that solution row, find its family_id
    (log_ref_id), and delete every row that shares the same log_ref_id.

    Fallback (legacy / backward-compat): when solution_id is absent, the old
    group-key deletion path runs so pre-migration rows are still removable.
    """
    project_name = request.args.get("project_name")
    solution_id  = request.args.get("solution_id")

    try:
        if solution_id:
            # ── Primary path: delete by solution family ───────────────────────
            # Load the target solution to find its family_id (log_ref_id).
            target_rows = query(
                f"SELECT id, log_ref_id, project_name FROM {TABLE} "
                f"WHERE row_type = 'solution' AND id = %s",
                (solution_id,),
            )
            if not target_rows:
                return jsonify({"error": "Solution not found"}), 404

            target        = target_rows[0]
            # family_id is the root solution's ID stored in log_ref_id.
            # For a root solution, log_ref_id == its own id.
            family_id     = target.get("log_ref_id") or solution_id
            sol_project   = target.get("project_name") or project_name

            del_conditions = ["row_type = 'solution'", "log_ref_id = %s"]
            del_params: list = [family_id]
            if sol_project:
                del_conditions.append("LOWER(project_name) = LOWER(%s)")
                del_params.append(sol_project)

            # Collect IDs first so we can clean up Pinecone vectors
            id_rows = query(
                f"SELECT id FROM {TABLE} WHERE {' AND '.join(del_conditions)}",
                tuple(del_params),
            )
            execute(
                f"DELETE FROM {TABLE} WHERE {' AND '.join(del_conditions)}",
                tuple(del_params),
            )

            # Best-effort Pinecone cleanup — never block the response
            for id_row in id_rows:
                try:
                    from ai.pinecone_service import delete_vector
                    delete_vector(id_row["id"])
                except Exception as _pexc:
                    logger.warning(
                        "[DeleteSolution] Pinecone cleanup failed for id=%r: %s",
                        id_row.get("id"), _pexc,
                    )

            logger.info(
                "[DeleteSolution] Deleted solution family — family_id=%r "
                "rows=%d project=%r",
                family_id, len(id_rows), sol_project,
            )
            return make_response("", 204)

        # ── Legacy path: delete by error group key ────────────────────────────
        # Kept for pre-migration rows that don't have a proper family_id, and
        # for any caller that doesn't supply solution_id.
        from ai.error_matching import derive_solution_group_key

        group_key = None
        try:
            log_conditions = ["row_type = 'log'", "error IS NOT NULL"]
            log_params: list = []
            if project_name:
                log_conditions.insert(0, "LOWER(project_name) = LOWER(%s)")
                log_params.insert(0, project_name)
            hash_candidates = build_error_hash_candidates(error_hash, None)
            if hash_candidates:
                log_conditions.append(
                    f"({' OR '.join(['error_hash = %s'] * len(hash_candidates))})"
                )
                log_params.extend(hash_candidates)
            else:
                log_conditions.append("error_hash = %s")
                log_params.append(error_hash)
            log_rows = query(
                f"SELECT error FROM {TABLE} WHERE {' AND '.join(log_conditions)} "
                f"ORDER BY timestamp DESC LIMIT 1",
                tuple(log_params),
            )
            if log_rows and log_rows[0].get("error"):
                group_key = derive_solution_group_key(log_rows[0]["error"])
        except Exception as _resolve_exc:
            logger.exception("[DeleteSolution] Group-key resolution failed: %s", _resolve_exc)

        keys_to_try = list(dict.fromkeys(filter(None, [group_key, error_hash])))
        for key in keys_to_try:
            if project_name:
                execute(
                    f"DELETE FROM {TABLE} WHERE row_type = 'solution' "
                    f"AND error_hash = %s AND LOWER(project_name) = LOWER(%s)",
                    (key, project_name),
                )
            else:
                execute(
                    f"DELETE FROM {TABLE} WHERE row_type = 'solution' AND error_hash = %s",
                    (key,),
                )

        logger.info(
            "[DeleteSolution] Legacy delete — keys=%r project=%r",
            keys_to_try, project_name,
        )
        return make_response("", 204)

    except Exception as e:
        logger.exception("[DeleteSolution] Failed: %s", e)
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN (users) — requires admin token
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/users", methods=["GET"])
def list_users():
    _, err = require_role("admin")
    if err:
        return err
    try:
        rows = query(
            f"SELECT * FROM {TABLE} WHERE row_type = 'user' ORDER BY created_at DESC"
        )
        return jsonify(serialize_rows(rows))
    except Exception:
        return jsonify([])


@app.route("/api/users", methods=["POST"])
def create_user():
    _, err = require_role("admin")
    if err:
        return err
    body = request.get_json() or {}
    try:
        row = execute_returning(
            f"INSERT INTO {TABLE} (id, row_type, email, role, oauth_provider, oauth_subject, created_at) "
            f"VALUES (%s,'user',%s,%s,%s,%s,NOW()) RETURNING *",
            (str(uuid.uuid4()), body.get("email"), body.get("role"),
             body.get("oauthProvider"), body.get("oauthSubject")),
        )
        return jsonify(serialize_row(row)), 201
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/users/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    _, err = require_role("admin")
    if err:
        return err
    try:
        count = execute(
            f"DELETE FROM {TABLE} WHERE row_type = 'user' AND id = %s",
            (user_id,),
        )
        if count == 0:
            return jsonify({"error": "User not found"}), 404
        return make_response("", 204)
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# TEST & DEBUG ENDPOINTS FOR SMART EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/test/smart-extraction", methods=["GET"])
def test_smart_extraction():
    """
    GET /api/test/smart-extraction
    
    Test the smart extraction functionality with various error formats.
    Returns results showing how each test case is processed.
    
    This demonstrates that the backend can automatically extract stack traces
    from the error field without requiring project code changes.
    """
    test_cases = [
        {
            "name": "Python traceback in error field",
            "description": "Full traceback sent in error field (most common)",
            "error": """Traceback (most recent call last):
  File "app/services/user.py", line 42, in get_user
    result = data['key']
KeyError: 'user_id'""",
            "error_detail": None,
        },
        {
            "name": "Error message first, traceback second",
            "description": "Short error on first line, traceback follows",
            "error": """KeyError: 'user_id'
Traceback (most recent call last):
  File "app/services/user.py", line 42, in get_user
    result = data['key']""",
            "error_detail": None,
        },
        {
            "name": "JavaScript stack trace",
            "description": "JavaScript/TypeScript error format",
            "error": """TypeError: Cannot read property 'id' of undefined
    at getUserId (services/user.js:42:15)
    at processRequest (api/handler.js:128:22)
    at async Server.handleRequest (server.js:89:5)""",
            "error_detail": None,
        },
        {
            "name": "Simple error without traceback",
            "description": "Plain error message with no stack trace",
            "error": "Connection timeout",
            "error_detail": None,
        },
        {
            "name": "Already properly separated",
            "description": "Error and error_detail correctly split",
            "error": "KeyError: 'user_id'",
            "error_detail": """Traceback (most recent call last):
  File "app/services/user.py", line 42, in get_user
    result = data['key']
KeyError: 'user_id'""",
        },
    ]
    
    results = []
    for test_case in test_cases:
        # Simulate the extraction logic
        error = test_case["error"]
        error_detail = test_case["error_detail"]
        
        if not error_detail:
            short_error, extracted_trace = _smart_extract_error_detail(error)
            extracted = bool(extracted_trace)
            final_error = short_error if extracted_trace else error
            final_error_detail = extracted_trace
        else:
            extracted = False
            final_error = error
            final_error_detail = error_detail
        
        results.append({
            "test_case": test_case["name"],
            "description": test_case["description"],
            "input": {
                "error": test_case["error"],
                "error_detail": test_case["error_detail"],
            },
            "output": {
                "error": final_error,
                "error_detail": final_error_detail,
                "extraction_performed": extracted,
                "error_detail_length": len(final_error_detail) if final_error_detail else 0,
            },
            "status": "✅ Extracted" if extracted else ("✅ Already separated" if error_detail else "⚠️ No trace found"),
        })
    
    return jsonify({
        "test_name": "Smart Stack Trace Extraction",
        "description": "Tests automatic extraction of stack traces from error field",
        "backend_version": "smart-extraction-v1",
        "parser_available": STACKTRACE_PARSER_AVAILABLE,
        "test_cases": len(test_cases),
        "results": results,
        "usage": {
            "endpoint": "POST /api/ingest/error",
            "automatic": "Backend automatically extracts stack traces when error_detail is NULL",
            "no_changes_needed": "Project root files don't need to be modified",
        },
    })


@app.route("/api/test/ingestion", methods=["POST"])
def test_ingestion():
    """
    POST /api/test/ingestion
    
    Test the complete ingestion flow including smart extraction.
    This creates a test project and sends a test error to verify the pipeline.
    
    Body: {
      "test_type": "python"|"javascript"|"simple"|"separated" (optional)
    }
    
    Returns the ingestion result plus extraction diagnostics.
    """
    body = request.get_json() or {}
    test_type = body.get("test_type", "python")
    
    # Test data for different scenarios
    test_data = {
        "python": {
            "project_name": "TestProject_Python",
            "error": """Traceback (most recent call last):
  File "app/services/user.py", line 42, in get_user
    result = data['key']
KeyError: 'user_id'""",
            "file_name": "app/main.py",
        },
        "javascript": {
            "project_name": "TestProject_JavaScript",
            "error": """TypeError: Cannot read property 'id' of undefined
    at getUserId (services/user.js:42:15)
    at processRequest (api/handler.js:128:22)""",
            "file_name": "services/user.js",
        },
        "simple": {
            "project_name": "TestProject_Simple",
            "error": "Connection timeout",
            "file_name": "app/network.py",
        },
        "separated": {
            "project_name": "TestProject_Separated",
            "error": "KeyError: 'user_id'",
            "error_detail": """Traceback (most recent call last):
  File "app/services/user.py", line 42, in get_user
    result = data['key']
KeyError: 'user_id'""",
            "file_name": "app/main.py",
        },
    }
    
    if test_type not in test_data:
        return jsonify({
            "error": "Invalid test_type",
            "valid_types": list(test_data.keys()),
        }), 400
    
    payload = test_data[test_type]
    
    # Process through ingestion logic
    project_name = payload["project_name"]
    error = payload["error"]
    error_detail_input = payload.get("error_detail")
    
    actual_name = _validate_project(project_name)
    
    # Smart extraction
    error_detail = error_detail_input
    extracted = False
    if not error_detail:
        short_error, extracted_trace = _smart_extract_error_detail(error)
        if extracted_trace:
            error_detail = extracted_trace
            error = short_error
            extracted = True
    
    error_hash = derive_error_hash(error, error_detail)
    
    # Insert the test error
    try:
        inserted = _insert_result(
            actual_name, payload.get("file_name"),
            error, error_detail,
            error_hash, "open",
            0, 1,
            None, None, None, None, None, None,
        )
        
        return jsonify({
            "success": True,
            "test_type": test_type,
            "extraction_performed": extracted,
            "input": {
                "error": payload["error"],
                "error_detail": error_detail_input,
            },
            "stored": {
                "error": error,
                "error_detail": error_detail,
                "error_detail_length": len(error_detail) if error_detail else 0,
                "error_hash": error_hash,
            },
            "record": serialize_row(inserted),
            "next_steps": [
                f"View error at: GET /api/breaks/detail/{error_hash}?project_name={project_name}",
                "Open Error Details page in frontend to see parsed stack trace",
            ],
        }), 201
        
    except Exception as e:
        return jsonify({
            "error": "Ingestion failed",
            "detail": str(e),
            "test_type": test_type,
        }), 500


@app.route("/api/test/parser", methods=["POST"])
def test_parser():
    """
    POST /api/test/parser
    
    Test the stack trace parser directly without storing to database.
    
    Body: {
      "error": "KeyError: 'user_id'",
      "error_detail": "Traceback (most recent call last):\n  File..."
    }
    
    Returns parsed stack trace with extracted frames.
    """
    if not STACKTRACE_PARSER_AVAILABLE:
        return jsonify({
            "error": "Stack trace parser not available",
            "parser_available": False,
        }), 503
    
    body = request.get_json() or {}
    error = body.get("error", "")
    error_detail = body.get("error_detail", "")
    
    if not error:
        return jsonify({"error": "error field is required"}), 400
    
    # Test smart extraction if error_detail is missing
    extraction_performed = False
    if not error_detail:
        short_error, extracted_trace = _smart_extract_error_detail(error)
        if extracted_trace:
            error_detail = extracted_trace
            error = short_error
            extraction_performed = True
    
    if not error_detail:
        return jsonify({
            "error": "No stack trace found",
            "message": "error_detail is NULL and no stack trace detected in error field",
            "extraction_performed": False,
        }), 400
    
    try:
        parsed = parse_and_enhance_stacktrace(
            error,
            error_detail,
            enhance_with_source=True,
        )
        
        return jsonify({
            "success": True,
            "extraction_performed": extraction_performed,
            "input": {
                "error": error,
                "error_detail": error_detail,
                "error_detail_length": len(error_detail),
            },
            "parsed_stacktrace": parsed,
            "frame_count": len(parsed.get("frames", [])),
            "top_frame": parsed.get("frames", [None])[0] if parsed.get("frames") else None,
        })
        
    except Exception as e:
        import traceback as _tb
        return jsonify({
            "error": "Parser failed",
            "detail": str(e),
            "traceback": _tb.format_exc(),
            "input": {
                "error": error,
                "error_detail": error_detail[:200] + "..." if len(error_detail) > 200 else error_detail,
            },
        }), 500


# ═══════════════════════════════════════════════════════════════════════════════
# SEMANTIC ERROR GROUPS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/error-groups", methods=["GET"])
def list_error_groups():
    """
    GET /api/error-groups[?project_name=xxx]

    Returns all distinct semantic groups with occurrence counts.
    Cross-project by default; pass project_name to scope to one project.
    """
    project_name = request.args.get("project_name", "").strip() or None
    try:
        from ai.error_grouper import list_groups
        rows = list_groups(project_name=project_name)
        return jsonify({"groups": serialize_rows(rows)})
    except Exception as e:
        logger.exception("[ErrorGroups] list failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/error-groups/classify", methods=["POST"])
def classify_single_error():
    """
    POST /api/error-groups/classify
    Body: { "log_id": "...", "error_message": "...", "project_name": "...", "error_detail": "..." }

    Classifies one log row immediately (on-demand, e.g. from the detail page).
    Skips rows that have manual_group_override = TRUE.
    """
    body         = request.get_json() or {}
    log_id       = body.get("log_id")
    error_message= body.get("error_message", "").strip()
    project_name = body.get("project_name", "").strip()
    error_detail = body.get("error_detail") or None

    if not log_id or not error_message or not project_name:
        return jsonify({"error": "log_id, error_message and project_name are required"}), 400

    try:
        from ai.error_grouper import classify_error
        result = classify_error(
            log_id        = log_id,
            error_message = error_message,
            project_name  = project_name,
            error_detail  = error_detail,
        )
        return jsonify(result)
    except Exception as e:
        logger.exception("[ErrorGroups] classify failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/error-groups/backfill", methods=["POST"])
def backfill_error_groups():
    """
    POST /api/error-groups/backfill
    Body (all optional):
      {
        "batch_size":   50,
        "max_batches":  20,
        "project_name": "my_project"   // scope to one project
      }

    Classifies existing log rows that have error_group_id IS NULL.
    Safe to call repeatedly — already-classified rows are skipped.
    Returns a summary so the caller knows how many were processed and
    whether more rows remain (call again if done=false).
    """
    body         = request.get_json() or {}
    batch_size   = int(body.get("batch_size",  50))
    max_batches  = int(body.get("max_batches", 20))
    project_name = body.get("project_name", "").strip() or None

    try:
        from ai.error_grouper import backfill_unclassified
        summary = backfill_unclassified(
            batch_size   = batch_size,
            max_batches  = max_batches,
            project_name = project_name,
        )
        return jsonify(summary)
    except Exception as e:
        logger.exception("[ErrorGroups] backfill failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/error-groups/override", methods=["PATCH"])
def override_error_group():
    """
    PATCH /api/error-groups/override
    Body:
      {
        "log_id":      "...",
        "group_id":    "...",   // existing group_id OR a new UUID
        "group_name":  "..."
      }

    Manually assigns a log row to a semantic group.
    Sets manual_group_override = TRUE so the AI will never reclassify this row.
    """
    body       = request.get_json() or {}
    log_id     = body.get("log_id")
    group_id   = body.get("group_id")
    group_name = body.get("group_name", "").strip()

    if not log_id or not group_id or not group_name:
        return jsonify({"error": "log_id, group_id and group_name are required"}), 400

    try:
        from ai.error_grouper import apply_manual_override
        ok = apply_manual_override(log_id=log_id, group_id=group_id, group_name=group_name)
        if ok:
            return jsonify({"updated": True, "log_id": log_id, "group_id": group_id, "group_name": group_name})
        return jsonify({"error": "Update failed"}), 500
    except Exception as e:
        logger.exception("[ErrorGroups] override failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/error-groups/merge", methods=["POST"])
def merge_error_groups():
    """
    POST /api/error-groups/merge
    Body:
      {
        "source_group_id": "...",
        "target_group_id": "...",
        "target_group_name": "..."   // new canonical name for the merged group
      }

    Moves all log rows from source_group_id into target_group_id.
    All affected rows get manual_group_override = TRUE so AI won't undo the merge.
    """
    body              = request.get_json() or {}
    source_group_id   = body.get("source_group_id")
    target_group_id   = body.get("target_group_id")
    target_group_name = body.get("target_group_name", "").strip()

    if not source_group_id or not target_group_id or not target_group_name:
        return jsonify({"error": "source_group_id, target_group_id and target_group_name are required"}), 400

    if source_group_id == target_group_id:
        return jsonify({"error": "source and target groups are the same"}), 400

    try:
        count = execute(
            f"UPDATE {TABLE} "
            f"SET error_group_id = %s, error_group_name = %s, manual_group_override = TRUE "
            f"WHERE row_type = 'log' AND error_group_id = %s",
            (target_group_id, target_group_name, source_group_id),
        )
        logger.info(
            "[ErrorGroups] merge source=%r -> target=%r rows=%s",
            source_group_id, target_group_id, count,
        )
        return jsonify({
            "merged":            True,
            "source_group_id":   source_group_id,
            "target_group_id":   target_group_id,
            "target_group_name": target_group_name,
            "rows_moved":        count,
        })
    except Exception as e:
        logger.exception("[ErrorGroups] merge failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/error-groups/rename", methods=["PATCH"])
def rename_error_group():
    """
    PATCH /api/error-groups/rename
    Body: { "group_id": "...", "group_name": "..." }

    Renames a semantic group across all its log rows.
    """
    body       = request.get_json() or {}
    group_id   = body.get("group_id")
    group_name = body.get("group_name", "").strip()

    if not group_id or not group_name:
        return jsonify({"error": "group_id and group_name are required"}), 400

    try:
        count = execute(
            f"UPDATE {TABLE} SET error_group_name = %s "
            f"WHERE row_type = 'log' AND error_group_id = %s",
            (group_name, group_id),
        )
        logger.info("[ErrorGroups] rename group_id=%r name=%r rows=%s", group_id, group_name, count)
        return jsonify({"renamed": True, "group_id": group_id, "group_name": group_name, "rows_updated": count})
    except Exception as e:
        logger.exception("[ErrorGroups] rename failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# DEVELOPMENT SERVER
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 Airbrake Backend - Python Flask Server")
    print("=" * 70)
    print(f"📊 Database: {TABLE}")
    print(f"🔧 Debug Mode: {DEBUG_BREAK_DETAIL}")
    print(f"🤖 KB Available: {KB_AVAILABLE}")
    print(f"🧠 AI Recommendations: {AI_RECOMMENDATIONS_AVAILABLE}")
    print("=" * 70)
    print("🌐 Starting server on http://localhost:5000")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5000, debug=True)
