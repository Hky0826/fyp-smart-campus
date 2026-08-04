"""Database-independent, RBAC-aware A* navigation.

The functions in this module intentionally accept mappings or small objects.  This
keeps route behaviour testable without a SQLAlchemy session and prevents the
frontend or an LLM from becoming an authority on access control.
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


class NavigationError(Exception):
    """Base class for route calculation failures."""


class NoRouteError(NavigationError):
    pass


@dataclass(frozen=True)
class GraphNode:
    node_id: int
    floorplan_id: int
    x: float
    y: float
    label: str = ""
    node_type: str = "OTHER"
    accessible: bool = True
    allowed_roles: frozenset[str] = frozenset()
    allowed_role_ids: frozenset[int] = frozenset()
    scale_ratio: float = 1.0
    building: str | None = None
    floor: int | None = None


@dataclass(frozen=True)
class GraphEdge:
    edge_id: int
    source: int
    destination: int
    distance: float
    bidirectional: bool = True
    accessible: bool = True
    custom_path: Any = None
    allowed_roles: frozenset[str] = frozenset()
    allowed_role_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class PathResult:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    distance: float


def _value(item: Any, *names: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        for name in names:
            if name in item:
                return item[name]
    else:
        for name in names:
            if hasattr(item, name):
                return getattr(item, name)
    return default


def as_node(item: Any) -> GraphNode:
    return item if isinstance(item, GraphNode) else GraphNode(
        node_id=int(_value(item, "node_id", "id")),
        floorplan_id=int(_value(item, "floorplan_id", default=0)),
        x=float(_value(item, "coord_x", "cord_x", "x", default=0)),
        y=float(_value(item, "coord_y", "cord_y", "y", default=0)),
        label=str(_value(item, "room_label", "label", default="") or ""),
        node_type=str(_value(item, "node_type", default="OTHER") or "OTHER"),
        accessible=str(_value(item, "is_accessible", "accessible", default="ALLOW")).upper() not in {"DENY", "FALSE", "0"},
        allowed_roles=frozenset(str(r).upper() for r in (_value(item, "allowed_roles", default=()) or ())),
        scale_ratio=float(_value(item, "scale_ratio", default=1.0) or 1.0),
    )


def as_edge(item: Any) -> GraphEdge:
    custom = _value(item, "custom_path", default=None)
    if isinstance(custom, str):
        try:
            custom = json.loads(custom)
        except (TypeError, ValueError):
            custom = None
    return item if isinstance(item, GraphEdge) else GraphEdge(
        edge_id=int(_value(item, "edge_id", "id")),
        source=int(_value(item, "source_node_id", "source", "from_node_id")),
        destination=int(_value(item, "destination_node_id", "destination", "to_node_id")),
        distance=max(0.0, float(_value(item, "weight_distance", "distance", default=0) or 0)),
        bidirectional=bool(_value(item, "is_bidirectional", "bidirectional", default=True)),
        accessible=str(_value(item, "is_accessible", "accessible", default="ALLOW")).upper() not in {"DENY", "FALSE", "0"},
        custom_path=custom,
        allowed_roles=frozenset(str(r).upper() for r in (_value(item, "allowed_roles", default=()) or ())),
    )


def _permitted(allowed: frozenset[str], roles: frozenset[str]) -> bool:
    return not allowed or bool(allowed & roles) or bool({"SUPER_ADMIN", "SYSTEM_ADMIN"} & roles)


def _heuristic(a: GraphNode, b: GraphNode) -> float:
    if a.floorplan_id != b.floorplan_id:
        return 0.0
    return math.hypot(a.x - b.x, a.y - b.y) * (a.scale_ratio or 1.0)


def find_path(
    nodes: Iterable[Any],
    edges: Iterable[Any],
    start_id: int,
    destination_id: int,
    *,
    roles: Iterable[str] = (),
    allow_inaccessible: bool = False,
    transition_penalty: float = 30.0,
) -> PathResult:
    """Find the lowest-cost permitted route using A* (Dijkstra cross-floor)."""
    node_map = {n.node_id: n for n in (as_node(n) for n in nodes)}
    if start_id not in node_map or destination_id not in node_map:
        raise NoRouteError("The requested start or destination node does not exist")
    role_set = frozenset(str(r).upper() for r in roles)
    permitted_nodes = {nid for nid, node in node_map.items() if (allow_inaccessible or node.accessible) and _permitted(node.allowed_roles, role_set)}
    if start_id not in permitted_nodes or destination_id not in permitted_nodes:
        raise NoRouteError("The requested node is not available for this role")

    adjacency: dict[int, list[tuple[int, GraphEdge]]] = {nid: [] for nid in node_map}
    for edge in (as_edge(e) for e in edges):
        if edge.source not in node_map or edge.destination not in node_map:
            continue
        if not allow_inaccessible and not edge.accessible:
            continue
        if not _permitted(edge.allowed_roles, role_set):
            continue
        if edge.source in permitted_nodes and edge.destination in permitted_nodes:
            adjacency[edge.source].append((edge.destination, edge))
            if edge.bidirectional:
                adjacency[edge.destination].append((edge.source, edge))

    queue: list[tuple[float, float, int]] = [(0.0, 0.0, start_id)]
    cost = {start_id: 0.0}
    previous: dict[int, tuple[int, GraphEdge]] = {}
    while queue:
        _, current_cost, current = heapq.heappop(queue)
        if current_cost > cost.get(current, math.inf):
            continue
        if current == destination_id:
            break
        for neighbour, edge in adjacency.get(current, ()):
            cross_floor = node_map[current].floorplan_id != node_map[neighbour].floorplan_id
            candidate = current_cost + edge.distance + (transition_penalty if cross_floor else 0.0)
            if candidate < cost.get(neighbour, math.inf):
                cost[neighbour] = candidate
                previous[neighbour] = (current, edge)
                priority = candidate + _heuristic(node_map[neighbour], node_map[destination_id])
                heapq.heappush(queue, (priority, candidate, neighbour))

    if destination_id not in cost:
        raise NoRouteError("No accessible route exists between the requested nodes")
    ids = [destination_id]
    traversed: list[GraphEdge] = []
    current = destination_id
    while current != start_id:
        parent, edge = previous[current]
        ids.append(parent)
        traversed.append(edge)
        current = parent
    ids.reverse()
    traversed.reverse()
    return PathResult(tuple(node_map[i] for i in ids), tuple(traversed), cost[destination_id])


# Explicit alias used by callers and by parity tests.
astar = find_path
