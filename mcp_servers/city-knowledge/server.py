"""MCP server: city-knowledge.

Wraps Qdrant as MCP tools. 3 tools:
- search_city_guide
- get_city_overview
- list_indexed_cities
"""
from __future__ import annotations

import json
import logging
import os
from typing import Literal

from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from schemas import CityMeta, CityOverview, GuideChunk, ToolErrorResponse

logging.basicConfig(level=logging.INFO, format="[city-knowledge] %(levelname)s %(message)s")
log = logging.getLogger("city-knowledge")

mcp = FastMCP("city-knowledge")

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "trip_planner_v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

_client: QdrantClient | None = None
_openai: OpenAI | None = None


def _qdrant() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=15.0)
    return _client


def _openai_client() -> OpenAI:
    global _openai
    if _openai is not None:
        return _openai
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set for city-knowledge server")
    kwargs: dict = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    _openai = OpenAI(**kwargs)
    return _openai


def _embed(text: str) -> list[float]:
    cli = _openai_client()
    resp = cli.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return list(resp.data[0].embedding)


@mcp.tool()
async def search_city_guide(
    city: str,
    query: str,
    k: int = 5,
    section: Literal["see", "do", "eat", "drink", "sleep", "get-around"] | None = None,
) -> list[dict]:
    """Semantic search over Wikivoyage-indexed content for a city."""
    try:
        vector = _embed(query)
        must: list[qm.FieldCondition] = [
            qm.FieldCondition(key="city", match=qm.MatchValue(value=city)),
            qm.FieldCondition(key="kind", match=qm.MatchValue(value="guide")),
        ]
        if section:
            must.append(qm.FieldCondition(key="section", match=qm.MatchValue(value=section)))
        flt = qm.Filter(must=must)
        res = _qdrant().query_points(
            collection_name=QDRANT_COLLECTION,
            query=vector,
            query_filter=flt,
            limit=k,
            with_payload=True,
        )
        chunks: list[GuideChunk] = []
        for r in res.points:
            p = r.payload or {}
            chunks.append(
                GuideChunk(
                    chunk_id=str(r.id),
                    city=p.get("city", city),
                    section=p.get("section", "general"),
                    text=p.get("text", ""),
                    source_url=p.get("source_url", ""),
                    score=float(r.score),
                )
            )
        return [c.model_dump() for c in chunks]
    except Exception as exc:
        log.exception("search_city_guide failed")
        return [ToolErrorResponse(error_code="EXTERNAL_API_ERROR", message=str(exc), retryable=True).model_dump()]


@mcp.tool()
async def get_city_overview(city: str) -> dict:
    """Return structured overview of a city: currency, best season, safety, transport summary."""
    try:
        res, _ = _qdrant().scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=qm.Filter(
                must=[
                    qm.FieldCondition(key="city", match=qm.MatchValue(value=city)),
                    qm.FieldCondition(key="kind", match=qm.MatchValue(value="overview")),
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not res:
            return ToolErrorResponse(
                error_code="NOT_FOUND",
                message=f"No overview indexed for city {city}",
                retryable=False,
            ).model_dump()
        p = res[0].payload or {}
        text = p.get("text") or ""
        meta = {}
        try:
            meta = json.loads(text) if text.startswith("{") else {}
        except Exception:
            meta = {}
        return CityOverview(
            city=p.get("city", city),
            country=meta.get("country", p.get("country", "")),
            currency=meta.get("currency", "USD"),
            languages=meta.get("languages", []),
            best_season=meta.get("best_season", ""),
            safety_level=meta.get("safety_level", "low_risk"),
            safety_notes=meta.get("safety_notes", ""),
            transport_summary=meta.get("transport_summary", ""),
            timezone=meta.get("timezone", "UTC"),
        ).model_dump()
    except Exception as exc:
        log.exception("get_city_overview failed")
        return ToolErrorResponse(error_code="EXTERNAL_API_ERROR", message=str(exc), retryable=True).model_dump()


@mcp.tool()
async def list_indexed_cities() -> list[dict]:
    """Return all cities indexed in the RAG store."""
    try:
        cities: dict[str, dict] = {}
        offset = None
        while True:
            points, next_offset = _qdrant().scroll(
                collection_name=QDRANT_COLLECTION,
                with_payload=True,
                with_vectors=False,
                limit=512,
                offset=offset,
            )
            for p in points:
                payload = p.payload or {}
                city = payload.get("city")
                if not city:
                    continue
                agg = cities.setdefault(
                    city,
                    {
                        "city": city,
                        "country": payload.get("country", ""),
                        "chunk_count": 0,
                        "ingested_at": "",
                    },
                )
                agg["chunk_count"] += 1
                ts = payload.get("ingested_at", "")
                if ts and ts > agg["ingested_at"]:
                    agg["ingested_at"] = ts
            if not next_offset:
                break
            offset = next_offset
        return [CityMeta(**c).model_dump() for c in cities.values()]
    except Exception as exc:
        log.exception("list_indexed_cities failed")
        return [ToolErrorResponse(error_code="EXTERNAL_API_ERROR", message=str(exc), retryable=True).model_dump()]


if __name__ == "__main__":
    mcp.run(transport="stdio")
