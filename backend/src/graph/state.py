"""TripState — the LangGraph state model."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.schemas import (
    CityOverview,
    CostBreakdown,
    EditRecord,
    GuideChunk,
    PhotoAnalysis,
    Place,
    Plan,
    Restaurant,
    WeatherDaily,
)


class TripState(BaseModel):
    session_id: str

    # Form input
    city: str = ""
    days: int = 1
    budget_usd: float = 0.0
    interests: list[str] = []
    dietary: list[str] = []
    photo_b64: str | None = None
    photo_mime: str = "image/jpeg"

    # Derived
    photo_analysis: PhotoAnalysis | None = None
    city_overview: CityOverview | None = None
    city_context: list[GuideChunk] = []
    candidate_places: list[Place] = []
    candidate_restaurants: list[Restaurant] = []
    weather: WeatherDaily | None = None
    day_assignment: dict[int, list[str]] = Field(default_factory=dict)
    route_per_day: dict[int, list[str]] = Field(default_factory=dict)

    # Plan
    plan: Plan | None = None
    plan_markdown: str | None = None
    plan_cost_breakdown: CostBreakdown | None = None

    # Edit
    pending_edit_text: str | None = None
    edit_history: list[EditRecord] = []

    # Aggregated tool calls (for faithfulness judge)
    tool_calls_aggregated: list[dict] = []

    # Routing / state
    status: Literal["draft", "awaiting_review", "finalized"] = "draft"
    last_node: str = ""
    error: str | None = None
    budget_warning: str | None = None
    budget_acknowledged: bool = False
    accept_signal: bool = False
