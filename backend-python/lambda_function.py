
"""
AWS Lambda entry point.

Uses Mangum to wrap the Flask WSGI app (via an ASGI adapter) for
Lambda Function URL (HTTP API v2 payload format).

Lambda environment variables required:
  DSQL_ENDPOINT  = ezt2bkam5s4kjre73r25easkcu.dsql.us-east-1.on.aws
  DSQL_REGION    = us-east-1

Handler setting in Lambda console:
  lambda_function.lambda_handler       <- main HTTP handler
  lambda_function.alert_handler        <- EventBridge scheduled rule (every 1 min)
"""

import asyncio
import os
import sys
import traceback

# Ensure the backend-python directory is always on sys.path so local imports
# like `from app import app` resolve correctly in Lambda execution environments.
sys.path.insert(0, os.path.dirname(__file__))

# Python 3.14 removed the implicit auto-creation of an event loop in
# asyncio.get_event_loop() when called from the main thread with no
# running loop. Mangum 0.19.0 relies on that old behavior, so we create
# and set one explicitly at import time.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from flask import Flask, jsonify

try:
    from mangum import Mangum
except Exception as exc:  # pragma: no cover - import safety
    Mangum = None  # type: ignore
    _MANGUM_IMPORT_ERROR = exc
else:
    _MANGUM_IMPORT_ERROR = None

try:
    from asgiref.wsgi import WsgiToAsgi
except Exception as exc:  # pragma: no cover - import safety
    WsgiToAsgi = None  # type: ignore
    _WSGI_IMPORT_ERROR = exc
else:
    _WSGI_IMPORT_ERROR = None


def _build_fallback_app():
    fallback_app = Flask(__name__)

    @fallback_app.route("/api/health")
    def health():
        return jsonify({"status": "degraded", "message": "backend import failed; AI functionality disabled"})

    @fallback_app.route("/api/debug/ai-health")
    def ai_health():
        return jsonify({"status": "degraded", "error": "backend import failed"})

    return fallback_app


try:
    from app import app as _flask_app
except Exception as exc:
    import traceback as _tb
    print("========================================")
    print("FAILED TO IMPORT APP")
    print(f"exception type: {type(exc).__name__}")
    print(f"exception message: {exc}")
    print("full traceback:")
    print(_tb.format_exc())
    print("--- Diagnostic: checking for critical packages on sys.path ---")
    _base = os.path.dirname(__file__)
    for _pkg in ("auth", "jira", "ai", "db.py", "app.py"):
        _path = os.path.join(_base, _pkg)
        print(f"  {_pkg}: {'EXISTS' if os.path.exists(_path) else 'MISSING'} ({_path})")
    print("Fallback app will be created.")
    print("========================================")
    app = _build_fallback_app()
else:
    print("========================================")
    print("REAL Flask app imported successfully.")
    try:
        routes = sorted([f"{rule.rule} [{','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))}]" for rule in _flask_app.url_map.iter_rules() if rule.rule != '/static/<path:filename>'])
        print(f"Registered {len(routes)} Flask routes:")
        for route in routes:
            print(f"  {route}")
        # Verify critical auth routes are registered
        _route_paths = {rule.rule for rule in _flask_app.url_map.iter_rules()}
        _required_routes = ["/api/auth/google", "/api/auth/google/callback", "/api/auth/me", "/api/auth/logout", "/api/health"]
        for _r in _required_routes:
            status = "OK" if _r in _route_paths else "MISSING"
            print(f"  [VERIFY] {_r}: {status}")
    except Exception as route_exc:
        import traceback as _tb
        print("Failed to inspect app.url_map")
        print(f"exception type: {type(route_exc).__name__}")
        print(f"exception message: {route_exc}")
        print(_tb.format_exc())
    print("========================================")
    app = _flask_app

# -- Main HTTP handler ----------------------------------------------------
# Flask is a WSGI app. Mangum 0.19 expects an ASGI app, so wrap Flask
# with asgiref's WsgiToAsgi adapter before passing it to Mangum.
if WsgiToAsgi is not None and Mangum is not None:
    _asgi_app = WsgiToAsgi(app)
    _mangum = Mangum(_asgi_app, lifespan="off")
else:
    _mangum = None


def lambda_handler(event, context):
    """Handle all incoming HTTP requests via Lambda Function URL."""
    # Ensure an event loop exists in this execution context too
    # (Lambda may reuse threads across invocations).
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    if _mangum is None:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": jsonify({
                "status": "degraded",
                "message": "Lambda adapter unavailable",
                "mangum_error": str(_MANGUM_IMPORT_ERROR) if _MANGUM_IMPORT_ERROR else None,
                "wsgi_error": str(_WSGI_IMPORT_ERROR) if _WSGI_IMPORT_ERROR else None,
            }).get_data(as_text=True),
        }
    return _mangum(event, context)


# -- Alert engine handler ---------------------------------------------------
# Wire an EventBridge scheduled rule (rate: 1 minute) to this handler.
def alert_handler(event, context):
    """Run one pass of the alert engine. Called by EventBridge scheduled rule."""
    from alert_engine import run_alert_check_once
    run_alert_check_once()
    return {"status": "ok"}

