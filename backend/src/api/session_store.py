"""In-memory session registry. State persistence handled by LangGraph SqliteSaver checkpointer.

This store only tracks: SSE event broadcasters, last known state, latest PDF bytes.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from src.graph.state import TripState

log = logging.getLogger(__name__)


@dataclass
class Session:
    session_id: str
    created_at: float = field(default_factory=time.time)
    state: TripState | None = None
    events: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1024))
    pdf_bytes: bytes | None = None
    plan_markdown: str | None = None
    task: asyncio.Task | None = None
    awaiting_input: dict | None = None  # payload of last interrupt() if graph is paused

    async def emit(self, event: dict) -> None:
        # put_nowait so a stalled / disconnected SSE consumer can never block the graph
        # task. await put() would wait forever on a full queue and never raise QueueFull.
        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("event queue full for session %s, dropping event", self.session_id)


_sessions: dict[str, Session] = {}
_lock = asyncio.Lock()


async def create_session() -> Session:
    sid = uuid.uuid4().hex
    s = Session(session_id=sid)
    async with _lock:
        _sessions[sid] = s
    return s


def get_session(session_id: str) -> Session | None:
    return _sessions.get(session_id)


def configurable(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
