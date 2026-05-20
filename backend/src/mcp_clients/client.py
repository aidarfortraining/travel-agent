"""MultiServerMCPClient setup. Lazy singleton — tools resolved on first call."""
from __future__ import annotations

import json
import logging
import sys
from functools import lru_cache
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from src.config import settings

log = logging.getLogger(__name__)


def _server_config() -> dict[str, dict[str, Any]]:
    root = settings.mcp_servers_root
    py = sys.executable or "python"

    # Don't pass empty values for optional env vars — empty OPENAI_BASE_URL breaks
    # the OpenAI SDK with `httpx.UnsupportedProtocol`.
    city_knowledge_env = {
        "QDRANT_URL": settings.qdrant_url,
        "QDRANT_COLLECTION": settings.qdrant_collection,
        "OPENAI_API_KEY": settings.openai_api_key,
        "OPENAI_EMBEDDING_MODEL": settings.openai_embedding_model,
    }
    if settings.qdrant_api_key:
        city_knowledge_env["QDRANT_API_KEY"] = settings.qdrant_api_key
    if settings.openai_base_url:
        city_knowledge_env["OPENAI_BASE_URL"] = settings.openai_base_url

    return {
        "travel-tools": {
            "command": py,
            "args": [str(root / "travel-tools" / "server.py")],
            "transport": "stdio",
        },
        "city-knowledge": {
            "command": py,
            "args": [str(root / "city-knowledge" / "server.py")],
            "transport": "stdio",
            "env": city_knowledge_env,
        },
        "trip-utilities": {
            "command": py,
            "args": [str(root / "trip-utilities" / "server.py")],
            "transport": "stdio",
        },
    }


@lru_cache(maxsize=1)
def get_client() -> MultiServerMCPClient:
    cfg = _server_config()
    log.info("initializing MCP client with %d servers", len(cfg))
    return MultiServerMCPClient(cfg)


_tools_cache: dict[str, Any] | None = None


async def get_tools_by_name() -> dict[str, Any]:
    """Return a flat name → tool map across all 3 servers."""
    global _tools_cache
    if _tools_cache is not None:
        return _tools_cache
    client = get_client()
    tools = await client.get_tools()
    _tools_cache = {t.name: t for t in tools}
    log.info("loaded %d MCP tools: %s", len(_tools_cache), sorted(_tools_cache))
    return _tools_cache


def _unwrap_mcp_result(raw: Any) -> list[Any]:
    """langchain-mcp-adapters wraps tool output as list[{"type":"text", "text":"<json>"}].

    Returns a list of parsed JSON values (dicts/lists/primitives). Falls back gracefully
    on unexpected shapes so MCP tools that already return plain Python continue to work.
    """
    if isinstance(raw, list):
        out: list[Any] = []
        for item in raw:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                try:
                    out.append(json.loads(item["text"]))
                except json.JSONDecodeError:
                    out.append(item["text"])
            else:
                out.append(item)
        return out
    if isinstance(raw, str):
        try:
            return [json.loads(raw)]
        except json.JSONDecodeError:
            return [raw]
    return [raw]


async def call_tool_list(name: str, **kwargs) -> list[Any]:
    """Call a tool whose declared return is a list (e.g. find_places, search_city_guide)."""
    tools = await get_tools_by_name()
    if name not in tools:
        raise KeyError(f"MCP tool not found: {name}. Available: {sorted(tools)}")
    raw = await tools[name].ainvoke(kwargs)
    return _unwrap_mcp_result(raw)


async def call_tool(name: str, **kwargs) -> Any:
    """Call a tool whose declared return is a single object (e.g. get_city_overview).

    Returns the first unwrapped item, or an empty dict if nothing came back.
    For list-returning tools use `call_tool_list` instead.
    """
    tools = await get_tools_by_name()
    if name not in tools:
        raise KeyError(f"MCP tool not found: {name}. Available: {sorted(tools)}")
    raw = await tools[name].ainvoke(kwargs)
    items = _unwrap_mcp_result(raw)
    return items[0] if items else {}
