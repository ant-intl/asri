from __future__ import annotations

from typing import Any


def is_qwen_model(model_name: str | None) -> bool:
    """Return whether the model is a Qwen series model."""
    normalized = (model_name or "").lower().replace("_", "-")
    return "qwen" in normalized


def is_deepseek_v4_model(model_name: str | None) -> bool:
    """Return whether the model uses DeepSeek V4 chat-template thinking flags."""
    normalized = (model_name or "").lower().replace("_", "-")
    return "deepseek" in normalized and "v4" in normalized


def disabled_thinking_extra_body(model_name: str | None) -> dict[str, Any] | None:
    """Return provider-specific extra_body for disabling hidden reasoning.

    Only Qwen series models support the ``chat_template_kwargs.enable_thinking`` flag.
    DeepSeek V4 defaults to non-thinking when no thinking kwargs are supplied.
    Other providers (OpenAI, Anthropic, Gemini, etc.) do not support this flag.
    """
    if is_deepseek_v4_model(model_name):
        return None
    if not is_qwen_model(model_name):
        return None  # Non-Qwen models don't support thinking flags
    return {"chat_template_kwargs": {"enable_thinking": False}}
