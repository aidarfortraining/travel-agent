"""Faithfulness judge — LLM-as-judge that checks for hallucinated places."""
from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.client import ainvoke_text
from src.llm.prompts import FAITHFULNESS_JUDGE_SYSTEM

log = logging.getLogger(__name__)


PROMPT = """ITINERARY:
{plan_markdown}

ALL TOOL CALLS MADE DURING PLANNING (truncated JSON):
{tool_calls_json}

TASK:
1. Extract every place name mentioned in the itinerary (attractions + restaurants).
2. Collect every `name` field appearing inside tool result_summary.
3. For each place in the itinerary, check whether it appears in the collected names (case-insensitive, allow minor spelling and translations).
4. List any place in the itinerary that is NOT in the tool results — these are hallucinations.

Return strict JSON only:
{{
  "total_places_in_plan": 0,
  "places_grounded_in_tools": 0,
  "hallucinated_places": [],
  "faithfulness_score": 0.0
}}"""


def _truncate_tool_calls(calls: list[dict]) -> str:
    serializable = []
    for c in calls[:40]:
        serializable.append(
            {
                "tool": c.get("tool"),
                "args": {k: v for k, v in (c.get("args") or {}).items() if k in {"city", "category", "query"}},
                "result_summary": c.get("result_summary"),
            }
        )
    return json.dumps(serializable, ensure_ascii=False)[:6000]


async def _judge(plan_markdown: str, tool_calls: list[dict]) -> dict[str, Any]:
    prompt = PROMPT.format(plan_markdown=plan_markdown[:6000], tool_calls_json=_truncate_tool_calls(tool_calls))
    raw = await ainvoke_text(
        system=FAITHFULNESS_JUDGE_SYSTEM,
        user=prompt,
        temperature=0.0,
        max_tokens=800,
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
        log.warning("faithfulness: bad JSON: %s | raw=%s", exc, cleaned[:200])
        return {
            "total_places_in_plan": 0,
            "places_grounded_in_tools": 0,
            "hallucinated_places": [],
            "faithfulness_score": 0.0,
        }


async def faithfulness_evaluator(run, example) -> dict:
    outputs = run.outputs or {}
    plan_md = outputs.get("plan_markdown", "") or ""
    tool_calls = outputs.get("tool_calls", []) or []
    verdict = await _judge(plan_md, tool_calls)
    score = float(verdict.get("faithfulness_score", 0.0))
    return {
        "key": "faithfulness",
        "score": score,
        "comment": f"hallucinated: {verdict.get('hallucinated_places', [])}",
        "metadata": verdict,
    }
