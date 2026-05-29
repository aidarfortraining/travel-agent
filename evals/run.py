"""Run evaluation: invoke the graph in EVAL_MODE on each dataset example, score with judges."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "src" / "config.py").exists():
    sys.path.insert(0, str(ROOT))
elif (ROOT / "backend" / "src" / "config.py").exists():
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

# Force eval mode BEFORE importing graph builder
os.environ["EVAL_MODE"] = "true"

from langsmith import evaluate  # noqa: E402

from evals.judges import constraint_adherence_evaluator, faithfulness_evaluator  # noqa: E402
from src.graph.builder import build_graph_uncached  # noqa: E402
from src.graph.state import TripState  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("eval")


async def _ainvoke_one(inputs: dict) -> dict:
    graph = await build_graph_uncached()
    state = TripState(
        session_id=f"eval-{inputs.get('id', 'x')}",
        city=inputs["city"],
        days=int(inputs["days"]),
        budget_usd=float(inputs["budget_usd"]),
        interests=list(inputs.get("interests", [])),
        dietary=list(inputs.get("dietary", [])),
        photo_b64=inputs.get("photo_b64"),
    )
    final = await graph.ainvoke(state)
    # LangGraph returns a dict-of-mixed-types when the state is a pydantic model:
    # top-level is a dict but nested values like plan_cost_breakdown stay as pydantic
    # instances. Normalize via model_dump on individual fields rather than rely on
    # recursive top-level dumping.
    if hasattr(final, "model_dump"):
        d = final.model_dump()
    elif isinstance(final, dict):
        d = final
    else:
        d = {}

    cost = d.get("plan_cost_breakdown")
    if hasattr(cost, "model_dump"):
        cost = cost.model_dump()
    elif not isinstance(cost, dict):
        cost = {}

    tool_calls_raw = d.get("tool_calls_aggregated", []) or []
    tool_calls: list[dict] = []
    for c in tool_calls_raw:
        if hasattr(c, "model_dump"):
            tool_calls.append(c.model_dump())
        elif isinstance(c, dict):
            tool_calls.append(c)
    return {
        "plan_markdown": d.get("plan_markdown", "") or "",
        "plan_cost_usd": float(cost.get("grand_total_usd", 0.0)),
        "tool_calls": tool_calls,
    }


def target(inputs: dict) -> dict:
    return asyncio.run(_ainvoke_one(inputs))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="trip-planner-golden-v1")
    parser.add_argument("--experiment-prefix", default=os.getenv("EXPERIMENT_PREFIX", "pro-temp07"))
    parser.add_argument("--max-concurrency", type=int, default=2)
    args = parser.parse_args()

    log.info("starting evaluation: dataset=%s, prefix=%s", args.dataset, args.experiment_prefix)
    result = evaluate(
        target,
        data=args.dataset,
        evaluators=[constraint_adherence_evaluator, faithfulness_evaluator],
        experiment_prefix=args.experiment_prefix,
        max_concurrency=args.max_concurrency,
    )
    try:
        df = result.to_pandas()
        log.info("results:\n%s", df.describe(include="all"))
        out = ROOT / "evals" / "results" / f"{args.experiment_prefix}.csv"
        df.to_csv(out, index=False)
        log.info("wrote %s", out)
    except Exception as exc:
        log.warning("failed to convert results to pandas: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
