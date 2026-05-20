"""Node 6: candidate_places — find POI, restaurants, weather via travel-tools MCP."""
from __future__ import annotations

import logging

from src.graph.state import TripState
from src.mcp_clients.client import call_tool, call_tool_list
from src.schemas import Place, Restaurant, WeatherDaily

log = logging.getLogger(__name__)


INTEREST_TO_CATEGORIES: dict[str, list[str]] = {
    "history": ["historical", "museum"],
    "art": ["museum"],
    "architecture": ["historical", "religious"],
    "food": [],
    "nature": ["park", "viewpoint"],
    "family": ["park", "museum"],
    "nightlife": ["nightlife"],
    "shopping": ["shopping"],
    "religious": ["religious"],
}

DEFAULT_CATEGORIES = ["historical", "museum", "viewpoint", "park"]


def _record(calls: list[dict], tool: str, args: dict, result: object) -> list[dict]:
    summary = result
    if isinstance(result, list):
        summary = {"count": len(result), "names": [r.get("name") for r in result if isinstance(r, dict)][:10]}
    elif isinstance(result, dict):
        summary = {k: result.get(k) for k in ("city", "is_forecast", "is_error", "verdict") if k in result}
    return calls + [{"tool": tool, "args": args, "result_summary": summary}]


async def candidate_places(state: TripState) -> dict:
    aggregated = list(state.tool_calls_aggregated)
    categories: list[str] = []
    for interest in state.interests:
        for cat in INTEREST_TO_CATEGORIES.get(interest.lower(), []):
            if cat not in categories:
                categories.append(cat)
    if not categories:
        categories = list(DEFAULT_CATEGORIES)
    per_category_limit = max(4, state.days * 2)

    places: list[Place] = []
    for cat in categories[:5]:
        try:
            result = await call_tool_list(
                "find_places", city=state.city, category=cat, budget_tier="mid", limit=per_category_limit
            )
            aggregated = _record(aggregated, "find_places", {"city": state.city, "category": cat}, result)
            for r in result:
                if isinstance(r, dict) and not r.get("is_error"):
                    places.append(Place.model_validate(r))
        except Exception as exc:
            log.warning("find_places(%s) failed: %s", cat, exc)

    rest_limit = max(state.days * 3, 6)
    try:
        result = await call_tool_list(
            "find_restaurants",
            city=state.city,
            dietary=state.dietary,
            cuisine=None,
            price_tier="$$",
            limit=rest_limit,
        )
        aggregated = _record(aggregated, "find_restaurants", {"city": state.city, "dietary": state.dietary}, result)
        restaurants = [Restaurant.model_validate(r) for r in result if isinstance(r, dict) and not r.get("is_error")]
    except Exception as exc:
        log.warning("find_restaurants failed: %s", exc)
        restaurants = []

    try:
        wresult = await call_tool("get_weather_forecast", city=state.city)
        aggregated = _record(aggregated, "get_weather_forecast", {"city": state.city}, wresult)
        if isinstance(wresult, dict) and not wresult.get("is_error"):
            weather = WeatherDaily.model_validate(wresult)
        else:
            weather = None
    except Exception as exc:
        log.warning("get_weather_forecast failed: %s", exc)
        weather = None

    return {
        "last_node": "candidate_places",
        "candidate_places": places,
        "candidate_restaurants": restaurants,
        "weather": weather,
        "tool_calls_aggregated": aggregated,
    }
