"""Edit intent schemas — output of parse_edit_intent node."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EditIntent(BaseModel):
    action: Literal["remove", "add", "replace", "constrain"]
    target: str
    detail: str | None = None
    raw_text: str = ""


class EditRecord(BaseModel):
    timestamp: str
    intent: EditIntent
    applied: bool = False
    notes: str = ""
