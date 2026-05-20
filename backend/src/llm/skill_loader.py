"""Load SKILL.md content from disk for embedding in system prompts."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.config import settings


@lru_cache(maxsize=4)
def load_skill(name: str = "itinerary-formatter") -> str:
    path: Path = settings.skill_root / name / "SKILL.md"
    if not path.exists():
        return f"# {name}\n\n(SKILL.md file missing at {path})"
    return path.read_text(encoding="utf-8")
