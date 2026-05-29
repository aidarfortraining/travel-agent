"""Session endpoints: create, submit form input, edit, accept."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.runner import (
    get_snapshot_state,
    resume_run,
    start_run,
)
from src.api.session_store import create_session, get_session
from src.graph.state import TripState

router = APIRouter(prefix="/sessions", tags=["sessions"])
log = logging.getLogger(__name__)


class CreateSessionResponse(BaseModel):
    session_id: str


@router.post("", response_model=CreateSessionResponse)
async def create() -> CreateSessionResponse:
    s = await create_session()
    return CreateSessionResponse(session_id=s.session_id)


class TripInput(BaseModel):
    city: str
    days: int = Field(ge=1, le=14)
    budget_usd: float = Field(ge=0)
    interests: list[str] = []
    dietary: list[Literal["halal", "vegan", "vegetarian", "gluten-free", "kosher"]] = []


class SubmitResponse(BaseModel):
    session_id: str
    started: bool


@router.post("/{session_id}/input", response_model=SubmitResponse)
async def submit_input(session_id: str, payload: TripInput) -> SubmitResponse:
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    state = TripState(
        session_id=session_id,
        city=payload.city,
        days=payload.days,
        budget_usd=payload.budget_usd,
        interests=payload.interests,
        dietary=payload.dietary,
        photo_b64=(s.state.photo_b64 if s.state else None),
        photo_mime=(s.state.photo_mime if s.state else "image/jpeg"),
    )
    await start_run(s, state)
    return SubmitResponse(session_id=session_id, started=True)


class EditRequest(BaseModel):
    text: str


@router.post("/{session_id}/edit", response_model=SubmitResponse)
async def submit_edit(session_id: str, payload: EditRequest) -> SubmitResponse:
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not s.awaiting_input or s.awaiting_input.get("type") != "review_plan":
        raise HTTPException(status_code=409, detail="graph is not awaiting an edit")
    await resume_run(s, {"accept": False, "edit": payload.text})
    return SubmitResponse(session_id=session_id, started=True)


@router.post("/{session_id}/accept", response_model=SubmitResponse)
async def accept(session_id: str) -> SubmitResponse:
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not s.awaiting_input or s.awaiting_input.get("type") != "review_plan":
        raise HTTPException(status_code=409, detail="graph is not awaiting a review decision")
    await resume_run(s, {"accept": True})
    return SubmitResponse(session_id=session_id, started=True)


class BudgetAdjustRequest(BaseModel):
    accept_reduced: bool = True
    new_budget_usd: float | None = None


@router.post("/{session_id}/adjust-budget", response_model=SubmitResponse)
async def adjust_budget(session_id: str, payload: BudgetAdjustRequest) -> SubmitResponse:
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not s.awaiting_input or s.awaiting_input.get("type") != "budget_explain":
        raise HTTPException(status_code=409, detail="graph is not in budget review")
    await resume_run(s, payload.model_dump())
    return SubmitResponse(session_id=session_id, started=True)


@router.get("/{session_id}/state")
async def session_state(session_id: str) -> dict:
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    snap = await get_snapshot_state(s)
    if snap:
        s.state = snap
        if snap.plan_markdown:
            s.plan_markdown = snap.plan_markdown
    return {
        "session_id": session_id,
        "status": s.state.status if s.state else "draft",
        "plan_markdown": s.plan_markdown,
        "awaiting_input": s.awaiting_input,
        "city": s.state.city if s.state else "",
        "days": s.state.days if s.state else 0,
        "budget_usd": s.state.budget_usd if s.state else 0,
        "interests": s.state.interests if s.state else [],
        "dietary": s.state.dietary if s.state else [],
    }
