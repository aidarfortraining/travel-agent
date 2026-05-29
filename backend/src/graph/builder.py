"""LangGraph builder. Wires 14 nodes, 3 branches, 2 loops, 2 HITL interrupts."""
from __future__ import annotations

import asyncio
import logging

from langgraph.checkpoint.serde.base import maybe_add_typed_methods
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from src.config import settings
from src.graph.branches import budget_feasible, edit_or_accept, has_photo
from src.graph.nodes.budget_check import budget_check
from src.graph.nodes.candidate_places import candidate_places
from src.graph.nodes.city_research import city_research
from src.graph.nodes.cluster_by_day import cluster_by_day
from src.graph.nodes.collect_input import collect_input
from src.graph.nodes.enrich_input import enrich_input
from src.graph.nodes.explain_and_ask import explain_and_ask
from src.graph.nodes.finalize_and_export import finalize_and_export
from src.graph.nodes.generate_plan import generate_plan
from src.graph.nodes.optimize_route import optimize_route
from src.graph.nodes.parse_edit_intent import parse_edit_intent
from src.graph.nodes.patch_plan import patch_plan
from src.graph.nodes.present_plan import present_plan
from src.graph.nodes.vision_identify import vision_identify
from src.graph.state import TripState

log = logging.getLogger(__name__)


def _build_state_graph() -> StateGraph:
    g = StateGraph(TripState)

    # Nodes
    g.add_node("collect_input", collect_input)
    g.add_node("vision_identify", vision_identify)
    g.add_node("enrich_input", enrich_input)
    g.add_node("city_research", city_research)
    g.add_node("candidate_places", candidate_places)
    g.add_node("budget_check", budget_check)
    g.add_node("explain_and_ask", explain_and_ask)
    g.add_node("cluster_by_day", cluster_by_day)
    g.add_node("optimize_route", optimize_route)
    g.add_node("generate_plan", generate_plan)
    g.add_node("present_plan", present_plan)
    g.add_node("parse_edit_intent", parse_edit_intent)
    g.add_node("patch_plan", patch_plan)
    g.add_node("finalize_and_export", finalize_and_export)

    # Edges
    g.add_edge(START, "collect_input")
    g.add_conditional_edges("collect_input", has_photo,
                            {"vision_identify": "vision_identify", "city_research": "city_research"})
    g.add_edge("vision_identify", "enrich_input")
    g.add_edge("enrich_input", "city_research")
    g.add_edge("city_research", "candidate_places")
    g.add_edge("candidate_places", "budget_check")
    g.add_conditional_edges("budget_check", budget_feasible,
                            {"cluster_by_day": "cluster_by_day", "explain_and_ask": "explain_and_ask"})
    g.add_edge("explain_and_ask", "city_research")  # loop back after user adjustment
    g.add_edge("cluster_by_day", "optimize_route")
    g.add_edge("optimize_route", "generate_plan")
    g.add_edge("generate_plan", "present_plan")
    g.add_conditional_edges("present_plan", edit_or_accept,
                            {"parse_edit_intent": "parse_edit_intent",
                             "finalize_and_export": "finalize_and_export"})
    g.add_edge("parse_edit_intent", "patch_plan")
    g.add_edge("patch_plan", "present_plan")  # loop back to user review
    g.add_edge("finalize_and_export", END)

    return g


_checkpointer_singleton: AsyncSqliteSaver | None = None
_checkpointer_cm = None


def _checkpoint_serde() -> JsonPlusSerializer:
    """Serializer that explicitly allow-lists the project's pydantic models for
    msgpack checkpoint (de)serialization.

    LangGraph's default permissively allows unregistered types but logs a warning
    ("will be blocked in a future version"). Registering them is the forward-
    compatible fix. The allow-list is collected dynamically from the schemas
    package plus TripState, so any new model is covered automatically. The wire
    format is unchanged — this only governs which types are admitted on read, so
    existing checkpoints remain readable.
    """
    import src.schemas as schemas

    allowed: set[type] = {
        obj
        for obj in vars(schemas).values()
        if isinstance(obj, type) and issubclass(obj, BaseModel)
    }
    allowed.add(TripState)
    return JsonPlusSerializer(allowed_msgpack_modules=list(allowed))


async def get_checkpointer() -> AsyncSqliteSaver:
    """Open / cache a single SqliteSaver async checkpointer."""
    global _checkpointer_singleton, _checkpointer_cm
    if _checkpointer_singleton is not None:
        return _checkpointer_singleton
    settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
    _checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path))
    _checkpointer_singleton = await _checkpointer_cm.__aenter__()
    _checkpointer_singleton.serde = maybe_add_typed_methods(_checkpoint_serde())
    return _checkpointer_singleton


_graph_singleton = None
_graph_lock = asyncio.Lock()


async def build_graph():
    """Compile the graph with checkpointing. Cached as a process-singleton."""
    global _graph_singleton
    if _graph_singleton is not None:
        return _graph_singleton
    async with _graph_lock:
        if _graph_singleton is not None:
            return _graph_singleton
        cp = await get_checkpointer()
        sg = _build_state_graph()
        _graph_singleton = sg.compile(checkpointer=cp)
        log.info("LangGraph compiled (eval_mode=%s)", settings.eval_mode)
        return _graph_singleton


async def build_graph_uncached():
    """For evaluation runs that want a fresh graph (memory checkpoint)."""
    sg = _build_state_graph()
    return sg.compile()
