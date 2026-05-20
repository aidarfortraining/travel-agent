"""Unified LLM client for OpenAI mini models via langchain-openai.

Single mini model is used for every LLM call in the graph (vision, edit intent,
generate_plan, LLM-as-judge). The model name is configurable via env (`OPENAI_MODEL`).
A second mini model name (`OPENAI_MODEL_B`) exists only for the A/B evals experiment.

All LLM calls flow through this module so LangSmith tracing, retries, and structured
output are uniformly applied.
"""
from __future__ import annotations

import logging
from typing import Any, Type, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMRateLimit(Exception):
    pass


class LLMTransient(Exception):
    pass


def _is_rate_limit(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate" in msg or "quota" in msg


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(x in msg for x in ("5xx", "500", "502", "503", "504", "timeout", "temporarily"))


def _build_chat(
    *,
    model: str | None = None,
    temperature: float,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": model or settings.openai_model,
        "temperature": temperature,
        "api_key": settings.openai_api_key or None,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)


def get_chat(
    *,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    model: str | None = None,
) -> ChatOpenAI:
    """Default chat handle for the project's mini model."""
    return _build_chat(model=model, temperature=temperature, max_tokens=max_tokens)


async def _call_with_retry(coro_factory, *, description: str):
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((LLMRateLimit, LLMTransient)),
        reraise=True,
    ):
        with attempt:
            try:
                return await coro_factory()
            except Exception as exc:
                if _is_rate_limit(exc):
                    log.warning("rate limit on %s: %s", description, exc)
                    raise LLMRateLimit(str(exc)) from exc
                if _is_transient(exc):
                    log.warning("transient error on %s: %s", description, exc)
                    raise LLMTransient(str(exc)) from exc
                raise


async def ainvoke_text(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    images: list[dict[str, Any]] | None = None,
) -> str:
    """Single text completion with system + user message.

    `images`: list of {"mime_type": "image/jpeg", "data": "<base64>"} for vision (GPT-4o family).
    Returns plain string. Falls back to empty string on definitive failure.
    """
    chat = _build_chat(
        model=model,
        temperature=temperature if temperature is not None else 0.7,
        max_tokens=max_tokens or 4096,
    )

    if images:
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for img in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{img['mime_type']};base64,{img['data']}"},
                }
            )
        messages: list[BaseMessage] = [SystemMessage(content=system), HumanMessage(content=content)]
    else:
        messages = [SystemMessage(content=system), HumanMessage(content=user)]

    async def _do():
        result = await chat.ainvoke(messages)
        text = result.content if isinstance(result.content, str) else str(result.content)
        return text

    try:
        return await _call_with_retry(_do, description="ainvoke_text")
    except Exception as exc:
        log.error("LLM call failed permanently: %s", exc)
        return ""


async def ainvoke_structured(
    *,
    system: str,
    user: str,
    schema: Type[T],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> T | None:
    """Structured output via OpenAI tool-mode + pydantic schema."""
    chat = _build_chat(
        model=model,
        temperature=temperature if temperature is not None else 0.1,
        max_tokens=max_tokens or 1024,
    )
    structured = chat.with_structured_output(schema)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    async def _do():
        return await structured.ainvoke(messages)

    try:
        result = await _call_with_retry(_do, description="ainvoke_structured")
        if isinstance(result, schema):
            return result
        if isinstance(result, dict):
            return schema.model_validate(result)
        return None
    except Exception as exc:
        log.error("Structured LLM call failed permanently: %s", exc)
        return None


__all__ = [
    "ainvoke_structured",
    "ainvoke_text",
    "get_chat",
    "LLMRateLimit",
    "LLMTransient",
]
