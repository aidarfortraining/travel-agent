"""Node 8: explain_and_ask — HITL when budget infeasible."""
from __future__ import annotations

import logging

from langgraph.types import interrupt

from src.config import settings
from src.graph.state import TripState

log = logging.getLogger(__name__)


async def explain_and_ask(state: TripState) -> dict:
    message = state.budget_warning or "Бюджет недостаточен для запрошенного маршрута."
    if settings.eval_mode:
        # Simulate "accept reduced scope" so the next budget_feasible branch routes to
        # cluster_by_day instead of looping back into explain_and_ask forever.
        log.info("EVAL_MODE: auto-accept explain_and_ask")
        return {
            "last_node": "explain_and_ask",
            "budget_warning": None,
            "budget_acknowledged": True,
        }
    decision = interrupt({"type": "budget_explain", "message": message})
    if isinstance(decision, dict):
        if decision.get("accept_reduced"):
            return {
                "last_node": "explain_and_ask",
                "budget_warning": None,
                "budget_acknowledged": True,
            }
        if decision.get("new_budget_usd"):
            return {
                "last_node": "explain_and_ask",
                "budget_usd": float(decision["new_budget_usd"]),
                "budget_warning": None,
                "budget_acknowledged": True,
            }
    return {
        "last_node": "explain_and_ask",
        "budget_warning": None,
        "budget_acknowledged": True,
    }
