"""Node 12: present_plan — HITL, await edit or accept."""
from __future__ import annotations

import logging

from langgraph.types import interrupt

from src.config import settings
from src.graph.state import TripState

log = logging.getLogger(__name__)


async def present_plan(state: TripState) -> dict:
    if settings.eval_mode:
        log.info("EVAL_MODE: auto-accept present_plan")
        return {"last_node": "present_plan", "accept_signal": True}
    decision = interrupt({
        "type": "review_plan",
        "plan_markdown": state.plan_markdown,
        "cost": state.plan_cost_breakdown.model_dump() if state.plan_cost_breakdown else None,
    })
    if isinstance(decision, dict):
        if decision.get("accept"):
            return {"last_node": "present_plan", "accept_signal": True, "pending_edit_text": None}
        edit_text = decision.get("edit")
        if edit_text:
            return {"last_node": "present_plan", "accept_signal": False, "pending_edit_text": edit_text}
    return {"last_node": "present_plan", "accept_signal": True}
