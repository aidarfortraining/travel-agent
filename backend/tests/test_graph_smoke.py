"""Smoke test: build the graph, ensure key modules import without error."""
from __future__ import annotations

import asyncio



def test_state_imports():
    from src.graph.state import TripState

    s = TripState(session_id="test", city="Istanbul", days=3, budget_usd=300, interests=["history"])
    assert s.city == "Istanbul"
    assert s.days == 3


def test_branches():
    from src.graph.branches import budget_feasible, edit_or_accept, has_photo
    from src.graph.state import TripState

    s = TripState(session_id="t", photo_b64="aGVsbG8=")
    assert has_photo(s) == "vision_identify"

    s2 = TripState(session_id="t")
    assert has_photo(s2) == "city_research"

    s3 = TripState(session_id="t", budget_warning="too low")
    assert budget_feasible(s3) == "explain_and_ask"

    s4 = TripState(session_id="t")
    assert budget_feasible(s4) == "cluster_by_day"

    s5 = TripState(session_id="t", accept_signal=True)
    assert edit_or_accept(s5) == "finalize_and_export"

    s6 = TripState(session_id="t", pending_edit_text="убери музеи")
    assert edit_or_accept(s6) == "parse_edit_intent"


def test_collect_input_validation():
    from src.graph.nodes.collect_input import collect_input
    from src.graph.state import TripState

    s = TripState(session_id="t", city="Istanbul", days=3, budget_usd=300)
    res = asyncio.run(collect_input(s))
    assert res["error"] is None

    bad = TripState(session_id="t", city="", days=0, budget_usd=-1)
    res = asyncio.run(collect_input(bad))
    assert res["error"] is not None


def test_cluster_by_day_assigns_all_places():
    from src.graph.nodes.cluster_by_day import cluster_by_day
    from src.graph.state import TripState
    from src.schemas import Place

    places = [
        Place(osm_id=f"node/{i}", name=f"P{i}", category="museum", lat=41.0 + i * 0.001, lon=29.0 + i * 0.001)
        for i in range(9)
    ]
    s = TripState(session_id="t", city="Istanbul", days=3, candidate_places=places)
    out = asyncio.run(cluster_by_day(s))
    da = out["day_assignment"]
    assert sorted(da.keys()) == [1, 2, 3]
    flat = [pid for ids in da.values() for pid in ids]
    assert len(flat) == 9
    assert set(flat) == {p.osm_id for p in places}


def test_optimize_route_orders_nearest_neighbor():
    from src.graph.nodes.optimize_route import optimize_route
    from src.graph.state import TripState
    from src.schemas import Place

    places = [
        Place(osm_id="node/1", name="A", category="x", lat=41.0, lon=29.0),
        Place(osm_id="node/2", name="B", category="x", lat=41.05, lon=29.05),
        Place(osm_id="node/3", name="C", category="x", lat=41.5, lon=29.5),
    ]
    s = TripState(
        session_id="t",
        candidate_places=places,
        day_assignment={1: ["node/3", "node/1", "node/2"]},
    )
    out = asyncio.run(optimize_route(s))
    ordered = out["route_per_day"][1]
    assert ordered[0] == "node/3"  # NN start = farthest extreme
    assert set(ordered) == {p.osm_id for p in places}
