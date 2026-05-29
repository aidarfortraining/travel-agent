"""MCP server: trip-utilities. 3 tools: convert_currency, estimate_plan_cost, validate_dietary_match."""
from __future__ import annotations

import logging
import time
from datetime import date

import httpx
from mcp.server.fastmcp import FastMCP

from schemas import (
    CostBreakdown,
    CostBreakdownDay,
    CurrencyConversion,
    DietaryCheckResult,
    Plan,
    ToolErrorResponse,
)

logging.basicConfig(level=logging.INFO, format="[trip-utilities] %(levelname)s %(message)s")
log = logging.getLogger("trip-utilities")

mcp = FastMCP("trip-utilities")

FX_URL = "https://api.frankfurter.app/latest"  # free, no API key, ECB-sourced rates
_FX_CACHE: dict[tuple[str, str], tuple[float, float, str]] = {}
_CACHE_TTL_S = 3600


SOFT_HALAL_CUISINES = {
    "turkish", "middle_eastern", "lebanese", "arab", "persian",
    "pakistani", "malaysian", "indian",
}
HALAL_INCOMPATIBLE_CUISINES = {"bbq", "german", "american_southern", "japanese"}
SOFT_VEGETARIAN_CUISINES = {"indian", "mediterranean"}


@mcp.tool()
async def convert_currency(amount: float, from_ccy: str, to_ccy: str) -> dict:
    """Convert amount via exchangerate.host. Cached in-memory for 1 hour."""
    try:
        from_ccy = from_ccy.upper()
        to_ccy = to_ccy.upper()
        if from_ccy == to_ccy:
            return CurrencyConversion(
                amount=amount,
                from_ccy=from_ccy,
                to_ccy=to_ccy,
                converted=amount,
                rate=1.0,
                rate_date=date.today().isoformat(),
            ).model_dump()
        cache_key = (from_ccy, to_ccy)
        now = time.time()
        cached = _FX_CACHE.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_S:
            rate = cached[1]
            rate_date = cached[2]
        else:
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.get(FX_URL, params={"from": from_ccy, "to": to_ccy})
                r.raise_for_status()
                data = r.json()
            rates = data.get("rates") or {}
            rate = float(rates.get(to_ccy, 0.0))
            if rate == 0.0:
                return ToolErrorResponse(
                    error_code="EXTERNAL_API_ERROR",
                    message=f"FX rate not available for {from_ccy}->{to_ccy}",
                    retryable=False,
                ).model_dump()
            rate_date = data.get("date") or date.today().isoformat()
            _FX_CACHE[cache_key] = (now, rate, rate_date)
        return CurrencyConversion(
            amount=amount,
            from_ccy=from_ccy,
            to_ccy=to_ccy,
            converted=amount * rate,
            rate=rate,
            rate_date=rate_date,
        ).model_dump()
    except Exception as exc:
        log.exception("convert_currency failed")
        return ToolErrorResponse(error_code="EXTERNAL_API_ERROR", message=str(exc), retryable=True).model_dump()


@mcp.tool()
async def estimate_plan_cost(plan: dict) -> dict:
    """Sum costs by category per day from a Plan dict."""
    try:
        p = Plan.model_validate(plan)
        per_day: list[CostBreakdownDay] = []
        grand = 0.0
        for d in p.days:
            attractions = 0.0
            restaurants = 0.0
            transport = 0.0
            for b in d.blocks:
                if b.place_type == "attraction":
                    attractions += b.estimated_cost_usd
                elif b.place_type == "restaurant":
                    restaurants += b.estimated_cost_usd
                elif b.place_type == "transition":
                    transport += b.estimated_cost_usd
            total = attractions + restaurants + transport
            per_day.append(
                CostBreakdownDay(
                    day_number=d.day_number,
                    attractions_usd=round(attractions, 2),
                    restaurants_usd=round(restaurants, 2),
                    transport_usd=round(transport, 2),
                    total_usd=round(total, 2),
                )
            )
            grand += total
        accom_total = (p.accommodation_per_night_usd or 0.0) * max(len(p.days) - 1, 0)
        return CostBreakdown(
            per_day=per_day,
            grand_total_usd=round(grand, 2),
            accommodation_total_usd=round(accom_total, 2),
            grand_total_with_accommodation_usd=round(grand + accom_total, 2),
        ).model_dump()
    except Exception as exc:
        log.exception("estimate_plan_cost failed")
        return ToolErrorResponse(error_code="INVALID_INPUT", message=str(exc), retryable=False).model_dump()


def _check_one_restriction(
    cuisine: str | None,
    tags: list[str],
    restriction: str,
) -> tuple[str, float, str]:
    cuisine_lc = (cuisine or "").lower().strip()
    tag_set = {t.lower() for t in tags}
    diet_tag_yes = f"diet:{restriction.replace('-', '_')}:yes"
    if restriction == "halal":
        if diet_tag_yes in tag_set:
            return "accommodates", 1.0, "OSM diet:halal=yes tag present"
        if cuisine_lc in SOFT_HALAL_CUISINES:
            return "partial", 0.6, f"cuisine '{cuisine_lc}' typically halal-compatible"
        if cuisine_lc in HALAL_INCOMPATIBLE_CUISINES:
            return "does_not_accommodate", 0.9, f"cuisine '{cuisine_lc}' often contains pork or non-halal items"
        return "unknown", 0.0, "no diet tag and cuisine inconclusive"
    if restriction == "vegan":
        if diet_tag_yes in tag_set or cuisine_lc == "vegan":
            return "accommodates", 1.0, "explicit vegan tag/cuisine"
        if cuisine_lc == "vegetarian":
            return "partial", 0.5, "vegetarian cuisine may have vegan options"
        return "unknown", 0.0, "no vegan tag"
    if restriction == "vegetarian":
        if diet_tag_yes in tag_set or cuisine_lc in {"vegetarian", "vegan"}:
            return "accommodates", 1.0, "explicit vegetarian/vegan tag"
        if cuisine_lc in SOFT_VEGETARIAN_CUISINES:
            return "partial", 0.7, f"cuisine '{cuisine_lc}' usually has vegetarian options"
        return "unknown", 0.0, "no tag"
    if restriction == "gluten-free":
        if "diet:gluten_free:yes" in tag_set:
            return "accommodates", 1.0, "explicit gluten-free tag"
        return "unknown", 0.0, "no gluten-free tag"
    if restriction == "kosher":
        if diet_tag_yes in tag_set:
            return "accommodates", 1.0, "explicit kosher tag"
        return "unknown", 0.0, "kosher requires certification"
    return "unknown", 0.0, "unknown restriction"


@mcp.tool()
async def validate_dietary_match(
    place_name: str,
    place_cuisine: str | None,
    place_tags: list[str],
    restrictions: list[str],
) -> dict:
    """Heuristic dietary-match check. No LLM. Returns verdict + reasoning."""
    try:
        if not restrictions:
            return DietaryCheckResult(
                place_name=place_name,
                verdict="accommodates",
                confidence=1.0,
                reasoning="no restrictions to check",
                accommodated_restrictions=[],
                unaccommodated_restrictions=[],
            ).model_dump()
        verdicts: list[tuple[str, str, float, str]] = []
        for r in restrictions:
            v, c, why = _check_one_restriction(place_cuisine, place_tags, r)
            verdicts.append((r, v, c, why))
        accommodated = [r for r, v, *_ in verdicts if v in ("accommodates", "partial")]
        unaccommodated = [r for r, v, *_ in verdicts if v == "does_not_accommodate"]
        unknowns = [r for r, v, *_ in verdicts if v == "unknown"]
        if unaccommodated:
            overall_verdict = "does_not_accommodate"
            overall_conf = max(c for _, v, c, _ in verdicts if v == "does_not_accommodate")
        elif unknowns and not accommodated:
            overall_verdict = "unknown"
            overall_conf = 0.0
        elif any(v == "partial" for _, v, *_ in verdicts):
            overall_verdict = "partial"
            overall_conf = min(c for _, v, c, _ in verdicts if v in ("accommodates", "partial"))
        else:
            overall_verdict = "accommodates"
            overall_conf = 1.0
        reasoning = "; ".join(f"{r}: {why}" for r, _, _, why in verdicts)
        return DietaryCheckResult(
            place_name=place_name,
            verdict=overall_verdict,
            confidence=overall_conf,
            reasoning=reasoning,
            accommodated_restrictions=accommodated,
            unaccommodated_restrictions=unaccommodated + unknowns,
        ).model_dump()
    except Exception as exc:
        log.exception("validate_dietary_match failed")
        return ToolErrorResponse(error_code="INVALID_INPUT", message=str(exc), retryable=False).model_dump()


if __name__ == "__main__":
    mcp.run(transport="stdio")
