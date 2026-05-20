"""Unit tests for patch_plan edit application."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone


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
