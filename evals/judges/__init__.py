"""LLM-as-judge evaluators for trip-planner evals.

langsmith.evaluate() runs evaluators in a ThreadPoolExecutor where there is no
current event loop, so the underlying async evaluators must be wrapped in
asyncio.run(). Each wrapper preserves the original LangSmith-evaluator name so
the score key shows up correctly in dashboards.
"""
import asyncio

from .constraint_adherence import constraint_adherence_evaluator as _async_constraint
from .faithfulness import faithfulness_evaluator as _async_faithfulness


def constraint_adherence_evaluator(run, example) -> dict:
    return asyncio.run(_async_constraint(run, example))


def faithfulness_evaluator(run, example) -> dict:
    return asyncio.run(_async_faithfulness(run, example))


__all__ = ["constraint_adherence_evaluator", "faithfulness_evaluator"]
