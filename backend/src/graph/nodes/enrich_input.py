"""Node 4: enrich_input — merge photo analysis into interests."""
from __future__ import annotations

from src.graph.state import TripState


async def enrich_input(state: TripState) -> dict:
    if not state.photo_analysis:
        return {"last_node": "enrich_input"}
    pa = state.photo_analysis
    interests = list(state.interests)
    extra: list[str] = []
    if pa.place_type and pa.place_type not in {"other", "attraction"}:
        if pa.place_type not in interests:
            extra.append(pa.place_type)
    new_interests = interests + extra
    new_city = state.city
    if pa.city and pa.confidence >= 0.7 and not state.city:
        new_city = pa.city
    return {
        "last_node": "enrich_input",
        "interests": new_interests,
        "city": new_city,
    }
