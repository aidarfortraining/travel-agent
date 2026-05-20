"""Scrape Wikivoyage city pages, chunk by section, embed, upsert to Qdrant.

Usage:
    python scripts/ingest_wikivoyage.py --cities Istanbul Barcelona Lisbon Tokyo "Mexico City"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Detect layout: docker (/app/src) vs local (PROJECT_ROOT/backend/src)
if (PROJECT_ROOT / "src" / "rag" / "chunking.py").exists():
    sys.path.insert(0, str(PROJECT_ROOT))
elif (PROJECT_ROOT / "backend" / "src" / "rag" / "chunking.py").exists():
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
else:
    raise RuntimeError(f"Cannot locate backend/src/ from {PROJECT_ROOT}")

from src.rag.chunking import chunk_wikivoyage_text  # noqa: E402
from src.rag.embeddings import embed_text  # noqa: E402
from src.rag.qdrant_client import ensure_collection, get_client, upsert_chunks  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ingest")

WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"
WIKIVOYAGE_BASE = "https://en.wikivoyage.org/wiki/"


CITY_META_DEFAULTS: dict[str, dict] = {
    "Istanbul": {
        "country": "Turkey", "currency": "TRY",
        "languages": ["Turkish", "English"],
        "best_season": "Apr-Jun, Sep-Oct",
        "safety_level": "moderate_risk",
        "safety_notes": "Watch belongings in crowded bazaars; be cautious near demonstrations.",
        "transport_summary": "Tram T1 and metro M2 cover most tourist areas; Istanbulkart for all transit.",
        "timezone": "Europe/Istanbul",
    },
    "Barcelona": {
        "country": "Spain", "currency": "EUR",
        "languages": ["Catalan", "Spanish", "English"],
        "best_season": "May-Jun, Sep-Oct",
        "safety_level": "moderate_risk",
        "safety_notes": "Pickpocketing common in La Rambla and metro; carry minimal cash.",
        "transport_summary": "TMB metro (10 lines) and buses cover the city; T-Casual ticket for 10 trips.",
        "timezone": "Europe/Madrid",
    },
    "Lisbon": {
        "country": "Portugal", "currency": "EUR",
        "languages": ["Portuguese", "English"],
        "best_season": "Apr-Jun, Sep-Oct",
        "safety_level": "low_risk",
        "safety_notes": "Generally safe; watch for tram pickpockets on the 28 line.",
        "transport_summary": "Metro (4 lines) plus historic trams; Viva Viagem rechargeable card.",
        "timezone": "Europe/Lisbon",
    },
    "Tokyo": {
        "country": "Japan", "currency": "JPY",
        "languages": ["Japanese", "limited English"],
        "best_season": "Mar-Apr (sakura), Oct-Nov (foliage)",
        "safety_level": "low_risk",
        "safety_notes": "Extremely safe; respect quiet etiquette on trains.",
        "transport_summary": "JR + Tokyo Metro + Toei subway; Suica/Pasmo cards work across all.",
        "timezone": "Asia/Tokyo",
    },
    "Mexico City": {
        "country": "Mexico", "currency": "MXN",
        "languages": ["Spanish", "limited English"],
        "best_season": "Mar-May, Oct-Dec",
        "safety_level": "moderate_risk",
        "safety_notes": "Stick to tourist districts (Roma, Condesa, Centro); avoid hailing street taxis.",
        "transport_summary": "Metro is fastest; use Uber/Didi at night.",
        "timezone": "America/Mexico_City",
    },
}


def _api_fetch_page(client: httpx.Client, title: str) -> tuple[str, str]:
    """Returns (plain_text, source_url). Uses the Wikivoyage parse API for cleaner extraction."""
    params = {
        "action": "parse",
        "page": title,
        "prop": "wikitext|displaytitle",
        "format": "json",
        "redirects": "1",
    }
    r = client.get(WIKIVOYAGE_API, params=params, timeout=20.0)
    r.raise_for_status()
    data = r.json()
    wikitext = (data.get("parse") or {}).get("wikitext", {}).get("*", "")
    plain = _wikitext_to_plain(wikitext)
    page_title = (data.get("parse") or {}).get("title", title).replace(" ", "_")
    return plain, f"{WIKIVOYAGE_BASE}{page_title}"


def _wikitext_to_plain(wikitext: str) -> str:
    """Lossy wikitext cleanup: drop templates, file links, refs; keep section headers and links text."""
    text = wikitext
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Drop templates (potentially nested) — simple iterative remove
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\{\{[^{}]*?\}\}", " ", text, flags=re.DOTALL)
    # Drop File / Image links (also possibly nested brackets)
    text = re.sub(r"\[\[(File|Image):[^\[\]]*?\]\]", "", text, flags=re.IGNORECASE)
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\[\[(File|Image):.*?\]\]", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Wiki links: [[Page|label]] → label; [[Page]] → Page
    text = re.sub(r"\[\[([^\[\]|]+?)\|([^\[\]]+?)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\[\]]+?)\]\]", r"\1", text)
    # External links: [url label] → label
    text = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    # Bold/italic markers
    text = re.sub(r"'''(.+?)'''", r"\1", text)
    text = re.sub(r"''(.+?)''", r"\1", text)
    # HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_id(city: str, section: str, idx: int, text: str) -> str:
    h = hashlib.md5(f"{city}|{section}|{idx}|{text[:80]}".encode("utf-8")).hexdigest()
    return h


def ingest_city(city: str, *, dry_run: bool = False) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    meta = CITY_META_DEFAULTS.get(city, {"country": "", "currency": "USD"})
    title = city.replace(" ", "_")
    log.info("scraping %s", title)
    with httpx.Client(headers={"User-Agent": "TripPlanner-Ingest/0.1 (educational)"}) as cli:
        plain, source_url = _api_fetch_page(cli, title)
    if not plain or len(plain) < 500:
        log.warning("page for %s looks empty / too short (%d chars)", city, len(plain))
    chunks = chunk_wikivoyage_text(plain)
    log.info("city %s → %d chunks (%d chars)", city, len(chunks), len(plain))
    upsert_payload: list[dict] = []
    for i, ch in enumerate(chunks):
        cid = _chunk_id(city, ch.section, i, ch.text)
        vector = None if dry_run else embed_text(ch.text)
        upsert_payload.append(
            {
                "id": cid,
                "vector": vector,
                "text": ch.text,
                "section": ch.section,
                "city": city,
                "kind": "guide",
                "source_url": source_url,
                "title": title,
                "country": meta.get("country", ""),
                "ingested_at": ts,
            }
        )
    overview_text = json.dumps(meta, ensure_ascii=False)
    overview_id = _chunk_id(city, "overview", 0, overview_text)
    vector = None if dry_run else embed_text(f"Overview of {city}: {meta.get('country', '')}")
    upsert_payload.append(
        {
            "id": overview_id,
            "vector": vector,
            "text": overview_text,
            "section": "overview",
            "city": city,
            "kind": "overview",
            "source_url": source_url,
            "title": title,
            "country": meta.get("country", ""),
            "ingested_at": ts,
        }
    )
    if dry_run:
        log.info("dry-run: would upsert %d points for %s", len(upsert_payload), city)
        return len(upsert_payload)
    count = upsert_chunks(upsert_payload)
    log.info("upserted %d points for %s", count, city)
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cities",
        nargs="+",
        required=True,
        help="City names. Multi-word names should be quoted, e.g. 'Mexico City'.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        ensure_collection(get_client())

    total = 0
    for city in args.cities:
        try:
            total += ingest_city(city, dry_run=args.dry_run)
            time.sleep(1.5)
        except Exception:
            log.exception("ingest failed for %s", city)
    log.info("ingest complete: %d total points across %d cities", total, len(args.cities))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
