"""Node 5: city_research — RAG search via city-knowledge MCP server."""
from __future__ import annotations

import logging

from src.graph.state import TripState
from src.mcp_clients.client import call_tool, call_tool_list
from src.schemas import CityOverview, GuideChunk

log = logging.getLogger(__name__)


def _record_call(state_calls: list[dict], tool: str, args: dict, result: object) -> list[dict]:
    summary = result
    if isinstance(result, list):
        summary = {"count": len(result), "first": result[0] if result else None}
    return state_calls + [{"tool": tool, "args": args, "result_summary": summary}]


async def city_research(state: TripState) -> dict:
    aggregated = list(state.tool_calls_aggregated)
    queries: list[tuple[str, str | None]] = [
        (f"top attractions in {state.city}", "see"),
        (f"{', '.join(state.interests) or 'tourist'} highlights in {state.city}", None),
    ]
    chunks: list[GuideChunk] = []
    for q, section in queries:
        try:
            result = await call_tool_list("search_city_guide", city=state.city, query=q, k=4, section=section)
            aggregated = _record_call(aggregated, "search_city_guide", {"city": state.city, "query": q, "section": section}, result)
            for r in result:
                if isinstance(r, dict) and not r.get("is_error"):
                    chunks.append(GuideChunk.model_validate(r))
        except Exception as exc:
            log.warning("search_city_guide failed: %s", exc)
    try:
        ov_raw = await call_tool("get_city_overview", city=state.city)
        aggregated = _record_call(aggregated, "get_city_overview", {"city": state.city}, ov_raw)
        if isinstance(ov_raw, dict) and not ov_raw.get("is_error"):
            overview = CityOverview.model_validate(ov_raw)
        else:
            overview = CityOverview(city=state.city)
    except Exception as exc:
        log.warning("get_city_overview failed: %s", exc)
        overview = CityOverview(city=state.city)

    return {
        "last_node": "city_research",
        "city_context": chunks,
        "city_overview": overview,
        "tool_calls_aggregated": aggregated,
    }
