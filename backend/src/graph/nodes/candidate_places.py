"""Node 6: candidate_places — find POI, restaurants, weather via travel-tools MCP."""
from __future__ import annotations

import asyncio
import logging

from src.graph.state import TripState
from src.mcp_clients.client import call_tool, call_tool_list
from src.schemas import Place, Restaurant, WeatherDaily

log = logging.getLogger(__name__)

# Hard cap on how long this node may spend gathering external data. Overpass is
# unstable (regular 504/429/timeouts across all mirrors); without a ceiling the
# sequential per-category retries could block the graph for 10+ minutes and the
# UI sits on "Генерация" looking stuck. We fan out all calls concurrently and use
# whatever results arrived within the budget — a thin plan beats a hung graph.
GATHER_BUDGET_SECONDS = 75.0


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


async def _gather_with_budget(labeled_coros: dict[str, object]) -> dict[str, object]:
    """Run labeled coroutines concurrently, capped by GATHER_BUDGET_SECONDS.

    Returns {label: result_or_exception}. Unfinished tasks are cancelled and
    omitted — the caller treats a missing label as "no data for this call".
    """
    tasks = {asyncio.ensure_future(coro): label for label, coro in labeled_coros.items()}
    done, pending = await asyncio.wait(tasks.keys(), timeout=GATHER_BUDGET_SECONDS)
    for task in pending:
        task.cancel()
        log.warning("candidate_places: '%s' exceeded %.0fs budget, skipped", tasks[task], GATHER_BUDGET_SECONDS)
    # Await cancelled tasks so their exceptions are retrieved (avoids noisy
    # "Task exception was never retrieved" warnings under degraded Overpass).
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    results: dict[str, object] = {}
    for task in done:
        try:
            results[tasks[task]] = task.result()
        except Exception as exc:  # noqa: BLE001 — surfaced per-call below
            results[tasks[task]] = exc
    return results


async def candidate_places(state: TripState) -> dict:
    aggregated = list(state.tool_calls_aggregated)
    categories: list[str] = []
    for interest in state.interests:
        for cat in INTEREST_TO_CATEGORIES.get(interest.lower(), []):
            if cat not in categories:
                categories.append(cat)
    if not categories:
        categories = list(DEFAULT_CATEGORIES)
    categories = categories[:5]
    per_category_limit = max(4, state.days * 2)
    rest_limit = max(state.days * 3, 6)

    # Fan out every external call concurrently instead of awaiting them serially:
    # wall time becomes ~max(single call) rather than sum, and the shared budget
    # caps a degraded Overpass instead of letting it stall the node for minutes.
    labeled_coros: dict[str, object] = {
        f"places:{cat}": call_tool_list(
            "find_places", city=state.city, category=cat, budget_tier="mid", limit=per_category_limit
        )
        for cat in categories
    }
    labeled_coros["restaurants"] = call_tool_list(
        "find_restaurants",
        city=state.city,
        dietary=state.dietary,
        cuisine=None,
        price_tier="$$",
        limit=rest_limit,
    )
    labeled_coros["weather"] = call_tool("get_weather_forecast", city=state.city)

    results = await _gather_with_budget(labeled_coros)

    places: list[Place] = []
    for cat in categories:
        result = results.get(f"places:{cat}")
        if isinstance(result, Exception) or result is None:
            log.warning("find_places(%s) failed/skipped: %s", cat, result)
            continue
        aggregated = _record(aggregated, "find_places", {"city": state.city, "category": cat}, result)
        for r in result:
            if isinstance(r, dict) and not r.get("is_error"):
                places.append(Place.model_validate(r))

    restaurants: list[Restaurant] = []
    rest_result = results.get("restaurants")
    if isinstance(rest_result, Exception) or rest_result is None:
        log.warning("find_restaurants failed/skipped: %s", rest_result)
    else:
        aggregated = _record(aggregated, "find_restaurants", {"city": state.city, "dietary": state.dietary}, rest_result)
        restaurants = [Restaurant.model_validate(r) for r in rest_result if isinstance(r, dict) and not r.get("is_error")]

    weather = None
    wresult = results.get("weather")
    if isinstance(wresult, Exception) or wresult is None:
        log.warning("get_weather_forecast failed/skipped: %s", wresult)
    else:
        aggregated = _record(aggregated, "get_weather_forecast", {"city": state.city}, wresult)
        if isinstance(wresult, dict) and not wresult.get("is_error"):
            weather = WeatherDaily.model_validate(wresult)

    return {
        "last_node": "candidate_places",
        "candidate_places": places,
        "candidate_restaurants": restaurants,
        "weather": weather,
        "tool_calls_aggregated": aggregated,
    }
