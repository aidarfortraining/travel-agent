"""Photo analysis schema — output of vision_identify node."""
from __future__ import annotations

from pydantic import BaseModel


class PhotoAnalysis(BaseModel):
    landmark: str
    city: str
    place_type: str = "attraction"
    description: str = ""
    confidence: float = 0.5
