"""Node 15: finalize_and_export — mark final, ready for PDF export."""
from __future__ import annotations

import logging

from src.graph.state import TripState

log = logging.getLogger(__name__)


async def finalize_and_export(state: TripState) -> dict:
    if not state.plan_markdown:
        return {"last_node": "finalize_and_export", "status": "finalized", "error": "no plan to export"}
    return {"last_node": "finalize_and_export", "status": "finalized"}
