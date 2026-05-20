"""Local pydantic schemas — duplicated from backend/src/schemas (separate process)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Place(BaseModel):
    osm_id: str
    name: str
    category: str
    lat: float
    lon: float
    address: str | None = None
    opening_hours: str | None = None
    website: str | None = None
    wikipedia: str | None = None
    estimated_visit_minutes: int = 60
    estimated_cost_usd: float = 0.0


class Restaurant(BaseModel):
    osm_id: str
    name: str
    cuisine: str | None = None
    lat: float
    lon: float
    address: str | None = None
    dietary_tags: list[str] = []
    dietary_confidence: float = 0.0
    price_tier: str = "$$"
    opening_hours: str | None = None
    phone: str | None = None
    estimated_meal_cost_usd: float = 15.0


class WeatherDailyEntry(BaseModel):
    date: str
    temp_min_c: float
    temp_max_c: float
    precipitation_mm: float
    weather_code: int
    weather_desc: str


class WeatherDaily(BaseModel):
    city: str
    is_forecast: bool = True
    entries: list[WeatherDailyEntry] = []


class LatLon(BaseModel):
    lat: float
    lon: float


class RouteSegment(BaseModel):
    from_idx: int
    to_idx: int
    distance_m: float
    duration_seconds: float


class RouteResult(BaseModel):
    mode: str
    segments: list[RouteSegment] = []
    total_distance_m: float = 0.0
    total_duration_seconds: float = 0.0
    warning: str | None = None


class ToolErrorResponse(BaseModel):
    is_error: bool = True
    error_code: Literal[
        "EXTERNAL_API_ERROR", "INVALID_INPUT", "NOT_FOUND", "TIMEOUT", "RATE_LIMIT"
    ]
    message: str
    retryable: bool = False
