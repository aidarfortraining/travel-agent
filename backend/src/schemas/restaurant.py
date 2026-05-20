"""Restaurant schema — from travel-tools MCP server."""
from __future__ import annotations

from pydantic import BaseModel


class Restaurant(BaseModel):
    osm_id: str
    name: str
    cuisine: str | None = None
    lat: float
    lon: float
    address: str | None = None
    dietary_tags: list[str] = []
    dietary_confidence: float = 0.0
    price_tier: str = "$$"
    opening_hours: str | None = None
    phone: str | None = None
    estimated_meal_cost_usd: float = 15.0

    @property
    def source_url(self) -> str:
        kind, _, ident = self.osm_id.partition("/")
        if kind in {"node", "way", "relation"} and ident:
            return f"https://www.openstreetmap.org/{kind}/{ident}"
        return f"https://www.openstreetmap.org/?mlat={self.lat}&mlon={self.lon}"
