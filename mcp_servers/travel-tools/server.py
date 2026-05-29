"""MCP server: travel-tools.

Exposes 4 tools:
- find_places (Overpass / OpenStreetMap POI search)
- find_restaurants (Overpass with dietary filtering)
- get_weather_forecast (Open-Meteo)
- compute_route (OSRM)

All HTTP via httpx.AsyncClient with 10s timeout. Errors → ToolErrorResponse.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP

from schemas import (
    LatLon,
    Place,
    Restaurant,
    RouteResult,
    RouteSegment,
    ToolErrorResponse,
    WeatherDaily,
    WeatherDailyEntry,
)

logging.basicConfig(level=logging.INFO, format="[travel-tools] %(levelname)s %(message)s")
log = logging.getLogger("travel-tools")

mcp = FastMCP("travel-tools")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OSRM_URL = "https://router.project-osrm.org"

CATEGORY_TO_OVERPASS = {
    "museum": '["tourism"="museum"]',
    "park": '["leisure"~"park|garden"]',
    "viewpoint": '["tourism"="viewpoint"]',
    "historical": '["historic"]',
    "religious": '["amenity"="place_of_worship"]',
    "nightlife": '["amenity"~"bar|nightclub|pub"]',
    "shopping": '["shop"~"mall|market"]',
}

VISIT_MINUTES = {
    "museum": 120,
    "park": 60,
    "viewpoint": 30,
    "historical": 60,
    "religious": 45,
    "nightlife": 90,
    "shopping": 60,
}

BUDGET_TIER_USD = {"free": 0.0, "low": 8.0, "mid": 15.0, "high": 30.0}

FREE_BY_NATURE = {"park", "viewpoint", "religious"}

USER_AGENT = "TripPlanner/0.1 (educational; contact: localhost)"


async def _geocode_city(city: str) -> tuple[float, float] | None:
    """Return (lat, lon) for city via Open-Meteo geocoding (free, no key)."""
    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}) as cli:
        r = await cli.get(GEOCODE_URL, params={"name": city, "count": 1, "language": "en"})
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None
        return float(results[0]["latitude"]), float(results[0]["longitude"])


async def _overpass_query(query: str) -> dict:
    """POST to Overpass with retry across mirrors. Backs off on 429/5xx/timeouts.

    Per-request timeout is kept tight (15s): a degraded mirror should fail fast so
    the next mirror / retry fits inside the caller's overall budget, rather than
    blocking 30s per attempt. Healthy Overpass responses for these bbox queries
    return well under 15s.
    """
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT}) as cli:
        for attempt in range(5):
            url = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
            try:
                r = await cli.post(url, data={"data": query})
                if r.status_code in (429, 502, 503, 504):
                    log.warning("overpass %s -> %d, retry %d", url, r.status_code, attempt + 1)
                    last_exc = httpx.HTTPStatusError(
                        f"{r.status_code} from {url}", request=r.request, response=r
                    )
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                r.raise_for_status()
                return r.json()
            except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ConnectError) as exc:
                log.warning("overpass %s -> %s, retry %d", url, exc.__class__.__name__, attempt + 1)
                last_exc = exc
                await asyncio.sleep(min(2 ** attempt, 8))
    if last_exc:
        raise last_exc
    raise RuntimeError("overpass: no response from any mirror")


def _make_place_from_element(el: dict, category: str) -> Place | None:
    name = (el.get("tags") or {}).get("name") or (el.get("tags") or {}).get("name:en")
    if not name:
        return None
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    if lat is None or lon is None:
        return None
    tags = el.get("tags") or {}
    kind = el.get("type", "node")
    osm_id = f"{kind}/{el.get('id')}"
    visit = VISIT_MINUTES.get(category, 60)
    if tags.get("fee") == "no" or category in FREE_BY_NATURE:
        cost = 0.0
    elif tags.get("fee") == "yes":
        cost = BUDGET_TIER_USD["mid"]
    else:
        cost = BUDGET_TIER_USD["low"]
    return Place(
        osm_id=osm_id,
        name=str(name),
        category=category,
        lat=float(lat),
        lon=float(lon),
        address=tags.get("addr:street") or tags.get("addr:full"),
        opening_hours=tags.get("opening_hours"),
        website=tags.get("website") or tags.get("contact:website"),
        wikipedia=tags.get("wikipedia"),
        estimated_visit_minutes=visit,
        estimated_cost_usd=cost,
    )


@mcp.tool()
async def find_places(
    city: str,
    category: Literal["museum", "park", "viewpoint", "historical", "religious", "nightlife", "shopping"],
    budget_tier: Literal["free", "low", "mid", "high"] = "mid",
    limit: int = 10,
) -> list[dict]:
    """Search POIs in a city by category via Overpass / OSM. Returns up to `limit` Place objects."""
    try:
        coords = await _geocode_city(city)
        if not coords:
            return [ToolErrorResponse(error_code="NOT_FOUND", message=f"City {city} not found", retryable=False).model_dump()]
        lat, lon = coords
        filt = CATEGORY_TO_OVERPASS.get(category)
        if not filt:
            return [ToolErrorResponse(error_code="INVALID_INPUT", message=f"Unknown category {category}", retryable=False).model_dump()]
        radius = 10000
        query = f"""
[out:json][timeout:25];
(
  node{filt}(around:{radius},{lat},{lon});
  way{filt}(around:{radius},{lat},{lon});
);
out center {min(limit * 3, 60)};
"""
        data = await _overpass_query(query)
        elements = data.get("elements") or []
        places: list[Place] = []
        for el in elements:
            p = _make_place_from_element(el, category)
            if p:
                # Only override cost for non-free categories
                if p.estimated_cost_usd > 0:
                    p.estimated_cost_usd = BUDGET_TIER_USD[budget_tier]
                places.append(p)
            if len(places) >= limit:
                break
        return [p.model_dump() for p in places]
    except httpx.TimeoutException:
        return [ToolErrorResponse(error_code="TIMEOUT", message="Overpass timed out", retryable=True).model_dump()]
    except Exception as exc:
        log.exception("find_places failed")
        return [ToolErrorResponse(error_code="EXTERNAL_API_ERROR", message=str(exc), retryable=True).model_dump()]


def _restaurant_from_element(el: dict, hard_match_diets: list[str]) -> Restaurant | None:
    name = (el.get("tags") or {}).get("name") or (el.get("tags") or {}).get("name:en")
    if not name:
        return None
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    if lat is None or lon is None:
        return None
    tags = el.get("tags") or {}
    kind = el.get("type", "node")
    osm_id = f"{kind}/{el.get('id')}"
    cuisine = tags.get("cuisine")
    dietary_tags: list[str] = []
    confidence = 0.0
    soft_diet_cuisines = {
        "halal": {"turkish", "middle_eastern", "lebanese", "arab", "persian", "pakistani", "malaysian", "indian"},
        "vegan": set(),
        "vegetarian": {"indian", "mediterranean"},
        "gluten-free": set(),
        "kosher": set(),
    }
    for d in hard_match_diets:
        tag_key = f"diet:{d.replace('-', '_')}"
        if tags.get(tag_key) == "yes":
            dietary_tags.append(d)
            confidence = 1.0
        elif cuisine and cuisine in soft_diet_cuisines.get(d, set()):
            dietary_tags.append(d)
            confidence = max(confidence, 0.6)
    price_map = {"cheap": "$", "moderate": "$$", "expensive": "$$$"}
    price_tier = price_map.get((tags.get("price") or "").lower(), "$$")
    return Restaurant(
        osm_id=osm_id,
        name=str(name),
        cuisine=cuisine,
        lat=float(lat),
        lon=float(lon),
        address=tags.get("addr:street") or tags.get("addr:full"),
        dietary_tags=dietary_tags,
        dietary_confidence=confidence if hard_match_diets else 1.0,
        price_tier=price_tier,
        opening_hours=tags.get("opening_hours"),
        phone=tags.get("phone"),
        estimated_meal_cost_usd={"$": 8.0, "$$": 18.0, "$$$": 35.0, "$$$$": 60.0}.get(price_tier, 18.0),
    )


@mcp.tool()
async def find_restaurants(
    city: str,
    dietary: list[str],
    cuisine: str | None = None,
    price_tier: Literal["$", "$$", "$$$", "$$$$"] = "$$",
    limit: int = 10,
) -> list[dict]:
    """Find restaurants in a city honoring dietary restrictions via Overpass / OSM diet tags."""
    try:
        coords = await _geocode_city(city)
        if not coords:
            return [ToolErrorResponse(error_code="NOT_FOUND", message=f"City {city} not found", retryable=False).model_dump()]
        lat, lon = coords
        radius = 8000
        if dietary:
            tag_filters = "".join(f'["diet:{d.replace("-", "_")}"="yes"]' for d in dietary)
            query = f"""
[out:json][timeout:25];
(
  node["amenity"="restaurant"]{tag_filters}(around:{radius},{lat},{lon});
);
out center {limit * 2};
"""
            data = await _overpass_query(query)
            hard = data.get("elements") or []
        else:
            hard = []
        if len(hard) < 3:
            soft_filter = ""
            if cuisine:
                soft_filter = f'["cuisine"~"{cuisine}"]'
            elif "halal" in dietary:
                soft_filter = '["cuisine"~"turkish|middle_eastern|lebanese|arab|persian|pakistani"]'
            q2 = f"""
[out:json][timeout:25];
(
  node["amenity"="restaurant"]{soft_filter}(around:{radius},{lat},{lon});
);
out center {limit * 3};
"""
            data2 = await _overpass_query(q2)
            soft = data2.get("elements") or []
        else:
            soft = []
        seen_ids: set[int] = set()
        restaurants: list[Restaurant] = []
        for el in hard + soft:
            if el.get("id") in seen_ids:
                continue
            seen_ids.add(el.get("id"))
            r = _restaurant_from_element(el, dietary or [])
            if r and (not dietary or r.dietary_confidence >= 0.5):
                restaurants.append(r)
            if len(restaurants) >= limit:
                break
        return [r.model_dump() for r in restaurants]
    except httpx.TimeoutException:
        return [ToolErrorResponse(error_code="TIMEOUT", message="Overpass timed out", retryable=True).model_dump()]
    except Exception as exc:
        log.exception("find_restaurants failed")
        return [ToolErrorResponse(error_code="EXTERNAL_API_ERROR", message=str(exc), retryable=True).model_dump()]


WMO_DESC = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Showers", 81: "Heavy showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm",
}


@mcp.tool()
async def get_weather_forecast(
    city: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Daily weather forecast for the city via Open-Meteo. Up to 16 days ahead."""
    try:
        coords = await _geocode_city(city)
        if not coords:
            return ToolErrorResponse(error_code="NOT_FOUND", message=f"City {city} not found", retryable=False).model_dump()
        lat, lon = coords
        today = date.today()
        start = datetime.fromisoformat(start_date).date() if start_date else today
        end = datetime.fromisoformat(end_date).date() if end_date else min(start + timedelta(days=14), today + timedelta(days=16))
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "auto",
        }
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}) as cli:
            r = await cli.get(FORECAST_URL, params=params)
            r.raise_for_status()
            data = r.json()
        d = data.get("daily") or {}
        entries: list[WeatherDailyEntry] = []
        dates = d.get("time") or []
        for i, ds in enumerate(dates):
            wc = int((d.get("weather_code") or [0])[i])
            entries.append(
                WeatherDailyEntry(
                    date=ds,
                    temp_min_c=float((d.get("temperature_2m_min") or [0])[i]),
                    temp_max_c=float((d.get("temperature_2m_max") or [0])[i]),
                    precipitation_mm=float((d.get("precipitation_sum") or [0])[i]),
                    weather_code=wc,
                    weather_desc=WMO_DESC.get(wc, "Unknown"),
                )
            )
        return WeatherDaily(city=city, is_forecast=True, entries=entries).model_dump()
    except httpx.TimeoutException:
        return ToolErrorResponse(error_code="TIMEOUT", message="Open-Meteo timed out", retryable=True).model_dump()
    except Exception as exc:
        log.exception("get_weather_forecast failed")
        return ToolErrorResponse(error_code="EXTERNAL_API_ERROR", message=str(exc), retryable=True).model_dump()


@mcp.tool()
async def compute_route(
    points: list[dict],
    mode: Literal["walk", "transit", "drive"] = "walk",
) -> dict:
    """Compute travel time/distance for an ordered list of {lat, lon} points via OSRM."""
    try:
        latlons = [LatLon(**p) for p in points]
        if len(latlons) < 2:
            return RouteResult(mode=mode, segments=[], warning="Need at least 2 points").model_dump()
        profile = {"walk": "foot", "drive": "driving", "transit": "foot"}[mode]
        coords = ";".join(f"{p.lon},{p.lat}" for p in latlons)
        url = f"{OSRM_URL}/route/v1/{profile}/{coords}"
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT}) as cli:
            r = await cli.get(url, params={"overview": "false", "annotations": "duration,distance"})
            r.raise_for_status()
            data = r.json()
        routes = data.get("routes") or []
        if not routes:
            return ToolErrorResponse(error_code="NOT_FOUND", message="No route found", retryable=False).model_dump()
        legs = routes[0].get("legs") or []
        segments = [
            RouteSegment(
                from_idx=i,
                to_idx=i + 1,
                distance_m=float(leg.get("distance", 0.0)),
                duration_seconds=float(leg.get("duration", 0.0)),
            )
            for i, leg in enumerate(legs)
        ]
        total_d = float(routes[0].get("distance", sum(s.distance_m for s in segments)))
        total_t = float(routes[0].get("duration", sum(s.duration_seconds for s in segments)))
        if mode == "transit":
            for s in segments:
                s.duration_seconds *= 0.7
            total_t *= 0.7
        return RouteResult(
            mode=mode,
            segments=segments,
            total_distance_m=total_d,
            total_duration_seconds=total_t,
            warning="Transit times are approximate (OSRM does not model transit)" if mode == "transit" else None,
        ).model_dump()
    except httpx.TimeoutException:
        return ToolErrorResponse(error_code="TIMEOUT", message="OSRM timed out", retryable=True).model_dump()
    except Exception as exc:
        log.exception("compute_route failed")
        return ToolErrorResponse(error_code="EXTERNAL_API_ERROR", message=str(exc), retryable=True).model_dump()


if __name__ == "__main__":
    mcp.run(transport="stdio")
