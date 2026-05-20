"""PDF export smoke test."""
from __future__ import annotations

import pytest


def test_markdown_to_pdf_produces_bytes():
    try:
        from src.export.pdf import markdown_to_pdf_bytes
    except OSError:
        pytest.skip("weasyprint native deps missing")
    md = "# Title\n\nHello **world**.\n\n- a\n- b"
    out = markdown_to_pdf_bytes(md)
    assert isinstance(out, bytes)
    assert out.startswith(b"%PDF")
    assert len(out) > 500
