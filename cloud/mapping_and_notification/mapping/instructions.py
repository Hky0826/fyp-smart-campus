from __future__ import annotations

import math
from typing import Any

from .pathfinding import GraphEdge, GraphNode


def _points(edge: GraphEdge, start: GraphNode, end: GraphNode) -> list[tuple[float, float]]:
    points = edge.custom_path
    if isinstance(points, list) and len(points) >= 2:
        parsed = [(float(p["x"]), float(p["y"])) for p in points if isinstance(p, dict) and "x" in p and "y" in p]
        if len(parsed) >= 2:
            if edge.source != start.node_id:
                parsed.reverse()
            return parsed
    return [(start.x, start.y), (end.x, end.y)]


def turn_direction(in_vec: tuple[float, float], out_vec: tuple[float, float]) -> str:
    mag1, mag2 = math.hypot(*in_vec), math.hypot(*out_vec)
    if mag1 < 0.001 or mag2 < 0.001:
        return "straight"
    a = (in_vec[0] / mag1, in_vec[1] / mag1)
    b = (out_vec[0] / mag2, out_vec[1] / mag2)
    cross, dot = a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]
    if math.atan2(abs(cross), dot) < math.pi / 9:
        return "straight"
    return "right" if cross > 0 else "left"


def build_instructions(nodes: tuple[GraphNode, ...] | list[GraphNode], edges: tuple[GraphEdge, ...] | list[GraphEdge]) -> list[dict[str, Any]]:
    """Return stable, speakable steps while retaining node/edge identity."""
    if len(nodes) < 2:
        return []
    result: list[dict[str, Any]] = [{"step": 1, "action": "start", "instruction": f"Start at {nodes[0].label or 'your current location'}.", "node_id": nodes[0].node_id}]
    merged: dict[str, Any] | None = None
    for index, edge in enumerate(edges):
        start, end = nodes[index], nodes[index + 1]
        if start.floorplan_id != end.floorplan_id:
            if merged:
                result.append(merged); merged = None
            action = ("take the " + end.node_type.lower()) if end.node_type in {"ELEVATOR", "STAIRWELL", "ENTRANCE"} else "continue"
            result.append({"step": len(result) + 1, "action": "transition", "instruction": f"{action.capitalize()} to floor {end.floorplan_id}.", "from_node_id": start.node_id, "to_node_id": end.node_id, "edge_id": edge.edge_id})
            continue
        pts = _points(edge, start, end)
        direction = "straight"
        if index and index - 1 < len(edges):
            previous_points = _points(edges[index - 1], nodes[index - 1], start)
            direction = turn_direction((previous_points[-1][0] - previous_points[-2][0], previous_points[-1][1] - previous_points[-2][1]), (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
        text = f"Walk {direction} to {end.label}." if end.label and end.node_type != "CORRIDOR" else f"Walk {direction}."
        if direction == "straight" and merged:
            merged["instruction"] = merged["instruction"].rstrip(".") + "; then continue straight."
            merged["to_node_id"] = end.node_id
            merged["edge_ids"].append(edge.edge_id)
        else:
            if merged:
                result.append(merged)
            merged = {"step": len(result) + 1, "action": direction, "instruction": text, "from_node_id": start.node_id, "to_node_id": end.node_id, "edge_ids": [edge.edge_id]}
    if merged:
        result.append(merged)
    result.append({"step": len(result) + 1, "action": "arrive", "instruction": f"You have arrived at {nodes[-1].label or 'your destination'}.", "node_id": nodes[-1].node_id})
    return result
