"""
Nova-powered solution extractor for Jira issues.

When a Jira issue reaches a terminal state (Done / Closed / Resolved),
this module uses Nova Lite to extract ONLY the final technical solution
from the issue's description + comments.

Nova is instructed to ignore:
  - Greetings and sign-offs
  - Status update comments ("I'll look into this")
  - Questions and clarifications
  - Duplicate or superseded information

Nova returns:
  {
    "root_cause":  str | None   — what caused the error
    "final_fix":   str | None   — the exact technical fix applied
    "confidence":  float        — 0.0–1.0, Nova's self-assessed confidence
    "extracted":   bool         — False if Nova found nothing actionable
  }

If Nova is unavailable, falls back to using the resolution + last comment
as a best-effort solution.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Prompt template ───────────────────────────────────────────────────────────
_EXTRACT_PROMPT = """You are a technical solution extractor for a software error monitoring system.

A Jira issue has been resolved. Your task is to extract ONLY the final technical solution from the content below.

STRICT RULES:
- Return ONLY the root cause and the technical fix that was actually applied.
- IGNORE: greetings, sign-offs, status updates, questions, clarifications, mentions of who is looking into it.
- IGNORE: comments that do not describe a technical action taken.
- IGNORE: duplicate information — if the same fix is mentioned multiple times, include it once.
- If no clear technical fix is present in the content, set extracted to false.
- Be concise. Root cause: 1-3 sentences. Final fix: 1-5 sentences.

ISSUE SUMMARY:
{summary}

ISSUE DESCRIPTION:
{description}

COMMENTS (chronological, most recent last):
{comments}

RESOLUTION FIELD:
{resolution}

Return ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "root_cause": "<root cause sentence or null>",
  "final_fix": "<technical fix sentence(s) or null>",
  "confidence": <0.0 to 1.0>,
  "extracted": <true or false>
}}"""


# ── Public API ────────────────────────────────────────────────────────────────

def extract_solution_from_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """
    Use Nova to extract the final technical solution from a resolved Jira issue.

    issue dict must have: summary, description, comments, resolution, status

    Returns:
      { root_cause, final_fix, confidence, extracted, raw_nova_response }
    """
    summary     = (issue.get("summary") or "").strip()
    description = (issue.get("description") or "").strip()
    resolution  = _resolve_field(issue.get("resolution"))
    comments    = issue.get("comments") or []

    # Build comment text — filter out empty bodies
    comment_lines = []
    for idx, c in enumerate(comments, start=1):
        body   = (c.get("body") or "").strip()
        # Use displayName (Jira Cloud) falling back to display_name (webhook handler normalised)
        author = (c.get("author") or {}).get("displayName") or (c.get("author") or {}).get("display_name", "Unknown")
        if body:
            comment_lines.append(f"[{idx}] {author}: {body}")

    comments_text = "\n\n".join(comment_lines) if comment_lines else "(no comments)"

    prompt = _EXTRACT_PROMPT.format(
        summary     = summary[:500],
        description = (description or "(no description)")[:1000],
        comments    = comments_text[:3000],
        resolution  = (resolution or "(none)"),
    )

    logger.info(
        "[NovaExtractor] Extracting solution from issue=%s comments=%d",
        issue.get("key", "?"), len(comments),
    )

    nova_response = _call_nova(prompt)

    if not nova_response:
        logger.warning("[NovaExtractor] Nova unavailable — falling back to heuristic extraction")
        return _fallback_extraction(issue)

    parsed = _parse_nova_response(nova_response)
    parsed["raw_nova_response"] = nova_response
    parsed["issue_key"]         = issue.get("key", "")

    if parsed.get("extracted"):
        logger.info(
            "[NovaExtractor] Extraction succeeded — confidence=%.2f root_cause=%s",
            parsed.get("confidence", 0.0),
            (parsed.get("root_cause") or "")[:60],
        )
    else:
        logger.info("[NovaExtractor] Nova found no actionable technical content")

    return parsed


# ── Nova call helpers ─────────────────────────────────────────────────────────

def _call_nova(prompt: str) -> Optional[str]:
    """Call Nova Lite via Bedrock. Returns raw text response or None."""
    try:
        from ai.bedrock_llm import invoke_nova
        result = invoke_nova(prompt, max_tokens=512, temperature=0.0)
        return result
    except Exception as exc:
        logger.warning("[NovaExtractor] Nova call failed: %s", exc)
        return None


def _parse_nova_response(raw: str) -> dict[str, Any]:
    """Parse Nova's JSON response. Returns safe defaults on any parse error."""
    default: dict[str, Any] = {
        "root_cause": None,
        "final_fix":  None,
        "confidence": 0.0,
        "extracted":  False,
    }

    if not raw:
        return default

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text  = "\n".join(
            l for l in lines if not l.startswith("```")
        ).strip()

    # Find first { ... } block
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        logger.warning("[NovaExtractor] No JSON block found in Nova response")
        return default

    try:
        parsed = json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        logger.warning("[NovaExtractor] JSON parse failed: %s", exc)
        return default

    root_cause = parsed.get("root_cause")
    final_fix  = parsed.get("final_fix")
    confidence = float(parsed.get("confidence") or 0.0)
    extracted  = bool(parsed.get("extracted", False))

    # If extracted but both fields are null/empty, mark as not extracted
    if extracted and not root_cause and not final_fix:
        extracted = False

    # Quality gate: if final_fix is a single word or very short (< 15 chars),
    # Nova likely latched onto a keyword rather than extracting a real fix.
    # Treat as not extracted so the comment fallback fires instead.
    if extracted and final_fix and len(final_fix.strip().split()) <= 2:
        logger.info(
            "[NovaExtractor] final_fix too short (%r) — rejecting as low quality",
            final_fix.strip()[:40],
        )
        extracted = False
        final_fix = None

    return {
        "root_cause": root_cause if isinstance(root_cause, str) and root_cause.strip() else None,
        "final_fix":  final_fix  if isinstance(final_fix,  str) and final_fix.strip()  else None,
        "confidence": min(1.0, max(0.0, confidence)),
        "extracted":  extracted,
    }


def _fallback_extraction(issue: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort extraction without Nova.

    Uses the resolution field + the last non-empty comment as the fix.
    Confidence is set low (0.3) to indicate this was not AI-validated.
    """
    resolution = _resolve_field(issue.get("resolution"))
    comments   = issue.get("comments") or []

    # Last non-empty comment body
    last_comment = None
    for c in reversed(comments):
        body = (c.get("body") or "").strip()
        if body and len(body) > 10:
            last_comment = body
            break

    description = (issue.get("description") or "").strip()

    # Build a best-effort fix string
    parts = []
    if resolution and resolution.lower() not in ("done", "fixed", "resolved", "complete"):
        parts.append(f"Resolution: {resolution}")
    if last_comment:
        parts.append(f"Last comment: {last_comment[:500]}")
    elif description:
        parts.append(description[:500])

    final_fix = "\n\n".join(parts) if parts else None

    return {
        "root_cause":        None,
        "final_fix":         final_fix,
        "confidence":        0.3 if final_fix else 0.0,
        "extracted":         bool(final_fix),
        "raw_nova_response": None,
        "issue_key":         issue.get("key", ""),
        "fallback":          True,
    }


def _resolve_field(resolution: Any) -> Optional[str]:
    """Normalise the resolution field (can be str or dict)."""
    if not resolution:
        return None
    if isinstance(resolution, str):
        return resolution.strip() or None
    if isinstance(resolution, dict):
        return (resolution.get("name") or "").strip() or None
    return None


def build_solution_text(extraction: dict[str, Any]) -> Optional[str]:
    """
    Combine root_cause + final_fix into a single solution string
    suitable for passing to insert_solution().

    Returns None if extraction has nothing actionable.
    """
    root_cause = (extraction.get("root_cause") or "").strip()
    final_fix  = (extraction.get("final_fix")  or "").strip()

    if not root_cause and not final_fix:
        return None

    parts = []
    if root_cause:
        parts.append(f"Root Cause: {root_cause}")
    if final_fix:
        parts.append(f"Fix: {final_fix}")

    return "\n\n".join(parts)
