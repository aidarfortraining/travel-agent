"""Conditional edge functions for LangGraph."""
from __future__ import annotations

from src.graph.state import TripState


def has_photo(state: TripState) -> str:
    return "vision_identify" if state.photo_b64 else "city_research"


def budget_feasible(state: TripState) -> str:
    return "cluster_by_day" if not state.budget_warning else "explain_and_ask"


def edit_or_accept(state: TripState) -> str:
    if state.accept_signal:
        return "finalize_and_export"
    if state.pending_edit_text:
        return "parse_edit_intent"
    return "finalize_and_export"
