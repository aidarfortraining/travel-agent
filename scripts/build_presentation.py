"""Render docs/presentation.md → docs/presentation.pdf as a slide deck.

Each `---` separator in the markdown becomes a page break. Uses the same
weasyprint pipeline that backend/src/export/pdf.py uses for trip-plan PDFs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import markdown as md_lib
from weasyprint import CSS, HTML

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "presentation.md"
OUT = ROOT / "docs" / "presentation.pdf"


SLIDE_CSS = CSS(
    string="""
    @page { size: 297mm 210mm; margin: 14mm 18mm; }
    body { font-family: 'DejaVu Sans', sans-serif; color: #1a1f2c; font-size: 14pt; line-height: 1.45; margin: 0; }
    .slide { page-break-after: always; min-height: 170mm; display: block; }
    .slide:last-of-type { page-break-after: auto; }
    h1 { font-size: 32pt; color: #1a3552; margin: 0 0 14pt 0; line-height: 1.1; }
    h2 { font-size: 24pt; color: #1a3552; margin: 0 0 12pt 0; border-bottom: 2px solid #d0d4dc; padding-bottom: 6pt; }
    h3 { font-size: 16pt; color: #1a3552; margin: 14pt 0 6pt 0; }
    p { margin: 6pt 0; }
    ul, ol { margin: 6pt 0 6pt 22pt; padding: 0; }
    li { margin: 3pt 0; }
    strong { color: #0e2440; }
    blockquote { border-left: 4px solid #b8c0cc; margin: 10pt 0; padding: 6pt 14pt; color: #444; background: #f6f7f9; }
    a { color: #1a3552; text-decoration: none; border-bottom: 1px dotted #1a3552; }
    table { border-collapse: collapse; width: 100%; margin: 10pt 0; font-size: 12pt; }
    th, td { border: 1px solid #c5cbd6; padding: 6pt 10pt; text-align: left; vertical-align: top; }
    th { background: #e8ecf4; color: #0e2440; }
    hr { display: none; }
    code { background: #f0f2f6; padding: 1px 5px; border-radius: 3px; font-family: 'DejaVu Sans Mono', monospace; font-size: 11pt; }
    pre { background: #f0f2f6; padding: 10pt; border-radius: 4px; overflow: hidden; font-size: 9.5pt; line-height: 1.35; }
    pre code { background: transparent; padding: 0; font-size: 9.5pt; }
    img { max-width: 100%; max-height: 130mm; display: block; margin: 8pt auto; border: 1px solid #d0d4dc; border-radius: 4px; }
    """
)


def _split_slides(md_text: str) -> list[str]:
    """Split markdown on standalone `---` lines. Strip empty leading/trailing slides."""
    parts: list[list[str]] = [[]]
    for line in md_text.splitlines():
        if line.strip() == "---":
            parts.append([])
        else:
            parts[-1].append(line)
    return ["\n".join(p).strip() for p in parts if "\n".join(p).strip()]


def main() -> int:
    if not SRC.exists():
        print(f"missing source: {SRC}", file=sys.stderr)
        return 1
    md_text = SRC.read_text(encoding="utf-8")
    slides = _split_slides(md_text)

    html_slides: list[str] = []
    for slide_md in slides:
        slide_html = md_lib.markdown(
            slide_md,
            extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
            output_format="html5",
        )
        html_slides.append(f'<section class="slide">{slide_html}</section>')

    full_html = (
        '<!doctype html><html><head><meta charset="utf-8"/></head>'
        "<body>" + "".join(html_slides) + "</body></html>"
    )

    pdf_bytes = HTML(string=full_html, base_url=str(ROOT)).write_pdf(stylesheets=[SLIDE_CSS])
    if pdf_bytes is None:
        print("weasyprint returned no PDF bytes", file=sys.stderr)
        return 2

    OUT.write_bytes(pdf_bytes)
    print(f"wrote {OUT} ({len(slides)} slides, {len(pdf_bytes)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
