"""Smoke tests for city-knowledge server. Requires a populated Qdrant — usually skipped in CI."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVER_DIR))

SKIP_QDRANT = os.getenv("SKIP_QDRANT_TESTS", "1") == "1"


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
        "city_knowledge_server", _SERVER_DIR / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_imports_ok():
    _load()


@pytest.mark.skipif(SKIP_QDRANT, reason="needs running Qdrant with data")
def test_list_indexed_cities_returns_list():
    import asyncio

    server = _load()
    result = asyncio.run(server.list_indexed_cities())
    assert isinstance(result, list)
