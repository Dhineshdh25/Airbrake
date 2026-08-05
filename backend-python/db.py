"""
Aurora DSQL database connection.

Uses IAM token authentication via boto3.
The connection is created lazily on first use so the module
can be imported at Lambda cold-start without needing env vars.

Required Lambda environment variables:
  DSQL_ENDPOINT  = ezt2bkam5s4kjre73r25easkcu.dsql.us-east-1.on.aws
  DSQL_REGION    = us-east-1  (optional, default us-east-1)

For local dev, also set in .env:
  AWS_ACCESS_KEY_ID     = your key id
  AWS_SECRET_ACCESS_KEY = your secret key
  AWS_DEFAULT_REGION    = us-east-1
"""

import os
import psycopg2
import psycopg2.extras
import boto3
from typing import Optional
import json
import uuid

# Load .env file for local development (no-op in Lambda)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — env vars must be set manually

_conn: Optional[psycopg2.extensions.connection] = None


def _get_token(endpoint: str, region: str) -> str:
    """Generate an IAM auth token for Aurora DSQL via boto3.

    Different boto3/botocore versions expose this method with
    different parameter casing (PascalCase vs snake_case), so
    try both to stay compatible across environments.
    """
    client = boto3.client("dsql", region_name=region)

    try:
        # Newer boto3: PascalCase kwargs
        return client.generate_db_connect_admin_auth_token(
            Hostname=endpoint,
            Region=region,
            ExpiresIn=900,
        )
    except TypeError:
        pass

    try:
        # Older/alternate boto3: snake_case kwargs
        return client.generate_db_connect_admin_auth_token(
            hostname=endpoint,
            region=region,
            expires_in=900,
        )
    except TypeError:
        pass

    # Last resort: positional args
    return client.generate_db_connect_admin_auth_token(endpoint, region)


def get_connection() -> psycopg2.extensions.connection:
    """Return a lazy singleton connection to Aurora DSQL."""
    global _conn

    # Re-use if still open
    if _conn is not None:
        try:
            # Quick liveness check
            _conn.cursor().execute("SELECT 1")
            return _conn
        except Exception:
            _conn = None  # stale connection, recreate

    endpoint = os.environ.get("DSQL_ENDPOINT", "ezt2bkam5s4kjre73r25easkcu.dsql.us-east-1.on.aws")
    region   = os.environ.get("DSQL_REGION", "us-east-1")

    if not endpoint:
        raise RuntimeError(
            "[DB] DSQL_ENDPOINT is not set. "
            "Add it in Lambda → Configuration → Environment variables."
        )

    print(f"[DB] Connecting to Aurora DSQL: {endpoint}")
    token = _get_token(endpoint, region)

    _conn = psycopg2.connect(
        host=endpoint,
        port=5432,
        dbname="postgres",
        user="admin",
        password=token,
        sslmode="require",
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
    )
    _conn.autocommit = True
    print("[DB] Aurora DSQL connected")
    return _conn


def query(sql: str, params=None) -> list:
    """Execute a SELECT and return list of dicts."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params=None) -> int:
    """Execute INSERT/UPDATE/DELETE and return rowcount."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def execute_returning(sql: str, params=None) -> Optional[dict]:
    """Execute INSERT/UPDATE with RETURNING and return the first row."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
        return dict(row) if row else None


def try_claim_jira_ticket(error_hash: str, project_name: Optional[str], metadata: dict) -> bool:
    """Attempt to insert a placeholder jira_ticket row.

    Returns True if inserted (claim succeeded), False if a conflict occurred.
    """
    conn = get_connection()
    row_id = str(uuid.uuid4())
    payload = metadata.copy()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO projects_data (id, row_type, metadata, created_at) VALUES (%s,'jira_ticket',%s,NOW())",
                (row_id, json.dumps(payload)),
            )
        return True
    except psycopg2.IntegrityError as exc:
        # Unique constraint (index) violation — another worker claimed it
        conn.rollback()
        return False


def update_claimed_jira_ticket(error_hash: str, project_name: Optional[str], metadata: dict) -> int:
    """Update the most recent jira_ticket claim row for this error_hash with full metadata.

    Returns number of rows updated (0 or 1).
    """
    conn = get_connection()
    params = [json.dumps(metadata), error_hash]
    sql = (
        "UPDATE projects_data SET metadata = %s WHERE id = ("
        "SELECT id FROM projects_data WHERE row_type = 'jira_ticket' AND metadata::jsonb->>'error_hash' = %s "
    )
    if project_name:
        sql += "AND metadata::jsonb->>'project_name' = %s "
        params.append(project_name)
    sql += "ORDER BY created_at DESC LIMIT 1)"
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.rowcount


def find_jira_ticket_by_hash(error_hash: str, project_name: Optional[str]) -> Optional[dict]:
    """Return the most recent jira_ticket metadata dict for this error_hash, or None."""
    if not error_hash:
        return None
    params = [error_hash]
    sql = (
        "SELECT metadata FROM projects_data "
        "WHERE row_type = 'jira_ticket' AND metadata::jsonb->>'error_hash' = %s "
    )
    if project_name:
        sql += "AND metadata::jsonb->>'project_name' = %s "
        params.append(project_name)
    sql += "ORDER BY created_at DESC LIMIT 1"
    rows = query(sql, tuple(params))
    if not rows:
        return None
    raw = rows[0].get('metadata')
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
