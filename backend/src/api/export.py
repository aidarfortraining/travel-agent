"""PDF export endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response

from src.api.runner import get_snapshot_state
from src.api.session_store import get_session
from src.export.pdf import markdown_to_pdf_bytes

router = APIRouter(prefix="/sessions", tags=["export"])
log = logging.getLogger(__name__)


@router.get("/{session_id}/pdf")
async def download_pdf(session_id: str) -> Response:
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    snap = await get_snapshot_state(s)
    md = (snap.plan_markdown if snap else None) or s.plan_markdown
    if not md:
        raise HTTPException(status_code=409, detail="plan not ready")
    if s.pdf_bytes is None or s.plan_markdown != md:
        s.pdf_bytes = markdown_to_pdf_bytes(md)
        s.plan_markdown = md
    headers = {"Content-Disposition": f'attachment; filename="trip-{session_id[:8]}.pdf"'}
    return Response(content=s.pdf_bytes, media_type="application/pdf", headers=headers)
