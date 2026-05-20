"""Photo upload endpoint — stores base64 on session, vision_identify will pick it up."""
from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.api.session_store import get_session
from src.graph.state import TripState

router = APIRouter(prefix="/sessions", tags=["photo"])
log = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024


@router.post("/{session_id}/photo")
async def upload_photo(session_id: str, file: UploadFile = File(...)) -> dict:
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large (>{MAX_BYTES // 1024}KB)")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="must be an image")
    b64 = base64.b64encode(data).decode("ascii")
    if s.state is None:
        s.state = TripState(session_id=session_id, photo_b64=b64, photo_mime=file.content_type or "image/jpeg")
    else:
        s.state = s.state.model_copy(update={
            "photo_b64": b64,
            "photo_mime": file.content_type or "image/jpeg",
        })
    return {"ok": True, "bytes": len(data), "mime": file.content_type}
