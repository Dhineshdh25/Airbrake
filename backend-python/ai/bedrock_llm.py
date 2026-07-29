"""Amazon Bedrock Nova Lite wrapper with graceful fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

try:
    import boto3
except Exception as exc:  # pragma: no cover - optional dependency
    boto3 = None  # type: ignore
    _BOTO3_IMPORT_ERROR = exc
else:
    _BOTO3_IMPORT_ERROR = None


def _get_bedrock_region() -> str:
    return os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION") or "us-east-1"


def _get_nova_model_id() -> str:
    return os.getenv("BEDROCK_NOVA_MODEL_ID") or os.getenv("BEDROCK_MODEL_ID") or "amazon.nova-lite-v1:0"


def _get_runtime_client():
    if boto3 is None:
        raise RuntimeError(f"boto3 import failed: {_BOTO3_IMPORT_ERROR}")
    return boto3.client("bedrock-runtime", region_name=_get_bedrock_region())


def _call_nova(prompt: str, max_tokens: int = 256) -> Optional[str]:
    try:
        client = _get_runtime_client()
        model_id = _get_nova_model_id()
        logger.info("[Nova] Bedrock request about to send — model_id=%s prompt_length=%d max_tokens=%d", model_id, len(prompt), max_tokens)
        body = json.dumps({
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "maxTokens": max_tokens,
            "temperature": 0.0,
        })
        response = client.invoke_model(modelId=model_id, body=body)
        payload = json.loads(response.get("body").read().decode("utf-8"))
        logger.info("[Nova] Bedrock raw response payload=%r", payload)
        output = payload.get("output")
        output_items = []
        if isinstance(output, dict):
            output_items = [output]
        elif isinstance(output, list):
            output_items = output

        text_parts = []
        for item in output_items:
            if not isinstance(item, dict):
                continue
            message = item.get("message") if isinstance(item.get("message"), dict) else item
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text_parts.append(str(part.get("text", "")))
            elif isinstance(content, str):
                text_parts.append(content)

        trimmed = "".join(text_parts).strip()
        if trimmed:
            logger.info("[Nova] Parsed Nova text response length=%d text=%r", len(trimmed), trimmed[:500])
            return trimmed
        logger.info("[Nova] No text content received from Nova response")
        return None
    except Exception as exc:
        logger.exception("Bedrock Nova failed — component=bedrock_llm operation=invoke_model")
        return None


def generate_ai_response(prompt: str, context: Optional[Any] = None, max_tokens: int = 256) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        logger.info("[Nova] Prompt empty — using fallback response")
        return _fallback_summary(context)
    logger.info("[Nova] Prompt sent to Nova — length=%d", len(prompt))
    result = _call_nova(prompt, max_tokens=max_tokens)
    if result and result.strip():
        trimmed = result.strip()
        logger.info("[Nova] Nova response received — length=%d text=%r", len(trimmed), trimmed[:300])
        return trimmed
    logger.info("[Nova] No response from Nova — using fallback")
    fallback = _fallback_summary(context)
    logger.info("[Nova] Fallback used: %r", fallback)
    return fallback


def generate_suggested_solution(prompt: str, context: Optional[Any] = None) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        logger.info("[Nova] Recommendation prompt empty — using fallback")
        return _fallback_summary(context)
    if isinstance(context, list):
        prompt = _build_recommendation_prompt(prompt, context)
    logger.info("[Nova] Recommendation context provided — solutions=%d", len(context) if isinstance(context, list) else 0)
    return generate_ai_response(prompt, context)


def _fallback_summary(context: Any) -> str:
    if isinstance(context, list) and context:
        first = context[0]
        if isinstance(first, dict):
            usage = first.get("usage_count") or 0
            ver = first.get("version") or 1
            return (
                "This recommendation is based on a previously successful resolution. "
                f"Used {usage} time(s) • v{ver}."
            )
    return "No similar solution was found."


def _build_recommendation_prompt(error_prompt: str, solutions: List[Any]) -> str:
    solution_entries = []
    for idx, s in enumerate(solutions[:5], start=1):
        sol_text = (s.get("solution") or "").strip()
        if not sol_text:
            continue
        usage = s.get("usage_count") or 0
        version = s.get("version") or 1
        confidence = s.get("confidence_score")
        meta_parts = [f"Used {usage} times", f"v{version}"]
        if confidence is not None:
            meta_parts.append(f"confidence {confidence}%")
        solution_entries.append(
            f"{idx}. {sol_text} ({' • '.join(meta_parts)})"
        )

    solutions_text = "\n".join(solution_entries) if solution_entries else "No retrieved solutions available."
    return (
        "Use the following information to write a concise developer-facing recommendation. "
        "Do not repeat the full solution text verbatim; the actual solution will be shown separately. "
        "Explain why the selected solution is relevant and how it matches this error. "
        "Mention that the solution has been successfully used before if applicable.\n\n"
        f"Error: {error_prompt}\n\n"
        f"Top retrieved solutions:\n{solutions_text}\n\n"
        "Output only the recommendation, not the full solution text."
    )

def generate_error_description(
    error_message: str,
    error_detail: Optional[str] = None,
    project_name: Optional[str] = None,
    solutions: Optional[List[Any]] = None,
) -> str:
    """Generate a concise explanation of what the error means.

    Args:
        error_message: The error title or message
        error_detail: Stack trace or additional error context
        project_name: Project name (optional context)
        solutions: List of recommended solutions (for context, not output)

    Returns:
        A 40-80 word description explaining the error.
    """
    if not isinstance(error_message, str) or not error_message.strip():
        return ""

    parts = [f"Error: {error_message.strip()}"]

    if error_detail and isinstance(error_detail, str) and error_detail.strip():
        # Truncate stack trace to first 500 chars to avoid huge prompts
        truncated_detail = error_detail.strip()[:500]
        parts.append(f"Details: {truncated_detail}")

    if project_name and isinstance(project_name, str) and project_name.strip():
        parts.append(f"Project: {project_name.strip()}")

    prompt = "\n".join(parts)

    full_prompt = (
        "Explain what this error means in 40-80 words. "
        "Cover: 1) what the error indicates, 2) the likely cause, 3) the impact. "
        "Be developer-friendly and concise. "
        "Do not repeat the error message word-for-word. "
        "Do not invent information not in the error context. "
        "Return only the explanation.\n\n"
        + prompt
    )

    result = _call_nova(full_prompt, max_tokens=150)
    if result and result.strip():
        return result.strip()
    return ""