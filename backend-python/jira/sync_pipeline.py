"""
Jira → Airbrake solution sync pipeline.

When a Jira issue is resolved this module:
  1. Fetches the full issue + comments from Jira
  2. Uses Nova to extract the final technical solution
  3. Runs that solution through the EXACT SAME pipeline as Save Solution:
       normalize → embedding → pinecone → duplicate detection → nova validation
       → knowledge base insert → confidence update
  4. Marks the Airbrake log row as resolved (only on successful ingestion)
  5. Records resolved_from=jira, resolved_by=<display_name>, jira_resolver_account_id

NEVER bypasses insert_solution(). Jira is just another solution source.
If ingestion fails the log row is left unresolved and marked sync_failed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TABLE = "projects_data"

# ── Import pipeline functions (same pattern as app.py) ───────────────────────
try:
    from ai.knowledge_base import insert_solution
except Exception as _kb_exc:
    logger.error("[SyncPipeline] knowledge_base import failed: %s", _kb_exc)
    def insert_solution(*a, **kw):
        raise RuntimeError(f"Knowledge Base unavailable: {_kb_exc}")

try:
    from db import execute, query
except Exception as _db_exc:
    logger.error("[SyncPipeline] db import failed: %s", _db_exc)
    def execute(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
    def query(*a, **kw):
        raise RuntimeError(f"DB unavailable: {_db_exc}")
