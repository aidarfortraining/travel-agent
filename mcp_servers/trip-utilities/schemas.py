"""Local pydantic schemas for trip-utilities MCP server."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class TimeBlock(BaseModel):
    period: Literal["morning", "afternoon", "evening"]
    start_time: str
    place_id: str
    place_name: str = ""
    place_type: Literal["attraction", "restaurant", "transition"]
    estimated_cost_usd: float = 0.0
    estimated_duration_minutes: int = 60
    notes: str = ""
    source_url: str | None = None
    dietary_marker: str | None = None


class DayPlan(BaseModel):
    day_number: int
    date: str | None = None
    blocks: list[TimeBlock] = []


class Plan(BaseModel):
    city: str
    days: list[DayPlan] = []
    accommodation_per_night_usd: float | None = None


class CostBreakdownDay(BaseModel):
    day_number: int
    attractions_usd: float = 0.0
    restaurants_usd: float = 0.0
    transport_usd: float = 0.0
    total_usd: float = 0.0


class CostBreakdown(BaseModel):
    per_day: list[CostBreakdownDay] = []
    grand_total_usd: float = 0.0
    accommodation_total_usd: float = 0.0
    grand_total_with_accommodation_usd: float = 0.0


class CurrencyConversion(BaseModel):
    amount: float
    from_ccy: str
    to_ccy: str
    converted: float
    rate: float
    rate_date: str


class DietaryCheckResult(BaseModel):
    place_name: str
    verdict: Literal["accommodates", "partial", "does_not_accommodate", "unknown"]
    confidence: float
    reasoning: str
    accommodated_restrictions: list[str] = []
    unaccommodated_restrictions: list[str] = []


class ToolErrorResponse(BaseModel):
    is_error: bool = True
    error_code: Literal[
        "EXTERNAL_API_ERROR", "INVALID_INPUT", "NOT_FOUND", "TIMEOUT", "RATE_LIMIT"
    ]
    message: str
    retryable: bool = False
