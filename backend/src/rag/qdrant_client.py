"""Qdrant client — one collection for all cities, filter by city metadata."""
from __future__ import annotations

import logging
from typing import Iterable

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from src.config import settings
from src.rag.embeddings import VECTOR_SIZE, aembed_text, embed_text

log = logging.getLogger(__name__)


def get_client() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        prefer_grpc=False,
        timeout=15.0,
    )


def ensure_collection(client: QdrantClient | None = None) -> None:
    cli = client or get_client()
    coll = settings.qdrant_collection
    existing = {c.name for c in cli.get_collections().collections}
    if coll in existing:
        return
    cli.create_collection(
        collection_name=coll,
        vectors_config=qm.VectorParams(size=VECTOR_SIZE, distance=qm.Distance.COSINE),
    )
    cli.create_payload_index(coll, field_name="city", field_schema=qm.PayloadSchemaType.KEYWORD)
    cli.create_payload_index(coll, field_name="section", field_schema=qm.PayloadSchemaType.KEYWORD)
    cli.create_payload_index(coll, field_name="kind", field_schema=qm.PayloadSchemaType.KEYWORD)
    log.info("created Qdrant collection %s", coll)


def upsert_chunks(
    chunks: Iterable[dict],
    *,
    client: QdrantClient | None = None,
) -> int:
    cli = client or get_client()
    ensure_collection(cli)
    points: list[qm.PointStruct] = []
    for c in chunks:
        vector = c.get("vector") or embed_text(c["text"], task_type="RETRIEVAL_DOCUMENT")
        points.append(
            qm.PointStruct(
                id=c["id"],
                vector=vector,
                payload={
                    "city": c["city"],
                    "section": c.get("section", "general"),
                    "kind": c.get("kind", "guide"),
                    "text": c["text"],
                    "source_url": c.get("source_url", ""),
                    "title": c.get("title", ""),
                    "ingested_at": c.get("ingested_at", ""),
                    "country": c.get("country", ""),
                },
            )
        )
    cli.upsert(collection_name=settings.qdrant_collection, points=points)
    return len(points)


async def asearch(
    *,
    city: str,
    query: str,
    k: int = 5,
    section: str | None = None,
    kind: str | None = None,
) -> list[dict]:
    vector = await aembed_text(query, task_type="RETRIEVAL_QUERY")
    cli = get_client()
    must: list[qm.FieldCondition] = [
        qm.FieldCondition(key="city", match=qm.MatchValue(value=city))
    ]
    if section:
        must.append(qm.FieldCondition(key="section", match=qm.MatchValue(value=section)))
    if kind:
        must.append(qm.FieldCondition(key="kind", match=qm.MatchValue(value=kind)))
    flt = qm.Filter(must=must)
    # qdrant-client >= 1.18 removed `.search()`; use `query_points` and iterate `.points`.
    res = cli.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        query_filter=flt,
        limit=k,
        with_payload=True,
    )
    return [
        {
            "chunk_id": str(r.id),
            "score": float(r.score),
            **(r.payload or {}),
        }
        for r in res.points
    ]


def list_cities() -> list[dict]:
    cli = get_client()
    ensure_collection(cli)
    cities: dict[str, dict] = {}
    offset = None
    while True:
        points, next_offset = cli.scroll(
            collection_name=settings.qdrant_collection,
            with_payload=True,
            with_vectors=False,
            limit=512,
            offset=offset,
        )
        for p in points:
            city = (p.payload or {}).get("city")
            if not city:
                continue
            agg = cities.setdefault(
                city,
                {
                    "city": city,
                    "country": (p.payload or {}).get("country", ""),
                    "chunk_count": 0,
                    "ingested_at": "",
                },
            )
            agg["chunk_count"] += 1
            payload_ts = (p.payload or {}).get("ingested_at", "")
            if payload_ts and payload_ts > agg["ingested_at"]:
                agg["ingested_at"] = payload_ts
        if not next_offset:
            break
        offset = next_offset
    return list(cities.values())


def get_overview(city: str) -> dict | None:
    cli = get_client()
    ensure_collection(cli)
    res, _ = cli.scroll(
        collection_name=settings.qdrant_collection,
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
        return None
    p = res[0].payload or {}
    return p
