"""Upload evals/dataset.jsonl to LangSmith as a Dataset. Idempotent (skips if exists)."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "src" / "config.py").exists():
    sys.path.insert(0, str(ROOT))
elif (ROOT / "backend" / "src" / "config.py").exists():
    sys.path.insert(0, str(ROOT / "backend"))

from langsmith import Client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("upload")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="trip-planner-golden-v1")
    parser.add_argument("--file", default=str(ROOT / "evals" / "dataset.jsonl"))
    args = parser.parse_args()

    client = Client()
    existing = [d for d in client.list_datasets() if d.name == args.name]
    if existing:
        log.info("dataset %s already exists (id=%s); skipping create", args.name, existing[0].id)
        ds = existing[0]
    else:
        ds = client.create_dataset(args.name, description="Trip Planner golden dataset (10 examples)")
        log.info("created dataset %s (id=%s)", args.name, ds.id)

    with open(args.file, encoding="utf-8") as f:
        examples = [json.loads(line) for line in f if line.strip()]

    for ex in examples:
        client.create_example(
            dataset_id=ds.id,
            inputs={"id": ex["id"], **ex["input"]},
            outputs={"expected": ex["expected"], "tags": ex.get("tags", [])},
        )
    log.info("uploaded %d examples to %s", len(examples), args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
