"""Embeddings via OpenAI text-embedding-3-small.

Sync `embed_text` and `embed_batch` are used by the ingest script; async `aembed_text`
is used at query time by Qdrant search. The `openai` SDK is imported lazily so unit
tests that don't touch embeddings can run without the package installed.
"""
from __future__ import annotations

import logging

from src.config import settings

log = logging.getLogger(__name__)

# text-embedding-3-small native dim is 1536. text-embedding-3-large is 3072.
VECTOR_SIZE = 1536

_sync_client = None
_async_client = None


def _ensure_sync_client():
    global _sync_client
    if _sync_client is not None:
        return _sync_client
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import OpenAI

    kwargs: dict = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    _sync_client = OpenAI(**kwargs)
    return _sync_client


def _ensure_async_client():
    global _async_client
    if _async_client is not None:
        return _async_client
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import AsyncOpenAI

    kwargs: dict = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    _async_client = AsyncOpenAI(**kwargs)
    return _async_client


def embed_text(text: str, *, task_type: str = "document") -> list[float]:
    """task_type is accepted for API symmetry but ignored — OpenAI uses one endpoint for both."""
    client = _ensure_sync_client()
    resp = client.embeddings.create(model=settings.openai_embedding_model, input=text)
    return list(resp.data[0].embedding)


def embed_batch(texts: list[str], *, task_type: str = "document") -> list[list[float]]:
    if not texts:
        return []
    client = _ensure_sync_client()
    resp = client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    return [list(d.embedding) for d in resp.data]


async def aembed_text(text: str, *, task_type: str = "query") -> list[float]:
    client = _ensure_async_client()
    resp = await client.embeddings.create(model=settings.openai_embedding_model, input=text)
    return list(resp.data[0].embedding)
