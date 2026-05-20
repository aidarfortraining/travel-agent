"""Node 1: collect_input — pydantic validation only."""
from __future__ import annotations

from src.graph.state import TripState


async def collect_input(state: TripState) -> dict:
    issues: list[str] = []
    if not state.city:
        issues.append("city is empty")
    if state.days < 1 or state.days > 14:
        issues.append("days must be between 1 and 14")
    if state.budget_usd < 0:
        issues.append("budget must be non-negative")
    err = "; ".join(issues) if issues else None
    return {"last_node": "collect_input", "error": err}
