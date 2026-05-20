"""Node 9: cluster_by_day — KMeans on lat/lon to assign places to days."""
from __future__ import annotations

import logging

import numpy as np
from sklearn.cluster import KMeans

from src.graph.state import TripState

log = logging.getLogger(__name__)


def _select_places(state: TripState) -> list:
    needed = state.days * 3
    if len(state.candidate_places) <= needed:
        return list(state.candidate_places)
    return list(state.candidate_places[:needed])


async def cluster_by_day(state: TripState) -> dict:
    selected = _select_places(state)
    day_assignment: dict[int, list[str]] = {i + 1: [] for i in range(state.days)}
    if not selected:
        return {"last_node": "cluster_by_day", "day_assignment": day_assignment}
    if len(selected) <= state.days or state.days == 1:
        for i, p in enumerate(selected):
            day_assignment[(i % state.days) + 1].append(p.osm_id)
        return {"last_node": "cluster_by_day", "day_assignment": day_assignment}
    coords = np.array([[p.lat, p.lon] for p in selected], dtype=float)
    try:
        km = KMeans(n_clusters=state.days, n_init=4, random_state=0)
        labels = km.fit_predict(coords)
    except Exception as exc:
        log.warning("KMeans failed: %s — falling back to round-robin", exc)
        labels = np.array([i % state.days for i in range(len(selected))])
    for p, lbl in zip(selected, labels):
        day_assignment[int(lbl) + 1].append(p.osm_id)
    return {"last_node": "cluster_by_day", "day_assignment": day_assignment}
