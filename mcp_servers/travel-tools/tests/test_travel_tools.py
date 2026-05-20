"""Smoke tests for travel-tools server. Skipped if no network."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVER_DIR))


def _load() -> object:
    """Load this MCP server's server.py under a unique name to avoid clashing
    with sibling MCP servers that also expose a module called `server`."""
    for name in ("server", "schemas"):
        sys.modules.pop(name, None)
    # Make sure THIS server's dir wins lookup for the bare `from schemas import ...`
    # in server.py; siblings may have prepended their own _SERVER_DIR earlier.
    server_dir = str(_SERVER_DIR)
    while server_dir in sys.path:
        sys.path.remove(server_dir)
    sys.path.insert(0, server_dir)
    spec = importlib.util.spec_from_file_location(
        "travel_tools_server", _SERVER_DIR / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


SKIP_NETWORK = os.getenv("SKIP_NETWORK_TESTS", "1") == "1"


@pytest.mark.skipif(SKIP_NETWORK, reason="network test; set SKIP_NETWORK_TESTS=0 to enable")
def test_find_places_istanbul_museums():
    server = _load()

    result = asyncio.run(server.find_places(city="Istanbul", category="museum", limit=5))
    assert isinstance(result, list)
    assert len(result) >= 1
    first = result[0]
    assert "is_error" not in first or first.get("is_error") is False
    if "name" in first:
        assert first["name"]
        assert first["category"] == "museum"


@pytest.mark.skipif(SKIP_NETWORK, reason="network test")
def test_get_weather_forecast_istanbul():
    server = _load()

    result = asyncio.run(server.get_weather_forecast(city="Istanbul"))
    assert isinstance(result, dict)
    assert result.get("city") == "Istanbul"
    if "entries" in result:
        assert isinstance(result["entries"], list)


def test_overpass_filter_mapping_complete():
    server = _load()

    expected = {"museum", "park", "viewpoint", "historical", "religious", "nightlife", "shopping"}
    assert expected.issubset(server.CATEGORY_TO_OVERPASS.keys())
