"""Constraint adherence judge — LLM-as-judge via OpenAI mini at temperature 0.0."""
from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.client import ainvoke_text
from src.llm.prompts import CONSTRAINT_ADHERENCE_JUDGE_SYSTEM

log = logging.getLogger(__name__)


PROMPT = """USER CONSTRAINTS:
- Budget: ${budget_usd} total
- Dietary restrictions: {dietary}
- Number of days requested: {days}

GENERATED ITINERARY:
{plan_markdown}

CONSTRAINTS TO CHECK:
1. Does the total estimated cost stay within ${budget_usd}? If the plan explicitly says "over budget by $X" — that's still a fail.
2. For each restaurant mentioned: does it accommodate {dietary}? Soft matches (🟡) count as pass; missing markers count as fail.
3. Does the plan have exactly {days} days (look for ## День N headers)?

Return strict JSON only:
{{
  "budget_pass": true|false,
  "dietary_pass": true|false,
  "days_pass": true|false,
  "overall_pass": true|false,
  "violations": ["..."],
  "confidence": 0.0
}}"""


async def _judge(plan_markdown: str, budget_usd: float, dietary: list[str], days: int) -> dict[str, Any]:
    prompt = PROMPT.format(
        budget_usd=budget_usd,
        dietary=", ".join(dietary) or "none",
        days=days,
        plan_markdown=plan_markdown[:6000],
    )
    raw = await ainvoke_text(
        system=CONSTRAINT_ADHERENCE_JUDGE_SYSTEM,
        user=prompt,
        temperature=0.0,
        max_tokens=600,
    )
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except Exception as exc:
        log.warning("constraint_adherence: bad JSON: %s | raw=%s", exc, cleaned[:200])
        return {
            "budget_pass": False,
            "dietary_pass": False,
            "days_pass": False,
            "overall_pass": False,
            "violations": [f"judge_parse_error: {exc}"],
            "confidence": 0.0,
        }


async def constraint_adherence_evaluator(run, example) -> dict:  # langsmith signature
    outputs = run.outputs or {}
    inputs = example.inputs or {}
    plan_md = outputs.get("plan_markdown", "") or ""
    verdict = await _judge(
        plan_md,
        budget_usd=float(inputs.get("budget_usd", 0)),
        dietary=list(inputs.get("dietary", [])),
        days=int(inputs.get("days", 0)),
    )
    score = 1.0 if verdict.get("overall_pass") else 0.0
    return {
        "key": "constraint_adherence",
        "score": score,
        "comment": "; ".join(verdict.get("violations", [])) or "ok",
        "metadata": verdict,
    }
