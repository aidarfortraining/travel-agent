"""Sanity check: env vars, Qdrant reachable, OpenAI ping, LangSmith config.

Usage:  python scripts/verify_setup.py
Exits 0 on full success, 1 if any check failed.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if (PROJECT_ROOT / "src" / "config.py").exists():
    sys.path.insert(0, str(PROJECT_ROOT))
elif (PROJECT_ROOT / "backend" / "src" / "config.py").exists():
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
else:
    raise RuntimeError(f"Cannot locate backend/src/ from {PROJECT_ROOT}")


def _print_status(name: str, ok: bool, detail: str = "") -> None:
    mark = "OK " if ok else "FAIL"
    print(f"[{mark}] {name}{' — ' + detail if detail else ''}")


def check_env() -> bool:
    from src.config import settings

    missing = []
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if not settings.langsmith_api_key:
        missing.append("LANGSMITH_API_KEY (tracing will be disabled)")
    detail = "; ".join(missing) if missing else "all required vars set"
    return _print_status("env vars", not missing or missing == ["LANGSMITH_API_KEY (tracing will be disabled)"], detail) or True


def check_qdrant() -> bool:
    try:
        from src.rag.qdrant_client import ensure_collection, get_client

        cli = get_client()
        info = cli.get_collections()
        ensure_collection(cli)
        _print_status("Qdrant", True, f"{len(info.collections)} existing collections")
        return True
    except Exception as exc:
        _print_status("Qdrant", False, str(exc))
        return False


def check_openai_embeddings() -> bool:
    try:
        from src.rag.embeddings import VECTOR_SIZE, embed_text

        v = embed_text("hello world")
        ok = isinstance(v, list) and len(v) == VECTOR_SIZE
        _print_status("OpenAI embeddings", ok, f"dim={len(v)} (expected {VECTOR_SIZE})")
        return ok
    except Exception as exc:
        _print_status("OpenAI embeddings", False, str(exc))
        return False


def check_openai_chat() -> bool:
    try:
        import asyncio

        from src.llm.client import ainvoke_text

        out = asyncio.run(
            ainvoke_text(
                system="Reply with the single word OK.",
                user="ping",
                temperature=0.0,
                max_tokens=8,
            )
        )
        ok = bool(out) and "ok" in out.lower()
        _print_status("OpenAI chat", ok, f"reply={out[:40]!r}")
        return ok
    except Exception as exc:
        _print_status("OpenAI chat", False, str(exc))
        return False


def check_langsmith() -> bool:
    try:
        from src.config import settings

        if not settings.langsmith_api_key:
            _print_status("LangSmith", False, "no API key")
            return False
        from langsmith import Client

        cli = Client(api_key=settings.langsmith_api_key)
        _ = list(cli.list_projects())[:1]
        _print_status("LangSmith", True, settings.langsmith_project)
        return True
    except Exception as exc:
        _print_status("LangSmith", False, str(exc))
        return False


def check_mcp_servers() -> bool:
    from src.config import settings

    root = settings.mcp_servers_root
    paths = [
        root / "travel-tools" / "server.py",
        root / "city-knowledge" / "server.py",
        root / "trip-utilities" / "server.py",
    ]
    missing = [str(p) for p in paths if not p.exists()]
    ok = not missing
    _print_status("MCP server files", ok, ", ".join(missing) or f"all present at {root}")
    return ok


def check_skill() -> bool:
    from src.config import settings

    p = settings.skill_root / "itinerary-formatter" / "SKILL.md"
    ok = p.exists()
    _print_status("SKILL.md", ok, str(p))
    return ok


def main() -> int:
    print("Trip Planner setup verification")
    print("=" * 60)
    results = [
        check_env(),
        check_skill(),
        check_mcp_servers(),
        check_qdrant(),
        check_openai_embeddings(),
        check_openai_chat(),
        check_langsmith(),
    ]
    print("=" * 60)
    if all(results):
        print("All checks passed.")
        return 0
    print(f"{sum(1 for r in results if not r)} check(s) failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
