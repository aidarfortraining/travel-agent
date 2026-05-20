"""Markdown → PDF via weasyprint."""
from __future__ import annotations

import logging

import markdown as md_lib
from weasyprint import CSS, HTML

log = logging.getLogger(__name__)

_PDF_CSS = CSS(
    string="""
    @page { size: A4; margin: 18mm 16mm; }
    body { font-family: 'DejaVu Sans', sans-serif; color: #222; font-size: 11pt; line-height: 1.5; }
    h1 { font-size: 20pt; color: #1a3552; margin-top: 0; }
    h2 { font-size: 14pt; color: #1a3552; border-bottom: 1px solid #d0d4dc; padding-bottom: 4px; margin-top: 18px; }
    h3 { font-size: 12pt; color: #1a3552; margin-top: 12px; }
    blockquote { border-left: 3px solid #b8c0cc; margin: 8px 0; padding: 4px 12px; color: #555; background: #f6f7f9; }
    a { color: #1a3552; text-decoration: none; border-bottom: 1px dotted #1a3552; }
    table { border-collapse: collapse; width: 100%; margin: 8px 0; }
    th, td { border: 1px solid #d0d4dc; padding: 4px 8px; text-align: left; font-size: 10pt; }
    th { background: #f0f2f6; }
    hr { border: none; border-top: 1px dashed #c0c5cf; margin: 8px 0; }
    code { background: #f0f2f6; padding: 1px 4px; border-radius: 2px; font-family: 'DejaVu Sans Mono', monospace; }
    """
)


def markdown_to_pdf_bytes(markdown_text: str) -> bytes:
    html_body = md_lib.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
        output_format="html5",
    )
    html_doc = f"""<!doctype html><html><head><meta charset="utf-8"/></head>
<body>{html_body}</body></html>"""
    pdf_bytes = HTML(string=html_doc).write_pdf(stylesheets=[_PDF_CSS])
    if pdf_bytes is None:
        raise RuntimeError("weasyprint returned no PDF bytes")
    return pdf_bytes
