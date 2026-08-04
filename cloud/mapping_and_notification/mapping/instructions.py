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
    """Return stable, speakable steps matching original engine format while retaining node/edge identity."""
    if len(nodes) < 2:
        return []

    start_label = nodes[0].label or f"Node {nodes[0].node_id}"
    result: list[dict[str, Any]] = [{
        "step": 1,
        "type": "start",
        "action": "depart",
        "instruction": f"Start at {start_label}.",
        "description": f"Start at {start_label}.",
        "node_id": nodes[0].node_id
    }]

    merged: dict[str, Any] | None = None
    for index, edge in enumerate(edges):
        start, end = nodes[index], nodes[index + 1]
        if start.floorplan_id != end.floorplan_id:
            if merged:
                result.append(merged)
                merged = None

            trans_type = "elevator" if end.node_type == "ELEVATOR" else ("stairwell" if end.node_type == "STAIRWELL" else "entrance")
            verb = "Take the elevator" if trans_type == "elevator" else ("Take the stairwell" if trans_type == "stairwell" else "Take the entrance")
            target_floor = getattr(end, "floor", None) or end.floorplan_id
            trans_text = f"{verb} to floor {target_floor}."

            result.append({
                "step": len(result) + 1,
                "type": "transition",
                "action": trans_type,
                "instruction": trans_text,
                "description": trans_text,
                "from_node_id": start.node_id,
                "to_node_id": end.node_id,
                "edge_id": edge.edge_id
            })
            continue

        pts = _points(edge, start, end)
        direction = "straight"
        if index and index - 1 < len(edges):
            previous_points = _points(edges[index - 1], nodes[index - 1], start)
            direction = turn_direction(
                (previous_points[-1][0] - previous_points[-2][0], previous_points[-1][1] - previous_points[-2][1]),
                (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            )

        has_landmark = bool(end.label and end.node_type != "CORRIDOR")
        landmark_text = f" at {end.label}" if has_landmark else ""
        landmark_to = f" to {end.label}" if has_landmark else ""

        if direction in {"left", "right"}:
            if merged:
                result.append(merged)
                merged = None
            turn_text = f"Turn {direction}{landmark_text}."
            result.append({
                "step": len(result) + 1,
                "type": "turn",
                "action": direction,
                "direction": direction,
                "instruction": turn_text,
                "description": turn_text,
                "from_node_id": start.node_id,
                "to_node_id": end.node_id,
                "edge_ids": [edge.edge_id],
                "distance_m": round(edge.distance, 1)
            })
        else:
            if merged:
                merged["instruction"] = f"Walk straight{landmark_to}."
                merged["description"] = merged["instruction"]
                merged["to_node_id"] = end.node_id
                merged["edge_ids"].append(edge.edge_id)
                merged["distance_m"] = round(merged.get("distance_m", 0) + edge.distance, 1)
            else:
                walk_text = f"Walk straight{landmark_to}."
                merged = {
                    "step": len(result) + 1,
                    "type": "walk",
                    "action": "straight",
                    "instruction": walk_text,
                    "description": walk_text,
                    "from_node_id": start.node_id,
                    "to_node_id": end.node_id,
                    "edge_ids": [edge.edge_id],
                    "distance_m": round(edge.distance, 1)
                }

    if merged:
        result.append(merged)

    dest_label = nodes[-1].label or f"Node {nodes[-1].node_id}"
    result.append({
        "step": len(result) + 1,
        "type": "arrive",
        "action": "arrive",
        "instruction": f"You have arrived at {dest_label}.",
        "description": f"You have arrived at {dest_label}.",
        "node_id": nodes[-1].node_id
    })
    return result
