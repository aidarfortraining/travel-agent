"""Compare two LangSmith experiments → markdown report."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "src" / "config.py").exists():
    sys.path.insert(0, str(ROOT))
elif (ROOT / "backend" / "src" / "config.py").exists():
    sys.path.insert(0, str(ROOT / "backend"))

from langsmith import Client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("compare")


def _resolve_project(client: Client, prefix: str) -> str | None:
    """Find the most recent LangSmith project whose name starts with `prefix`.

    `evaluate(experiment_prefix=...)` appends a random suffix, so an exact lookup
    by prefix fails. We list projects, filter by startswith, and pick the latest.
    """
    try:
        client.read_project(project_name=prefix)
        return prefix
    except Exception:
        pass
    projects = list(client.list_projects())
    matches = [p for p in projects if p.name and p.name.startswith(prefix)]
    if not matches:
        return None
    matches.sort(key=lambda p: getattr(p, "start_time", None) or "", reverse=True)
    return matches[0].name


def _experiment_metrics(client: Client, prefix: str) -> dict[str, float]:
    project_name = _resolve_project(client, prefix)
    if not project_name:
        log.warning("no LangSmith project matches prefix %s", prefix)
        return {}
    log.info("resolved %s -> %s", prefix, project_name)
    runs = list(client.list_runs(project_name=project_name, execution_order=1))
    if not runs:
        return {}
    feedback = []
    for r in runs:
        try:
            fb = list(client.list_feedback(run_ids=[r.id]))
            feedback.extend(fb)
        except Exception:
            pass
    by_key: dict[str, list[float]] = {}
    for f in feedback:
        if f.score is None:
            continue
        by_key.setdefault(f.key, []).append(float(f.score))
    return {k: mean(v) for k, v in by_key.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True, help="experiment_prefix A")
    parser.add_argument("--b", required=True, help="experiment_prefix B")
    parser.add_argument("--out", default=str(ROOT / "evals" / "results" / "ab_pro_vs_flash.md"))
    args = parser.parse_args()

    client = Client()
    metrics_a = _experiment_metrics(client, args.a)
    metrics_b = _experiment_metrics(client, args.b)
    keys = sorted(set(metrics_a) | set(metrics_b))
    rows = []
    for k in keys:
        va = metrics_a.get(k, 0.0)
        vb = metrics_b.get(k, 0.0)
        rows.append(f"| {k} | {va:.3f} | {vb:.3f} | {vb - va:+.3f} |")

    md = f"""# A/B Experiment: {args.a} vs {args.b}

## Results

| Metric | {args.a} | {args.b} | Δ |
|---|---|---|---|
{chr(10).join(rows)}

## Notes

- All runs share the same golden dataset (`trip-planner-golden-v1`).
- LLM-as-judge metrics use the project's primary OpenAI mini model at temperature 0.0.
- Differences below 0.05 are within noise on 10-example datasets.
"""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    log.info("wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
