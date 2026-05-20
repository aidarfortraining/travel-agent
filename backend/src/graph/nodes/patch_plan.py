"""Node 14: patch_plan — apply structured edit to state without full regeneration."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from src.graph.state import TripState
from src.schemas import EditIntent, EditRecord, Plan

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


def _render_markdown(
    plan: Plan,
    city: str,
    budget_usd: float,
    days_total: int,
    state: TripState | None = None,
) -> str:
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


async def patch_plan(state: TripState) -> dict:
    if not state.edit_history or not state.plan:
        return {"last_node": "patch_plan"}
    record = state.edit_history[-1]
    intent = record.intent
    new_plan = state.plan
    notes = "no-op"
    changed = 0
    if intent.action == "remove":
        new_plan, notes, changed = _apply_remove(state.plan, intent)
    elif intent.action == "constrain":
        new_plan, notes, changed = _apply_constrain(state.plan, intent)
    elif intent.action == "replace":
        new_plan, notes, changed = _apply_remove(state.plan, intent)
        notes = f"replace: removed {changed} target(s) (a follow-up regen could add alternatives)"
    elif intent.action == "add":
        notes = "add: no automatic insert in patch_plan; suggest a full regen for this intent"

    # Preserve the rich LLM markdown when the patch made no structural change —
    # otherwise we'd silently replace the user-facing plan with a stripped-down view.
    if changed == 0 and state.plan_markdown:
        new_markdown = state.plan_markdown
        notes = f"{notes}; markdown preserved (no-op)"
    else:
        new_markdown = _render_markdown(new_plan, state.city, state.budget_usd, state.days, state)

    updated_record = record.model_copy(update={"applied": True, "notes": notes})
    new_history = list(state.edit_history[:-1]) + [updated_record]
    return {
        "last_node": "patch_plan",
        "plan": new_plan,
        "plan_markdown": new_markdown,
        "edit_history": new_history,
        "pending_edit_text": None,
        "accept_signal": False,
    }
