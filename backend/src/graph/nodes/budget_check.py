"""Node 7: budget_check — pre-flight cost estimate, decides whether to interrupt for user."""
from __future__ import annotations

import logging

from src.graph.state import TripState

log = logging.getLogger(__name__)


def _attractions_cost(places, days: int, slots_per_day: int = 2) -> float:
    needed = days * slots_per_day
    sorted_by_cost = sorted(places, key=lambda p: p.estimated_cost_usd)
    return sum(p.estimated_cost_usd for p in sorted_by_cost[:needed])


def _restaurants_cost(restaurants, days: int) -> float:
    cheapest = sorted(restaurants, key=lambda r: r.estimated_meal_cost_usd)
    needed = days * 2
    return sum(r.estimated_meal_cost_usd for r in cheapest[:needed])


async def budget_check(state: TripState) -> dict:
    # Skip the warning on second pass — the user (or EVAL_MODE auto-accept) has
    # already opted in to a reduced/expanded scope; re-flagging would loop back
    # into explain_and_ask forever.
    if state.budget_acknowledged:
        return {"last_node": "budget_check", "budget_warning": None}
    if not state.candidate_places:
        return {"last_node": "budget_check", "budget_warning": None}
    est = _attractions_cost(state.candidate_places, state.days) + _restaurants_cost(
        state.candidate_restaurants, state.days
    )
    warning: str | None = None
    if est > state.budget_usd * 1.15:
        gap = est - state.budget_usd
        warning = (
            f"Минимально-реалистичная стоимость поездки: ${est:.0f}. "
            f"Это на ${gap:.0f} выше заявленного бюджета (${state.budget_usd:.0f}). "
            f"Сократим количество платных мест и используем бесплатные альтернативы."
        )
    return {"last_node": "budget_check", "budget_warning": warning}
