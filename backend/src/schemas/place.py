"""Place schema — POI from OSM via travel-tools MCP server."""
from __future__ import annotations

from pydantic import BaseModel


class Place(BaseModel):
    osm_id: str
    name: str
    category: str
    lat: float
    lon: float
    address: str | None = None
    opening_hours: str | None = None
    website: str | None = None
    wikipedia: str | None = None
    estimated_visit_minutes: int = 60
    estimated_cost_usd: float = 0.0

    @property
    def source_url(self) -> str:
        kind, _, ident = self.osm_id.partition("/")
        if kind in {"node", "way", "relation"} and ident:
            return f"https://www.openstreetmap.org/{kind}/{ident}"
        return f"https://www.openstreetmap.org/?mlat={self.lat}&mlon={self.lon}"
