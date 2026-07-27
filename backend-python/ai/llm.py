"""Amazon Bedrock Nova Lite wrapper with graceful fallback."""

from __future__ import annotations

try:
    from ai.bedrock_llm import generate_ai_response, generate_suggested_solution, generate_error_description
except Exception as exc:  # pragma: no cover - import safety
    def generate_ai_response(prompt: str, context=None, max_tokens: int = 256) -> str:
        return f"AI unavailable — component=ai.llm error={type(exc).__name__}: {exc}"

    def generate_suggested_solution(prompt: str, context=None) -> str:
        return f"AI unavailable — component=ai.llm error={type(exc).__name__}: {exc}"

    def generate_error_description(error_message: str, error_detail=None, project_name=None, solutions=None) -> str:
        return "An error occurred in the application. Review the stack trace for details."

__all__ = ["generate_ai_response", "generate_suggested_solution", "generate_error_description"]
