"""Tests for trip-utilities server (offline — no network)."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVER_DIR))


def _load() -> object:
    """Load this MCP server's server.py under a unique name to avoid clashing
    with sibling MCP servers that also expose a module called `server`."""
    for name in ("server", "schemas"):
        sys.modules.pop(name, None)
    server_dir = str(_SERVER_DIR)
    while server_dir in sys.path:
        sys.path.remove(server_dir)
    sys.path.insert(0, server_dir)
    spec = importlib.util.spec_from_file_location(
        "trip_utilities_server", _SERVER_DIR / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_validate_halal_turkish_cuisine_is_partial():
    server = _load()

    result = asyncio.run(
        server.validate_dietary_match(
            place_name="Hamdi",
            place_cuisine="turkish",
            place_tags=[],
            restrictions=["halal"],
        )
    )
    assert result["verdict"] in ("partial", "accommodates")
    assert result["confidence"] >= 0.5


def test_validate_halal_explicit_tag_is_accommodates():
    server = _load()

    result = asyncio.run(
        server.validate_dietary_match(
            place_name="Halal Spot",
            place_cuisine=None,
            place_tags=["diet:halal:yes"],
            restrictions=["halal"],
        )
    )
    assert result["verdict"] == "accommodates"
    assert result["confidence"] == 1.0


def test_estimate_plan_cost_simple():
    server = _load()

    plan = {
        "city": "Istanbul",
        "days": [
            {
                "day_number": 1,
                "blocks": [
                    {
                        "period": "morning",
                        "start_time": "09:00",
                        "place_id": "p1",
                        "place_type": "attraction",
                        "estimated_cost_usd": 25.0,
                    },
                    {
                        "period": "afternoon",
                        "start_time": "13:00",
                        "place_id": "r1",
                        "place_type": "restaurant",
                        "estimated_cost_usd": 18.0,
                    },
                ],
            }
        ],
    }
    result = asyncio.run(server.estimate_plan_cost(plan=plan))
    assert result["per_day"][0]["attractions_usd"] == 25.0
    assert result["per_day"][0]["restaurants_usd"] == 18.0
    assert result["per_day"][0]["total_usd"] == 43.0
    assert result["grand_total_usd"] == 43.0
