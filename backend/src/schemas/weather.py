"""Weather schemas."""
from __future__ import annotations

from pydantic import BaseModel


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
