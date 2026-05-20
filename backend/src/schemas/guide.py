"""Guide / city schemas — from city-knowledge MCP server."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class GuideChunk(BaseModel):
    chunk_id: str
    city: str
    section: str
    text: str
    source_url: str
    score: float = 0.0


class CityOverview(BaseModel):
    city: str
    country: str = ""
    currency: str = "USD"
    languages: list[str] = []
    best_season: str = ""
    safety_level: Literal["low_risk", "moderate_risk", "high_risk"] = "low_risk"
    safety_notes: str = ""
    transport_summary: str = ""
    timezone: str = "UTC"


class CityMeta(BaseModel):
    city: str
    country: str = ""
    chunk_count: int = 0
    ingested_at: str = ""
