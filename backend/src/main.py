"""FastAPI application entry."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# config import has the side effect of loading .env and setting LangSmith env vars
from src.config import settings  # noqa: F401  must precede other imports
from src.api import export, photo, sessions, stream  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.langsmith_tracing and settings.langsmith_api_key:
        log.info("LangSmith tracing enabled, project=%s", settings.langsmith_project)
    else:
        log.warning("LangSmith tracing is disabled (set LANGSMITH_API_KEY to enable)")

    settings.session_store_path.mkdir(parents=True, exist_ok=True)
    settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)

    yield


app = FastAPI(
    title="Trip Planner API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(sessions.router)
app.include_router(stream.router)
app.include_router(photo.router)
app.include_router(export.router)
