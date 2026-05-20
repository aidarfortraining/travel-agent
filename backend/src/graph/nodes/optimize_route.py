"""Node 10: optimize_route — nearest-neighbor ordering within each day."""
from __future__ import annotations

import logging
import math

from src.graph.state import TripState

log = logging.getLogger(__name__)


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _order_nearest_neighbor(places) -> list:
    if not places:
        return []
    remaining = list(places)
    start = max(remaining, key=lambda p: (p.lat, p.lon))
    remaining.remove(start)
    ordered = [start]
    while remaining:
        last = ordered[-1]
        nxt = min(remaining, key=lambda p: _haversine((last.lat, last.lon), (p.lat, p.lon)))
        ordered.append(nxt)
        remaining.remove(nxt)
    return ordered


async def optimize_route(state: TripState) -> dict:
    by_id = {p.osm_id: p for p in state.candidate_places}
    route_per_day: dict[int, list[str]] = {}
    for day_num, place_ids in state.day_assignment.items():
        places = [by_id[pid] for pid in place_ids if pid in by_id]
        ordered = _order_nearest_neighbor(places)
        route_per_day[day_num] = [p.osm_id for p in ordered]
    return {"last_node": "optimize_route", "route_per_day": route_per_day}
