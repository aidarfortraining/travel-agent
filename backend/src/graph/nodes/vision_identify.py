"""Node 3: vision_identify — OpenAI mini vision on uploaded photo."""
from __future__ import annotations

import json
import logging

from src.graph.state import TripState
from src.llm.client import ainvoke_text
from src.llm.prompts import VISION_IDENTIFY_SYSTEM
from src.schemas import PhotoAnalysis

log = logging.getLogger(__name__)


async def vision_identify(state: TripState) -> dict:
    if not state.photo_b64:
        return {"last_node": "vision_identify"}
    response = await ainvoke_text(
        system=VISION_IDENTIFY_SYSTEM,
        user=f"User said they want to travel to: {state.city}. Identify this place.",
        temperature=0.1,
        max_tokens=512,
        images=[{"mime_type": state.photo_mime or "image/jpeg", "data": state.photo_b64}],
    )
    if not response:
        return {"last_node": "vision_identify"}
    try:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        data = json.loads(cleaned)
        analysis = PhotoAnalysis(
            landmark=str(data.get("landmark", "")),
            city=str(data.get("city", state.city)),
            place_type=str(data.get("place_type", "attraction")),
            description=str(data.get("description", "")),
            confidence=float(data.get("confidence", 0.5)),
        )
        return {"last_node": "vision_identify", "photo_analysis": analysis}
    except Exception as exc:
        log.warning("vision_identify parsing failed: %s | raw=%s", exc, response[:200])
        return {"last_node": "vision_identify"}
