"""Node 14: patch_plan — apply structured edit, then LLM-rerender the rich markdown."""
from __future__ import annotations

import logging
import re

from src.graph.state import TripState
from src.llm.client import ainvoke_text
from src.llm.prompts import EDIT_RERENDER_SYSTEM_TEMPLATE, EDIT_RERENDER_USER_TEMPLATE
from src.llm.skill_loader import load_skill
from src.mcp_clients.client import call_tool, call_tool_list
from src.schemas import CostBreakdown, EditIntent, Plan, TimeBlock

log = logging.getLogger(__name__)


REMOVE_KEYWORDS = {
    "museum": ["museum", "музе"],
    "nightlife": ["nightlife", "bar", "club", "ночн", "бар", "клуб"],
    "shopping": ["shopping", "shop", "магазин", "шоп"],
    "religious": ["religious", "mosque", "church", "мечеть", "церков"],
    "park": ["park", "парк"],
    "historical": ["historical", "historic", "истори"],
    "alcohol": ["alcohol", "wine", "beer", "алкогол", "вино", "пив"],
}

# Categories accepted by the travel-tools find_places MCP tool (used by _apply_add).
FIND_PLACES_CATEGORIES = {"museum", "park", "viewpoint", "historical", "religious", "nightlife", "shopping"}

_FOOD_WORDS = ["еды", "еда", "ресторан", "food", "restaurant", "street food", "кафе", "халяль", "halal", "обед", "ужин"]


def _matches_remove_target(name: str, category: str, target: str) -> bool:
    target_lc = target.lower()
    keywords: list[str] = []
    for cat_key, words in REMOVE_KEYWORDS.items():
        if cat_key in target_lc or any(w in target_lc for w in words):
            keywords.extend(words)
            if cat_key == category.lower():
                return True
    if keywords:
        text = f"{name} {category}".lower()
        return any(w in text for w in keywords)
    return target_lc in f"{name} {category}".lower()


def _apply_remove(plan: Plan, intent: EditIntent) -> tuple[Plan, str, int]:
    removed = 0
    new_days = []
    for d in plan.days:
        kept = []
        for b in d.blocks:
            note = (b.notes or "").lower()
            if note in REMOVE_KEYWORDS:
                cat = note
            elif "museum" in note:
                cat = "museum"
            else:
                cat = b.place_type
            if _matches_remove_target(b.place_name, cat, intent.target):
                removed += 1
                continue
            kept.append(b)
        new_days.append(d.model_copy(update={"blocks": kept}))
    notes = f"removed {removed} block(s) matching '{intent.target}'"
    return plan.model_copy(update={"days": new_days}), notes, removed


def _apply_constrain(plan: Plan, intent: EditIntent) -> tuple[Plan, str, int]:
    m = re.search(r"\$\s*(\d+)", intent.target + " " + (intent.detail or ""))
    if not m:
        return plan, "constrain with no numeric value — no-op", 0
    cap = float(m.group(1))
    new_days = []
    dropped = 0
    for d in plan.days:
        kept = []
        running = 0.0
        for b in sorted(d.blocks, key=lambda x: x.estimated_cost_usd):
            if running + b.estimated_cost_usd <= cap:
                kept.append(b)
                running += b.estimated_cost_usd
            else:
                dropped += 1
        new_days.append(d.model_copy(update={"blocks": sorted(kept, key=lambda x: x.start_time)}))
    return plan.model_copy(update={"days": new_days}), f"enforced per-day cap ${cap:.0f}; dropped {dropped} blocks", dropped


def _target_kind_category(target: str) -> tuple[str, str]:
    """Map a free-form add/replace target onto ('restaurant'|'attraction', category)."""
    t = target.lower()
    if any(w in t for w in _FOOD_WORDS):
        return "restaurant", ""
    for cat, words in REMOVE_KEYWORDS.items():
        if cat in t or any(w in t for w in words):
            return "attraction", cat
    return "attraction", ""


def _used_ids(plan: Plan) -> set[str]:
    return {b.place_id for d in plan.days for b in d.blocks}


def _shortest_day(plan: Plan):
    return min(plan.days, key=lambda d: len(d.blocks)) if plan.days else None


async def _apply_add(
    plan: Plan, intent: EditIntent, state: TripState, target_override: str | None = None
) -> tuple[Plan, str, int]:
    """Insert one place of the requested kind into the day with the fewest blocks.

    `target_override` lets `replace` add the *replacement* (intent.detail) rather than the
    removed thing (intent.target). Source order: unused candidate from state, then a fresh
    find_places MCP call for attraction categories. Restaurants come only from the
    already-fetched candidate set.
    """
    add_target = target_override or intent.target
    day = _shortest_day(plan)
    if day is None:
        return plan, "add: empty plan, nothing to add to", 0
    used = _used_ids(plan)
    kind, category = _target_kind_category(add_target)

    block: TimeBlock | None = None
    if kind == "restaurant":
        for r in state.candidate_restaurants:
            if r.osm_id not in used:
                block = TimeBlock(
                    period="evening", start_time="20:30", place_id=r.osm_id,
                    place_name=r.name, place_type="restaurant",
                    estimated_cost_usd=r.estimated_meal_cost_usd, source_url=r.source_url,
                    notes=r.cuisine or "restaurant",
                )
                break
    else:
        pool = [
            p for p in state.candidate_places
            if p.osm_id not in used and (not category or p.category == category)
        ]
        if not pool and category in FIND_PLACES_CATEGORIES:
            try:
                fetched = await call_tool_list("find_places", city=state.city, category=category, limit=5)
                for raw in fetched:
                    if not isinstance(raw, dict) or raw.get("is_error") or raw.get("error_code"):
                        continue
                    oid = raw.get("osm_id")
                    if oid and oid not in used:
                        block = TimeBlock(
                            period="afternoon", start_time="16:30", place_id=oid,
                            place_name=raw.get("name", "место"), place_type="attraction",
                            estimated_cost_usd=float(raw.get("estimated_cost_usd", 0.0)),
                            estimated_duration_minutes=int(raw.get("estimated_visit_minutes", 60)),
                            source_url=f"https://www.openstreetmap.org/{oid}", notes=category,
                        )
                        break
            except Exception as exc:
                log.warning("add: find_places fallback failed: %s", exc)
        elif pool:
            p = pool[0]
            block = TimeBlock(
                period="afternoon", start_time="16:30", place_id=p.osm_id,
                place_name=p.name, place_type="attraction",
                estimated_cost_usd=p.estimated_cost_usd,
                estimated_duration_minutes=p.estimated_visit_minutes,
                source_url=p.source_url, notes=p.category,
            )

    if block is None:
        return plan, f"add: no candidate found for '{add_target}'", 0

    new_days = [
        d.model_copy(update={"blocks": sorted([*d.blocks, block], key=lambda x: x.start_time)})
        if d.day_number == day.day_number else d
        for d in plan.days
    ]
    return plan.model_copy(update={"days": new_days}), f"added '{block.place_name}' to day {day.day_number}", 1


def _dietary_marker(state: TripState, place_id: str) -> str:
    if not state.dietary:
        return ""
    for r in state.candidate_restaurants:
        if r.osm_id == place_id:
            if r.dietary_confidence >= 1.0:
                return f"🟢 {','.join(state.dietary)} (подтверждено)"
            if r.dietary_confidence >= 0.5:
                return f"🟡 {','.join(state.dietary)} (вероятно)"
    return ""


def _format_itinerary_for_llm(plan: Plan, state: TripState) -> str:
    rows: list[str] = []
    for d in plan.days:
        head = f"День {d.day_number}" + (f" ({d.date})" if d.date else "")
        rows.append(head)
        for b in sorted(d.blocks, key=lambda x: x.start_time):
            cat = b.notes or b.place_type
            url = b.source_url or "#"
            dur = "" if b.place_type == "restaurant" else f" | ~{b.estimated_duration_minutes}min"
            marker = _dietary_marker(state, b.place_id) if b.place_type == "restaurant" else ""
            marker = f" | {marker}" if marker else ""
            rows.append(
                f"  - {b.start_time} | {b.place_name} | {cat} | ${b.estimated_cost_usd:.0f}{dur} | source={url}{marker}"
            )
    return "\n".join(rows) or "(empty itinerary)"


def _format_weather_for_llm(state: TripState) -> str:
    if not state.weather or not state.weather.entries:
        return "(no forecast)"
    rows = []
    for i, e in enumerate(state.weather.entries[: state.days], start=1):
        rows.append(f"  Day {i} ({e.date}): {e.weather_desc}, {e.temp_min_c:.0f}–{e.temp_max_c:.0f}°C, rain {e.precipitation_mm:.0f}mm")
    return "\n".join(rows)


def _format_city_overview(ov) -> str:
    if not ov:
        return "(no overview)"
    return (
        f"city={ov.city}; country={ov.country}; currency={ov.currency}; "
        f"best_season={ov.best_season}; transport={ov.transport_summary}"
    )


async def _rich_rerender(plan: Plan, state: TripState, edit_note: str) -> str:
    """LLM-rerender the edited plan into the full rich markdown. Returns '' on failure."""
    system = EDIT_RERENDER_SYSTEM_TEMPLATE.format(skill_content=load_skill("itinerary-formatter"))
    user = EDIT_RERENDER_USER_TEMPLATE.format(
        city=state.city,
        days=state.days,
        budget_usd=state.budget_usd,
        budget_per_day=state.budget_usd / max(state.days, 1),
        interests=", ".join(state.interests) or "general tourism",
        dietary=", ".join(state.dietary) or "none",
        city_overview=_format_city_overview(state.city_overview),
        edit_note=edit_note,
        itinerary=_format_itinerary_for_llm(plan, state),
        weather=_format_weather_for_llm(state),
    )
    md = await ainvoke_text(system=system, user=user, temperature=0.4, max_tokens=4096)
    return _strip_outer_fence(md or "")


def _strip_outer_fence(md: str) -> str:
    s = md.strip()
    if not s.startswith("```"):
        return md
    nl = s.find("\n")
    if nl == -1:
        return md
    body = s[nl + 1:]
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3].rstrip()
    return body


def _render_markdown(
    plan: Plan,
    city: str,
    budget_usd: float,
    days_total: int,
    state: TripState | None = None,
) -> str:
    """Deterministic bare render — fallback only, when the LLM rerender returns empty."""
    weather_by_day: dict[int, str] = {}
    if state and state.weather and state.weather.entries:
        for i, e in enumerate(state.weather.entries[:days_total], start=1):
            weather_by_day[i] = (
                f"погода: {e.weather_desc}, {e.temp_min_c:.0f}°–{e.temp_max_c:.0f}°C, {e.precipitation_mm:.0f}мм осадков"
            )

    parts = [
        f"# Поездка в {city}, {days_total} дней",
        "",
        f"**Бюджет:** ${budget_usd:.0f} (${budget_usd / max(days_total, 1):.0f} в день)",
    ]
    if state and state.interests:
        parts.append(f"**Интересы:** {', '.join(state.interests)}")
    if state and state.dietary:
        parts.append(f"**Пищевые ограничения:** {', '.join(state.dietary)}")
    parts.append("")

    grand = 0.0
    for d in plan.days:
        header = f"## День {d.day_number}"
        if d.date:
            header += f" — {d.date}"
        parts.append(header)
        if d.day_number in weather_by_day:
            parts.append(f"> {weather_by_day[d.day_number]}")
            parts.append("")
        day_total = 0.0
        for b in sorted(d.blocks, key=lambda x: x.start_time):
            marker = f" {b.dietary_marker}" if b.dietary_marker else ""
            link = b.source_url or "#"
            parts.append(
                f"- **{b.start_time}** — [{b.place_name}]({link}){marker} — "
                f"{'обед/ужин' if b.place_type == 'restaurant' else 'визит'} — "
                f"${b.estimated_cost_usd:.0f}"
            )
            day_total += b.estimated_cost_usd
        parts.append("")
        warn = " ⚠ превышение" if day_total > budget_usd / max(days_total, 1) else ""
        parts.append(f"**Итого за день:** ${day_total:.0f}{warn}")
        parts.append("")
        grand += day_total
    parts.append("## Сводный бюджет")
    parts.append(f"Всего: **${grand:.0f}** из ${budget_usd:.0f}.")
    return "\n".join(parts)


# Matches any prior italic-blockquote notice we prepend (no-op or parse-failed) so
# repeated edits don't stack notices. Plan blockquotes (weather/transport) don't use
# the leading `_`, so this won't strip real content.
_NOOP_NOTICE_RE = re.compile(r"^> _[^\n]*_\n\n", flags=re.MULTILINE)


def _prepend_noop_notice(markdown: str, intent: EditIntent) -> str:
    """Surface a no-match edit to the user instead of silently returning the same plan.
    Strips any prior notice first so repeated no-ops don't stack."""
    clean = _NOOP_NOTICE_RE.sub("", markdown, count=1)
    label = intent.raw_text or intent.target
    return f"> _Правка «{label}» не нашла совпадений — план оставлен без изменений._\n\n{clean}"


def _prepend_parse_failed_notice(markdown: str, intent: EditIntent) -> str:
    """Distinct from no-op: the edit couldn't be parsed (transient LLM failure)."""
    clean = _NOOP_NOTICE_RE.sub("", markdown, count=1)
    label = intent.raw_text or intent.target
    return f"> _Не удалось разобрать правку «{label}» — попробуйте переформулировать._\n\n{clean}"


async def _recompute_cost(plan: Plan, prev: CostBreakdown | None) -> CostBreakdown | None:
    try:
        raw = await call_tool("estimate_plan_cost", plan=plan.model_dump())
        if raw.get("is_error"):
            return prev
        return CostBreakdown.model_validate(raw)
    except Exception as exc:
        log.warning("patch_plan: estimate_plan_cost failed: %s", exc)
        return prev


async def patch_plan(state: TripState) -> dict:
    if not state.edit_history or not state.plan:
        return {"last_node": "patch_plan"}
    record = state.edit_history[-1]
    intent = record.intent

    # The LLM failed to parse this edit (not a no-match). Keep the plan and tell the
    # user to rephrase, rather than running a placeholder action that reads as broken.
    if record.notes == "parse_failed":
        new_markdown = (
            _prepend_parse_failed_notice(state.plan_markdown, intent)
            if state.plan_markdown else state.plan_markdown
        )
        updated = record.model_copy(update={"applied": False, "notes": "parse_failed; not applied"})
        return {
            "last_node": "patch_plan",
            "plan": state.plan,
            "plan_markdown": new_markdown,
            "plan_cost_breakdown": state.plan_cost_breakdown,
            "edit_history": list(state.edit_history[:-1]) + [updated],
            "pending_edit_text": None,
            "accept_signal": False,
        }

    new_plan = state.plan
    notes = "no-op"
    changed = 0
    if intent.action == "remove":
        new_plan, notes, changed = _apply_remove(state.plan, intent)
    elif intent.action == "constrain":
        new_plan, notes, changed = _apply_constrain(state.plan, intent)
    elif intent.action == "replace":
        # remove what the user named (target), add the replacement (detail)
        new_plan, notes, removed = _apply_remove(state.plan, intent)
        new_plan, add_notes, added = await _apply_add(
            new_plan, intent, state, target_override=intent.detail or intent.target
        )
        changed = removed + added
        notes = f"replace: removed {removed}, {add_notes}"
    elif intent.action == "add":
        new_plan, notes, changed = await _apply_add(state.plan, intent, state)

    cost = state.plan_cost_breakdown
    if changed == 0 and state.plan_markdown:
        # Nothing matched — keep the rich plan, but tell the user it was a no-op.
        new_markdown = _prepend_noop_notice(state.plan_markdown, intent)
        notes = f"{notes}; no change (markdown preserved + notice)"
    else:
        new_markdown = await _rich_rerender(new_plan, state, f"{intent.action}: {intent.target}")
        if not new_markdown:
            log.warning("patch_plan: LLM rerender empty, falling back to bare render")
            new_markdown = _render_markdown(new_plan, state.city, state.budget_usd, state.days, state)
        cost = await _recompute_cost(new_plan, state.plan_cost_breakdown)

    updated_record = record.model_copy(update={"applied": True, "notes": notes})
    new_history = list(state.edit_history[:-1]) + [updated_record]
    return {
        "last_node": "patch_plan",
        "plan": new_plan,
        "plan_markdown": new_markdown,
        "plan_cost_breakdown": cost,
        "edit_history": new_history,
        "pending_edit_text": None,
        "accept_signal": False,
    }
