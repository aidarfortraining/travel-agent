"""Shared error envelope for tools / external calls."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ToolErrorResponse(BaseModel):
    is_error: bool = True
    error_code: Literal[
        "EXTERNAL_API_ERROR",
        "INVALID_INPUT",
        "NOT_FOUND",
        "TIMEOUT",
        "RATE_LIMIT",
    ]
    message: str
    retryable: bool = False
