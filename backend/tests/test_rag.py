"""RAG chunking unit tests (offline)."""
from __future__ import annotations


def test_chunking_splits_by_section():
    from src.rag.chunking import chunk_wikivoyage_text

    text = """
== See ==
Hagia Sophia is a must-see. It is large.

== Eat ==
Try local kebab. It is delicious.

== Do ==
Walk along the Bosphorus.
"""
    chunks = chunk_wikivoyage_text(text)
    sections = {c.section for c in chunks}
    assert "see" in sections
    assert "eat" in sections
    assert "do" in sections


def test_chunking_handles_long_section():
    from src.rag.chunking import chunk_wikivoyage_text

    long_text = "== Do ==\n" + ("Paragraph. " * 600 + "\n\n") * 3
    chunks = chunk_wikivoyage_text(long_text)
    assert len(chunks) >= 1
    assert all(c.section == "do" for c in chunks)
