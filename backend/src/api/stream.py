"""SSE endpoint streaming graph events to the React frontend."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.api.session_store import get_session

router = APIRouter(prefix="/sessions", tags=["stream"])
log = logging.getLogger(__name__)


@router.get("/{session_id}/stream")
async def stream(session_id: str, request: Request):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    async def generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(s.events.get(), timeout=20.0)
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}
                continue
            yield {"event": event.get("type", "message"), "data": json.dumps(event)}
            if event.get("type") in ("done", "error", "interrupt"):
                return

    # Headers ensure no proxy buffers the stream (nginx + cloud LBs sometimes do).
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return EventSourceResponse(generator(), headers=headers)
