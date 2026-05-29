"""Unit tests for patch_plan edit application.

The LLM rerender and MCP cost recompute are monkeypatched out so these tests stay
offline and deterministic — they assert the *structural* edit, not the rich markdown
(the rich rerender is covered by the live e2e run).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest


async def _fake_rerender(plan, state, note):
    return "RERENDERED"


async def _fake_cost(plan, prev):
    return prev


@pytest.fixture(autouse=True)
def _stub_llm_and_mcp(monkeypatch):
    monkeypatch.setattr("src.graph.nodes.patch_plan._rich_rerender", _fake_rerender)
    monkeypatch.setattr("src.graph.nodes.patch_plan._recompute_cost", _fake_cost)


def _state_with_plan():
    from src.graph.state import TripState
    from src.schemas import DayPlan, EditIntent, EditRecord, Plan, TimeBlock

    plan = Plan(
        city="Istanbul",
        days=[
            DayPlan(
                day_number=1,
                blocks=[
                    TimeBlock(
                        period="morning", start_time="09:00",
                        place_id="node/1", place_name="Topkapi Museum",
                        place_type="attraction", estimated_cost_usd=25.0,
                        notes="museum",
                    ),
                    TimeBlock(
                        period="afternoon", start_time="13:00",
                        place_id="node/2", place_name="Hagia Sophia",
                        place_type="attraction", estimated_cost_usd=20.0,
                    ),
                ],
            )
        ],
    )
    intent = EditIntent(action="remove", target="museums", detail=None, raw_text="убери музеи")
    record = EditRecord(timestamp=datetime.now(timezone.utc).isoformat(), intent=intent)
    return TripState(
        session_id="t",
        city="Istanbul",
        days=1,
        budget_usd=200,
        plan=plan,
        plan_markdown="# rich plan",
        edit_history=[record],
    )


def test_patch_plan_removes_museums():
    from src.graph.nodes.patch_plan import patch_plan

    state = _state_with_plan()
    out = asyncio.run(patch_plan(state))
    new_plan = out["plan"]
    names = [b.place_name for d in new_plan.days for b in d.blocks]
    assert "Topkapi Museum" not in names
    assert out["edit_history"][-1].applied is True
    # a successful edit triggers the rich LLM rerender, not the bare render
    assert out["plan_markdown"] == "RERENDERED"


def test_patch_plan_constrain_drops_expensive_blocks():
    from src.graph.nodes.patch_plan import patch_plan
    from src.graph.state import TripState
    from src.schemas import DayPlan, EditIntent, EditRecord, Plan, TimeBlock

    plan = Plan(city="Istanbul", days=[DayPlan(day_number=1, blocks=[
        TimeBlock(period="morning", start_time="09:00", place_id="a", place_name="Cheap", place_type="attraction", estimated_cost_usd=10),
        TimeBlock(period="afternoon", start_time="13:00", place_id="b", place_name="Mid", place_type="attraction", estimated_cost_usd=20),
        TimeBlock(period="evening", start_time="19:00", place_id="c", place_name="Pricey", place_type="attraction", estimated_cost_usd=40),
    ])])
    intent = EditIntent(action="constrain", target="максимум $40 в день", detail=None, raw_text="$40 max per day")
    record = EditRecord(timestamp="2026-05-18T20:00:00Z", intent=intent)
    state = TripState(session_id="t", city="Istanbul", days=1, budget_usd=200, plan=plan, edit_history=[record])
    out = asyncio.run(patch_plan(state))
    names = [b.place_name for d in out["plan"].days for b in d.blocks]
    assert "Pricey" not in names


def test_patch_plan_add_inserts_candidate():
    from src.graph.nodes.patch_plan import patch_plan
    from src.graph.state import TripState
    from src.schemas import DayPlan, EditIntent, EditRecord, Place, Plan, TimeBlock

    plan = Plan(city="Istanbul", days=[DayPlan(day_number=1, blocks=[
        TimeBlock(period="morning", start_time="09:00", place_id="node/1", place_name="Hagia Sophia", place_type="attraction", estimated_cost_usd=20),
    ])])
    park = Place(osm_id="node/99", name="Gülhane Park", category="park", lat=41.0, lon=28.9, estimated_cost_usd=0.0)
    intent = EditIntent(action="add", target="парк", detail=None, raw_text="добавь парк")
    record = EditRecord(timestamp="2026-05-18T20:00:00Z", intent=intent)
    state = TripState(
        session_id="t", city="Istanbul", days=1, budget_usd=200,
        plan=plan, plan_markdown="# rich plan", candidate_places=[park], edit_history=[record],
    )
    out = asyncio.run(patch_plan(state))
    names = [b.place_name for d in out["plan"].days for b in d.blocks]
    assert "Gülhane Park" in names
    assert out["edit_history"][-1].applied is True


def test_patch_plan_replace_adds_detail_not_target():
    """`вместо музея парк` must remove the museum and add a PARK, not another museum."""
    from src.graph.nodes.patch_plan import patch_plan
    from src.graph.state import TripState
    from src.schemas import DayPlan, EditIntent, EditRecord, Place, Plan, TimeBlock

    plan = Plan(city="Istanbul", days=[DayPlan(day_number=1, blocks=[
        TimeBlock(period="morning", start_time="09:00", place_id="node/1", place_name="Some Museum", place_type="attraction", estimated_cost_usd=15, notes="museum"),
    ])])
    park = Place(osm_id="node/77", name="Gülhane Park", category="park", lat=41.0, lon=28.9, estimated_cost_usd=0.0)
    intent = EditIntent(action="replace", target="музей", detail="парк", raw_text="вместо музея парк")
    record = EditRecord(timestamp="2026-05-18T20:00:00Z", intent=intent)
    state = TripState(
        session_id="t", city="Istanbul", days=1, budget_usd=200,
        plan=plan, plan_markdown="# rich plan", candidate_places=[park], edit_history=[record],
    )
    out = asyncio.run(patch_plan(state))
    names = [b.place_name for d in out["plan"].days for b in d.blocks]
    cats = [b.notes for d in out["plan"].days for b in d.blocks]
    assert "Some Museum" not in names
    assert "Gülhane Park" in names
    assert "museum" not in cats  # did NOT re-add a museum


def test_patch_plan_noop_keeps_markdown_with_notice():
    from src.graph.nodes.patch_plan import patch_plan
    from src.graph.state import TripState
    from src.schemas import DayPlan, EditIntent, EditRecord, Plan, TimeBlock

    plan = Plan(city="Istanbul", days=[DayPlan(day_number=1, blocks=[
        TimeBlock(period="morning", start_time="09:00", place_id="node/1", place_name="Hagia Sophia", place_type="attraction", estimated_cost_usd=20, notes="religious"),
    ])])
    # remove "музеи" but there are no museums -> changed == 0
    intent = EditIntent(action="remove", target="музеи", detail=None, raw_text="убери музеи")
    record = EditRecord(timestamp="2026-05-18T20:00:00Z", intent=intent)
    state = TripState(
        session_id="t", city="Istanbul", days=1, budget_usd=200,
        plan=plan, plan_markdown="# rich plan\n\nbody", edit_history=[record],
    )
    out = asyncio.run(patch_plan(state))
    md = out["plan_markdown"]
    assert md.startswith("> _Правка")
    assert "# rich plan" in md  # original content preserved
    names = [b.place_name for d in out["plan"].days for b in d.blocks]
    assert names == ["Hagia Sophia"]  # nothing removed
