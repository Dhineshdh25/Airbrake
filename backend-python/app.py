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
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any
from flask import Flask, request, jsonify, make_response, g, has_request_context, Response, stream_with_context
from queue import Queue
from threading import Lock
from collections import defaultdict

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

# ── Authentication (Google OAuth 2.0 / OIDC) ─────────────────────────────────
try:
    from auth import (  # noqa: E402
        auth_bp,
        csrf_protect,
        get_current_user,
        require_auth,
        require_permission,
        VALID_ROLES,
        get_accessible_project,
        get_accessible_project_by_name,
        get_accessible_log,
        _build_project_access_condition,
        _build_log_access_condition,
    )
except Exception as _auth_import_exc:
    import traceback as _auth_tb
    print(f"[app] CRITICAL: auth package import FAILED — {type(_auth_import_exc).__name__}: {_auth_import_exc}")
    print(_auth_tb.format_exc())
    # Re-raise — without auth the app cannot function correctly
    raise
app.register_blueprint(auth_bp)   # registers all /api/auth/* routes

# ── Jira OAuth integration (Phase 1) ─────────────────────────────────────────
try:
    from jira import jira_bp          # noqa: E402
except Exception as _jira_import_exc:
    import traceback as _jira_tb
    print(f"[app] CRITICAL: jira package import FAILED — {type(_jira_import_exc).__name__}: {_jira_import_exc}")
    print(_jira_tb.format_exc())
    raise
app.register_blueprint(jira_bp)   # registers all /api/jira/* routes

# ── SSE (Server-Sent Events) Infrastructure ──────────────────────────────────
class SSEConnectionManager:
    """Manages SSE connections for real-time log streaming."""
    
    def __init__(self):
        self.connections: Dict[str, Queue] = {}
        self.connection_filters: Dict[str, Dict[str, Any]] = {}
        self.lock = Lock()
    
    def add_connection(self, connection_id: str, filters: Dict[str, Any]) -> Queue:
        """Register a new SSE connection with optional filters."""
        with self.lock:
            queue = Queue(maxsize=100)
            self.connections[connection_id] = queue
            self.connection_filters[connection_id] = filters
            logger.info(f"[SSE] New connection: {connection_id} with filters: {filters}")
            return queue
    
    def remove_connection(self, connection_id: str):
        """Remove an SSE connection."""
        with self.lock:
            if connection_id in self.connections:
                del self.connections[connection_id]
                del self.connection_filters[connection_id]
                logger.info(f"[SSE] Connection closed: {connection_id}")
    
    def broadcast_log(self, log_data: Dict[str, Any]):
        """Broadcast a new log entry to all matching connections."""
        with self.lock:
            for conn_id, queue in list(self.connections.items()):
                try:
                    # Check if log matches connection filters
                    filters = self.connection_filters.get(conn_id, {})
                    if self._matches_filters(log_data, filters):
                        if not queue.full():
                            queue.put(log_data)
                        else:
                            # Drop oldest message if queue is full
                            try:
                                queue.get_nowait()
                                queue.put(log_data)
                            except:
                                pass
                except Exception as e:
                    logger.error(f"[SSE] Failed to broadcast to {conn_id}: {e}")
    
    def _matches_filters(self, log_data: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if log entry matches the connection's filters."""
        if not filters:
            return True
        
        # Project filter
        project_name = filters.get('project_name')
        if project_name and log_data.get('project_name') != project_name:
            return False
        
        # Error status filter (errors only, resolved, etc.)
        status_filter = filters.get('status')
        if status_filter == 'errors_only' and not log_data.get('error'):
            return False
        if status_filter == 'resolved' and log_data.get('error_status') != 'resolved':
            return False
        if status_filter == 'active' and log_data.get('error_status') == 'resolved':
            return False
        
        # Severity filter (if we add severity levels)
        severity = filters.get('severity')
        if severity and log_data.get('severity') != severity:
            return False
        
        return True
    
    def get_connection_count(self) -> int:
        """Get the number of active connections."""
        with self.lock:
            return len(self.connections)

# Global SSE manager
sse_manager = SSEConnectionManager()


@app.before_request
def attach_request_context():
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.request_id = request_id
    g.request_started_at = time.monotonic()
    print(f"[req:{request_id}] {request.method} {request.path}")

    # CSRF protection — Double-Submit Cookie
    csrf_result = csrf_protect()
    if csrf_result is not None:
        return csrf_result


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    import traceback as _tb_mod
    from werkzeug.exceptions import HTTPException

    # HTTP exceptions (4xx, 5xx) — return proper status code, no traceback
    if isinstance(exc, HTTPException):
        logger.warning("[app] HTTPException — %s %s → %d %s",
                       request.method, request.path, exc.code, exc.name)
        return jsonify({"error": exc.name}), exc.code

    # Unexpected exceptions — log traceback server-side, return safe 500
    tb_str = _tb_mod.format_exc()
    print(f"[app] Unhandled exception — {type(exc).__name__}: {exc}")
    print(tb_str)
    return jsonify({
        "error": "Internal server error",
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
# Origins allowed to make credentialed requests (cookies).
# Configurable via ALLOWED_ORIGINS env var (comma-separated).
# Falls back to a safe default set for this project.
_DEFAULT_ORIGINS = (
    "http://airbrake.s3-website-us-east-1.amazonaws.com,"
    "http://localhost:3000"
)

ALLOWED_ORIGINS: set[str] = set(
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
)

# Headers the frontend is allowed to send
_ALLOWED_HEADERS = "Content-Type, X-CSRF-Token, X-Device-ID"


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin", "")

    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    else:
        # Unknown origin — no CORS headers at all.
        # This blocks credentialed cross-origin requests from untrusted sites.
        # Direct (non-browser) requests still work — they don't send an Origin header.
        pass

    # These are safe to set unconditionally (they only matter when Allow-Origin is present)
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
    response.headers["Access-Control-Max-Age"] = "86400"

    if hasattr(g, "request_started_at"):
        elapsed_ms = (time.monotonic() - g.request_started_at) * 1000
        print(f"[req:{getattr(g, 'request_id', 'n/a')}] completed status={response.status_code} elapsed_ms={elapsed_ms:.2f}")
    return response


@app.route("/api/<path:p>", methods=["OPTIONS"])
@app.route("/api/", methods=["OPTIONS"])
def options_handler(p=""):
    return make_response("", 204)


# ── Auth helpers ──────────────────────────────────────────────────────────────
# DEV_SESSIONS is only active when DEV_AUTH=1 and NOT in production.
# In production, only real sessions (cookie-based) are accepted.
from auth.middleware import get_current_user as _get_current_user_middleware, _is_dev_auth_enabled, _DEV_SESSIONS, _is_production


def get_session():
    """Resolve the current session from cookie or Bearer token.

    Returns {"userId": str, "role": str} or None.
    Compatible with existing require_role() callers.
    """
    user = _get_current_user_middleware()
    if user:
        return {"userId": user["id"], "role": user["role"]}
    return None


def require_role(*roles):
    """Return (session, error_response). If error_response is not None, return it."""
    session = get_session()
    if not session:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    if session["role"] not in roles:
        return None, (jsonify({"error": "Forbidden"}), 403)
    return session, None


# Keep DEV_SESSIONS available for backward compatibility in tests,
# but it is only consulted via auth.middleware when DEV_AUTH=1
DEV_SESSIONS = _DEV_SESSIONS if _is_dev_auth_enabled() else {}


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


# ═══════════════════════════════════════════════════════════════════════════════
# REAL-TIME LOG STREAMING (SSE)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/logs/stream")
@require_permission("logs:read")
def stream_logs():
    """
    GET /api/logs/stream
    
    Server-Sent Events (SSE) endpoint for real-time log streaming.
    
    Query Parameters:
      - project_name: Filter by specific project
      - status: Filter by status (errors_only, resolved, active, all)
      - severity: Filter by severity level
    
    Usage:
      const eventSource = new EventSource('/api/logs/stream?project_name=MyProject&status=errors_only');
      eventSource.onmessage = (event) => {
        const log = JSON.parse(event.data);
        console.log('New log:', log);
      };
    """
    connection_id = str(uuid.uuid4())
    
    # Parse filters from query parameters
    filters = {
        'project_name': request.args.get('project_name'),
        'status': request.args.get('status', 'all'),
        'severity': request.args.get('severity'),
    }
    
    # Register connection
    message_queue = sse_manager.add_connection(connection_id, filters)
    
    def generate():
        """Generator function for SSE stream."""
        try:
            # Send initial connection confirmation
            yield f"data: {json.dumps({'type': 'connected', 'connection_id': connection_id, 'filters': filters})}\n\n"
            
            # Send periodic heartbeat and messages
            last_heartbeat = time.time()
            heartbeat_interval = 30  # seconds
            
            while True:
                try:
                    # Non-blocking get with timeout
                    if not message_queue.empty():
                        message = message_queue.get(timeout=1)
                        yield f"data: {json.dumps({'type': 'log', 'data': message})}\n\n"
                    else:
                        # Send heartbeat if needed
                        current_time = time.time()
                        if current_time - last_heartbeat >= heartbeat_interval:
                            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
                            last_heartbeat = current_time
                        time.sleep(0.5)  # Prevent tight loop
                        
                except Exception as e:
                    logger.error(f"[SSE] Error in stream for {connection_id}: {e}")
                    break
                    
        finally:
            # Clean up connection
            sse_manager.remove_connection(connection_id)
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
            'Connection': 'keep-alive',
        }
    )


@app.route("/api/logs/stream/stats")
@require_permission("logs:read")
def stream_stats():
    """
    GET /api/logs/stream/stats
    
    Get statistics about active SSE connections.
    """
    return jsonify({
        "active_connections": sse_manager.get_connection_count(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })





@app.route("/api/debug/project-tables")
@require_auth(roles=["admin"])
def debug_project_tables():
    """Debug endpoint — lists all projects from project_data."""
    if _is_production():
        return jsonify({"error": "Not Found"}), 404
    rows = query(
        f"SELECT project_name AS name FROM {TABLE} WHERE row_type = 'project' ORDER BY project_name"
    )
    names = [r["name"] for r in rows]
    return jsonify({"tables": names, "count": len(names)})


@app.route("/api/debug/columns")
@require_auth(roles=["admin"])
def debug_columns():
    """Debug endpoint — lists all columns in projects_data."""
    if _is_production():
        return jsonify({"error": "Not Found"}), 404
    rows = query("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'projects_data'
        ORDER BY ordinal_position
    """)
    return jsonify({"columns": [r["column_name"] for r in rows], "count": len(rows)})


@app.route("/api/debug/kb-status")
@require_auth(roles=["admin"])
def debug_kb_status():
    """Debug endpoint — shows Knowledge Base and AI import status.
    Visible directly in browser: GET /api/debug/kb-status
    """
    if _is_production():
        return jsonify({"error": "Not Found"}), 404
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
@require_auth(roles=["admin"])
def debug_ai_health():
    """Lightweight diagnostic endpoint for Bedrock, Pinecone, Aurora, and imports."""
    if _is_production():
        return jsonify({"error": "Not Found"}), 404
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
@require_auth(roles=["admin"])
def debug_nova_direct():
    if _is_production():
        return jsonify({"error": "Not Found"}), 404
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
            "messages": [{
                "role": "user",
                "content": [{"text": prompt}],
            }],
            "inferenceConfig": {
                "maxTokens": 512,
                "temperature": 0.0,
            },
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
# Role-based access helpers live in auth/middleware.py and are imported via
# the auth package import above. They are available as module-level names here:
#   _build_project_access_condition(user) → (cond, params)
#   _build_log_access_condition(user)     → (cond, params)


@app.route("/api/projects")
@require_permission("projects:read")
def list_projects():
    """
    Return projects the authenticated user can access based on role:
      admin/viewer → all projects (any valid owner)
      developer    → only projects they own OR have an assigned log in
    Never returns NULL-owner rows.

    Response shape per project:
      { id, name, category, is_live, owner_user_id,
        responsible_user_id, responsible_user_email }
    responsible_user_* come from the metadata JSONB column.
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    access_cond, access_params = _build_project_access_condition(user)
    category = request.args.get("category")
    try:
        if category:
            rows = query(
                f"SELECT id, project_name AS name, category, is_live, "
                f"       owner_user_id, metadata "
                f"FROM {TABLE} "
                f"WHERE row_type = 'project' AND {access_cond} AND category = %s "
                f"ORDER BY project_name",
                access_params + [category],
            )
        else:
            rows = query(
                f"SELECT id, project_name AS name, category, is_live, "
                f"       owner_user_id, metadata "
                f"FROM {TABLE} "
                f"WHERE row_type = 'project' AND {access_cond} "
                f"ORDER BY project_name",
                access_params,
            )
        return jsonify([_format_project(r) for r in rows])
    except Exception as e:
        print(f"[Projects] error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects", methods=["POST"])
@require_auth(roles=["admin"])
def create_project():
    """
    POST /api/projects
    Register a new project owned by the authenticated user.

    Body:
      {
        "name":     "my_new_project",   ← required
        "category": "Production",       ← optional, defaults to 'Production'
        "is_live":  true                ← optional, defaults to true
      }

    Ownership is always taken from the authenticated session — never from
    the request body, query parameters, or headers.
    Duplicate project names are checked per owner only.
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = user["id"]

    body = request.get_json() or {}
    name = str(body.get("name") or body.get("project_name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    category = str(body.get("category") or "Production").strip()
    is_live  = body.get("is_live", True)
    if not isinstance(is_live, bool):
        is_live = True

    try:
        # Return existing project only if it belongs to THIS user (per-owner uniqueness)
        existing = query(
            f"SELECT id, project_name AS name, category, is_live FROM {TABLE} "
            f"WHERE row_type = 'project' "
            f"  AND LOWER(project_name) = LOWER(%s) "
            f"  AND owner_user_id = %s",
            (name, user_id),
        )
        if existing:
            return jsonify(serialize_row(existing[0])), 200

        # Generate project row id — used as both id and project_id
        new_id = str(uuid.uuid4())
        row = execute_returning(
            f"INSERT INTO {TABLE} "
            f"  (id, row_type, project_name, category, is_live, owner_user_id, project_id, created_at) "
            f"VALUES (%s, 'project', %s, %s, %s, %s, %s, NOW()) "
            f"RETURNING id, project_name AS name, category, is_live, owner_user_id",
            (new_id, name, category, is_live, user_id, new_id),
        )
        print(f"[Projects] New project: '{name}' owner={user_id}")
        return jsonify(serialize_row(row)), 201
    except Exception as e:
        print(f"[Projects] create error: {e}")
        return jsonify({"error": "Internal server error"}), 500


def _format_project(row: dict) -> dict:
    """
    Build a safe project dict for the frontend.

    Pulls responsible_user_id and responsible_user_email out of the
    metadata JSONB column so the frontend doesn't need to parse JSON.
    """
    raw_meta = row.get("metadata")
    if isinstance(raw_meta, str):
        try:
            meta = json.loads(raw_meta)
        except Exception:
            meta = {}
    elif isinstance(raw_meta, dict):
        meta = raw_meta
    else:
        meta = {}
    return {
        "id":                     str(row.get("id") or ""),
        "name":                   row.get("name") or row.get("project_name") or "",
        "category":               row.get("category") or "",
        "is_live":                bool(row.get("is_live")),
        "owner_user_id":          str(row.get("owner_user_id") or ""),
        "responsible_user_id":    meta.get("responsible_user_id") or "",
        "responsible_user_email": meta.get("responsible_user_email") or "",
    }


@app.route("/api/projects/<project_id>/responsible-user", methods=["PATCH"])
@require_auth(roles=["admin"])
def set_project_responsible_user(project_id):
    """
    PATCH /api/projects/<project_id>/responsible-user

    Assign or unassign a responsible user for a project.  Admin-only.

    Body:
      { "user_id": "<uuid>" }   — assign a user
      { "user_id": null }       — unassign (set to Unassigned)

    The responsible_user_id and responsible_user_email are stored in the
    project row's metadata JSONB column — no schema migration needed.

    Response: the updated project dict (same shape as GET /api/projects items).
    """
    caller = get_current_user()
    if not caller:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json() or {}
    new_user_id = (body.get("user_id") or "").strip() or None

    try:
        # Verify project exists
        proj_rows = query(
            f"SELECT id, project_name AS name, category, is_live, owner_user_id, metadata "
            f"FROM {TABLE} WHERE row_type = 'project' AND id = %s",
            (project_id,),
        )
        if not proj_rows:
            return jsonify({"error": "Project not found"}), 404

        # Resolve the new responsible user (if any)
        new_email = ""
        if new_user_id:
            user_rows = query(
                f"SELECT email FROM {TABLE} WHERE row_type = 'user' AND id = %s LIMIT 1",
                (new_user_id,),
            )
            if not user_rows:
                return jsonify({"error": "User not found"}), 404
            new_email = user_rows[0].get("email") or ""

        # Merge into existing metadata (preserves other metadata fields)
        if new_user_id:
            execute(
                f"UPDATE {TABLE} "
                f"SET metadata = COALESCE(metadata::jsonb, '{{}}'::jsonb) "
                f"           || jsonb_build_object("
                f"               'responsible_user_id',    %s::text, "
                f"               'responsible_user_email', %s::text"
                f"             ) "
                f"WHERE row_type = 'project' AND id = %s",
                (new_user_id, new_email, project_id),
            )
        else:
            # Unassign — remove the keys from metadata
            execute(
                f"UPDATE {TABLE} "
                f"SET metadata = COALESCE(metadata::jsonb, '{{}}'::jsonb) "
                f"           - 'responsible_user_id' "
                f"           - 'responsible_user_email' "
                f"WHERE row_type = 'project' AND id = %s",
                (project_id,),
            )

        # Re-fetch and return the updated row
        updated = query(
            f"SELECT id, project_name AS name, category, is_live, owner_user_id, metadata "
            f"FROM {TABLE} WHERE row_type = 'project' AND id = %s",
            (project_id,),
        )
        if not updated:
            return jsonify({"error": "Project not found after update"}), 404

        logger.info(
            "[Projects] Admin %s set responsible_user=%s for project_id=%s",
            caller["id"], new_user_id or "(unassigned)", project_id,
        )
        return jsonify(_format_project(updated[0]))

    except Exception as exc:
        logger.exception("[Projects] responsible-user PATCH error: %s", exc)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects/live")
@require_permission("projects:read")
def list_live_projects():
    """Return live projects the authenticated user can access based on role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    access_cond, access_params = _build_project_access_condition(user)
    try:
        rows = query(
            f"SELECT id, project_name AS name, category, is_live FROM {TABLE} "
            f"WHERE row_type = 'project' AND is_live = true AND {access_cond} "
            f"ORDER BY project_name",
            access_params,
        )
        return jsonify(serialize_rows(rows))
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED FILTERING & MULTI-PROJECT LOGS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/logs/multi-project")
@require_permission("logs:read")
def multi_project_logs():
    """
    GET /api/logs/multi-project
    
    Get logs from multiple projects at once with advanced filtering.
    
    Query Parameters:
      - projects: Comma-separated list of project names (required)
      - from, to: Date range filters
      - search: Full-text search
      - regex: Regex pattern search
      - severity: Severity filter
      - status: Status filter (all, errors, resolved, active, success)
      - page, limit: Pagination
    
    Example:
      GET /api/logs/multi-project?projects=Project1,Project2&status=errors&search=timeout
    """
    projects_param = request.args.get("projects", "")
    if not projects_param:
        return jsonify({"error": "projects parameter is required"}), 400
    
    project_names = [p.strip() for p in projects_param.split(",") if p.strip()]
    if not project_names:
        return jsonify({"error": "At least one project name is required"}), 400
    
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    offset = (page - 1) * limit
    
    # Parse filters
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    search = request.args.get("search")
    regex_pattern = request.args.get("regex")
    severity = request.args.get("severity")
    file_path = request.args.get("file_path")
    status_filter = request.args.get("status", "all")
    
    try:
        # Build WHERE clause for multiple projects
        project_conditions = " OR ".join(["LOWER(project_name) = LOWER(%s)"] * len(project_names))
        filters = [f"({project_conditions})"]
        count_params = list(project_names)
        query_params = list(project_names)
        
        # Date filters
        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append("DATE(timestamp) >= %s")
            count_params.append(from_date_clean)
            query_params.append(from_date_clean)
        
        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append("DATE(timestamp) <= %s")
            count_params.append(to_date_clean)
            query_params.append(to_date_clean)
        
        # Full-text search
        if search:
            filters.append("(LOWER(error) LIKE LOWER(%s) OR LOWER(error_detail) LIKE LOWER(%s) OR LOWER(file_name) LIKE LOWER(%s))")
            search_pattern = f"%{search}%"
            count_params.extend([search_pattern, search_pattern, search_pattern])
            query_params.extend([search_pattern, search_pattern, search_pattern])
        
        # Regex search
        if regex_pattern:
            try:
                re.compile(regex_pattern)
                filters.append("(error ~* %s OR error_detail ~* %s)")
                count_params.extend([regex_pattern, regex_pattern])
                query_params.extend([regex_pattern, regex_pattern])
            except re.error as regex_error:
                return jsonify({"error": f"Invalid regex pattern: {str(regex_error)}"}), 400
        
        # Severity filter
        if severity:
            filters.append("severity = %s")
            count_params.append(severity)
            query_params.append(severity)
        
        # File path filter
        if file_path:
            filters.append("LOWER(file_name) LIKE LOWER(%s)")
            file_pattern = f"%{file_path}%"
            count_params.append(file_pattern)
            query_params.append(file_pattern)
        
        # Status filter
        if status_filter == "errors":
            filters.append("error IS NOT NULL AND error != ''")
        elif status_filter == "resolved":
            filters.append("error IS NOT NULL AND error != '' AND error_status = 'resolved'")
        elif status_filter == "active":
            filters.append("error IS NOT NULL AND error != '' AND (error_status IS NULL OR error_status != 'resolved')")
        elif status_filter == "success":
            filters.append("(error IS NULL OR error = '')")
        
        where_clause = " AND ".join(filters)
        
        # Get total count
        count_query = f"SELECT COUNT(*) as total FROM {TABLE} WHERE row_type = 'log' AND {where_clause}"
        count_result = query(count_query, tuple(count_params))
        total_records = int(count_result[0].get("total", 0)) if count_result else 0
        total_pages = (total_records + limit - 1) // limit if limit > 0 else 0
        
        # Add pagination params
        query_params.extend([limit, offset])
        
        # Fetch logs
        logs_query = (
            f"SELECT project_name, file_name, timestamp, success_count, failure_count, error, "
            f"error_detail, error_status, resolved_at, reopened_at, "
            f"llm_usage, input_tokens, output_tokens, calculated_cost "
            f"FROM {TABLE} WHERE row_type = 'log' AND {where_clause} "
            f"ORDER BY timestamp DESC LIMIT %s OFFSET %s"
        )
        logs = query(logs_query, tuple(query_params))
        
        # Calculate stats per project
        project_stats = {}
        for log in logs:
            proj = log.get("project_name")
            if proj not in project_stats:
                project_stats[proj] = {"total": 0, "errors": 0, "success": 0}
            project_stats[proj]["total"] += 1
            if log.get("error"):
                project_stats[proj]["errors"] += 1
            else:
                project_stats[proj]["success"] += 1
        
        return jsonify({
            "logs": serialize_rows(logs),
            "total": total_records,
            "projects": project_names,
            "projectStats": project_stats,
            "appliedFilters": {
                "from": from_date,
                "to": to_date,
                "search": search,
                "regex": regex_pattern,
                "severity": severity,
                "file_path": file_path,
                "status": status_filter,
            },
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
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/filters/presets", methods=["GET"])
@require_permission("filters:read")
def get_filter_presets():
    """
    GET /api/filters/presets
    
    Get saved filter presets for the current user.
    Returns common presets plus user-defined ones.
    """
    # TODO: Add user authentication and load user-specific presets from DB
    # For now, return system-wide common presets
    
    common_presets = [
        {
            "id": "recent-errors",
            "name": "Recent Errors (24h)",
            "description": "All errors from the last 24 hours",
            "filters": {
                "status": "errors",
                "from": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "to": datetime.now(timezone.utc).isoformat(),
            },
            "isSystem": True,
        },
        {
            "id": "critical-errors",
            "name": "Critical Errors",
            "description": "High-severity unresolved errors",
            "filters": {
                "status": "active",
                "severity": "critical",
            },
            "isSystem": True,
        },
        {
            "id": "timeout-errors",
            "name": "Timeout Errors",
            "description": "All timeout-related errors",
            "filters": {
                "status": "errors",
                "search": "timeout",
            },
            "isSystem": True,
        },
        {
            "id": "database-errors",
            "name": "Database Errors",
            "description": "Database connection and query errors",
            "filters": {
                "status": "errors",
                "regex": "database|sql|connection|query",
            },
            "isSystem": True,
        },
        {
            "id": "this-week-resolved",
            "name": "Resolved This Week",
            "description": "Errors resolved in the last 7 days",
            "filters": {
                "status": "resolved",
                "from": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
            },
            "isSystem": True,
        },
    ]
    
    return jsonify({"presets": common_presets})


@app.route("/api/filters/presets", methods=["POST"])
@require_permission("filters:write")
def create_filter_preset():
    """
    POST /api/filters/presets
    
    Create a new saved filter preset.
    
    Body:
      {
        "name": "My Custom Filter",
        "description": "Description of the filter",
        "filters": {
          "status": "errors",
          "search": "keyword",
          ...
        }
      }
    """
    body = request.get_json() or {}
    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    filters = body.get("filters", {})
    
    if not name:
        return jsonify({"error": "name is required"}), 400
    
    if not filters:
        return jsonify({"error": "filters object is required"}), 400
    
    # TODO: Add user authentication and save to database
    # For now, just return the preset as confirmation
    preset_id = str(uuid.uuid4())
    
    preset = {
        "id": preset_id,
        "name": name,
        "description": description,
        "filters": filters,
        "isSystem": False,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    
    return jsonify({"preset": preset, "message": "Preset created (in-memory only, not persisted yet)"}), 201


@app.route("/api/filters/presets/<preset_id>", methods=["DELETE"])
@require_permission("filters:write")
def delete_filter_preset(preset_id):
    """
    DELETE /api/filters/presets/:id
    
    Delete a saved filter preset.
    """
    # TODO: Add user authentication and delete from database
    return jsonify({"message": f"Preset {preset_id} deleted (in-memory only)"}), 200


# ═══════════════════════════════════════════════════════════════════════════════
# LOG GROUPING & AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/logs/grouping/by-error-type")
@require_permission("logs:read")
def group_by_error_type():
    """
    GET /api/logs/grouping/by-error-type
    
    Group logs by error type/hash with occurrence counts.
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - from, to: Date range
      - status: Filter by status (all, active, resolved)
      - limit: Max groups to return (default: 50)
    
    Returns errors grouped by their error_hash with counts and latest occurrence.
    """
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    status_filter = request.args.get("status", "all")
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    
    try:
        filters = ["row_type = 'log'", "error IS NOT NULL", "error != ''"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append("DATE(timestamp) >= %s")
            params.append(from_date_clean)
        
        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append("DATE(timestamp) <= %s")
            params.append(to_date_clean)
        
        if status_filter == "active":
            filters.append("(error_status IS NULL OR error_status != 'resolved')")
        elif status_filter == "resolved":
            filters.append("error_status = 'resolved'")
        
        where_clause = " AND ".join(filters)
        params.append(limit)
        
        query_sql = f"""
            SELECT 
                error_hash,
                error_group_id,
                error_group_name,
                COUNT(*) as occurrence_count,
                MAX(timestamp) as latest_occurrence,
                MIN(timestamp) as first_occurrence,
                STRING_AGG(DISTINCT project_name, ', ') as affected_projects,
                STRING_AGG(DISTINCT file_name, ', ') as affected_files,
                MAX(error) as sample_error_message,
                SUM(failure_count) as total_failures
            FROM {TABLE}
            WHERE {where_clause}
            GROUP BY error_hash, error_group_id, error_group_name
            ORDER BY occurrence_count DESC, latest_occurrence DESC
            LIMIT %s
        """
        
        groups = query(query_sql, tuple(params))
        
        return jsonify({
            "groups": serialize_rows(groups),
            "total_groups": len(groups),
            "filters": {
                "project_name": project_name,
                "from": from_date,
                "to": to_date,
                "status": status_filter,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/logs/grouping/by-file")
@require_permission("logs:read")
def group_by_file():
    """
    GET /api/logs/grouping/by-file
    
    Group logs by file/module with error statistics.
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - from, to: Date range
      - status: Filter by status
      - limit: Max files to return (default: 50)
    
    Returns files with error counts, success counts, and failure rates.
    """
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    status_filter = request.args.get("status", "all")
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    
    try:
        filters = ["row_type = 'log'", "file_name IS NOT NULL"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append("DATE(timestamp) >= %s")
            params.append(from_date_clean)
        
        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append("DATE(timestamp) <= %s")
            params.append(to_date_clean)
        
        where_clause = " AND ".join(filters)
        params.append(limit)
        
        query_sql = f"""
            SELECT 
                file_name,
                project_name,
                COUNT(*) as total_logs,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as error_count,
                COUNT(CASE WHEN error IS NULL OR error = '' THEN 1 END) as success_count,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' AND error_status = 'resolved' THEN 1 END) as resolved_count,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' AND (error_status IS NULL OR error_status != 'resolved') THEN 1 END) as active_error_count,
                MAX(timestamp) as latest_log,
                ROUND(
                    100.0 * COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) / NULLIF(COUNT(*), 0),
                    2
                ) as error_rate_percent
            FROM {TABLE}
            WHERE {where_clause}
            GROUP BY file_name, project_name
            ORDER BY error_count DESC, total_logs DESC
            LIMIT %s
        """
        
        groups = query(query_sql, tuple(params))
        
        return jsonify({
            "files": serialize_rows(groups),
            "total_files": len(groups),
            "filters": {
                "project_name": project_name,
                "from": from_date,
                "to": to_date,
                "status": status_filter,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/logs/grouping/by-time")
@require_permission("logs:read")
def group_by_time():
    """
    GET /api/logs/grouping/by-time
    
    Group logs by time buckets (hourly, daily, weekly).
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - from, to: Date range (required)
      - bucket: Time bucket size (hour, day, week) - default: day
      - status: Filter by status
    
    Returns time-series data showing error trends over time.
    """
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    bucket = request.args.get("bucket", "day")
    status_filter = request.args.get("status", "all")
    
    if not from_date or not to_date:
        return jsonify({"error": "from and to date parameters are required"}), 400
    
    if bucket not in ["hour", "day", "week"]:
        return jsonify({"error": "bucket must be one of: hour, day, week"}), 400
    
    try:
        filters = ["row_type = 'log'"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
        to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
        filters.append("DATE(timestamp) >= %s")
        filters.append("DATE(timestamp) <= %s")
        params.extend([from_date_clean, to_date_clean])
        
        # Determine PostgreSQL date_trunc format
        trunc_format = {
            "hour": "hour",
            "day": "day",
            "week": "week"
        }[bucket]
        
        where_clause = " AND ".join(filters)
        
        query_sql = f"""
            SELECT 
                DATE_TRUNC('{trunc_format}', timestamp) as time_bucket,
                COUNT(*) as total_logs,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as error_count,
                COUNT(CASE WHEN error IS NULL OR error = '' THEN 1 END) as success_count,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' AND error_status = 'resolved' THEN 1 END) as resolved_count,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' AND (error_status IS NULL OR error_status != 'resolved') THEN 1 END) as active_error_count,
                ROUND(
                    100.0 * COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) / NULLIF(COUNT(*), 0),
                    2
                ) as error_rate_percent
            FROM {TABLE}
            WHERE {where_clause}
            GROUP BY time_bucket
            ORDER BY time_bucket ASC
        """
        
        time_series = query(query_sql, tuple(params))
        
        return jsonify({
            "timeSeries": serialize_rows(time_series),
            "bucket": bucket,
            "dataPoints": len(time_series),
            "filters": {
                "project_name": project_name,
                "from": from_date,
                "to": to_date,
                "status": status_filter,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/logs/grouping/by-project")
@require_permission("logs:read")
def group_by_project():
    """
    GET /api/logs/grouping/by-project
    
    Aggregate statistics across all projects.
    
    Query Parameters:
      - from, to: Date range
      - status: Filter by status
      - sort: Sort by (errors, total, error_rate) - default: errors
    
    Returns project-level aggregations with error rates and trends.
    """
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    status_filter = request.args.get("status", "all")
    sort_by = request.args.get("sort", "errors")
    
    if sort_by not in ["errors", "total", "error_rate"]:
        return jsonify({"error": "sort must be one of: errors, total, error_rate"}), 400
    
    try:
        filters = ["row_type = 'log'"]
        params = []
        
        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append("DATE(timestamp) >= %s")
            params.append(from_date_clean)
        
        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append("DATE(timestamp) <= %s")
            params.append(to_date_clean)
        
        where_clause = " AND ".join(filters)
        
        # Determine sort column
        sort_column = {
            "errors": "error_count",
            "total": "total_logs",
            "error_rate": "error_rate_percent"
        }[sort_by]
        
        query_sql = f"""
            SELECT 
                project_name,
                COUNT(*) as total_logs,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as error_count,
                COUNT(CASE WHEN error IS NULL OR error = '' THEN 1 END) as success_count,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' AND error_status = 'resolved' THEN 1 END) as resolved_count,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' AND (error_status IS NULL OR error_status != 'resolved') THEN 1 END) as active_error_count,
                COUNT(DISTINCT error_hash) as unique_error_types,
                MAX(timestamp) as latest_log,
                MIN(timestamp) as first_log,
                ROUND(
                    100.0 * COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) / NULLIF(COUNT(*), 0),
                    2
                ) as error_rate_percent,
                SUM(COALESCE(calculated_cost, 0)) as total_cost
            FROM {TABLE}
            WHERE {where_clause}
            GROUP BY project_name
            ORDER BY {sort_column} DESC
        """
        
        projects = query(query_sql, tuple(params))
        
        # Calculate totals
        total_logs = sum(p.get("total_logs", 0) for p in projects)
        total_errors = sum(p.get("error_count", 0) for p in projects)
        total_success = sum(p.get("success_count", 0) for p in projects)
        
        return jsonify({
            "projects": serialize_rows(projects),
            "total_projects": len(projects),
            "totals": {
                "total_logs": total_logs,
                "total_errors": total_errors,
                "total_success": total_success,
                "overall_error_rate": round(100.0 * total_errors / total_logs, 2) if total_logs > 0 else 0,
            },
            "filters": {
                "from": from_date,
                "to": to_date,
                "status": status_filter,
                "sort": sort_by,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/logs/deduplication/similar")
@require_permission("logs:read")
def find_similar_errors():
    """
    GET /api/logs/deduplication/similar
    
    Find and group similar errors that may be duplicates.
    Uses error_hash and error_group_id for semantic similarity.
    
    Query Parameters:
      - project_name: Filter by project (required)
      - from, to: Date range
      - min_occurrences: Minimum occurrences to include (default: 2)
      - time_window: Time window in hours to consider duplicates (default: 24)
    
    Returns groups of similar errors with deduplication suggestions.
    """
    project_name = request.args.get("project_name")
    if not project_name:
        return jsonify({"error": "project_name parameter is required"}), 400
    
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    min_occurrences = max(1, int(request.args.get("min_occurrences", 2)))
    time_window_hours = max(1, int(request.args.get("time_window", 24)))
    
    try:
        filters = [
            "row_type = 'log'",
            "LOWER(project_name) = LOWER(%s)",
            "error IS NOT NULL",
            "error != ''"
        ]
        params = [project_name]
        
        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append("DATE(timestamp) >= %s")
            params.append(from_date_clean)
        
        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append("DATE(timestamp) <= %s")
            params.append(to_date_clean)
        
        where_clause = " AND ".join(filters)
        params.extend([min_occurrences, time_window_hours])
        
        query_sql = f"""
            WITH similar_groups AS (
                SELECT 
                    COALESCE(error_hash, MD5(LOWER(TRIM(error)))) as group_key,
                    error_group_id,
                    error_group_name,
                    COUNT(*) as occurrence_count,
                    MAX(timestamp) as latest_occurrence,
                    MIN(timestamp) as first_occurrence,
                    EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) / 3600 as time_span_hours,
                    STRING_AGG(DISTINCT file_name, ', ') as affected_files,
                    MAX(error) as sample_error,
                    MAX(error_detail) as sample_detail
                FROM {TABLE}
                WHERE {where_clause}
                GROUP BY group_key, error_group_id, error_group_name
                HAVING 
                    COUNT(*) >= %s
                    AND EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) / 3600 <= %s
            )
            SELECT *,
                CASE 
                    WHEN occurrence_count >= 10 THEN 'high'
                    WHEN occurrence_count >= 5 THEN 'medium'
                    ELSE 'low'
                END as duplication_severity
            FROM similar_groups
            ORDER BY occurrence_count DESC, latest_occurrence DESC
        """
        
        duplicates = query(query_sql, tuple(params))
        
        return jsonify({
            "duplicateGroups": serialize_rows(duplicates),
            "total_groups": len(duplicates),
            "summary": {
                "high_duplication": len([d for d in duplicates if d.get("duplication_severity") == "high"]),
                "medium_duplication": len([d for d in duplicates if d.get("duplication_severity") == "medium"]),
                "low_duplication": len([d for d in duplicates if d.get("duplication_severity") == "low"]),
            },
            "filters": {
                "project_name": project_name,
                "from": from_date,
                "to": to_date,
                "min_occurrences": min_occurrences,
                "time_window_hours": time_window_hours,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/logs/aggregation/summary")
@require_permission("logs:read")
def aggregation_summary():
    """
    GET /api/logs/aggregation/summary
    
    Get high-level aggregation summary with key metrics.
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - from, to: Date range
    
    Returns comprehensive summary with counts, rates, and trends.
    """
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    
    try:
        filters = ["row_type = 'log'"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append("DATE(timestamp) >= %s")
            params.append(from_date_clean)
        
        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append("DATE(timestamp) <= %s")
            params.append(to_date_clean)
        
        where_clause = " AND ".join(filters)
        
        query_sql = f"""
            SELECT 
                COUNT(*) as total_logs,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as total_errors,
                COUNT(CASE WHEN error IS NULL OR error = '' THEN 1 END) as total_success,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' AND error_status = 'resolved' THEN 1 END) as resolved_errors,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' AND (error_status IS NULL OR error_status != 'resolved') THEN 1 END) as active_errors,
                COUNT(DISTINCT error_hash) as unique_error_types,
                COUNT(DISTINCT project_name) as affected_projects,
                COUNT(DISTINCT file_name) as affected_files,
                MAX(timestamp) as latest_log_time,
                MIN(timestamp) as first_log_time,
                SUM(COALESCE(calculated_cost, 0)) as total_cost,
                AVG(COALESCE(input_tokens, 0)) as avg_input_tokens,
                AVG(COALESCE(output_tokens, 0)) as avg_output_tokens,
                ROUND(
                    100.0 * COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) / NULLIF(COUNT(*), 0),
                    2
                ) as error_rate_percent,
                ROUND(
                    100.0 * COUNT(CASE WHEN error_status = 'resolved' THEN 1 END) / 
                    NULLIF(COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END), 0),
                    2
                ) as resolution_rate_percent
            FROM {TABLE}
            WHERE {where_clause}
        """
        
        result = query(query_sql, tuple(params))
        summary = serialize_row(result[0]) if result else {}
        
        return jsonify({
            "summary": summary,
            "filters": {
                "project_name": project_name,
                "from": from_date,
                "to": to_date,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# VISUALIZATION DATA ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/visualization/timeline")
@require_permission("visualization:read")
def visualization_timeline():
    """
    GET /api/visualization/timeline
    
    Get timeline chart data showing error frequency over time.
    Optimized for line charts and area charts.
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - from, to: Date range (required)
      - bucket: hour, day, week (default: day)
      - metric: errors, total, error_rate (default: errors)
    
    Returns data formatted for Chart.js, Recharts, or similar libraries.
    """
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    bucket = request.args.get("bucket", "day")
    metric = request.args.get("metric", "errors")
    
    if not from_date or not to_date:
        return jsonify({"error": "from and to parameters are required"}), 400
    
    if bucket not in ["hour", "day", "week"]:
        return jsonify({"error": "bucket must be one of: hour, day, week"}), 400
    
    if metric not in ["errors", "total", "error_rate"]:
        return jsonify({"error": "metric must be one of: errors, total, error_rate"}), 400
    
    try:
        filters = ["row_type = 'log'"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
        to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
        filters.append("DATE(timestamp) >= %s")
        filters.append("DATE(timestamp) <= %s")
        params.extend([from_date_clean, to_date_clean])
        
        trunc_format = {"hour": "hour", "day": "day", "week": "week"}[bucket]
        where_clause = " AND ".join(filters)
        
        query_sql = f"""
            SELECT 
                DATE_TRUNC('{trunc_format}', timestamp) as time_bucket,
                COUNT(*) as total,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as errors,
                ROUND(
                    100.0 * COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) / NULLIF(COUNT(*), 0),
                    2
                ) as error_rate
            FROM {TABLE}
            WHERE {where_clause}
            GROUP BY time_bucket
            ORDER BY time_bucket ASC
        """
        
        time_series = query(query_sql, tuple(params))
        
        # Format for chart libraries
        labels = [row["time_bucket"].isoformat() if row["time_bucket"] else "" for row in time_series]
        data = [float(row[metric]) if row[metric] is not None else 0 for row in time_series]
        
        # Calculate statistics
        avg_value = sum(data) / len(data) if data else 0
        max_value = max(data) if data else 0
        min_value = min(data) if data else 0
        
        return jsonify({
            "chartData": {
                "labels": labels,
                "datasets": [{
                    "label": metric.replace("_", " ").title(),
                    "data": data,
                    "metric": metric,
                }]
            },
            "statistics": {
                "average": round(avg_value, 2),
                "maximum": round(max_value, 2),
                "minimum": round(min_value, 2),
                "dataPoints": len(data),
            },
            "config": {
                "bucket": bucket,
                "metric": metric,
                "from": from_date,
                "to": to_date,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/visualization/heatmap")
@require_permission("visualization:read")
def visualization_heatmap():
    """
    GET /api/visualization/heatmap
    
    Get heatmap data showing error density by hour of day and day of week.
    Perfect for identifying patterns in error occurrence times.
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - from, to: Date range (required)
    
    Returns matrix data for heatmap visualization.
    """
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    
    if not from_date or not to_date:
        return jsonify({"error": "from and to parameters are required"}), 400
    
    try:
        filters = ["row_type = 'log'", "error IS NOT NULL", "error != ''"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
        to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
        filters.append("DATE(timestamp) >= %s")
        filters.append("DATE(timestamp) <= %s")
        params.extend([from_date_clean, to_date_clean])
        
        where_clause = " AND ".join(filters)
        
        query_sql = f"""
            SELECT 
                EXTRACT(DOW FROM timestamp) as day_of_week,
                EXTRACT(HOUR FROM timestamp) as hour_of_day,
                COUNT(*) as error_count
            FROM {TABLE}
            WHERE {where_clause}
            GROUP BY day_of_week, hour_of_day
            ORDER BY day_of_week, hour_of_day
        """
        
        results = query(query_sql, tuple(params))
        
        # Build heatmap matrix (7 days x 24 hours)
        heatmap = [[0 for _ in range(24)] for _ in range(7)]
        max_count = 0
        
        for row in results:
            day = int(row["day_of_week"])  # 0=Sunday, 6=Saturday
            hour = int(row["hour_of_day"])  # 0-23
            count = int(row["error_count"])
            heatmap[day][hour] = count
            max_count = max(max_count, count)
        
        # Day labels
        day_labels = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        hour_labels = [f"{h:02d}:00" for h in range(24)]
        
        return jsonify({
            "heatmapData": {
                "matrix": heatmap,
                "xLabels": hour_labels,
                "yLabels": day_labels,
                "maxValue": max_count,
            },
            "insights": {
                "peakDay": day_labels[max(range(7), key=lambda d: sum(heatmap[d]))],
                "peakHour": f"{max(range(24), key=lambda h: sum(heatmap[d][h] for d in range(7))):02d}:00",
                "totalErrors": sum(sum(row) for row in heatmap),
            },
            "config": {
                "from": from_date,
                "to": to_date,
                "project_name": project_name,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/visualization/distribution")
@require_permission("visualization:read")
def visualization_distribution():
    """
    GET /api/visualization/distribution
    
    Get distribution data for pie charts and donut charts.
    Shows breakdown by project, error type, status, etc.
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - from, to: Date range
      - dimension: What to distribute by (project, status, file, error_type)
      - limit: Max slices (default: 10)
    
    Returns data formatted for pie/donut charts.
    """
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    dimension = request.args.get("dimension", "status")
    limit = min(20, max(1, int(request.args.get("limit", 10))))
    
    if dimension not in ["project", "status", "file", "error_type"]:
        return jsonify({"error": "dimension must be one of: project, status, file, error_type"}), 400
    
    try:
        filters = ["row_type = 'log'"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append("DATE(timestamp) >= %s")
            params.append(from_date_clean)
        
        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append("DATE(timestamp) <= %s")
            params.append(to_date_clean)
        
        where_clause = " AND ".join(filters)
        
        # Build query based on dimension
        if dimension == "status":
            query_sql = f"""
                SELECT 
                    CASE 
                        WHEN error IS NULL OR error = '' THEN 'Success'
                        WHEN error_status = 'resolved' THEN 'Resolved'
                        ELSE 'Active Error'
                    END as label,
                    COUNT(*) as value
                FROM {TABLE}
                WHERE {where_clause}
                GROUP BY label
                ORDER BY value DESC
            """
        elif dimension == "project":
            params.append(limit)
            query_sql = f"""
                SELECT 
                    project_name as label,
                    COUNT(*) as value
                FROM {TABLE}
                WHERE {where_clause}
                GROUP BY project_name
                ORDER BY value DESC
                LIMIT %s
            """
        elif dimension == "file":
            filters.append("file_name IS NOT NULL")
            where_clause = " AND ".join(filters)
            params.append(limit)
            query_sql = f"""
                SELECT 
                    file_name as label,
                    COUNT(*) as value
                FROM {TABLE}
                WHERE {where_clause}
                GROUP BY file_name
                ORDER BY value DESC
                LIMIT %s
            """
        elif dimension == "error_type":
            filters.append("error IS NOT NULL")
            filters.append("error != ''")
            where_clause = " AND ".join(filters)
            params.append(limit)
            query_sql = f"""
                SELECT 
                    COALESCE(error_group_name, SUBSTRING(error FROM 1 FOR 50)) as label,
                    COUNT(*) as value
                FROM {TABLE}
                WHERE {where_clause}
                GROUP BY label
                ORDER BY value DESC
                LIMIT %s
            """
        
        results = query(query_sql, tuple(params))
        
        labels = [row["label"] for row in results]
        values = [int(row["value"]) for row in results]
        total = sum(values)
        percentages = [round(100.0 * v / total, 2) if total > 0 else 0 for v in values]
        
        # Generate colors
        colors = [
            "#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF",
            "#FF9F40", "#FF6384", "#C9CBCF", "#4BC0C0", "#FF6384"
        ]
        
        return jsonify({
            "chartData": {
                "labels": labels,
                "datasets": [{
                    "data": values,
                    "backgroundColor": colors[:len(labels)],
                    "percentages": percentages,
                }]
            },
            "summary": {
                "total": total,
                "categories": len(labels),
                "topCategory": labels[0] if labels else None,
                "topCategoryCount": values[0] if values else 0,
            },
            "config": {
                "dimension": dimension,
                "limit": limit,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/visualization/bar-chart")
@require_permission("visualization:read")
def visualization_bar_chart():
    """
    GET /api/visualization/bar-chart
    
    Get bar chart data comparing metrics across categories.
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - from, to: Date range
      - category: Group by (project, file, error_type) - default: project
      - metric: What to measure (errors, total, error_rate) - default: errors
      - limit: Max bars (default: 10)
    
    Returns data formatted for bar charts.
    """
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    category = request.args.get("category", "project")
    metric = request.args.get("metric", "errors")
    limit = min(50, max(1, int(request.args.get("limit", 10))))
    
    if category not in ["project", "file", "error_type"]:
        return jsonify({"error": "category must be one of: project, file, error_type"}), 400
    
    if metric not in ["errors", "total", "error_rate"]:
        return jsonify({"error": "metric must be one of: errors, total, error_rate"}), 400
    
    try:
        filters = ["row_type = 'log'"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append("DATE(timestamp) >= %s")
            params.append(from_date_clean)
        
        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append("DATE(timestamp) <= %s")
            params.append(to_date_clean)
        
        where_clause = " AND ".join(filters)
        params.append(limit)
        
        # Build query based on category
        if category == "project":
            group_col = "project_name"
        elif category == "file":
            group_col = "file_name"
            filters.append("file_name IS NOT NULL")
            where_clause = " AND ".join(filters)
        elif category == "error_type":
            group_col = "COALESCE(error_group_name, SUBSTRING(error FROM 1 FOR 50))"
            filters.append("error IS NOT NULL")
            filters.append("error != ''")
            where_clause = " AND ".join(filters)
        
        query_sql = f"""
            SELECT 
                {group_col} as label,
                COUNT(*) as total,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as errors,
                ROUND(
                    100.0 * COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) / NULLIF(COUNT(*), 0),
                    2
                ) as error_rate
            FROM {TABLE}
            WHERE {where_clause}
            GROUP BY {group_col}
            ORDER BY {metric} DESC
            LIMIT %s
        """
        
        results = query(query_sql, tuple(params))
        
        labels = [row["label"] for row in results]
        data = [float(row[metric]) if row[metric] is not None else 0 for row in results]
        
        return jsonify({
            "chartData": {
                "labels": labels,
                "datasets": [{
                    "label": metric.replace("_", " ").title(),
                    "data": data,
                    "backgroundColor": "#36A2EB",
                }]
            },
            "summary": {
                "categories": len(labels),
                "highest": labels[0] if labels else None,
                "highestValue": data[0] if data else 0,
            },
            "config": {
                "category": category,
                "metric": metric,
                "limit": limit,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


@app.route("/api/visualization/sparklines")
@require_permission("visualization:read")
def visualization_sparklines():
    """
    GET /api/visualization/sparklines
    
    Get compact sparkline data for mini-charts in dashboards.
    Returns last 24 data points for quick trend visualization.
    
    Query Parameters:
      - project_name: Filter by project (required)
      - metric: errors, total, error_rate (default: errors)
      - points: Number of points (default: 24, max: 100)
    
    Returns minimal data array for sparkline charts.
    """
    project_name = request.args.get("project_name")
    if not project_name:
        return jsonify({"error": "project_name parameter is required"}), 400
    
    metric = request.args.get("metric", "errors")
    points = min(100, max(1, int(request.args.get("points", 24))))
    
    if metric not in ["errors", "total", "error_rate"]:
        return jsonify({"error": "metric must be one of: errors, total, error_rate"}), 400
    
    try:
        # Get last N hours of data
        query_sql = f"""
            SELECT 
                DATE_TRUNC('hour', timestamp) as time_bucket,
                COUNT(*) as total,
                COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as errors,
                ROUND(
                    100.0 * COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) / NULLIF(COUNT(*), 0),
                    2
                ) as error_rate
            FROM {TABLE}
            WHERE row_type = 'log' 
                AND LOWER(project_name) = LOWER(%s)
                AND timestamp >= NOW() - INTERVAL '%s hours'
            GROUP BY time_bucket
            ORDER BY time_bucket DESC
            LIMIT %s
        """
        
        results = query(query_sql, (project_name, points, points))
        
        # Reverse to get chronological order
        results.reverse()
        
        data = [float(row[metric]) if row[metric] is not None else 0 for row in results]
        timestamps = [row["time_bucket"].isoformat() if row["time_bucket"] else "" for row in results]
        
        # Calculate trend
        trend = "stable"
        if len(data) >= 2:
            recent_avg = sum(data[-5:]) / min(5, len(data))
            older_avg = sum(data[:5]) / min(5, len(data))
            if recent_avg > older_avg * 1.2:
                trend = "increasing"
            elif recent_avg < older_avg * 0.8:
                trend = "decreasing"
        
        return jsonify({
            "sparklineData": {
                "values": data,
                "timestamps": timestamps,
                "metric": metric,
            },
            "statistics": {
                "current": data[-1] if data else 0,
                "average": round(sum(data) / len(data), 2) if data else 0,
                "maximum": max(data) if data else 0,
                "minimum": min(data) if data else 0,
                "trend": trend,
            },
            "config": {
                "project_name": project_name,
                "metric": metric,
                "points": len(data),
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# ENHANCED STACK TRACE FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/stacktrace/parse/<log_id>")
@require_permission("stacktrace:read")
def parse_stacktrace_by_id(log_id):
    """Parse stack trace for a specific log. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)
    try:
        rows = query(
            f"SELECT error, error_detail FROM {TABLE} "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([log_id] + log_access_params),
        )
        if not rows:
            return jsonify({"error": "Not Found"}), 404
        row = rows[0]
        parsed = parse_and_enhance_stacktrace(row["error"], row.get("error_detail"), enhance_with_source=False)
        return jsonify({"log_id": log_id, "stacktrace": parsed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stacktrace/filter-frames", methods=["POST"])
@require_permission("stacktrace:read")
def filter_stack_frames():
    """Filter stack frames by criteria (hide library frames, show only app code, etc)."""
    body = request.get_json() or {}
    frames = body.get("frames", [])
    filter_type = body.get("filter_type", "app_only")
    app_paths = body.get("app_paths", ["app/", "src/", "lib/"])
    
    if filter_type == "app_only":
        filtered = [f for f in frames if any(path in f.get("file_path", "") for path in app_paths)]
    elif filter_type == "no_stdlib":
        stdlib_patterns = ["site-packages/", "node_modules/", "/usr/lib/", "/usr/local/"]
        filtered = [f for f in frames if not any(pat in f.get("file_path", "") for pat in stdlib_patterns)]
    else:
        filtered = frames
    
    return jsonify({"filtered_frames": filtered, "original_count": len(frames), "filtered_count": len(filtered)})


@app.route("/api/stacktrace/github-link", methods=["POST"])
@require_permission("stacktrace:read")
def generate_github_link():
    """Generate GitHub permalink for a stack frame."""
    body = request.get_json() or {}
    repo_url = body.get("repo_url", "").rstrip("/")
    file_path = body.get("file_path", "")
    line_number = body.get("line_number")
    branch = body.get("branch", "main")
    
    if not repo_url or not file_path:
        return jsonify({"error": "repo_url and file_path required"}), 400
    
    # Clean file path
    file_path = file_path.lstrip("/")
    
    # Generate GitHub URL
    if line_number:
        github_url = f"{repo_url}/blob/{branch}/{file_path}#L{line_number}"
    else:
        github_url = f"{repo_url}/blob/{branch}/{file_path}"
    
    return jsonify({"github_url": github_url, "file_path": file_path, "line": line_number})


@app.route("/api/stacktrace/similar")
@require_permission("stacktrace:read")
def find_similar_stacktraces():
    """Find logs with similar stack traces based on file paths and line numbers."""
    project_name = request.args.get("project_name")
    error_hash = request.args.get("error_hash")
    limit = min(50, max(1, int(request.args.get("limit", 10))))
    
    if not error_hash:
        return jsonify({"error": "error_hash parameter required"}), 400
    
    try:
        filters = ["row_type = 'log'", "error_hash = %s", "error_detail IS NOT NULL"]
        params = [error_hash]
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        params.append(limit)
        where_clause = " AND ".join(filters)
        
        rows = query(
            f"SELECT id, project_name, error, error_detail, file_name, timestamp "
            f"FROM {TABLE} WHERE {where_clause} ORDER BY timestamp DESC LIMIT %s",
            tuple(params)
        )
        
        return jsonify({"similar_errors": serialize_rows(rows), "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# LOG ANNOTATIONS & METADATA
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/logs/<log_id>/tags", methods=["POST"])
@require_permission("logs:annotate")
def add_log_tags(log_id):
    """Add tags to a log entry. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    body = request.get_json() or {}
    tags = body.get("tags", [])
    if not tags:
        return jsonify({"error": "tags array required"}), 400
    try:
        count = execute(
            f"UPDATE {TABLE} SET tags = %s "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([json.dumps(tags), log_id] + log_access_params),
        )
        if count == 0:
            return jsonify({"error": "Not Found"}), 404
        return jsonify({"log_id": log_id, "tags": tags})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/<log_id>/tags", methods=["GET"])
@require_permission("logs:read")
def get_log_tags(log_id):
    """Get tags for a log entry. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)
    try:
        rows = query(
            f"SELECT tags FROM {TABLE} "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([log_id] + log_access_params),
        )
        if not rows:
            return jsonify({"error": "Not Found"}), 404
        tags = json.loads(rows[0]["tags"]) if rows[0].get("tags") else []
        return jsonify({"log_id": log_id, "tags": tags})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/<log_id>/comments", methods=["POST"])
@require_permission("logs:annotate")
def add_log_comment(log_id):
    """Add a comment to a log entry. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    user_id = user["id"]
    body = request.get_json() or {}
    comment_text = body.get("comment", "").strip()
    if not comment_text:
        return jsonify({"error": "comment text required"}), 400

    try:
        log_rows = query(
            f"SELECT id FROM {TABLE} "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([log_id] + log_access_params),
        )
        if not log_rows:
            return jsonify({"error": "Not Found"}), 404

        comment_id = str(uuid.uuid4())
        comment = {
            "id": comment_id, "log_id": log_id, "user_id": user_id,
            "comment": comment_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        execute(
            f"INSERT INTO {TABLE} (id, row_type, log_ref_id, metadata, created_at) "
            f"VALUES (%s, 'comment', %s, %s, NOW())",
            (comment_id, log_id, json.dumps(comment)),
        )
        return jsonify({"comment": comment}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/<log_id>/comments", methods=["GET"])
@require_permission("logs:read")
def get_log_comments(log_id):
    """Get comments for a log entry. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)
    try:
        log_rows = query(
            f"SELECT id FROM {TABLE} "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([log_id] + log_access_params),
        )
        if not log_rows:
            return jsonify({"error": "Not Found"}), 404

        rows = query(
            f"SELECT metadata, created_at FROM {TABLE} "
            f"WHERE row_type = 'comment' AND log_ref_id = %s ORDER BY created_at DESC",
            (log_id,),
        )
        comments = []
        for row in rows:
            if row.get("metadata"):
                comment = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                comments.append(comment)
        return jsonify({"log_id": log_id, "comments": comments, "count": len(comments)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/<log_id>/assign", methods=["POST"])
@require_permission("logs:annotate")
def assign_log(log_id):
    """Assign a log to a team member. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)
    body = request.get_json() or {}
    assignee = body.get("assignee", "").strip()
    if not assignee:
        return jsonify({"error": "assignee required"}), 400
    try:
        count = execute(
            f"UPDATE {TABLE} SET assigned_to = %s, assigned_at = NOW() "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([assignee, log_id] + log_access_params),
        )
        if count == 0:
            return jsonify({"error": "Not Found"}), 404
        return jsonify({"log_id": log_id, "assigned_to": assignee})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/<log_id>/priority", methods=["POST"])
@require_permission("logs:annotate")
def set_log_priority(log_id):
    """Set priority for a log entry. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)
    body = request.get_json() or {}
    priority = body.get("priority", "medium")
    if priority not in ["low", "medium", "high", "critical"]:
        return jsonify({"error": "priority must be: low, medium, high, critical"}), 400
    try:
        count = execute(
            f"UPDATE {TABLE} SET priority = %s "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([priority, log_id] + log_access_params),
        )
        if count == 0:
            return jsonify({"error": "Not Found"}), 404
        return jsonify({"log_id": log_id, "priority": priority})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/by-assignee/<assignee>")
@require_permission("logs:read")
def get_logs_by_assignee(assignee):
    """Get all logs assigned to a specific team member."""
    status = request.args.get("status", "active")
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    
    try:
        filters = ["row_type = 'log'", "assigned_to = %s"]
        params = [assignee]
        
        if status == "active":
            filters.append("(error_status IS NULL OR error_status != 'resolved')")
        elif status == "resolved":
            filters.append("error_status = 'resolved'")
        
        params.append(limit)
        where_clause = " AND ".join(filters)
        
        rows = query(
            f"SELECT id, project_name, file_name, error, timestamp, priority, error_status "
            f"FROM {TABLE} WHERE {where_clause} ORDER BY priority DESC, timestamp DESC LIMIT %s",
            tuple(params)
        )
        
        return jsonify({"assignee": assignee, "logs": serialize_rows(rows), "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# SMART NOTIFICATIONS SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/notifications/webhooks", methods=["POST"])
@require_permission("notifications:write")
def create_webhook():
    """Create a webhook for notifications (Slack, Teams, Discord, etc)."""
    body = request.get_json() or {}
    webhook_url = body.get("webhook_url", "").strip()
    webhook_type = body.get("type", "slack")
    project_name = body.get("project_name")
    trigger = body.get("trigger", "new_error")
    
    if not webhook_url:
        return jsonify({"error": "webhook_url required"}), 400
    
    try:
        webhook_id = str(uuid.uuid4())
        webhook_data = {
            "id": webhook_id,
            "url": webhook_url,
            "type": webhook_type,
            "project_name": project_name,
            "trigger": trigger,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        execute(
            f"INSERT INTO {TABLE} (id, row_type, metadata) VALUES (%s, 'webhook', %s)",
            (webhook_id, json.dumps(webhook_data))
        )
        
        return jsonify({"webhook": webhook_data}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/notifications/webhooks", methods=["GET"])
@require_permission("notifications:read")
def list_webhooks():
    """List all configured webhooks."""
    try:
        rows = query(f"SELECT id, metadata FROM {TABLE} WHERE row_type = 'webhook'")
        webhooks = [json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"] for r in rows]
        return jsonify({"webhooks": webhooks, "count": len(webhooks)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/notifications/webhooks/<webhook_id>", methods=["DELETE"])
@require_permission("notifications:write")
def delete_webhook(webhook_id):
    """Delete a webhook."""
    try:
        execute(f"DELETE FROM {TABLE} WHERE row_type = 'webhook' AND id = %s", (webhook_id,))
        return jsonify({"deleted": True, "webhook_id": webhook_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/notifications/alert-rules", methods=["POST"])
@require_permission("alerts:write")
def create_alert_rule():
    """Create an alert rule based on thresholds."""
    body = request.get_json() or {}
    rule_name = body.get("name", "").strip()
    condition = body.get("condition", {})
    action = body.get("action", {})
    
    if not rule_name or not condition:
        return jsonify({"error": "name and condition required"}), 400
    
    try:
        rule_id = str(uuid.uuid4())
        rule_data = {
            "id": rule_id,
            "name": rule_name,
            "condition": condition,
            "action": action,
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        execute(
            f"INSERT INTO {TABLE} (id, row_type, metadata) VALUES (%s, 'alert_rule', %s)",
            (rule_id, json.dumps(rule_data))
        )
        
        return jsonify({"rule": rule_data}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/notifications/alert-rules", methods=["GET"])
@require_permission("alerts:read")
def list_alert_rules():
    """List all alert rules."""
    try:
        rows = query(f"SELECT id, metadata FROM {TABLE} WHERE row_type = 'alert_rule'")
        rules = [json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"] for r in rows]
        return jsonify({"rules": rules, "count": len(rules)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# LOG RETENTION & MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/logs/retention/archive", methods=["POST"])
@require_auth(roles=["admin"])
def archive_old_logs():
    """Archive logs older than specified days."""
    body = request.get_json() or {}
    days = body.get("days", 90)
    project_name = body.get("project_name")
    
    try:
        filters = ["row_type = 'log'", f"timestamp < NOW() - INTERVAL '{days} days'"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        where_clause = " AND ".join(filters)
        
        # Mark as archived instead of deleting
        count = execute(
            f"UPDATE {TABLE} SET archived = TRUE, archived_at = NOW() WHERE {where_clause}",
            tuple(params) if params else None
        )
        
        return jsonify({"archived": count, "days": days, "project_name": project_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/retention/cleanup", methods=["POST"])
@require_auth(roles=["admin"])
def cleanup_old_logs():
    """Permanently delete archived logs older than specified days."""
    body = request.get_json() or {}
    days = body.get("days", 365)
    
    try:
        count = execute(
            f"DELETE FROM {TABLE} WHERE row_type = 'log' AND archived = TRUE AND archived_at < NOW() - INTERVAL '{days} days'"
        )
        
        return jsonify({"deleted": count, "days": days})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/bulk/resolve", methods=["POST"])
@require_permission("errors:resolve")
def bulk_resolve_logs():
    """Bulk resolve multiple logs. Scoped by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)

    body = request.get_json() or {}
    log_ids = body.get("log_ids", [])
    if not log_ids:
        return jsonify({"error": "log_ids array required"}), 400

    try:
        placeholders = ",".join(["%s"] * len(log_ids))
        count = execute(
            f"UPDATE {TABLE} SET error_status = 'resolved', resolved_at = NOW() "
            f"WHERE row_type = 'log' AND ({log_access_cond}) "
            f"AND id IN ({placeholders})",
            tuple(log_access_params + list(log_ids)),
        )
        return jsonify({"resolved": count, "log_ids": log_ids})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/retention/policy", methods=["GET", "POST"])
@require_auth(roles=["admin"])
def manage_retention_policy():
    """Get or set retention policy for projects."""
    if request.method == "GET":
        try:
            rows = query(f"SELECT metadata FROM {TABLE} WHERE row_type = 'retention_policy'")
            policies = [json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"] for r in rows]
            return jsonify({"policies": policies})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        body = request.get_json() or {}
        project_name = body.get("project_name", "*")
        retention_days = body.get("retention_days", 90)
        
        try:
            policy_id = str(uuid.uuid4())
            policy_data = {
                "id": policy_id,
                "project_name": project_name,
                "retention_days": retention_days,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            execute(
                f"INSERT INTO {TABLE} (id, row_type, metadata) VALUES (%s, 'retention_policy', %s)",
                (policy_id, json.dumps(policy_data))
            )
            
            return jsonify({"policy": policy_data}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE METRICS TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/metrics/llm-usage")
@require_permission("metrics:read")
def get_llm_usage_metrics():
    """Get LLM usage statistics and costs."""
    project_name = request.args.get("project_name")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    
    try:
        filters = ["row_type = 'log'", "llm_usage IS NOT NULL"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        if from_date:
            filters.append("DATE(timestamp) >= %s")
            params.append(from_date.split('T')[0] if 'T' in from_date else from_date)
        
        if to_date:
            filters.append("DATE(timestamp) <= %s")
            params.append(to_date.split('T')[0] if 'T' in to_date else to_date)
        
        where_clause = " AND ".join(filters)
        
        query_sql = f"""
            SELECT 
                COUNT(*) as total_requests,
                SUM(COALESCE(input_tokens, 0)) as total_input_tokens,
                SUM(COALESCE(output_tokens, 0)) as total_output_tokens,
                SUM(COALESCE(calculated_cost, 0)) as total_cost,
                AVG(COALESCE(input_tokens, 0)) as avg_input_tokens,
                AVG(COALESCE(output_tokens, 0)) as avg_output_tokens,
                AVG(COALESCE(calculated_cost, 0)) as avg_cost_per_request,
                STRING_AGG(DISTINCT llm_usage, ', ') as models_used
            FROM {TABLE}
            WHERE {where_clause}
        """
        
        result = query(query_sql, tuple(params) if params else None)
        metrics = serialize_row(result[0]) if result else {}
        
        return jsonify({"metrics": metrics})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/api-performance")
@require_permission("metrics:read")
def get_api_performance_metrics():
    """Get API endpoint performance metrics."""
    # This would track response times if we add middleware to log them
    return jsonify({
        "message": "API performance tracking requires middleware setup",
        "endpoints": []
    })


@app.route("/api/metrics/error-resolution-time")
@require_permission("metrics:read")
def get_error_resolution_metrics():
    """Calculate average time to resolve errors."""
    project_name = request.args.get("project_name")
    
    try:
        filters = [
            "row_type = 'log'",
            "error_status = 'resolved'",
            "resolved_at IS NOT NULL"
        ]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        where_clause = " AND ".join(filters)
        
        query_sql = f"""
            SELECT 
                COUNT(*) as resolved_count,
                AVG(EXTRACT(EPOCH FROM (resolved_at - timestamp)) / 3600) as avg_hours_to_resolve,
                MIN(EXTRACT(EPOCH FROM (resolved_at - timestamp)) / 3600) as min_hours_to_resolve,
                MAX(EXTRACT(EPOCH FROM (resolved_at - timestamp)) / 3600) as max_hours_to_resolve
            FROM {TABLE}
            WHERE {where_clause}
        """
        
        result = query(query_sql, tuple(params) if params else None)
        metrics = serialize_row(result[0]) if result else {}
        
        return jsonify({"resolution_metrics": metrics})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT ENRICHMENT
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/logs/<log_id>/context", methods=["POST"])
@require_permission("logs:annotate")
def add_log_context(log_id):
    """Add context to a log entry. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)
    body = request.get_json() or {}
    context_data = {
        "session_id": body.get("session_id"),
        "user_id": body.get("user_id"),
        "request_id": body.get("request_id"),
        "environment": body.get("environment"),
        "browser": body.get("browser"),
        "os": body.get("os"),
        "app_version": body.get("app_version"),
        "git_commit": body.get("git_commit"),
        "deployment_id": body.get("deployment_id"),
        "custom_data": body.get("custom_data", {}),
    }
    try:
        count = execute(
            f"UPDATE {TABLE} SET context_data = %s "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([json.dumps(context_data), log_id] + log_access_params),
        )
        if count == 0:
            return jsonify({"error": "Not Found"}), 404
        return jsonify({"log_id": log_id, "context": context_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/<log_id>/context", methods=["GET"])
@require_permission("logs:read")
def get_log_context(log_id):
    """Get context for a log entry. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)
    try:
        rows = query(
            f"SELECT context_data FROM {TABLE} "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([log_id] + log_access_params),
        )
        if not rows:
            return jsonify({"error": "Not Found"}), 404
        context = json.loads(rows[0]["context_data"]) if rows[0].get("context_data") else {}
        return jsonify({"log_id": log_id, "context": context})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/by-session/<session_id>")
@require_permission("logs:read")
def get_logs_by_session(session_id):
    """Get all logs for a specific user session."""
    try:
        rows = query(
            f"SELECT id, project_name, file_name, error, timestamp FROM {TABLE} "
            f"WHERE row_type = 'log' AND context_data::jsonb->>'session_id' = %s "
            f"ORDER BY timestamp ASC",
            (session_id,)
        )
        
        return jsonify({"session_id": session_id, "logs": serialize_rows(rows), "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs/by-deployment/<deployment_id>")
@require_permission("logs:read")
def get_logs_by_deployment(deployment_id):
    """Get all logs for a specific deployment."""
    try:
        rows = query(
            f"SELECT id, project_name, file_name, error, timestamp FROM {TABLE} "
            f"WHERE row_type = 'log' AND context_data::jsonb->>'deployment_id' = %s "
            f"ORDER BY timestamp DESC",
            (deployment_id,)
        )
        
        return jsonify({"deployment_id": deployment_id, "logs": serialize_rows(rows), "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/visualization/gauge")
@require_permission("visualization:read")
def visualization_gauge():
    """
    GET /api/visualization/gauge
    
    Get gauge/meter data for dashboard KPI widgets.
    Shows current value vs targets/thresholds.
    
    Query Parameters:
      - project_name: Filter by project (optional)
      - metric: error_rate, resolution_rate (default: error_rate)
      - period: Time period in hours (default: 24)
    
    Returns gauge data with thresholds and current value.
    """
    project_name = request.args.get("project_name")
    metric = request.args.get("metric", "error_rate")
    period = max(1, int(request.args.get("period", 24)))
    
    if metric not in ["error_rate", "resolution_rate"]:
        return jsonify({"error": "metric must be one of: error_rate, resolution_rate"}), 400
    
    try:
        filters = ["row_type = 'log'", f"timestamp >= NOW() - INTERVAL '{period} hours'"]
        params = []
        
        if project_name:
            filters.append("LOWER(project_name) = LOWER(%s)")
            params.append(project_name)
        
        where_clause = " AND ".join(filters)
        
        if metric == "error_rate":
            query_sql = f"""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as errors,
                    ROUND(
                        100.0 * COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) / NULLIF(COUNT(*), 0),
                        2
                    ) as value
                FROM {TABLE}
                WHERE {where_clause}
            """
        else:  # resolution_rate
            query_sql = f"""
                SELECT 
                    COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END) as total_errors,
                    COUNT(CASE WHEN error_status = 'resolved' THEN 1 END) as resolved,
                    ROUND(
                        100.0 * COUNT(CASE WHEN error_status = 'resolved' THEN 1 END) / 
                        NULLIF(COUNT(CASE WHEN error IS NOT NULL AND error != '' THEN 1 END), 0),
                        2
                    ) as value
                FROM {TABLE}
                WHERE {where_clause}
            """
        
        result = query(query_sql, tuple(params))
        row = result[0] if result else {}
        
        value = float(row.get("value", 0))
        
        # Define thresholds
        if metric == "error_rate":
            # Lower is better for error rate
            thresholds = {
                "excellent": 2.0,
                "good": 5.0,
                "warning": 10.0,
                "critical": 20.0,
            }
            status = "critical" if value > 20 else "warning" if value > 10 else "good" if value > 5 else "excellent"
        else:  # resolution_rate
            # Higher is better for resolution rate
            thresholds = {
                "excellent": 80.0,
                "good": 60.0,
                "warning": 40.0,
                "critical": 20.0,
            }
            status = "excellent" if value > 80 else "good" if value > 60 else "warning" if value > 40 else "critical"
        
        return jsonify({
            "gaugeData": {
                "value": value,
                "min": 0,
                "max": 100,
                "unit": "%",
                "status": status,
                "thresholds": thresholds,
            },
            "metadata": {
                "metric": metric,
                "period_hours": period,
                "project_name": project_name,
            }
        })
    except Exception as e:
        import traceback as _tb
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/projects/<path:name>/logs")
@require_permission("projects:read")
def project_logs(name):
    """
    GET /api/projects/<name>/logs

    Access by role:
      admin/viewer → can access any project by name
      developer    → only projects they own or have an assigned log in
    Log rows are further scoped by the same log access condition.
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    user_id  = user["id"]
    role     = user.get("role", "")

    project_name = name
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    offset = (page - 1) * limit

    from_date      = request.args.get("from")
    to_date        = request.args.get("to")
    search         = request.args.get("search")
    regex_pattern  = request.args.get("regex")
    severity       = request.args.get("severity")
    file_path      = request.args.get("file_path")
    status_filter  = request.args.get("status")

    print(f"[DEBUG] Advanced filters - from: {from_date}, to: {to_date}, search: {search}, "
          f"regex: {regex_pattern}, severity: {severity}, file_path: {file_path}, status: {status_filter}")

    try:
        # ── Step 1: verify the caller can access this project ─────────────────
        access_cond, access_params = _build_project_access_condition(user)
        proj_rows = query(
            f"SELECT id, project_name FROM {TABLE} "
            f"WHERE row_type = 'project' "
            f"  AND LOWER(project_name) = LOWER(%s) "
            f"  AND ({access_cond})",
            [project_name] + access_params,
        )

        if not proj_rows:
            return jsonify({
                "exists": False, "tableName": project_name.replace(" ", "_"),
                "total": 0, "filesProcessed": 0, "success": 0, "failure": 0, "resolved": 0,
                "totalCost": None, "errors": [], "logs": [],
                "pagination": {
                    "currentPage": 1, "totalPages": 0, "totalRecords": 0,
                    "limit": limit, "hasNextPage": False, "hasPreviousPage": False,
                },
            })

        authorized_project_id = proj_rows[0]["id"]

        # ── Step 2: build log-level access condition using the role helper ───
        log_access_cond, log_access_params = _build_log_access_condition(user)

        # ── Step 3: optional filters ──────────────────────────────────────────
        filters = []
        count_params  = [authorized_project_id] + log_access_params
        query_params  = [authorized_project_id] + log_access_params

        if from_date:
            from_date_clean = from_date.split('T')[0] if 'T' in from_date else from_date
            filters.append(" AND DATE(timestamp) >= %s")
            count_params.append(from_date_clean)
            query_params.append(from_date_clean)

        if to_date:
            to_date_clean = to_date.split('T')[0] if 'T' in to_date else to_date
            filters.append(" AND DATE(timestamp) <= %s")
            count_params.append(to_date_clean)
            query_params.append(to_date_clean)

        if search:
            filters.append(
                " AND (LOWER(error) LIKE LOWER(%s) OR LOWER(error_detail) LIKE LOWER(%s) "
                "OR LOWER(file_name) LIKE LOWER(%s))"
            )
            sp = f"%{search}%"
            count_params.extend([sp, sp, sp])
            query_params.extend([sp, sp, sp])

        if regex_pattern:
            try:
                re.compile(regex_pattern)
                filters.append(" AND (error ~* %s OR error_detail ~* %s)")
                count_params.extend([regex_pattern, regex_pattern])
                query_params.extend([regex_pattern, regex_pattern])
            except re.error as rx:
                return jsonify({"error": f"Invalid regex pattern: {rx}"}), 400

        if severity:
            filters.append(" AND severity = %s")
            count_params.append(severity)
            query_params.append(severity)

        if file_path:
            filters.append(" AND LOWER(file_name) LIKE LOWER(%s)")
            count_params.append(f"%{file_path}%")
            query_params.append(f"%{file_path}%")

        status_clause = ""
        if status_filter == "errors":
            status_clause = " AND error IS NOT NULL AND error != ''"
        elif status_filter == "resolved":
            status_clause = " AND error IS NOT NULL AND error != '' AND error_status = 'resolved'"
        elif status_filter == "active":
            status_clause = " AND error IS NOT NULL AND error != '' AND (error_status IS NULL OR error_status != 'resolved')"
        elif status_filter == "success":
            status_clause = " AND (error IS NULL OR error = '')"

        combined = "".join(filters) + status_clause
        base_cond = f"row_type = 'log' AND project_id = %s AND {log_access_cond}"

        # Total count
        count_result = query(
            f"SELECT COUNT(*) as total FROM {TABLE} WHERE {base_cond}{combined}",
            tuple(count_params),
        )
        total_records = int(count_result[0].get("total", 0)) if count_result else 0
        total_pages   = (total_records + limit - 1) // limit if limit > 0 else 0

        query_params.extend([limit, offset])
        logs = query(
            f"SELECT file_name, timestamp, success_count, failure_count, error, "
            f"llm_usage, input_tokens, output_tokens, calculated_cost, word_count, file_type, "
            f"error_status, resolved_at, reopened_at, error_detail "
            f"FROM {TABLE} WHERE {base_cond}{combined} "
            f"ORDER BY timestamp DESC LIMIT %s OFFSET %s",
            tuple(query_params),
        )

        # Status totals
        totals_result = query(
            f"SELECT "
            f"  COUNT(*) FILTER (WHERE error IS NULL OR error = '') AS success, "
            f"  COUNT(*) FILTER (WHERE error IS NOT NULL AND error != '' AND "
            f"    (error_status IS NULL OR error_status != 'resolved')) AS failure, "
            f"  COUNT(*) FILTER (WHERE error IS NOT NULL AND error != '' AND error_status = 'resolved') AS resolved "
            f"FROM {TABLE} WHERE {base_cond}{''.join(filters)}",
            tuple(count_params),
        )
        totals_row = totals_result[0] if totals_result else {}
        success  = int(totals_row.get("success", 0))
        failure  = int(totals_row.get("failure", 0))
        resolved = int(totals_row.get("resolved", 0))

        active_logs = [
            r for r in logs
            if r.get("error") and r.get("error") != "" and r.get("error_status") != "resolved"
        ]
        raw_cost   = sum(float(r.get("calculated_cost") or 0) for r in logs)
        total_cost = f"${raw_cost:.4f}" if raw_cost > 0 else None
        errors     = [{"timestamp": str(r["timestamp"]), "message": r["error"]} for r in active_logs]
        visible_logs = [
            {**r, "isResolved": bool(
                r.get("error") and r.get("error") != "" and r.get("error_status") == "resolved"
            )}
            for r in logs
        ]

        return jsonify({
            "exists": True, "tableName": project_name.replace(" ", "_"),
            "total": total_records, "filesProcessed": total_records,
            "success": success, "failure": failure, "resolved": resolved,
            "totalCost": total_cost,
            "errors": serialize_rows(errors), "logs": serialize_rows(visible_logs),
            "appliedFilters": {
                "from": from_date, "to": to_date, "search": search,
                "regex": regex_pattern, "severity": severity,
                "file_path": file_path, "status": status_filter,
            },
            "pagination": {
                "currentPage": page, "totalPages": total_pages,
                "totalRecords": total_records, "limit": limit,
                "hasNextPage": page < total_pages, "hasPreviousPage": page > 1,
            },
        })
    except Exception as e:
        import traceback as _tb
        tb_str = _tb.format_exc()
        request_id = g.get("request_id", "unknown")
        print(f"[req:{request_id}] [Projects:logs] ERROR: {type(e).__name__}: {e}\n{tb_str}")
        return jsonify({
            "success": False, "exists": False,
            "error": "Failed to load logs", "data": [],
            "trace_id": request_id, "fallback": True,
        }), 200


@app.route("/api/projects/<path:name>/errors", methods=["POST"])
@require_permission("errors:resolve")
def upsert_project_error(name):
    """
    Upsert an error log.
    admin      → can write to any project
    developer  → can write to projects they own or have assigned logs in
    viewer     → blocked by permission (errors:resolve not in viewer set)
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = user["id"]
    role    = user.get("role", "")

    try:
        # Verify the caller can access this project using the role helper
        access_cond, access_params = _build_project_access_condition(user)
        proj_rows = query(
            f"SELECT id, project_name, owner_user_id FROM {TABLE} "
            f"WHERE row_type = 'project' "
            f"  AND LOWER(project_name) = LOWER(%s) "
            f"  AND ({access_cond})",
            [name] + access_params,
        )
        if not proj_rows:
            return jsonify({"error": "Not Found"}), 404

        proj = proj_rows[0]
        authorized_project_id = proj["id"]
        proj_owner_id         = proj["owner_user_id"]

        body         = request.get_json() or {}
        file_name    = str(body.get("file_name", ""))
        error_detail = (body.get("error_detail") or "").strip() or None
        short_error  = str(body.get("error", "")).strip()

        if error_detail:
            lines = [l.strip() for l in error_detail.split("\n") if l.strip()]
            if lines:
                derived = lines[-1].split(":")[0].strip()
                if derived:
                    short_error = derived

        if not short_error:
            return jsonify({"error": "error or error_detail is required"}), 400

        error_hash = derive_error_hash(short_error, error_detail)

        # Update existing row — scoped to this project only
        updated = execute_returning(
            f"UPDATE {TABLE} SET failure_count = failure_count + 1, file_name = %s, "
            f"timestamp = NOW(), error_detail = COALESCE(%s, error_detail), "
            f"error_status = CASE WHEN error_status = 'resolved' THEN 'reopened' ELSE error_status END, "
            f"reopened_at = CASE WHEN error_status = 'resolved' THEN NOW() ELSE reopened_at END, "
            f"resolved_at = CASE WHEN error_status = 'resolved' THEN NULL ELSE resolved_at END "
            f"WHERE row_type = 'log' AND error_hash = %s AND project_id = %s "
            f"RETURNING id, error_status, failure_count",
            (file_name, error_detail, error_hash, authorized_project_id),
        )
        if updated:
            action = "reopened" if updated["error_status"] == "reopened" else "updated"
            return jsonify({"action": action, "error_status": updated["error_status"],
                            "failure_count": updated["failure_count"]})

        # Insert new row — inherit owner from project row
        inserted = execute_returning(
            f"INSERT INTO {TABLE} (id, row_type, project_name, project_id, owner_user_id, "
            f"file_name, timestamp, success_count, failure_count, error, error_detail, "
            f"error_hash, error_status) "
            f"VALUES (%s, 'log', %s, %s, %s, %s, NOW(), 0, 1, %s, %s, %s, 'open') "
            f"RETURNING id, error_status, failure_count",
            (str(uuid.uuid4()), proj["project_name"], authorized_project_id,
             proj_owner_id, file_name, short_error, error_detail, error_hash),
        )
        return jsonify({"action": "inserted", "error_status": inserted["error_status"],
                        "failure_count": inserted["failure_count"]})
    except Exception as e:
        print(f"[Projects] upsert error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects/<path:name>/errors/<hash>/resolve", methods=["PATCH"])
@require_permission("errors:resolve")
def resolve_project_error(name, hash):
    """Resolve an error. admin can resolve any; developer can resolve assigned/owned."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = user["id"]
    role    = user.get("role", "")

    try:
        # Verify project access using the role helper
        access_cond, access_params = _build_project_access_condition(user)
        proj_rows = query(
            f"SELECT id FROM {TABLE} "
            f"WHERE row_type = 'project' "
            f"  AND LOWER(project_name) = LOWER(%s) "
            f"  AND ({access_cond})",
            [name] + access_params,
        )
        if not proj_rows:
            return jsonify({"error": "Not Found"}), 404

        authorized_project_id = proj_rows[0]["id"]
        log_access_cond, log_access_params = _build_log_access_condition(user)

        execute(
            f"UPDATE {TABLE} SET error_status = %s, resolved_at = NOW(), "
            f"reopened_at = NULL "
            f"WHERE row_type = 'log' AND error_hash = %s "
            f"  AND project_id = %s AND ({log_access_cond})",
            tuple(["resolved", hash, authorized_project_id] + log_access_params),
        )
        return jsonify({"action": "resolved"})
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/projects/<path:name>/live", methods=["PATCH"])
@require_auth(roles=["admin"])
def toggle_project_live(name):
    """Toggle live flag. Admin only — can toggle any project."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json() or {}
    is_live = body.get("is_live")
    if not isinstance(is_live, bool):
        return jsonify({"error": "Body must contain { is_live: true | false }"}), 400
    try:
        # Admin sees all projects (TRUE condition) — use helper
        access_cond, access_params = _build_project_access_condition(user)
        row = execute_returning(
            f"UPDATE {TABLE} SET is_live = %s "
            f"WHERE row_type = 'project' AND LOWER(project_name) = LOWER(%s) "
            f"  AND ({access_cond}) "
            f"RETURNING id, project_name AS name, category, is_live",
            tuple([is_live, name] + access_params),
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
                   calculated_cost, llm_usage,
                   project_id=None, owner_user_id=None):
    """Insert a log row into projects_data and return it.

    project_id and owner_user_id are always read from the project row by the
    caller — never accepted directly from the ingest payload.
    """
    row_id = str(uuid.uuid4())
    return execute_returning(
        f"INSERT INTO {TABLE} ("
        f"id, row_type, project_name, project_id, owner_user_id, file_name, timestamp, "
        f"success_count, failure_count, error, error_detail, error_hash, error_status, "
        f"word_count, file_type, input_tokens, output_tokens, calculated_cost, llm_usage"
        f") VALUES (%s,'log',%s,%s,%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        f"RETURNING id, project_name, file_name, error, error_detail, "
        f"error_hash, error_status, success_count, failure_count, timestamp",
        (row_id, project_name, project_id, owner_user_id, file_name,
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
    """
    Return (project_row_dict) if the project exists, else None.

    For machine-to-machine ingest the project must already exist — we do NOT
    auto-register projects without an owner.  owner_user_id and project_id are
    read from the project row and stamped onto every log; they are never
    accepted from the incoming payload.

    Legacy NULL-owner projects are excluded — they must not receive new logs.
    """
    rows = query(
        f"SELECT id, project_name, owner_user_id "
        f"FROM {TABLE} "
        f"WHERE row_type = 'project' "
        f"  AND LOWER(project_name) = LOWER(%s) "
        f"  AND owner_user_id IS NOT NULL",
        (project_name,),
    )
    if rows:
        return dict(rows[0])

    # Check if a legacy NULL-owner project exists and warn
    legacy = query(
        f"SELECT id FROM {TABLE} "
        f"WHERE row_type = 'project' AND LOWER(project_name) = LOWER(%s) LIMIT 1",
        (project_name,),
    )
    if legacy:
        print(
            f"[Ingest] WARNING: project '{project_name}' exists but has NULL owner_user_id — "
            f"refusing ingest to prevent unowned log creation."
        )
        return None

    # Project does not exist at all — cannot ingest without an owner
    print(
        f"[Ingest] WARNING: project '{project_name}' not found. "
        f"Ingest rejected — create the project via POST /api/projects first."
    )
    return None


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
    """
    POST /api/ingest/error — machine-to-machine error ingestion.

    project_id and owner_user_id are resolved from the project row in the
    database.  They are NEVER accepted from the incoming payload.
    Projects without an owner (NULL owner_user_id) are rejected.
    """
    body = request.get_json() or {}
    project_name = str(body.get("project_name", "")).strip()
    error = str(body.get("error", "")).strip()
    if not project_name:
        return jsonify({"error": "project_name is required"}), 400
    if not error:
        return jsonify({"error": "error is required"}), 400
    if error.startswith("{") and ("workflowId" in error or "workflowStatus" in error):
        return jsonify({"error": "Invalid error value — workflow/system response passed"}), 400

    proj = _validate_project(project_name)
    if not proj:
        return jsonify({"error": f"Project '{project_name}' not found or has no owner. "
                                  f"Create it via POST /api/projects first."}), 400

    actual_name   = proj["project_name"]
    project_id    = proj["id"]
    owner_user_id = proj["owner_user_id"]

    opt = _parse_optional(body)

    # Smart extraction: auto-extract stack trace from error field
    error_detail = opt.get("error_detail")
    if not error_detail:
        short_error, extracted_trace = _smart_extract_error_detail(error)
        if extracted_trace:
            error_detail = extracted_trace
            error = short_error
            print(f'[Ingest] Auto-extracted stack trace for project="{actual_name}"')
        else:
            print(f'[Ingest] WARNING: No stack trace found for project="{actual_name}"')
    else:
        print(f'[Ingest] error_detail received ({len(error_detail)} chars) for project="{actual_name}"')

    error_hash = derive_error_hash(error, error_detail)

    try:
        inserted = _insert_result(
            actual_name, opt["file_name"], error, error_detail,
            error_hash, "open",
            opt.get("success_count", 0), opt.get("failure_count", 1),
            opt["word_count"], opt["file_type"], opt["input_tokens"],
            opt["output_tokens"], opt["calculated_cost"], opt["llm_usage"],
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
        print(f'[Ingest] Error row → "{actual_name}" owner={owner_user_id} | {error}')
        row = serialize_row(inserted)

        try:
            sse_manager.broadcast_log(row)
        except Exception as _sse_exc:
            logger.warning(f"[Ingest] SSE broadcast failed (non-fatal): {_sse_exc}")

        try:
            from ai.error_grouper import classify_error as _classify
            _classify(log_id=inserted["id"], error_message=error,
                      project_name=actual_name, error_detail=error_detail)
        except Exception as _cexc:
            logger.warning("[Ingest] classify_error failed (non-fatal): %s", _cexc)

        return jsonify({"success": True, "type": "error", **row}), 201
    except Exception as e:
        print(f"[Ingest] error: {e}")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


@app.route("/api/ingest/log", methods=["POST"])
def ingest_log():
    """
    POST /api/ingest/log — machine-to-machine log ingestion (error or success).

    project_id and owner_user_id resolved from the project row — never from payload.
    """
    body = request.get_json() or {}
    project_name = str(body.get("project_name", "")).strip()
    if not project_name:
        return jsonify({"error": "project_name is required"}), 400

    proj = _validate_project(project_name)
    if not proj:
        return jsonify({"error": f"Project '{project_name}' not found or has no owner. "
                                  f"Create it via POST /api/projects first."}), 400

    actual_name   = proj["project_name"]
    project_id    = proj["id"]
    owner_user_id = proj["owner_user_id"]

    opt = _parse_optional(body)
    error = str(body.get("error", "")).strip()
    is_workflow = error.startswith("{") and ("workflowId" in error or "workflowStatus" in error)
    is_error = bool(error) and not is_workflow

    # Smart extraction
    error_detail = opt.get("error_detail")
    if is_error and not error_detail:
        short_error, extracted_trace = _smart_extract_error_detail(error)
        if extracted_trace:
            error_detail = extracted_trace
            error = short_error

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
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
        t = "error" if is_error else "success"
        row = serialize_row(inserted)

        try:
            sse_manager.broadcast_log(row)
        except Exception as _sse_exc:
            logger.warning(f"[Ingest] SSE broadcast failed (non-fatal): {_sse_exc}")

        if is_error:
            try:
                from ai.error_grouper import classify_error as _classify
                _classify(log_id=inserted["id"], error_message=error,
                          project_name=actual_name, error_detail=error_detail)
            except Exception as _cexc:
                logger.warning("[Ingest] classify_error (log) failed (non-fatal): %s", _cexc)

        return jsonify({"success": True, "type": t, **row}), 201
    except Exception as e:
        print(f"[Ingest] log error: {e}")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


@app.route("/api/ingest/success", methods=["POST"])
def ingest_success():
    """
    POST /api/ingest/success — machine-to-machine success log.

    project_id and owner_user_id resolved from the project row — never from payload.
    """
    body = request.get_json() or {}
    project_name = str(body.get("project_name", "")).strip()
    if not project_name:
        return jsonify({"error": "project_name is required"}), 400

    proj = _validate_project(project_name)
    if not proj:
        return jsonify({"error": f"Project '{project_name}' not found or has no owner. "
                                  f"Create it via POST /api/projects first."}), 400

    actual_name   = proj["project_name"]
    project_id    = proj["id"]
    owner_user_id = proj["owner_user_id"]

    opt = _parse_optional(body)
    success_count = body.get("success_count", 1)

    try:
        inserted = _insert_result(
            actual_name, opt["file_name"],
            None, None, None, None,
            success_count, 0,
            opt["word_count"], opt["file_type"], opt["input_tokens"],
            opt["output_tokens"], opt["calculated_cost"], opt["llm_usage"],
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
        row = serialize_row(inserted)

        try:
            sse_manager.broadcast_log(row)
        except Exception as _sse_exc:
            logger.warning(f"[Ingest] SSE broadcast failed (non-fatal): {_sse_exc}")

        return jsonify({"success": True, "type": "success", **row}), 201
    except Exception as e:
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/dashboard/top-projects")
@require_permission("dashboard:read")
def dashboard_top_projects():
    """Top projects by log count — scoped by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    from_ts = request.args.get("from", "")
    to_ts   = request.args.get("to", "")
    try:
        conditions = [f"row_type = 'log'", f"({log_access_cond})"]
        params = list(log_access_params)
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
            params,
        )
        return jsonify({"projects": serialize_rows(rows)})
    except Exception as e:
        print(f"[Dashboard] top-projects: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/top-error-projects")
@require_permission("dashboard:read")
def dashboard_top_error_projects():
    """Top error projects — scoped by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    from_ts = request.args.get("from", "")
    to_ts   = request.args.get("to", "")
    try:
        conditions = [
            "row_type = 'log'", f"({log_access_cond})",
            "error IS NOT NULL", "error <> ''",
        ]
        params = list(log_access_params)
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
            params,
        )
        return jsonify({"projects": serialize_rows(rows)})
    except Exception as e:
        print(f"[Dashboard] top-error-projects: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/today-errors")
@require_permission("dashboard:read")
def dashboard_today_errors():
    """Today's errors — scoped by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = query(
            f"SELECT project_name AS project, file_name, error, "
            f"error_detail, error_hash, timestamp, "
            f"NULLIF(error_group_name, '') AS error_group_name, "
            f"NULLIF(error_group_id, '') AS error_group_id "
            f"FROM {TABLE} "
            f"WHERE row_type = 'log' AND ({log_access_cond}) "
            f"  AND error IS NOT NULL AND error <> '' "
            f"  AND timestamp AT TIME ZONE 'UTC' >= CURRENT_DATE "
            f"  AND timestamp AT TIME ZONE 'UTC' < CURRENT_DATE + INTERVAL '1 day' "
            f"ORDER BY timestamp DESC",
            log_access_params,
        )
        return jsonify({"date": date_str, "errors": serialize_rows(rows)})
    except Exception as e:
        print(f"[Dashboard] today-errors: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/errors")
@require_permission("dashboard:read")
def dashboard_errors():
    """All errors in a date range — scoped by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    from_ts = request.args.get("from", "")
    to_ts   = request.args.get("to", "")
    try:
        conditions = [
            "row_type = 'log'", f"({log_access_cond})",
            "error IS NOT NULL", "error <> ''",
        ]
        params = list(log_access_params)
        if from_ts:
            conditions.append("timestamp >= %s")
            params.append(from_ts)
        if to_ts:
            conditions.append("timestamp <= %s")
            params.append(to_ts)
        where = " AND ".join(conditions)
        rows = query(
            f"SELECT project_name AS project, file_name, error, "
            f"error_detail, error_hash, timestamp, "
            f"NULLIF(error_group_name, '') AS error_group_name, "
            f"NULLIF(error_group_id, '') AS error_group_id "
            f"FROM {TABLE} WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT 2000",
            params,
        )
        return jsonify({"errors": serialize_rows(rows)})
    except Exception as e:
        print(f"[Dashboard] errors: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/project-errors", methods=["GET"])
@require_permission("dashboard:read")
def dashboard_project_errors():
    """
    GET /api/dashboard/project-errors?project=<name>&from=<iso>&to=<iso>
    Scoped by role — admin/viewer see all, developer sees assigned only.
    """
    import traceback as _tb_mod

    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    project_name = request.args.get("project", "").strip()
    from_ts      = request.args.get("from", "").strip()
    to_ts        = request.args.get("to", "").strip()

    if not project_name:
        return jsonify({"error": "project query parameter is required"}), 400

    try:
        conditions = [
            "row_type = 'log'",
            f"({log_access_cond})",
            "error IS NOT NULL", "error <> ''",
            "project_name = %s",
        ]
        params = list(log_access_params) + [project_name]

        if from_ts:
            conditions.append("timestamp >= %s")
            params.append(from_ts)
        if to_ts:
            conditions.append("timestamp <= %s")
            params.append(to_ts)

        where = " AND ".join(conditions)
        rows = query(
            f"SELECT project_name AS project, file_name, error, "
            f"error_detail, error_hash, timestamp, "
            f"NULLIF(error_group_name, '') AS error_group_name, "
            f"NULLIF(error_group_id, '') AS error_group_id "
            f"FROM {TABLE} WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT 2000",
            params,
        )
        return jsonify({"errors": serialize_rows(rows)})

    except Exception as e:
        tb_str = _tb_mod.format_exc()
        print(f"[Dashboard] project-errors ERROR: {type(e).__name__}: {e}\n{tb_str}")
        return jsonify({
            "error": "Internal server error",
            "exception": type(e).__name__,
            "message": str(e),
        }), 500


# ═══════════════════════════════════════════════════════════════════════════════
# BREAKS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/jira/summary")
@require_permission("jira:read")
def jira_summary():
    """
    Return Jira ticket summary for the breaks page Jira section.
    Scoped by role:
      admin/viewer → all tickets
      developer    → only tickets linked to logs assigned to them
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)

    try:
        # Fetch jira_ticket rows whose linked log is accessible to this user.
        # jira_ticket rows store error_hash + project_name in metadata; we join
        # back to log rows to enforce the access condition.
        rows = query(
            f"SELECT jt.metadata "
            f"FROM {TABLE} jt "
            f"WHERE jt.row_type = 'jira_ticket' "
            f"  AND EXISTS ("
            f"    SELECT 1 FROM {TABLE} lg "
            f"    WHERE lg.row_type = 'log' "
            f"      AND lg.error_hash = jt.metadata::jsonb->>'error_hash' "
            f"      AND ({log_access_cond})"
            f"  ) "
            f"ORDER BY jt.created_at DESC",
            log_access_params,
        )

        tickets = []
        for row in rows:
            raw = row.get("metadata")
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw or {}
            except Exception:
                payload = {}

            error_hash   = payload.get("error_hash") or ""
            project_name = payload.get("project_name") or ""
            created_by   = payload.get("created_by") or ""
            created_at   = payload.get("created_at") or ""
            jira_key     = payload.get("jira_key") or payload.get("key") or ""
            jira_url     = payload.get("jira_url") or payload.get("url") or ""

            status = "Todo"
            if error_hash:
                log_rows = query(
                    f"SELECT error_status FROM {TABLE} "
                    f"WHERE row_type = 'log' "
                    f"  AND error_hash = %s "
                    f"  AND LOWER(project_name) = LOWER(%s) "
                    f"  AND ({log_access_cond})",
                    [error_hash, project_name] + log_access_params,
                )
                if log_rows:
                    error_status = (log_rows[0].get("error_status") or "").strip().lower()
                    if error_status == "resolved":
                        status = "Resolved"

            tickets.append({
                "error_hash":   error_hash,
                "project_name": project_name,
                "error":        payload.get("error_message") or payload.get("summary") or "",
                "jira_key":     jira_key,
                "jira_url":     jira_url,
                "created_by":   created_by,
                "created_at":   created_at,
                "status":       status,
            })

        resolved = sum(1 for t in tickets if t["status"] == "Resolved")
        todo     = sum(1 for t in tickets if t["status"] == "Todo")

        return jsonify({
            "total":    len(tickets),
            "resolved": resolved,
            "todo":     todo,
            "tickets":  tickets,
        })
    except Exception as exc:
        logger.exception("[Jira Summary] failed: %s", exc)
        return jsonify({"error": str(exc), "total": 0, "resolved": 0, "todo": 0, "tickets": []}), 500


@app.route("/api/breaks/grouped")
@require_permission("breaks:read")
def breaks_grouped():
    """
    Grouped breaks scoped by role:
      admin/viewer → all logs with a valid owner
      developer    → only logs they own or are assigned to them
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)

    page  = max(1, int(request.args.get("page", 1) or 1))
    limit = min(100, max(1, int(request.args.get("limit", 20) or 20)))
    offset = (page - 1) * limit
    status_f         = request.args.get("status", "")
    project_f        = request.args.get("project", "")
    semantic_group_f = request.args.get("semantic_group", "")
    from_ts = request.args.get("from", "")
    to_ts   = request.args.get("to", "")

    try:
        conditions = [
            "row_type = 'log'",
            f"({log_access_cond})",
            "error IS NOT NULL", "error <> ''",
        ]
        params = list(log_access_params)

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

        inner_sql = (
            f"SELECT "
            f"  id AS representative_id, project_name, "
            f"  error AS error_message, "
            f"  COALESCE(error_hash, MD5(LOWER(TRIM(error)))) AS error_hash, "
            f"  COALESCE(error_group_id, '') AS error_group_id, "
            f"  error_group_name, error_status, "
            f"  MIN(timestamp) OVER ("
            f"    PARTITION BY project_name, COALESCE(error_hash, MD5(LOWER(TRIM(error)))) "
            f"  ) AS first_seen, "
            f"  timestamp AS last_seen, "
            f"  ROW_NUMBER() OVER ("
            f"    PARTITION BY project_name, COALESCE(error_hash, MD5(LOWER(TRIM(error)))) "
            f"  ) AS occurrence_number, "
            f"  COUNT(*) OVER ("
            f"    PARTITION BY project_name, COALESCE(error_hash, MD5(LOWER(TRIM(error)))) "
            f"  ) AS total_for_error, "
            f"  BOOL_OR(error_status = 'reopened') OVER ("
            f"    PARTITION BY project_name, COALESCE(error_hash, MD5(LOWER(TRIM(error)))) "
            f"  ) AS has_reopened "
            f"FROM {TABLE} WHERE {where}"
        )

        row_sql = (
            f"SELECT "
            f"  representative_id, project_name, error_message, error_hash, "
            f"  error_group_id, error_group_name, error_status, "
            f"  occurrence_number AS occurrence_count, first_seen, last_seen, "
            f"  CASE "
            f"    WHEN error_status = 'resolved' THEN 'resolved' "
            f"    WHEN has_reopened THEN 'regression' "
            f"    WHEN total_for_error = 1 THEN 'new' "
            f"    ELSE 'existing' "
            f"  END AS status "
            f"FROM ({inner_sql}) AS inner_rows"
        )

        if status_f:
            count_sql = f"SELECT COUNT(*) AS cnt FROM ({row_sql}) AS g WHERE status = %s"
            total_rows = query(count_sql, tuple(params + [status_f]))
            total = total_rows[0].get("cnt", 0) if total_rows else 0
            data_sql = (
                f"SELECT * FROM ({row_sql}) AS g WHERE status = %s "
                f"ORDER BY last_seen DESC NULLS LAST LIMIT %s OFFSET %s"
            )
            all_params = params + [status_f, limit, offset]
        else:
            count_sql = f"SELECT COUNT(*) AS cnt FROM ({row_sql}) AS g"
            total_rows = query(count_sql, tuple(params))
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
            "data": [], "total": 0, "page": page, "limit": limit,
        }), 500


@app.route("/api/breaks/<break_id>")
@require_permission("breaks:read")
def get_break(break_id):
    """
    GET /api/breaks/:id
    admin/viewer → any log with valid owner
    developer    → only owned or assigned logs
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    try:
        rows = query(
            f"SELECT * FROM {TABLE} "
            f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
            tuple([break_id] + log_access_params),
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
@require_permission("breaks:read")
def get_break_detail(error_hash):
    """
    GET /api/breaks/detail/:error_hash
    admin/viewer → any log with valid owner
    developer    → only owned or assigned logs
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)

    request_id = g.get("request_id", "unknown")
    request_start = time.perf_counter()
    print(f"[PERF] [req:{request_id}] === REQUEST START === error_hash={error_hash}")
    try:
        parse_params_start = time.perf_counter()
        project_name = (request.args.get('project_name') or '').strip() or None
        log_id_param = request.args.get('log_id', '').strip() or None
        parse_params_elapsed = (time.perf_counter() - parse_params_start) * 1000
        print(f"[PERF] [req:{request_id}] Parse params: {parse_params_elapsed:.3f}ms")
        
        stage = "route_entered"
        debug_info = {
            "error_hash": error_hash,
            "project_name": project_name,
            "debug_enabled": DEBUG_BREAK_DETAIL,
            "stage": stage,
            "request_start_ms": round(request_start * 1000, 3),
        }

        print(f"[req:{request_id}] [Breaks:detail] TRACE START")
        print(f"[req:{request_id}] [Breaks:detail] URL error_hash={repr(error_hash)}")
        print(f"[req:{request_id}] [Breaks:detail] query_param project_name={repr(project_name)}")

        stage = "parsed_project"
        debug_info["stage"] = stage
        debug_info["project_name"] = project_name

        # Get grouped error info
        hash_gen_start = time.perf_counter()
        conditions = [
            "row_type = 'log'",
            "error IS NOT NULL",
            "error <> ''",
            f"({log_access_cond})",   # ← role-based access
        ]
        params = list(log_access_params)
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
        hash_gen_elapsed = (time.perf_counter() - hash_gen_start) * 1000
        print(f"[PERF] [req:{request_id}] Hash generation: {hash_gen_elapsed:.3f}ms")

        print(f"[req:{request_id}] [Breaks:detail] hash_candidates={hash_candidates}")
        
        if hash_candidates is None:
            print(f"[req:{request_id}] [Breaks:detail] WARNING: build_error_hash_candidates returned None!")
            if _error_matching_import_err:
                print(f"[req:{request_id}] [Breaks:detail] Import error was: {type(_error_matching_import_err).__name__}: {_error_matching_import_err}")
            hash_candidates = []
        
        primary_params = list(log_access_params)
        primary_conditions = ["row_type = 'log'", "error IS NOT NULL", "error <> ''", f"({log_access_cond})"]
        if error_hash:
            hash_clauses = []
            for idx, candidate in enumerate(hash_candidates):
                hash_clauses.append("error_hash = %s")
                primary_params.append(candidate)
                print(f"[req:{request_id}] [Breaks:detail] Added primary hash candidate[{idx}]={repr(candidate)}")
            if hash_clauses:
                primary_conditions.append(f"({' OR '.join(hash_clauses)})")
                print(f"[req:{request_id}] [Breaks:detail] Added primary hash condition with {len(hash_clauses)} candidates")

        if project_name:
            primary_conditions.insert(0, "LOWER(project_name) = LOWER(%s)")
            primary_params.insert(0, project_name)
            print(f"[req:{request_id}] [Breaks:detail] Inserted project_name at primary_params[0]={repr(project_name)}")

        log_query = None
        error_rows = []
        primary_where = ' AND '.join(primary_conditions)
        debug_info["primary_conditions"] = primary_conditions
        debug_info["primary_params"] = tuple(primary_params)
        debug_info["primary_param_count"] = len(primary_params)
        stage = "built_sql"
        debug_info["stage"] = stage

        if error_hash and primary_conditions:
            log_query = (
                "SELECT id, project_name, error AS error_message, error_detail, error_hash, "
                "failure_count, timestamp, error_status, reopened_at, file_name, "
                "error_group_name "
                f"FROM {TABLE} "
                f"WHERE {primary_where} "
                "ORDER BY timestamp DESC"
            )
            debug_info["primary_sql"] = log_query
            print(f"[req:{request_id}] [Breaks:detail] Primary SQL:\n{log_query}")
            debug_info["stage"] = "executing_primary_query"
            query_start = time.perf_counter()
            error_rows = query(log_query, tuple(primary_params))
            query_end = time.perf_counter()
            debug_info["primary_query_elapsed_ms"] = round((query_end - query_start) * 1000, 3)
            debug_info["primary_row_count"] = len(error_rows) if error_rows else 0
            print(f"[PERF] [req:{request_id}] Primary query: {debug_info['primary_query_elapsed_ms']:.3f}ms (returned {debug_info['primary_row_count']} rows)")
            print(f"[req:{request_id}] [Breaks:detail] Primary query returned {len(error_rows) if error_rows else 0} rows in {debug_info['primary_query_elapsed_ms']}ms")

        if not error_rows:
            fallback_params = list(log_access_params)
            fallback_conditions = ["row_type = 'log'", "error IS NOT NULL", "error <> ''", f"({log_access_cond})"]
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
            debug_info["fallback_sql"] = fallback_sql
            debug_info["fallback_params"] = tuple(fallback_params)
            debug_info["fallback_param_count"] = len(fallback_params)
            debug_info["stage"] = "executing_fallback_query"
            fallback_start = time.perf_counter()
            error_rows = query(fallback_sql, tuple(fallback_params))
            fallback_end = time.perf_counter()
            debug_info["fallback_query_elapsed_ms"] = round((fallback_end - fallback_start) * 1000, 3)
            debug_info["fallback_row_count"] = len(error_rows) if error_rows else 0
            debug_info["used_md5_fallback"] = True
            print(f"[PERF] [req:{request_id}] Fallback query: {debug_info['fallback_query_elapsed_ms']:.3f}ms (returned {debug_info['fallback_row_count']} rows)")
            print(f"[req:{request_id}] [Breaks:detail] Fallback query returned {len(error_rows) if error_rows else 0} rows in {debug_info['fallback_query_elapsed_ms']}ms")

        if not error_rows and not log_query:
            # Neither primary nor fallback was executed — use broad query scoped to this user
            where_clause = ' AND '.join(conditions)
            debug_info["conditions"] = conditions
            debug_info["params"] = tuple(params)
            debug_info["param_count"] = len(params)
            sql = (
                "SELECT id, project_name, error AS error_message, error_detail, error_hash, "
                "failure_count, timestamp, error_status, reopened_at, file_name, "
                "error_group_name "
                f"FROM {TABLE} "
                f"WHERE {where_clause} "
                "ORDER BY timestamp DESC"
            )
            debug_info["sql"] = sql
            debug_info["stage"] = "executing_query"
            query_start = time.perf_counter()
            error_rows = query(sql, tuple(params))
            query_end = time.perf_counter()
            debug_info["query_elapsed_ms"] = round((query_end - query_start) * 1000, 3)
            debug_info["row_count"] = len(error_rows) if error_rows else 0
            debug_info["first_row"] = serialize_row(error_rows[0]) if error_rows else None
            debug_info["first_row_keys"] = list(error_rows[0].keys()) if error_rows else []
            print(f"[PERF] [req:{request_id}] Broad query: {debug_info['query_elapsed_ms']:.3f}ms (returned {debug_info['row_count']} rows)")
            print(f"[req:{request_id}] [Breaks:detail] Query returned {len(error_rows) if error_rows else 0} rows in {debug_info['query_elapsed_ms']}ms")
        else:
            debug_info["row_count"] = len(error_rows) if error_rows else 0
            debug_info["first_row"] = serialize_row(error_rows[0]) if error_rows else None
            debug_info["first_row_keys"] = list(error_rows[0].keys()) if error_rows else []
            if error_rows:
                for i, row in enumerate(error_rows[:3]):
                    print(f"[req:{request_id}] [Breaks:detail] Row[{i}]: error_hash={row.get('error_hash')}, project_name={row.get('project_name')}, error={row.get('error_message', '')[:50]}")
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
        # Total occurrences across all matching rows
        occurrence_count = sum(int(r.get("failure_count", 1) or 0) for r in error_rows)
        timestamps = [r.get("timestamp") for r in error_rows if r.get("timestamp") is not None]
        first_seen = min(timestamps) if timestamps else None
        # last_seen is the most recent ACTUAL OCCURRENCE timestamp.
        # reopened_at is a lifecycle field (when someone clicked Reopen) and
        # must never influence last_seen — doing so would move old errors to
        # the top of the timeline as if a new occurrence had happened.
        last_seen = max(timestamps) if timestamps else None
        file_name = next((r.get("file_name") for r in error_rows if r.get("file_name")), first.get("file_name"))

        # ── Jira ticket mapping: check if we've already created a Jira ticket
        # for this error_hash (or its candidates). If present, include it so
        # the frontend can show the existing ticket and avoid duplicate creation.
        jira_ticket = None
        try:
            jira_start = time.perf_counter()
            jt_params = list(hash_candidates) if hash_candidates else [error_hash]
            jt_where = ' OR '.join(["metadata::jsonb->>'error_hash' = %s"] * len(jt_params))
            jt_sql = f"SELECT metadata FROM {TABLE} WHERE row_type = 'jira_ticket' AND ({jt_where})"
            if project_name:
                jt_sql += " AND LOWER(metadata::jsonb->>'project_name') = LOWER(%s)"
                jt_params.append(project_name)
            jt_sql += " ORDER BY created_at DESC LIMIT 1"
            jt_rows = query(jt_sql, tuple(jt_params))
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
                        logger.exception('[Breaks:detail] Failed to parse jira_ticket metadata')
            jira_elapsed = (time.perf_counter() - jira_start) * 1000
            debug_info['jira_lookup_elapsed_ms'] = round(jira_elapsed, 3)
            print(f"[PERF] [req:{request_id}] Jira lookup: {jira_elapsed:.3f}ms")
        except Exception as _jt_exc:
            logger.exception('[Breaks:detail] Jira ticket lookup failed: %s', _jt_exc)
            jira_elapsed = (time.perf_counter() - jira_start) * 1000
            debug_info['jira_lookup_elapsed_ms'] = round(jira_elapsed, 3)
            print(f"[PERF] [req:{request_id}] Jira lookup FAILED: {jira_elapsed:.3f}ms")

        # ── Status: use the SPECIFIC row when log_id supplied, not group aggregate ──
        # This is the critical fix: when the user opens a specific occurrence,
        # its error_status must come from that row alone.  Aggregating with
        # any(... == "resolved") causes one resolved row to make the entire
        # modal appear resolved.
        status_calc_start = time.perf_counter()
        specific_row = None
        if log_id_param:
            specific_row = next((r for r in error_rows if r.get("id") == log_id_param), None)
            # If the specific row wasn't in the group query results, fetch it directly.
            # This happens when the log_id belongs to the same error_hash group but
            # wasn't returned by the query (e.g. filtered out). Without this fallback
            # the code drops into the group-aggregate path which shows "resolved" if
            # ANY row in the group is resolved — wrong for per-occurrence deep links.
            if not specific_row:
                try:
                    direct_rows = query(
                        f"SELECT id, error_status, reopened_at, failure_count, "
                        f"file_name, timestamp, error_group_name "
                        f"FROM {TABLE} "
                        f"WHERE row_type = 'log' AND id = %s AND ({log_access_cond})",
                        tuple([log_id_param] + log_access_params),
                    )
                    if direct_rows:
                        specific_row = direct_rows[0]
                        error_rows = list(error_rows) + [specific_row]
                except Exception as _sr_exc:
                    logger.warning("[Breaks:detail] Direct log_id fetch failed: %s", _sr_exc)

        if specific_row:
            # Status from the specific row only
            row_status = specific_row.get("error_status") or "open"
            if row_status == "resolved":
                status = "resolved"
            elif row_status == "reopened":
                status = "regression"
            elif occurrence_count == 1:
                status = "new"
            else:
                status = "existing"
            # Use specific row's timestamps for resolved_at / reopened_at
            first = specific_row
        else:
            # No specific row — derive status from the group (backward compat)
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

        # Assign stable occurrence_number to each raw row based on chronological order
        # Chronological = oldest first. Compute cumulative counts so rows keep their
        # original sequential occurrence numbers even if paginated later.
        occur_num_start = time.perf_counter()
        try:
            # Sort ascending by timestamp for numbering
            asc = sorted(error_rows, key=lambda x: x.get("timestamp") or "")
            cumulative = 0
            occurrence_map = {}
            for row in asc:
                fc = int(row.get("failure_count", 1) or 0)
                occurrence_map[row.get("id")] = cumulative + 1
                cumulative += fc

            # Build returned occurrences in the original (DESC) order, attaching occurrence_number
            occurrences = []
            for r in error_rows:
                occurrences.append({
                    "id": r.get("id"),
                    "file_name": r.get("file_name"),
                    "timestamp": r.get("timestamp"),
                    "failure_count": int(r.get("failure_count", 1) or 0),
                    "occurrence_number": occurrence_map.get(r.get("id")),
                })
        except Exception as _num_exc:
            print(f"[req:{request_id}] [Breaks:detail] occurrence numbering failed: {_num_exc}")
            # Fallback: no numbering
            occurrences = [
                {"id": r.get("id"), "file_name": r.get("file_name"), "timestamp": r.get("timestamp"),
                 "failure_count": r.get("failure_count", 1), "occurrence_number": None}
                for r in error_rows
            ]
        occur_num_elapsed = (time.perf_counter() - occur_num_start) * 1000
        print(f"[PERF] [req:{request_id}] Occurrence numbering: {occur_num_elapsed:.3f}ms")

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
        solution_start = time.perf_counter()
        print(f"[PERF] [req:{request_id}] === SOLUTION LOOKUP START ===")
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
        finally:
            solution_elapsed = (time.perf_counter() - solution_start) * 1000
            debug_info['solution_elapsed_ms'] = round(solution_elapsed, 3)
            print(f"[PERF] [req:{request_id}] === SOLUTION LOOKUP END === {solution_elapsed:.3f}ms")

        ai_recommendation = None
        ai_start = time.perf_counter()
        print(f"[PERF] [req:{request_id}] === AI RECOMMENDATION START ===")
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
        finally:
            ai_elapsed = (time.perf_counter() - ai_start) * 1000
            debug_info['ai_elapsed_ms'] = round(ai_elapsed, 3)
            print(f"[PERF] [req:{request_id}] === AI RECOMMENDATION END === {ai_elapsed:.3f}ms")

        # Parse stack trace to extract structured frame information with source code lines
        parsed_stacktrace = None
        if STACKTRACE_PARSER_AVAILABLE:
            stacktrace_start = time.perf_counter()
            print(f"[PERF] [req:{request_id}] === STACKTRACE PARSING START ===")
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
            finally:
                stacktrace_elapsed = (time.perf_counter() - stacktrace_start) * 1000
                debug_info['stacktrace_elapsed_ms'] = round(stacktrace_elapsed, 3)
                print(f"[PERF] [req:{request_id}] === STACKTRACE PARSING END === {stacktrace_elapsed:.3f}ms")

        result = {
            "project_name": first["project_name"],
            "file_name": file_name,
            "error_message": first["error_message"],
            "error_detail": first.get("error_detail"),
            "parsed_stacktrace": parsed_stacktrace,
            "error_hash": error_hash,
            "error_group_name": first.get("error_group_name") or None,
            # occurrence_count: sequence number of this specific occurrence (or total if no log_id)
            "occurrence_count": occurrence_map.get(
                (specific_row or first).get("id"), occurrence_count
            ) if specific_row else occurrence_count,
            # total_occurrences: total count of all occurrences of this error
            "total_occurrences": occurrence_count,
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
        request_end = time.perf_counter()
        request_elapsed = (request_end - request_start) * 1000
        debug_info['request_elapsed_ms'] = round(request_elapsed, 3)
        print(f"[PERF] [req:{request_id}] === REQUEST END === Total: {request_elapsed:.3f}ms")
        print(f"[PERF] [req:{request_id}] BREAKDOWN:")
        print(f"[PERF] [req:{request_id}]   - Primary query: {debug_info.get('primary_query_elapsed_ms', 0):.3f}ms")
        print(f"[PERF] [req:{request_id}]   - Jira lookup: {debug_info.get('jira_lookup_elapsed_ms', 0):.3f}ms")
        print(f"[PERF] [req:{request_id}]   - Solution lookup: {debug_info.get('solution_elapsed_ms', 0):.3f}ms")
        print(f"[PERF] [req:{request_id}]   - AI recommendation: {debug_info.get('ai_elapsed_ms', 0):.3f}ms")
        print(f"[PERF] [req:{request_id}]   - Stacktrace parsing: {debug_info.get('stacktrace_elapsed_ms', 0):.3f}ms")
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
        request_end = time.perf_counter()
        debug_info["stage"] = "unhandled_exception"
        debug_info["exception"] = {"type": type(e).__name__, "message": str(e)}
        debug_info["traceback"] = tb_str
        debug_info["request_elapsed_ms"] = round((request_end - request_start) * 1000, 3)
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
@require_permission("dashboard:read")
def dashboard_legacy():
    """
    GET /api/dashboard — aggregated break counts, scoped by role.
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    log_access_cond, log_access_params = _build_log_access_condition(user)
    try:
        def safe_count(sql, params):
            try:
                r = query(sql, params)
                return int(r[0]["count"]) if r else 0
            except Exception:
                return 0

        last24h = safe_count(
            f"SELECT COUNT(*) AS count FROM {TABLE} "
            f"WHERE row_type = 'log' AND ({log_access_cond}) "
            f"  AND error IS NOT NULL AND error <> '' "
            f"  AND timestamp >= NOW() - INTERVAL '24 hours'",
            log_access_params,
        )
        last7d = safe_count(
            f"SELECT COUNT(*) AS count FROM {TABLE} "
            f"WHERE row_type = 'log' AND ({log_access_cond}) "
            f"  AND error IS NOT NULL AND error <> '' "
            f"  AND timestamp >= NOW() - INTERVAL '7 days'",
            log_access_params,
        )

        return jsonify({
            "breakCounts": {"last24h": last24h, "last7d": last7d},
            "errorRateTrend": [], "topServices": [],
            "timeSeries": [], "severityBreakdown": [],
            "deploymentEvents": [], "airbrakeUnreachable": False,
        })
    except Exception:
        return jsonify({
            "breakCounts": {"last24h": 0, "last7d": 0},
            "errorRateTrend": [], "topServices": [],
            "timeSeries": [], "severityBreakdown": [],
            "deploymentEvents": [], "airbrakeUnreachable": True,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR SOLUTIONS / KNOWLEDGE BASE
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/knowledge_base/reopen", methods=["POST"])
@require_permission("errors:resolve")
def reopen_error_solution():
    """Reopen an error. Access enforced by role before write."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)

    body         = request.get_json() or {}
    error_hash   = body.get("error_hash")
    project_name = body.get("project_name")
    log_id       = body.get("log_id") or None

    if not error_hash or not project_name:
        return jsonify({"error": "error_hash and project_name are required"}), 400
    if not log_id:
        return jsonify({"error": "log_id is required"}), 400

    try:
        count = execute(
            f"UPDATE {TABLE} "
            f"SET error_status = 'reopened', reopened_at = NOW(), resolved_at = NULL "
            f"WHERE row_type = 'log' "
            f"  AND id = %s "
            f"  AND ({log_access_cond}) "
            f"  AND error_status IN ('resolved', 'reopened')",
            tuple([log_id] + log_access_params),
        )
        if count == 0:
            return jsonify({"error": "Not Found"}), 404
        logger.info("[Reopen] log_id=%r error_hash=%r project=%r rows_updated=%d",
                    log_id, error_hash, project_name, count)

        # ── Sync linked Jira ticket back to To Do (non-fatal) ─────────────────
        if count and log_id:
            try:
                from jira.jira_sync import find_airbrake_token_for_webhook
                from jira.client import JiraClient
                from db import query as _q
                meta_rows = _q(
                    f"SELECT metadata FROM {TABLE} "
                    f"WHERE row_type = 'log' AND id = %s "
                    f"  AND metadata::jsonb ? 'jira_issue_key'",
                    (log_id,),
                )
                if meta_rows:
                    import json as _j
                    raw  = meta_rows[0].get("metadata")
                    meta = _j.loads(raw) if isinstance(raw, str) else (raw or {})
                    issue_key = meta.get("jira_issue_key", "")
                    if issue_key:
                        token_pair = find_airbrake_token_for_webhook()
                        if token_pair:
                            access_token, cloud_id = token_pair
                            client = JiraClient(access_token=access_token, cloud_id=cloud_id)
                            try:
                                client.transition_issue_to_todo(issue_key)
                                logger.info("[Reopen] Moved Jira ticket %s back to To Do", issue_key)
                            except Exception as jira_exc:
                                logger.warning("[Reopen] Could not move Jira ticket %s: %s", issue_key, jira_exc)
            except Exception as jira_outer_exc:
                logger.warning("[Reopen] Jira sync step failed (non-fatal): %s", jira_outer_exc)

        return jsonify({"reopened": count, "project_name": project_name, "error_hash": error_hash})
    except Exception as e:
        logger.exception("[Reopen] Failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge_base/resolve", methods=["POST"])
@require_permission("errors:resolve")
def resolve_error_solution():
    """Resolve an error. Access enforced by role before write."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)

    body         = request.get_json() or {}
    error_hash   = body.get("error_hash")
    project_name = body.get("project_name")
    log_id       = body.get("log_id") or None

    if not error_hash or not project_name:
        return jsonify({"error": "error_hash and project_name are required"}), 400
    if not log_id:
        return jsonify({"error": "log_id is required"}), 400

    try:
        count = execute(
            f"UPDATE {TABLE} "
            f"SET error_status = 'resolved', resolved_at = NOW() "
            f"WHERE row_type = 'log' "
            f"  AND id = %s "
            f"  AND ({log_access_cond}) "
            f"  AND error_status IN ('open', 'reopened')",
            tuple([log_id] + log_access_params),
        )
        if count == 0:
            return jsonify({"error": "Not Found"}), 404
        logger.info("[Resolve] log_id=%r error_hash=%r project=%r rows_updated=%d",
                    log_id, error_hash, project_name, count)
        return jsonify({"resolved": count, "project_name": project_name, "error_hash": error_hash})
    except Exception as e:
        logger.exception("[Resolve] Failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge_base/use", methods=["POST"])
@require_permission("errors:resolve")
def use_solution():
    """Apply a solution and resolve the log row. Access enforced by role."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    log_access_cond, log_access_params = _build_log_access_condition(user)

    body         = request.get_json() or {}
    solution_id  = body.get("solution_id")
    error_hash   = body.get("error_hash")
    project_name = body.get("project_name")
    log_id       = body.get("log_id") or None

    if not solution_id or not error_hash or not project_name:
        return jsonify({"error": "solution_id, error_hash and project_name are required"}), 400
    if not log_id:
        return jsonify({"error": "log_id is required"}), 400

    try:
        updated_solution = increment_usage(solution_id)

        count = execute(
            f"UPDATE {TABLE} "
            f"SET error_status = 'resolved', resolved_at = NOW() "
            f"WHERE row_type = 'log' "
            f"  AND id = %s "
            f"  AND ({log_access_cond}) "
            f"  AND error_status IN ('open', 'reopened')",
            tuple([log_id] + log_access_params),
        )
        if count == 0:
            return jsonify({"error": "Not Found"}), 404

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
@require_permission("breaks:read")
def get_solution_versions_route(solution_id):
    try:
        versions = get_solution_versions(solution_id)
        return jsonify({"versions": versions})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


@app.route("/api/knowledge_base/<solution_id>/versions/<version_id>", methods=["DELETE"])
@require_permission("errors:resolve")
def delete_solution_version_route(solution_id, version_id):
    try:
        count = delete_solution_version(version_id)
        return jsonify({"deleted": count > 0, "version_id": version_id})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


@app.route("/api/knowledge_base/top", methods=["GET"])
@require_permission("breaks:read")
def get_top_solutions_route():
    # Primary key: error_message (normalized in get_top_solutions).
    # error_hash accepted for backward-compat but ignored when error_message is present.
    # error_group_name enables the semantic-group fallback tier.
    error_message    = request.args.get("error_message", "").strip()
    error_hash       = request.args.get("error_hash", "").strip()
    error_group_name = request.args.get("error_group_name", "").strip() or None
    project_name     = request.args.get("project_name")
    limit            = int(request.args.get("limit", "5"))
    offset           = int(request.args.get("offset", "0"))

    if not error_message and not error_hash:
        return jsonify({"error": "error_message or error_hash is required"}), 400
    try:
        rows, total = get_top_solutions(
            error_message    = error_message,
            project_name     = project_name,
            limit            = limit,
            offset           = offset,
            error_hash       = error_hash or None,
            error_group_name = error_group_name,
        )
        return jsonify({"solutions": rows, "total": total})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "exception": type(e).__name__}), 500


@app.route("/api/knowledge_base/<error_hash>", methods=["GET"])
@require_permission("breaks:read")
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
@require_permission("errors:resolve")
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
@require_permission("errors:resolve")
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
# BOOTSTRAP — One-time admin user creation (works only when no admin exists)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/bootstrap", methods=["POST"])
def bootstrap_admin():
    """
    POST /api/auth/bootstrap

    Create the FIRST admin user. Only works when no admin users exist in the DB.
    Once an admin exists, this endpoint returns 403.

    Body:
      {
        "email": "you@example.com",
        "oauth_provider": "google",
        "oauth_subject": "google-sub-id"
      }

    After calling this once, the user can log in via Google OAuth.
    Remove this endpoint after initial setup if desired.
    """
    # Safety check: only works if no admin users exist
    existing_admins = query(
        f"SELECT id FROM {TABLE} WHERE row_type = 'user' AND role = 'admin' LIMIT 1"
    )
    if existing_admins:
        return jsonify({"error": "Admin user already exists. Bootstrap disabled."}), 403

    body = request.get_json() or {}
    email = (body.get("email") or "").strip()
    oauth_provider = (body.get("oauth_provider") or "google").strip()
    oauth_subject = (body.get("oauth_subject") or "").strip()

    if not email:
        return jsonify({"error": "email is required"}), 400
    if not oauth_subject:
        return jsonify({"error": "oauth_subject is required. Use /api/auth/bootstrap/google-id to find it."}), 400

    user_id = str(uuid.uuid4())
    try:
        execute(
            f"INSERT INTO {TABLE} (id, row_type, email, role, oauth_provider, oauth_subject, created_at) "
            f"VALUES (%s, 'user', %s, 'admin', %s, %s, NOW())",
            (user_id, email, oauth_provider, oauth_subject),
        )
        return jsonify({
            "success": True,
            "user_id": user_id,
            "email": email,
            "role": "admin",
            "oauth_provider": oauth_provider,
            "oauth_subject": oauth_subject,
            "message": "Admin user created. You can now log in with Google OAuth.",
        }), 201
    except Exception as e:
        return jsonify({"error": f"Failed to create user: {e}"}), 500


@app.route("/api/auth/bootstrap/google-id")
def bootstrap_google_id():
    """
    GET /api/auth/bootstrap/google-id

    Helper: Shows the Google OAuth subject (sub) from the most recent
    failed login attempt (stored as oauth state). This helps you find
    your Google 'sub' claim for the bootstrap call.

    Alternative: Use https://www.googleapis.com/oauth2/v3/userinfo
    with your Google access token to find your 'sub' value.
    """
    return jsonify({
        "instructions": "To find your Google OAuth subject ID, do the following:",
        "steps": [
            "1. Click 'Continue with Google' on the login page",
            "2. Complete the Google sign-in (it will redirect back with 'access_denied')",
            "3. Check Lambda CloudWatch logs for: '[Auth Callback] Unknown user rejected: provider=google sub=XXXX email=your@email'",
            "4. The 'sub' value (a numeric string like '117234567890123456789') is your oauth_subject",
            "5. Call POST /api/auth/bootstrap with that sub value",
        ],
        "example_curl": 'curl -X POST https://l7xnpjosjvyrlx55dxrwdvx5g40okeyd.lambda-url.us-east-1.on.aws/api/auth/bootstrap -H "Content-Type: application/json" -d \'{"email":"dhinesh.a@mpslimited.com","oauth_provider":"google","oauth_subject":"YOUR_GOOGLE_SUB_HERE"}\''
    })


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN (users) — requires admin role
# ═══════════════════════════════════════════════════════════════════════════════

# Safe columns to return — never expose oauth_subject, raw metadata, or
# access tokens to the frontend.
_USER_SAFE_COLS = "id, email, role, oauth_provider, created_at"


def _safe_user(row: dict) -> dict:
    """Strip sensitive fields before returning a user dict to the frontend."""
    return {
        "id":             str(row.get("id") or ""),
        "email":          row.get("email") or "",
        "role":           row.get("role") or "viewer",
        "oauth_provider": row.get("oauth_provider") or "",
        "created_at":     _safe_value(row.get("created_at")),
    }


@app.route("/api/users", methods=["GET"])
@require_auth(roles=["admin"])
def list_users():
    """
    GET /api/users

    Returns all user accounts.  Only accessible by admins.
    Response fields are restricted to non-sensitive columns — oauth_subject
    and raw metadata are never returned.
    """
    try:
        rows = query(
            f"SELECT {_USER_SAFE_COLS} FROM {TABLE} "
            f"WHERE row_type = 'user' ORDER BY created_at DESC"
        )
        return jsonify([_safe_user(r) for r in rows])
    except Exception as exc:
        logger.exception("[Users] list error: %s", exc)
        return jsonify([])


@app.route("/api/users", methods=["POST"])
@require_auth(roles=["admin"])
def create_user_admin():
    """
    POST /api/users

    Pre-register a new user.  Admin-only.

    Body:
      {
        "email": "user@example.com",   ← required
        "role":  "viewer"              ← required; must be in VALID_ROLES
      }

    Notes:
    - oauth_provider and oauth_subject are NOT required here.  They are set
      automatically when the user first logs in via Google OAuth.
    - Email uniqueness is enforced server-side.
    - The caller's identity always comes from the session — never the body.
    """
    caller = get_current_user()
    if not caller:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json() or {}
    email = (body.get("email") or "").strip().lower()
    role  = (body.get("role") or "viewer").strip()

    # ── Input validation ──────────────────────────────────────────────────────
    if not email:
        return jsonify({"error": "Bad Request", "message": "email is required"}), 400

    import re as _re
    if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Bad Request", "message": "Invalid email address"}), 400

    if role not in VALID_ROLES:
        return jsonify({
            "error":   "Bad Request",
            "message": f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}",
        }), 400

    try:
        # Duplicate check
        existing = query(
            f"SELECT id FROM {TABLE} WHERE row_type = 'user' AND email = %s LIMIT 1",
            (email,),
        )
        if existing:
            return jsonify({"error": "Conflict", "message": "A user with that email already exists"}), 409

        new_id = str(uuid.uuid4())
        row = execute_returning(
            f"INSERT INTO {TABLE} "
            f"  (id, row_type, email, role, created_at) "
            f"VALUES (%s, 'user', %s, %s, NOW()) "
            f"RETURNING {_USER_SAFE_COLS}",
            (new_id, email, role),
        )
        logger.info("[Users] Admin %s created user email=%s role=%s", caller["id"], email, role)
        return jsonify(_safe_user(row)), 201
    except Exception as exc:
        logger.exception("[Users] create error: %s", exc)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/users/<user_id>", methods=["PUT"])
@require_auth(roles=["admin"])
def update_user(user_id):
    """
    PUT /api/users/<user_id>

    Update a user's role (and optionally email).  Admin-only.

    Guards:
    - Cannot demote the last admin.
    - Returns 404 for unknown users.
    """
    caller = get_current_user()
    if not caller:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json() or {}
    new_role = body.get("role")
    if new_role is not None and new_role not in VALID_ROLES:
        return jsonify({
            "error":   "Bad Request",
            "message": f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}",
        }), 400

    try:
        rows = query(
            f"SELECT {_USER_SAFE_COLS} FROM {TABLE} WHERE row_type = 'user' AND id = %s",
            (user_id,),
        )
        if not rows:
            return jsonify({"error": "Not Found", "message": "User not found."}), 404

        existing_user = rows[0]

        # Prevent demotion of the last admin
        if new_role and new_role != "admin" and existing_user.get("role") == "admin":
            admin_count_rows = query(
                f"SELECT COUNT(*) AS cnt FROM {TABLE} "
                f"WHERE row_type = 'user' AND role = 'admin'"
            )
            admin_count = int((admin_count_rows[0] or {}).get("cnt") or 0)
            if admin_count <= 1:
                return jsonify({"error": "Forbidden", "message": "Cannot demote the last admin."}), 403

        # Build dynamic SET clause — only update supplied fields
        update_fields: dict = {}
        if "email" in body and (body["email"] or "").strip():
            update_fields["email"] = body["email"].strip().lower()
        if new_role is not None:
            update_fields["role"] = new_role

        if not update_fields:
            return jsonify(_safe_user(existing_user))

        set_clauses = ", ".join(f"{k} = %s" for k in update_fields)
        values = list(update_fields.values()) + [user_id]

        row = execute_returning(
            f"UPDATE {TABLE} SET {set_clauses} "
            f"WHERE row_type = 'user' AND id = %s "
            f"RETURNING {_USER_SAFE_COLS}",
            tuple(values),
        )
        if not row:
            return jsonify({"error": "Not Found", "message": "User not found."}), 404
        logger.info("[Users] Admin %s updated user_id=%s fields=%s", caller["id"], user_id, list(update_fields))
        return jsonify(_safe_user(row))
    except Exception as exc:
        logger.exception("[Users] PUT error: %s", exc)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/users/<user_id>", methods=["DELETE"])
@require_auth(roles=["admin"])
def delete_user(user_id):
    """
    DELETE /api/users/<user_id>

    Hard-delete a user row.  Admin-only.

    Guards:
    - Cannot delete the last admin.
    - Project rows owned by this user are left intact (owner_user_id preserved).
      They become unassigned from a responsible-user perspective but the data
      is not deleted.
    - Historical Jira ticket ownership (jira_ticket rows) is preserved — the
      created_by field is not modified.
    """
    caller = get_current_user()
    if not caller:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        rows = query(
            f"SELECT role FROM {TABLE} WHERE row_type = 'user' AND id = %s",
            (user_id,),
        )
        if not rows:
            return jsonify({"error": "User not found"}), 404

        if rows[0].get("role") == "admin":
            admin_count_rows = query(
                f"SELECT COUNT(*) AS cnt FROM {TABLE} "
                f"WHERE row_type = 'user' AND role = 'admin'"
            )
            admin_count = int((admin_count_rows[0] or {}).get("cnt") or 0)
            if admin_count <= 1:
                return jsonify({"error": "Forbidden", "message": "Cannot delete the last admin."}), 403

        # When a user is deleted, clear them as responsible_user from projects.
        # Projects themselves are NOT deleted — they become effectively unassigned.
        execute(
            f"UPDATE {TABLE} "
            f"SET metadata = COALESCE(metadata::jsonb, '{{}}'::jsonb) "
            f"           - 'responsible_user_id' "
            f"           - 'responsible_user_email' "
            f"WHERE row_type = 'project' "
            f"  AND metadata::jsonb->>'responsible_user_id' = %s",
            (user_id,),
        )

        count = execute(
            f"DELETE FROM {TABLE} WHERE row_type = 'user' AND id = %s",
            (user_id,),
        )
        if count == 0:
            return jsonify({"error": "User not found"}), 404

        logger.info("[Users] Admin %s deleted user_id=%s", caller["id"], user_id)
        return make_response("", 204)
    except Exception as exc:
        logger.exception("[Users] DELETE error: %s", exc)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/users/<target_user_id>/tickets")
@require_auth(roles=["admin"])
def get_user_ticket_counts(target_user_id):
    """
    GET /api/users/<target_user_id>/tickets

    Returns the resolved and open Jira ticket counts for any user.
    Admin-only — the requester's identity comes from the session, never the URL.

    Ownership is established via jira_ticket rows WHERE created_by = target_user_id.
    Status is read from the corresponding log rows (WHERE jira_issue_key = owned_key),
    because sync_pipeline.py writes jira_status onto row_type='log' rows — never onto
    jira_ticket rows.  jira_ticket rows do not carry a jira_status field.

    Anti-leakage guarantee:
    - Step 1 collects owned_keys using created_by = target_user_id only.
    - Step 2 reads jira_status from log rows WHERE jira_issue_key IN owned_keys.
      This reads a status value only, NOT re-determines ownership.
      No other user's tickets can appear because owned_keys is already
      scoped to this specific user's jira_ticket records.
    - If the same ARGUS key appears on multiple users' jira_ticket rows
      (possible if two users created tickets for the same error_hash), each
      user's owned_keys set is independent — their counts are independent too.

    Response:
      { "resolved": int, "open": int }
    """
    # Verify target user exists
    target = query(
        f"SELECT id FROM {TABLE} WHERE row_type = 'user' AND id = %s LIMIT 1",
        (target_user_id,),
    )
    if not target:
        return jsonify({"error": "User not found"}), 404

    try:
        from jira.webhook_handler import TERMINAL_STATUSES
        terminal_values = tuple(s.lower() for s in TERMINAL_STATUSES)

        # ── Step 1: collect jira_keys owned by this user ──────────────────────
        # jira_ticket rows written by ticket_service.py carry created_by = user_id.
        ticket_rows = query(
            f"SELECT metadata FROM {TABLE} "
            f"WHERE row_type = 'jira_ticket' "
            f"  AND metadata::jsonb->>'created_by' = %s",
            (target_user_id,),
        )

        owned_keys: set = set()
        for tr in ticket_rows:
            raw  = tr.get("metadata")
            meta = json.loads(raw) if isinstance(raw, str) else (raw or {})
            key  = (meta.get("jira_key") or meta.get("key") or "").strip()
            if key:
                owned_keys.add(key)

        # No tickets at all for this user → return zeros immediately
        if not owned_keys:
            return jsonify({"resolved": 0, "open": 0})

        # ── Step 2: read jira_status from log rows for this user's keys ───────
        # sync_pipeline.py writes jira_status onto log rows, not jira_ticket rows.
        # We read the most-recent jira_status for each owned key.
        # Only one status per key is needed to classify that ticket.
        placeholders = ", ".join(["%s"] * len(owned_keys))
        status_rows = query(
            f"SELECT DISTINCT ON (metadata::jsonb->>'jira_issue_key') "
            f"       metadata::jsonb->>'jira_issue_key' AS issue_key, "
            f"       metadata::jsonb->>'jira_status'    AS jira_status "
            f"FROM {TABLE} "
            f"WHERE row_type = 'log' "
            f"  AND metadata::jsonb->>'jira_issue_key' IN ({placeholders}) "
            f"ORDER BY metadata::jsonb->>'jira_issue_key', created_at DESC",
            tuple(sorted(owned_keys)),
        )

        # Build a lookup: issue_key → jira_status (from the most-recent log row)
        status_map: dict = {}
        for sr in status_rows:
            key    = (sr.get("issue_key") or "").strip()
            status = (sr.get("jira_status") or "").strip().lower()
            if key:
                status_map[key] = status

        # Classify each owned key using the status_map
        resolved   = 0
        open_count = 0
        for key in owned_keys:
            jira_status = status_map.get(key, "")
            if jira_status in terminal_values:
                resolved += 1
            else:
                open_count += 1

        return jsonify({"resolved": resolved, "open": open_count})

    except Exception as exc:
        logger.exception("[Users] ticket count error for user_id=%s: %s", target_user_id, exc)
        return jsonify({"error": "Internal server error"}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# TEST & DEBUG ENDPOINTS FOR SMART EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/test/smart-extraction", methods=["GET"])
@require_auth(roles=["admin"])
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
@require_auth(roles=["admin"])
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
@require_auth(roles=["admin"])
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
@require_permission("error-groups:read")
def list_error_groups():
    """
    GET /api/error-groups[?project_name=xxx]

    Returns all distinct semantic groups with occurrence counts.
    Cross-project by default; pass project_name to scope to one project.
    Groups are always a subset of the fixed taxonomy.
    """
    project_name = request.args.get("project_name", "").strip() or None
    try:
        from ai.error_grouper import list_groups
        rows = list_groups(project_name=project_name)
        return jsonify({"groups": serialize_rows(rows)})
    except Exception as e:
        logger.exception("[ErrorGroups] list failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/error-groups/taxonomy", methods=["GET"])
@require_permission("error-groups:read")
def get_error_taxonomy():
    """
    GET /api/error-groups/taxonomy

    Returns the full fixed taxonomy: all 18 predefined group names and their stable IDs.
    Useful for the frontend to render the complete list even before any errors are classified.
    """
    try:
        from ai.error_grouper import get_taxonomy
        return jsonify({"taxonomy": get_taxonomy()})
    except Exception as e:
        logger.exception("[ErrorGroups] taxonomy failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/error-groups/classify", methods=["POST"])
@require_permission("error-groups:write")
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
@require_permission("error-groups:write")
def backfill_error_groups():
    """
    POST /api/error-groups/backfill
    Body (all optional):
      {
        "batch_size":   50,
        "max_batches":  20,
        "project_name": "my_project",
        "reclassify":   false,   // set true to MERGE existing groups (not just classify NULL rows)
        "dry_run":      false    // set true to preview without writing
      }

    Default (reclassify=false):
      Classifies rows where error_group_id IS NULL.
      Safe to call repeatedly — already-classified rows are skipped.

    With reclassify=true:
      Re-runs AI classification on ALL existing groups.
      Merges groups that refer to the same semantic root cause.
      Use this when you see too many fragmented groups that should be one.
      Converges automatically — stops when no merges happen in a batch.
    """
    body         = request.get_json() or {}
    batch_size   = int(body.get("batch_size",  50))
    max_batches  = int(body.get("max_batches", 20))
    project_name = body.get("project_name", "").strip() or None
    dry_run      = bool(body.get("dry_run", False))
    reclassify   = bool(body.get("reclassify", False))

    try:
        if reclassify:
            from ai.error_grouper import reclassify_all
            summary = reclassify_all(
                batch_size   = batch_size,
                max_batches  = max_batches,
                project_name = project_name,
                dry_run      = dry_run,
            )
        else:
            from ai.error_grouper import backfill_unclassified
            summary = backfill_unclassified(
                batch_size   = batch_size,
                max_batches  = max_batches,
                project_name = project_name,
                dry_run      = dry_run,
            )
        return jsonify(summary)
    except Exception as e:
        logger.exception("[ErrorGroups] backfill failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/error-groups/override", methods=["PATCH"])
@require_permission("error-groups:write")
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
@require_permission("error-groups:write")
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
@require_permission("error-groups:write")
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
