"""Node 11: generate_plan — LLM-generates structured markdown plan via Skill."""
from __future__ import annotations

import logging

from src.graph.state import TripState
from src.llm.client import ainvoke_text
from src.llm.prompts import GENERATE_PLAN_SYSTEM_TEMPLATE, GENERATE_PLAN_USER_TEMPLATE
from src.llm.skill_loader import load_skill
from src.mcp_clients.client import call_tool
from src.schemas import (
    CostBreakdown,
    DayPlan,
    Plan,
    Restaurant,
    TimeBlock,
)

log = logging.getLogger(__name__)


def _format_places(places, ids: list[str] | None = None) -> str:
    items = places if ids is None else [p for p in places if p.osm_id in ids]
    if not items:
        return "(none)"
    lines = []
    for p in items[:25]:
        line = f"- {p.name} | {p.category} | lat={p.lat:.4f},lon={p.lon:.4f} | ${p.estimated_cost_usd:.0f} | visit ~{p.estimated_visit_minutes}min | source={p.source_url}"
        lines.append(line)
    return "\n".join(lines)


def _format_restaurants(restaurants: list[Restaurant], dietary: list[str]) -> str:
    if not restaurants:
        return "(none)"
    lines = []
    for r in restaurants[:20]:
        marker = ""
        if dietary:
            if r.dietary_confidence >= 1.0:
                marker = f" | 🟢 {','.join(dietary)} (подтверждено)"
            elif r.dietary_confidence >= 0.5:
                marker = f" | 🟡 {','.join(dietary)} (вероятно — кухня {r.cuisine or 'unknown'})"
        cuisine = r.cuisine or "—"
        lines.append(
            f"- {r.name} | {cuisine} | {r.price_tier} | ${r.estimated_meal_cost_usd:.0f} | source={r.source_url}{marker}"
        )
    return "\n".join(lines)


def _format_weather(weather, days: int) -> str:
    if not weather or not weather.entries:
        return "(no forecast)"
    rows = []
    for i, e in enumerate(weather.entries[:days]):
        rows.append(f"  Day {i + 1} ({e.date}): {e.weather_desc}, {e.temp_min_c:.0f}–{e.temp_max_c:.0f}°C, rain {e.precipitation_mm:.0f}mm")
    return "\n".join(rows)


def _format_day_assignment(route_per_day: dict[int, list[str]], places) -> str:
    by_id = {p.osm_id: p for p in places}
    rows = []
    for day, ids in sorted(route_per_day.items()):
        names = [by_id[i].name for i in ids if i in by_id]
        rows.append(f"  Day {day}: {' → '.join(names) if names else '(no places assigned)'}")
    return "\n".join(rows) or "(no assignment)"


def _format_context_chunks(chunks) -> str:
    if not chunks:
        return "(no Wikivoyage context — city may not be indexed)"
    rows = []
    for c in chunks[:8]:
        snippet = c.text[:400].replace("\n", " ")
        rows.append(f"- [{c.section}] {snippet}…")
    return "\n".join(rows)


def _format_city_overview(ov) -> str:
    if not ov:
        return "(no overview)"
    return (
        f"city={ov.city}; country={ov.country}; currency={ov.currency}; "
        f"best_season={ov.best_season}; languages={','.join(ov.languages)}; "
        f"transport={ov.transport_summary}"
    )


def _strip_outer_fence(md: str) -> str:
    """Some LLM responses wrap the whole plan in ```markdown ... ```. Strip the outer fence
    so ReactMarkdown renders the content as actual markdown rather than as a code block.
    """
    s = md.strip()
    if not s.startswith("```"):
        return md
    first_newline = s.find("\n")
    if first_newline == -1:
        return md
    body = s[first_newline + 1 :]
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -3].rstrip()
    return body


def _build_structured_plan(state: TripState) -> Plan:
    """Heuristic structured plan used for cost estimation. The markdown plan from the LLM is the user-facing one."""
    places_by_id = {p.osm_id: p for p in state.candidate_places}
    restaurants = list(state.candidate_restaurants)
    rest_idx = 0
    days_out: list[DayPlan] = []
    for day_num in range(1, state.days + 1):
        route = state.route_per_day.get(day_num, [])[:3]
        blocks: list[TimeBlock] = []
        if route:
            p = places_by_id.get(route[0])
            if p:
                blocks.append(TimeBlock(
                    period="morning", start_time="09:00",
                    place_id=p.osm_id, place_name=p.name, place_type="attraction",
                    estimated_cost_usd=p.estimated_cost_usd,
                    estimated_duration_minutes=p.estimated_visit_minutes,
                    source_url=f"https://www.openstreetmap.org/{p.osm_id}",
                    notes=p.category,
                ))
        if rest_idx < len(restaurants):
            r = restaurants[rest_idx]
            rest_idx += 1
            blocks.append(TimeBlock(
                period="afternoon", start_time="13:00",
                place_id=r.osm_id, place_name=r.name, place_type="restaurant",
                estimated_cost_usd=r.estimated_meal_cost_usd,
                source_url=f"https://www.openstreetmap.org/{r.osm_id}",
            ))
        if len(route) > 1:
            p = places_by_id.get(route[1])
            if p:
                blocks.append(TimeBlock(
                    period="afternoon", start_time="15:00",
                    place_id=p.osm_id, place_name=p.name, place_type="attraction",
                    estimated_cost_usd=p.estimated_cost_usd,
                    estimated_duration_minutes=p.estimated_visit_minutes,
                    source_url=f"https://www.openstreetmap.org/{p.osm_id}",
                    notes=p.category,
                ))
        if rest_idx < len(restaurants):
            r = restaurants[rest_idx]
            rest_idx += 1
            blocks.append(TimeBlock(
                period="evening", start_time="19:30",
                place_id=r.osm_id, place_name=r.name, place_type="restaurant",
                estimated_cost_usd=r.estimated_meal_cost_usd,
                source_url=f"https://www.openstreetmap.org/{r.osm_id}",
            ))
        days_out.append(DayPlan(day_number=day_num, blocks=blocks))
    return Plan(city=state.city, days=days_out)


async def generate_plan(state: TripState) -> dict:
    skill_content = load_skill("itinerary-formatter")
    system = GENERATE_PLAN_SYSTEM_TEMPLATE.format(skill_content=skill_content)
    budget_per_day = state.budget_usd / max(state.days, 1)

    photo_section = ""
    if state.photo_analysis:
        photo_section = (
            f"USER UPLOADED A PHOTO. We identified it as **{state.photo_analysis.landmark}** "
            f"(confidence {state.photo_analysis.confidence:.2f}). Include this landmark in the plan "
            f"if confidence ≥ 0.6 and the city matches."
        )

    user = GENERATE_PLAN_USER_TEMPLATE.format(
        city=state.city,
        days=state.days,
        budget_usd=state.budget_usd,
        budget_per_day=budget_per_day,
        interests=", ".join(state.interests) or "general tourism",
        dietary=", ".join(state.dietary) or "none",
        city_overview=_format_city_overview(state.city_overview),
        candidate_places=_format_places(state.candidate_places),
        candidate_restaurants=_format_restaurants(state.candidate_restaurants, state.dietary),
        weather=_format_weather(state.weather, state.days),
        day_assignment=_format_day_assignment(state.route_per_day, state.candidate_places),
        city_context=_format_context_chunks(state.city_context),
        photo_section=photo_section,
    )

    markdown = await ainvoke_text(
        system=system,
        user=user,
        temperature=0.7,
        max_tokens=4096,
    )
    markdown = _strip_outer_fence(markdown or "")

    structured_plan = _build_structured_plan(state)
    aggregated = list(state.tool_calls_aggregated)
    try:
        cost_raw = await call_tool("estimate_plan_cost", plan=structured_plan.model_dump())
        aggregated.append({
            "tool": "estimate_plan_cost",
            "args": {"days": state.days},
            "result_summary": {k: cost_raw.get(k) for k in ("grand_total_usd", "is_error")},
        })
        cost = CostBreakdown.model_validate(cost_raw) if not cost_raw.get("is_error") else None
    except Exception as exc:
        log.warning("estimate_plan_cost failed: %s", exc)
        cost = None

    if not markdown:
        markdown = _fallback_markdown(state, structured_plan, cost)

    return {
        "last_node": "generate_plan",
        "plan": structured_plan,
        "plan_markdown": markdown,
        "plan_cost_breakdown": cost,
        "status": "awaiting_review",
        "tool_calls_aggregated": aggregated,
    }


def _fallback_markdown(state: TripState, plan: Plan, cost: CostBreakdown | None) -> str:
    """Used only when the LLM returned empty (rate-limit exhaustion)."""
    parts: list[str] = [
        f"# Поездка в {state.city}, {state.days} дней",
        "",
        f"**Бюджет:** ${state.budget_usd:.0f}",
        f"**Интересы:** {', '.join(state.interests) or '—'}",
        f"**Пищевые ограничения:** {', '.join(state.dietary) or 'нет'}",
        "",
        "_Внимание: LLM-вызов не удался, показан heuristic-план._",
        "",
    ]
    for d in plan.days:
        parts.append(f"## День {d.day_number}")
        for b in d.blocks:
            parts.append(
                f"- **{b.start_time}** — [{b.place_name}]({b.source_url or '#'}) — ${b.estimated_cost_usd:.0f}"
            )
        parts.append("")
    if cost:
        parts.append(f"**Итого:** ${cost.grand_total_usd:.0f}")
    return "\n".join(parts)
