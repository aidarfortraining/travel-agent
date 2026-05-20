"""Wikivoyage section-based chunker.

Wikivoyage pages follow a stable section convention: See / Do / Eat / Drink / Sleep / Get around.
We split by these h2 headings, then sub-chunk long sections by token approximation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SECTION_MAP = {
    "see": "see",
    "do": "do",
    "eat": "eat",
    "drink": "drink",
    "sleep": "sleep",
    "get around": "get-around",
    "get in": "get-around",
    "buy": "do",
    "understand": "general",
    "talk": "general",
    "stay safe": "general",
    "respect": "general",
    "go next": "general",
}

MAX_CHUNK_CHARS = 2400
MIN_CHUNK_CHARS = 200


@dataclass
class Chunk:
    section: str
    text: str
    title: str = ""
    extra: dict = field(default_factory=dict)


def _normalize_section(name: str) -> str:
    return SECTION_MAP.get(name.strip().lower(), "general")


def split_by_section(plain_text: str) -> list[tuple[str, str]]:
    """Split flat text where lines like '== See ==' mark section boundaries.

    Returns a list of (section_key, section_body).
    """
    lines = plain_text.splitlines()
    sections: list[tuple[str, list[str]]] = [("general", [])]
    for line in lines:
        m = re.match(r"^={2,}\s*(.+?)\s*={2,}\s*$", line)
        if m:
            key = _normalize_section(m.group(1))
            sections.append((key, []))
        else:
            sections[-1][1].append(line)
    return [(k, "\n".join(b).strip()) for k, b in sections if "\n".join(b).strip()]


def chunk_section(section_key: str, body: str) -> list[Chunk]:
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) <= MAX_CHUNK_CHARS:
        if len(body) < MIN_CHUNK_CHARS:
            return [Chunk(section=section_key, text=body)] if body else []
        return [Chunk(section=section_key, text=body)]
    parts: list[Chunk] = []
    current: list[str] = []
    current_len = 0
    for para in body.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if current_len + len(para) + 2 > MAX_CHUNK_CHARS and current:
            parts.append(Chunk(section=section_key, text="\n\n".join(current)))
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para) + 2
    if current:
        parts.append(Chunk(section=section_key, text="\n\n".join(current)))
    return [c for c in parts if len(c.text) >= MIN_CHUNK_CHARS or len(parts) == 1]


def chunk_wikivoyage_text(text: str) -> list[Chunk]:
    out: list[Chunk] = []
    for section_key, body in split_by_section(text):
        out.extend(chunk_section(section_key, body))
    return out
