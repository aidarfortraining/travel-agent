"""Helpers to run / resume the LangGraph and stream events into a session queue."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.types import Command

from src.api.session_store import Session, configurable
from src.graph.builder import build_graph
from src.graph.state import TripState

log = logging.getLogger(__name__)


def _drain_event_queue(session: Session) -> None:
    """Clear leftover events from a previous run so the next SSE client sees only fresh updates."""
    while not session.events.empty():
        try:
            session.events.get_nowait()
        except asyncio.QueueEmpty:
            break


def _interrupt_payload(update: Any) -> dict:
    """Extract dict payload from a `__interrupt__` update emitted by graph.astream."""
    interrupts = list(update) if isinstance(update, (tuple, list)) else [update]
    if not interrupts:
        return {}
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"raw": value}


async def _refresh_state_from_snapshot(session: Session, cfg: dict) -> TripState | None:
    graph = await build_graph()
    snap = await graph.aget_state(cfg)
    if not snap or not snap.values:
        return None
    state = TripState.model_validate(snap.values)
    session.state = state
    if state.plan_markdown:
        session.plan_markdown = state.plan_markdown
    return state


async def _drain_run(session: Session, initial: TripState | None, command: Command | None) -> None:
    graph = await build_graph()
    cfg = configurable(session.session_id)
    if command is not None:
        stream = graph.astream(command, config=cfg, stream_mode="updates")
    elif initial is not None:
        stream = graph.astream(initial, config=cfg, stream_mode="updates")
    else:
        await session.emit({"type": "error", "message": "no initial state and no resume command"})
        return

    interrupted = False
    try:
        # Don't `return` out of the loop on interrupt — that abandons the astream
        # generator mid-`yield`, so Python closes it at GC and the resulting
        # GeneratorExit surfaces on the LangSmith run. LangGraph's astream ends on
        # its own right after yielding `__interrupt__`, so we just flag it and let
        # the loop finish naturally.
        async for event in stream:
            for node_name, update in event.items():
                if node_name == "__interrupt__":
                    payload = _interrupt_payload(update)
                    session.awaiting_input = payload
                    await _refresh_state_from_snapshot(session, cfg)
                    await session.emit({"type": "interrupt", "payload": payload})
                    interrupted = True
                    continue
                update_keys = list((update or {}).keys()) if isinstance(update, dict) else []
                await session.emit({"type": "node", "node": node_name, "update_keys": update_keys})

        if not interrupted:
            last_state = await _refresh_state_from_snapshot(session, cfg)
            session.awaiting_input = None
            await session.emit({"type": "done", "status": (last_state.status if last_state else "finalized")})
    except Exception as exc:
        log.exception("graph run failed")
        await session.emit({"type": "error", "message": str(exc)})
    finally:
        # Explicitly close the generator so cleanup runs in-context (covers task
        # cancellation, e.g. the SSE client disconnecting mid-run). No-op if the
        # stream already finished.
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                log.debug("stream.aclose() during cleanup", exc_info=True)


async def start_run(session: Session, initial: TripState) -> None:
    _drain_event_queue(session)
    session.state = initial
    session.awaiting_input = None
    session.task = asyncio.create_task(_drain_run(session, initial=initial, command=None))


async def resume_run(session: Session, resume_value: Any) -> None:
    _drain_event_queue(session)
    session.awaiting_input = None
    session.task = asyncio.create_task(_drain_run(session, initial=None, command=Command(resume=resume_value)))


async def get_snapshot_state(session: Session) -> TripState | None:
    """Fetch current persisted state from the checkpointer."""
    graph = await build_graph()
    snap = await graph.aget_state(configurable(session.session_id))
    if not snap or not snap.values:
        return None
    return TripState.model_validate(snap.values)
