"""Application configuration via pydantic-settings.

All env vars read here. No env access elsewhere — import `settings` from this module.

Note: this module is imported very early. It loads .env via python-dotenv and pushes
LangSmith env vars to os.environ BEFORE any langchain/langgraph import — otherwise
LangChain's autotrace callbacks miss them.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Eagerly populate os.environ from .env so subsequent imports see the values.
load_dotenv(override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM (OpenAI)
    openai_api_key: str = Field(default="")
    openai_base_url: str = ""  # optional override for Azure / proxies
    openai_model: str = "gpt-4.1-mini"
    openai_model_b: str = "gpt-4o-mini"  # secondary mini for A/B experiment
    openai_embedding_model: str = "text-embedding-3-small"

    # LangSmith
    langsmith_tracing: bool = True
    langsmith_api_key: str = ""
    langsmith_project: str = "trip-planner"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "trip_planner_v1"

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    session_store_path: Path = Path("./sessions")
    checkpoint_db_path: Path = Path("./checkpoints/graph.sqlite")

    # Eval mode bypasses HITL interrupts (interrupt() in nodes 8 and 12)
    eval_mode: bool = False

    # Repo layout — used by MCP client subprocess paths
    repo_root: Path = Path(__file__).resolve().parents[2]

    @property
    def mcp_servers_root(self) -> Path:
        return self.repo_root / "mcp_servers"

    @property
    def skill_root(self) -> Path:
        return self.repo_root / "skill"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


# Push LangSmith env vars so LangChain auto-tracing picks them up at import time.
if settings.langsmith_tracing and settings.langsmith_api_key:
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)


# OpenAI SDK reads OPENAI_BASE_URL from os.environ if not passed explicitly.
# An empty string ("") is NOT falsy for the SDK — it gets used as the URL and breaks
# with `httpx.UnsupportedProtocol`. Clear it so the SDK falls back to the default API host.
if not settings.openai_base_url and "OPENAI_BASE_URL" in os.environ and not os.environ["OPENAI_BASE_URL"]:
    del os.environ["OPENAI_BASE_URL"]
