"""Standalone offline smoke runner. Run with: python backend/tests/_smoke_run.py"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.graph.branches import budget_feasible, edit_or_accept, has_photo
from src.graph.nodes.budget_check import budget_check
from src.graph.nodes.cluster_by_day import cluster_by_day
from src.graph.nodes.collect_input import collect_input
from src.graph.nodes.enrich_input import enrich_input
from src.graph.nodes.finalize_and_export import finalize_and_export
from src.graph.nodes.optimize_route import optimize_route
from src.graph.nodes.patch_plan import patch_plan
from src.graph.state import TripState
from src.rag.chunking import chunk_wikivoyage_text
from src.schemas import (
    DayPlan,
    EditIntent,
    EditRecord,
    PhotoAnalysis,
    Place,
    Plan,
    Restaurant,
    TimeBlock,
)


def main() -> int:
    # Branches
    assert has_photo(TripState(session_id="t", photo_b64="abc")) == "vision_identify"
    assert has_photo(TripState(session_id="t")) == "city_research"
    assert budget_feasible(TripState(session_id="t", budget_warning="x")) == "explain_and_ask"
    assert budget_feasible(TripState(session_id="t")) == "cluster_by_day"
    assert edit_or_accept(TripState(session_id="t", accept_signal=True)) == "finalize_and_export"
    assert edit_or_accept(TripState(session_id="t", pending_edit_text="hi")) == "parse_edit_intent"
    assert edit_or_accept(TripState(session_id="t")) == "finalize_and_export"
    print("branches: PASS")

    # collect_input
    assert asyncio.run(collect_input(TripState(session_id="t", city="Istanbul", days=3, budget_usd=300)))["error"] is None
    assert asyncio.run(collect_input(TripState(session_id="t", city="", days=0, budget_usd=-1)))["error"] is not None
    print("collect_input: PASS")

    # enrich_input
    ps = PhotoAnalysis(landmark="Blue Mosque", city="Istanbul", place_type="religious", confidence=0.9)
    out = asyncio.run(enrich_input(TripState(session_id="t", interests=["history"], photo_analysis=ps)))
    assert "religious" in out["interests"]
    print("enrich_input: PASS")

    # finalize_and_export
    out = asyncio.run(finalize_and_export(TripState(session_id="t", plan_markdown="# plan")))
    assert out["status"] == "finalized"
    print("finalize_and_export: PASS")

    # cluster
    places = [Place(osm_id=f"node/{i}", name=f"P{i}", category="museum", lat=41.0 + i * 0.001, lon=29.0 + i * 0.001) for i in range(9)]
    out = asyncio.run(cluster_by_day(TripState(session_id="t", city="Istanbul", days=3, candidate_places=places)))
    flat = [pid for ids in out["day_assignment"].values() for pid in ids]
    assert set(flat) == {p.osm_id for p in places}
    print(f"cluster_by_day: PASS ({len(flat)} places)")

    out_r = asyncio.run(optimize_route(TripState(session_id="t", candidate_places=places, day_assignment=out["day_assignment"])))
    assert sum(len(v) for v in out_r["route_per_day"].values()) == 9
    print("optimize_route: PASS")

    # budget
    places_p = [Place(osm_id=f"node/{i}", name=f"P{i}", category="museum", lat=41.0, lon=29.0, estimated_cost_usd=15.0) for i in range(6)]
    rests = [Restaurant(osm_id=f"r/{i}", name=f"R{i}", lat=41.0, lon=29.0, estimated_meal_cost_usd=18.0) for i in range(6)]
    assert asyncio.run(budget_check(TripState(session_id="t", city="X", days=3, budget_usd=300, candidate_places=places_p, candidate_restaurants=rests)))["budget_warning"] is None
    assert asyncio.run(budget_check(TripState(session_id="t", city="X", days=3, budget_usd=50, candidate_places=places_p, candidate_restaurants=rests)))["budget_warning"] is not None
    print("budget_check: PASS")

    # patch remove
    plan = Plan(city="Istanbul", days=[DayPlan(day_number=1, blocks=[
        TimeBlock(period="morning", start_time="09:00", place_id="node/1", place_name="Topkapi Museum", place_type="attraction", estimated_cost_usd=25, notes="museum"),
        TimeBlock(period="afternoon", start_time="13:00", place_id="node/2", place_name="Hagia Sophia", place_type="attraction", estimated_cost_usd=20),
    ])])
    rec = EditRecord(timestamp=datetime.now(timezone.utc).isoformat(), intent=EditIntent(action="remove", target="museums", detail=None, raw_text="r"))
    out = asyncio.run(patch_plan(TripState(session_id="t", city="Istanbul", days=1, budget_usd=200, plan=plan, edit_history=[rec])))
    names = [b.place_name for d in out["plan"].days for b in d.blocks]
    assert "Topkapi Museum" not in names
    print(f"patch_plan remove: PASS ({names})")

    # patch constrain
    plan2 = Plan(city="Istanbul", days=[DayPlan(day_number=1, blocks=[
        TimeBlock(period="morning", start_time="09:00", place_id="a", place_name="Cheap", place_type="attraction", estimated_cost_usd=10),
        TimeBlock(period="afternoon", start_time="13:00", place_id="b", place_name="Mid", place_type="attraction", estimated_cost_usd=20),
        TimeBlock(period="evening", start_time="19:00", place_id="c", place_name="Pricey", place_type="attraction", estimated_cost_usd=40),
    ])])
    rec2 = EditRecord(timestamp="2026-05-18T20:00:00Z", intent=EditIntent(action="constrain", target="max $40 per day", detail=None, raw_text="r"))
    out2 = asyncio.run(patch_plan(TripState(session_id="t", city="Istanbul", days=1, budget_usd=200, plan=plan2, edit_history=[rec2])))
    names2 = [b.place_name for d in out2["plan"].days for b in d.blocks]
    assert "Pricey" not in names2
    print(f"patch_plan constrain: PASS ({names2})")

    # source URL
    assert Place(osm_id="node/12345", name="X", category="museum", lat=1.0, lon=2.0).source_url == "https://www.openstreetmap.org/node/12345"
    assert Restaurant(osm_id="way/67890", name="Y", lat=1.0, lon=2.0).source_url == "https://www.openstreetmap.org/way/67890"
    print("source_url: PASS")

    # chunking
    chunks = chunk_wikivoyage_text("== See ==\nA museum.\n\n== Eat ==\nKebab.\n\n== Do ==\nWalk.")
    sections = {c.section for c in chunks}
    assert "see" in sections and "eat" in sections and "do" in sections
    print("chunking: PASS")

    # PDF
    try:
        from src.export.pdf import markdown_to_pdf_bytes
        pdf = markdown_to_pdf_bytes("# Test\n\nHello **world**")
        assert pdf.startswith(b"%PDF") and len(pdf) > 500
        print(f"pdf: PASS ({len(pdf)} bytes)")
    except OSError as e:
        print(f"pdf: SKIP (native libs missing)")

    print("\nALL OFFLINE TESTS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
