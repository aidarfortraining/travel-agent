"""Render presentation/presentation.md → presentation/presentation.pdf as a slide deck.

Each `---` separator in the markdown becomes a page break. Uses the same
weasyprint pipeline that backend/src/export/pdf.py uses for trip-plan PDFs.

Paths are resolved relative to this file's directory, so the script is
self-contained: the markdown and its referenced images live alongside it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import markdown as md_lib
from weasyprint import CSS, HTML

HERE = Path(__file__).resolve().parent
SRC = HERE / "presentation.md"
OUT = HERE / "presentation.pdf"


# Palette: deep navy brand, teal accent, cool neutrals. DejaVu fonts are
# required for Cyrillic + offline rendering.
SLIDE_CSS = CSS(
    string="""
    @page {
        size: 297mm 210mm;
        margin: 16mm 20mm 17mm 20mm;
        @bottom-left  { content: "Trip Planner  ·  nFactorial LLM Stack";
                        font-family: 'DejaVu Sans', sans-serif; font-size: 8pt; color: #9aa6b6; }
        @bottom-right { content: counter(page);
                        font-family: 'DejaVu Sans', sans-serif; font-size: 8pt; color: #9aa6b6; }
    }
    /* Cover page bleeds to the edges and carries no footer. */
    @page :first { margin: 0; @bottom-left { content: normal; } @bottom-right { content: normal; } }

    body { font-family: 'DejaVu Sans', sans-serif; color: #25303f; font-size: 13.5pt;
           line-height: 1.5; margin: 0; }
    .slide { page-break-after: always; }
    .slide:last-of-type { page-break-after: auto; }

    /* ---- Content headings ---- */
    h1 { font-size: 30pt; color: #122a4d; margin: 0 0 14pt 0; line-height: 1.12; }
    h2 { font-size: 23pt; color: #122a4d; margin: 0 0 16pt 0; line-height: 1.12;
         padding: 1pt 0 9pt 15pt; border-left: 5px solid #15b3a4; border-bottom: 2px solid #e4e9f1; }
    h3 { font-size: 14pt; color: #0f8d82; margin: 16pt 0 5pt 0; letter-spacing: .3pt; }
    p { margin: 7pt 0; }
    ul, ol { margin: 7pt 0 7pt 22pt; padding: 0; }
    li { margin: 4pt 0; padding-left: 3pt; }
    li::marker { color: #15b3a4; }
    strong { color: #122a4d; }
    a { color: #1c4f8a; text-decoration: none; border-bottom: 1px dotted #6f97c4; }

    blockquote { border-left: 4px solid #15b3a4; background: #f1f7f6; border-radius: 0 6px 6px 0;
                 margin: 12pt 0; padding: 8pt 16pt; color: #36505a; }

    /* ---- Tables ---- */
    table { border-collapse: collapse; width: 100%; margin: 12pt 0; font-size: 11.5pt;
            border: 1px solid #dce3ee; border-radius: 6px; overflow: hidden; }
    th { background: #1c3a63; color: #ffffff; font-weight: bold; padding: 8pt 11pt;
         text-align: left; vertical-align: top; }
    td { padding: 7pt 11pt; text-align: left; vertical-align: top; border-top: 1px solid #e6ebf3; }
    tr:nth-child(even) td { background: #f5f8fc; }

    /* ---- Code ---- */
    code { background: #eef2f8; color: #1c3a63; padding: 1px 5px; border-radius: 3px;
           font-family: 'DejaVu Sans Mono', monospace; font-size: 10.5pt; }
    pre { background: #0f2036; color: #e7eef7; padding: 12pt 15pt; border-radius: 7px;
          overflow: hidden; font-size: 9.5pt; line-height: 1.4; }
    pre code { background: transparent; color: inherit; padding: 0; font-size: 9.5pt; }

    img { max-width: 100%; max-height: 128mm; display: block; margin: 10pt auto;
          border: 1px solid #d7deea; border-radius: 6px; box-shadow: 0 4px 14px rgba(18,42,77,.14); }

    /* ---- Cover slide (full-bleed) ---- */
    .slide--cover { min-height: 210mm; box-sizing: border-box; padding: 74mm 30mm 0 30mm;
                    background: linear-gradient(135deg, #0f2748 0%, #1c4f8a 100%); color: #ffffff; }
    .slide--cover h1 { color: #ffffff; font-size: 48pt; margin: 0; line-height: 1.04; }
    .slide--cover h1::after { content: ""; display: block; width: 130pt; height: 5pt;
                              background: #19c2b0; border-radius: 3px; margin-top: 18pt; }
    .slide--cover p:nth-of-type(1) { font-size: 19pt; color: #eaf2fb; margin: 22pt 0 0 0; }
    .slide--cover p:nth-of-type(1) strong { color: #8fe6db; font-weight: bold; }
    .slide--cover p:nth-of-type(2) { font-size: 13pt; color: #9fb6d4; margin: 10pt 0 0 0;
                                     letter-spacing: .6pt; text-transform: uppercase; }

    /* ---- Closing slide ---- */
    .slide--end { background: linear-gradient(135deg, #0f2748 0%, #1c4f8a 100%); color: #ffffff;
                  border-radius: 10px; padding: 34mm 30mm; min-height: 150mm; box-sizing: border-box; }
    .slide--end h2 { color: #ffffff; border: none; padding: 0; font-size: 30pt; }
    .slide--end h2::after { content: ""; display: block; width: 110pt; height: 4pt;
                            background: #19c2b0; border-radius: 3px; margin-top: 14pt; }
    .slide--end p { color: #dbe6f3; font-size: 15pt; }
    .slide--end strong { color: #ffffff; }
    .slide--end a { color: #9fe7dd; border: none; }
    .slide--end code { background: rgba(255,255,255,.14); color: #eaf2fb; border: none; }

    hr { display: none; }
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

    last = len(slides) - 1
    html_slides: list[str] = []
    for i, slide_md in enumerate(slides):
        slide_html = md_lib.markdown(
            slide_md,
            extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
            output_format="html5",
        )
        cls = "slide"
        if i == 0:
            cls = "slide slide--cover"
        elif i == last:
            cls = "slide slide--end"
        html_slides.append(f'<section class="{cls}">{slide_html}</section>')

    full_html = (
        '<!doctype html><html><head><meta charset="utf-8"/></head>'
        "<body>" + "".join(html_slides) + "</body></html>"
    )

    pdf_bytes = HTML(string=full_html, base_url=str(HERE)).write_pdf(stylesheets=[SLIDE_CSS])
    if pdf_bytes is None:
        print("weasyprint returned no PDF bytes", file=sys.stderr)
        return 2

    OUT.write_bytes(pdf_bytes)
    print(f"wrote {OUT} ({len(slides)} slides, {len(pdf_bytes)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
