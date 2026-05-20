"""Node 13: parse_edit_intent — OpenAI mini structured output."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.graph.state import TripState
from src.llm.client import ainvoke_structured
from src.llm.prompts import EDIT_INTENT_SYSTEM
from src.schemas import EditIntent, EditRecord

log = logging.getLogger(__name__)


async def parse_edit_intent(state: TripState) -> dict:
    text = state.pending_edit_text or ""
    if not text.strip():
        return {"last_node": "parse_edit_intent"}
    intent = await ainvoke_structured(
        system=EDIT_INTENT_SYSTEM,
        user=text,
        schema=EditIntent,
        temperature=0.1,
        max_tokens=512,
    )
    if intent is None:
        intent = EditIntent(action="constrain", target=text[:60], detail=None, raw_text=text)
    if not intent.raw_text:
        intent.raw_text = text
    record = EditRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        intent=intent,
        applied=False,
        notes="parsed",
    )
    history = list(state.edit_history) + [record]
    return {
        "last_node": "parse_edit_intent",
        "edit_history": history,
    }
