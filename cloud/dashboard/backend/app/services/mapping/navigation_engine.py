"""Native Python multi-floor / multi-building A* Navigation Engine.

Exact feature-parity port of mapping_and_notification/backend/controllers/engineController.js:
- Multi-floor and multi-building campus routing
- RBAC filtering for nodes and edges (ADMIN bypass; LECTURER inherits STAFF)
- Custom path waypoint geometry for curve-following turn detection
- Straight-walk segment merging and landmark announcements
- Elevator (30s) & stairwell (15s) transition time estimates
- Floorplan-keyed visualisation map for canvas highlighting & PNG rendering
"""

from __future__ import annotations

import heapq
import json
import math
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models.models import Edge, EdgeRBAC, Floorplan, Node, NodeRBAC

TRANSITION_TYPES = frozenset({"ELEVATOR", "STAIRWELL", "ENTRANCE"})
WALKING_SPEED_MS = 1.2
STRAIGHT_ANGLE_THRESHOLD = math.pi / 9  # ~20 degrees

ROLE_MAP = {
    "admin": 1,
    "super_admin": 1,
    "system_admin": 1,
    "content_admin": 1,
    "staff": 2,
    "lecturer": 3,
    "student": 4,
    "visitor": 5,
    "guest": 5,
}


class NavigationEngineError(Exception):
    """Structured navigation error carrying HTTP status and optional no_route flag."""

    def __init__(self, message: str, *, status_code: int = 400, no_route: bool = False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.no_route = no_route


def resolve_role_id(rbac_role: Any) -> int:
    if isinstance(rbac_role, (int, float)) and not isinstance(rbac_role, bool):
        val = int(rbac_role)
        return val if val > 0 else 5
    if rbac_role is None:
        return 5
    raw = str(rbac_role).strip().lower()
    if not raw:
        return 5
    if raw in ROLE_MAP:
        return ROLE_MAP[raw]
    try:
        return int(raw)
    except ValueError:
        return 5


def _is_corridor(node: dict | None) -> bool:
    if not node:
        return True
    if node.get("node_type") == "CORRIDOR":
        return True
    label = (node.get("room_label") or "").strip().lower()
    if label == "corridor" or label.startswith("corridor ") or label.startswith("corridor-"):
        return True
    return False


def _heuristic(node_a: dict, node_b: dict) -> float:
    if node_a["floorplan_id"] != node_b["floorplan_id"]:
        return 0.0
    dx = node_a["coord_x"] - node_b["coord_x"]
    dy = node_a["coord_y"] - node_b["coord_y"]
    return math.hypot(dx, dy) * (node_a.get("scale_ratio") or 1.0)


def _get_turn_direction(in_vec: tuple[float, float], out_vec: tuple[float, float]) -> str:
    mag1 = math.hypot(in_vec[0], in_vec[1])
    mag2 = math.hypot(out_vec[0], out_vec[1])
    if mag1 < 0.001 or mag2 < 0.001:
        return "straight"
    n1x, n1y = in_vec[0] / mag1, in_vec[1] / mag1
    n2x, n2y = out_vec[0] / mag2, out_vec[1] / mag2
    cross = n1x * n2y - n1y * n2x
    dot = n1x * n2x + n1y * n2y
    angle = math.atan2(abs(cross), dot)
    if angle < STRAIGHT_ANGLE_THRESHOLD:
        return "straight"
    return "right" if cross > 0 else "left"


def format_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} sec"
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins} min {secs} sec" if secs > 0 else f"{mins} min"


def generate_instructions(
    path_nodes: list[dict],
    edges_traversed: list[dict],
    edge_lookup: dict[str, dict],
) -> list[dict]:
    if len(path_nodes) < 2:
        return []

    instructions: list[dict] = []
    start_node = path_nodes[0]
    dest_node = path_nodes[-1]

    route_points: list[dict] = [
        {
            "x": start_node["coord_x"],
            "y": start_node["coord_y"],
            "floorplan_id": start_node["floorplan_id"],
            "floor_level": start_node["floor_level"],
            "building_name": start_node["building_name"],
            "scale_ratio": start_node.get("scale_ratio", 1.0),
            "node": start_node,
            "is_transition_after": False,
            "meters_from_prev": 0.0,
        }
    ]

    for i, edge in enumerate(edges_traversed):
        from_node = path_nodes[i]
        to_node = path_nodes[i + 1]

        if edge["is_cross_floor"]:
            if route_points:
                route_points[-1]["is_transition_after"] = True
            route_points.append(
                {
                    "x": to_node["coord_x"],
                    "y": to_node["coord_y"],
                    "floorplan_id": to_node["floorplan_id"],
                    "floor_level": to_node["floor_level"],
                    "building_name": to_node["building_name"],
                    "scale_ratio": to_node.get("scale_ratio", 1.0),
                    "node": to_node,
                    "is_transition_after": False,
                    "meters_from_prev": float(edge.get("weight_distance") or 0.0),
                }
            )
        else:
            db_edge = (
                edge_lookup.get(f"{edge['from_node_id']}-{edge['to_node_id']}")
                or edge_lookup.get(f"{edge['to_node_id']}-{edge['from_node_id']}")
            )
            pts = None
            if db_edge and db_edge.get("custom_path"):
                try:
                    parsed = json.loads(db_edge["custom_path"])
                    if isinstance(parsed, list) and len(parsed) >= 2:
                        pts = parsed
                        if int(db_edge["source_node_id"]) != int(edge["from_node_id"]):
                            pts = list(reversed(pts))
                except Exception:
                    pts = None

            if not pts:
                pts = [
                    {"x": from_node["coord_x"], "y": from_node["coord_y"]},
                    {"x": to_node["coord_x"], "y": to_node["coord_y"]},
                ]

            seg_px_lengths = []
            total_px_length = 0.0
            for j in range(len(pts) - 1):
                dist = math.hypot(pts[j + 1]["x"] - pts[j]["x"], pts[j + 1]["y"] - pts[j]["y"])
                seg_px_lengths.append(dist)
                total_px_length += dist

            total_meters = float(edge.get("weight_distance") or 0.0)
            scale_factor = total_meters / (total_px_length or 1.0)

            for j in range(1, len(pts)):
                p = pts[j]
                seg_meters = seg_px_lengths[j - 1] * scale_factor
                is_end_node = j == len(pts) - 1
                route_points.append(
                    {
                        "x": p["x"],
                        "y": p["y"],
                        "floorplan_id": from_node["floorplan_id"],
                        "floor_level": from_node["floor_level"],
                        "building_name": from_node["building_name"],
                        "scale_ratio": from_node.get("scale_ratio", 1.0),
                        "node": to_node if is_end_node else None,
                        "is_transition_after": False,
                        "meters_from_prev": seg_meters,
                    }
                )

    start_label = start_node.get("room_label") or f"Node {start_node['node_id']}"
    instructions.append(
        {
            "type": "start",
            "action": "depart",
            "node_id": start_node["node_id"],
            "label": start_node.get("room_label") or None,
            "floorplan_id": start_node["floorplan_id"],
            "floor_level": start_node["floor_level"],
            "building_name": start_node["building_name"],
            "instruction": f"Start from {start_label}",
            "description": f"Start from {start_label}",
        }
    )

    accum_distance = 0.0
    passed_landmarks: list[str] = []

    def emit_walk_step(dist: float, landmarks: list[str], floor_ctx: dict) -> None:
        rounded_dist = round(dist)
        seen: list[str] = []
        for lm in landmarks:
            cleaned = lm.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        if seen:
            desc = f"Walk straight for {rounded_dist} metres, passing {', '.join(seen)}."
        else:
            desc = f"Walk straight for {rounded_dist} metres."
        instructions.append(
            {
                "type": "walk",
                "action": "straight",
                "distance_m": rounded_dist,
                "floorplan_id": floor_ctx.get("floorplan_id"),
                "floor_level": floor_ctx.get("floor_level"),
                "building_name": floor_ctx.get("building_name"),
                "instruction": desc,
                "description": desc,
            }
        )

    for i in range(1, len(route_points)):
        prev_pt = route_points[i - 1]
        curr_pt = route_points[i]
        accum_distance += curr_pt["meters_from_prev"]

        if prev_pt["is_transition_after"]:
            pre_trans_dist = accum_distance - curr_pt["meters_from_prev"]
            if pre_trans_dist > 0.05:
                emit_walk_step(pre_trans_dist, passed_landmarks, prev_pt)
                passed_landmarks = []
            accum_distance = 0.0

            prev_node = prev_pt["node"] or {}
            node_type = prev_node.get("node_type")
            trans_type = (
                "elevator"
                if node_type == "ELEVATOR"
                else "stairwell"
                if node_type == "STAIRWELL"
                else "entrance"
            )
            from_floor = prev_pt["floor_level"]
            to_floor = curr_pt["floor_level"]
            from_bldg = prev_pt["building_name"]
            to_bldg = curr_pt["building_name"]
            is_bldg_swap = from_bldg != to_bldg

            if is_bldg_swap:
                via = (
                    f" via {prev_node['room_label']}"
                    if prev_node.get("room_label") and not _is_corridor(prev_node)
                    else ""
                )
                trans_text = f"Exit{via} and continue to {to_bldg}"
            else:
                verb = (
                    "Take the elevator"
                    if trans_type == "elevator"
                    else "Take the stairwell"
                    if trans_type == "stairwell"
                    else "Continue through the entrance"
                )
                landmark = (
                    f" ({prev_node['room_label']})"
                    if prev_node.get("room_label") and not _is_corridor(prev_node)
                    else ""
                )
                trans_text = f"{verb}{landmark} to Level {to_floor}"

            instructions.append(
                {
                    "type": "transition",
                    "action": trans_type,
                    "from_floor": from_floor,
                    "to_floor": to_floor,
                    "from_building": from_bldg,
                    "to_building": to_bldg,
                    "node_id": prev_node.get("node_id"),
                    "label": prev_node.get("room_label") or None,
                    "floorplan_id": prev_pt["floorplan_id"],
                    "floor_level": prev_pt["floor_level"],
                    "building_name": prev_pt["building_name"],
                    "instruction": trans_text,
                    "description": trans_text,
                }
            )
        else:
            next_pt = route_points[i + 1] if i + 1 < len(route_points) else None
            if next_pt and next_pt["floorplan_id"] == curr_pt["floorplan_id"]:
                in_vec = (curr_pt["x"] - prev_pt["x"], curr_pt["y"] - prev_pt["y"])
                out_vec = (next_pt["x"] - curr_pt["x"], next_pt["y"] - curr_pt["y"])
                turn = _get_turn_direction(in_vec, out_vec)
                if turn != "straight":
                    if accum_distance > 0.05:
                        emit_walk_step(accum_distance, passed_landmarks, curr_pt)
                        accum_distance = 0.0
                        passed_landmarks = []

                    curr_node = curr_pt["node"]
                    landmark_name = (
                        curr_node["room_label"]
                        if curr_node and not _is_corridor(curr_node)
                        else None
                    )
                    turn_text = (
                        f"Turn {turn} at {landmark_name}" if landmark_name else f"Turn {turn}"
                    )
                    instructions.append(
                        {
                            "type": "turn",
                            "action": turn,
                            "direction": turn,
                            "node_id": curr_node["node_id"] if curr_node else None,
                            "label": landmark_name,
                            "floorplan_id": curr_pt["floorplan_id"],
                            "floor_level": curr_pt["floor_level"],
                            "building_name": curr_pt["building_name"],
                            "instruction": turn_text,
                            "description": turn_text,
                        }
                    )
                    continue

            curr_node = curr_pt["node"]
            if (
                curr_node
                and curr_node.get("room_label")
                and curr_node["node_id"] != dest_node["node_id"]
                and not _is_corridor(curr_node)
            ):
                passed_landmarks.append(curr_node["room_label"])

    if accum_distance > 0.05:
        emit_walk_step(accum_distance, passed_landmarks, route_points[-1])

    dest_label = dest_node.get("room_label") or f"Node {dest_node['node_id']}"
    instructions.append(
        {
            "type": "arrive",
            "action": "destination",
            "node_id": dest_node["node_id"],
            "label": dest_node.get("room_label") or None,
            "floorplan_id": dest_node["floorplan_id"],
            "floor_level": dest_node["floor_level"],
            "building_name": dest_node["building_name"],
            "instruction": f"You have arrived at {dest_label}",
            "description": f"You have arrived at {dest_label}",
        }
    )

    return instructions


def run_navigation(
    db: Session,
    *,
    current_location: int | str,
    destination_node: int | str,
    rbac_role: int | str = "VISITOR",
    walking_speed: float = WALKING_SPEED_MS,
) -> dict:
    """Compute a role-filtered multi-floor/multi-building A* route."""
    user_role_id = resolve_role_id(rbac_role)
    eff_speed = float(walking_speed) if walking_speed and float(walking_speed) > 0 else WALKING_SPEED_MS

    # Fetch all nodes with floorplan + building context
    node_rows = (
        db.query(Node)
        .options(joinedload(Node.floorplan).joinedload(Floorplan.building))
        .all()
    )
    node_rbac_rows = db.query(NodeRBAC).all()
    node_roles_map: dict[int, list[int]] = {}
    for nr in node_rbac_rows:
        node_roles_map.setdefault(nr.node_id, []).append(nr.role_id)

    edge_rows = db.query(Edge).all()
    edge_rbac_rows = db.query(EdgeRBAC).all()
    edge_roles_map: dict[int, list[int]] = {}
    for er in edge_rbac_rows:
        edge_roles_map.setdefault(er.edge_id, []).append(er.role_id)

    node_map: dict[int, dict] = {}
    for n in node_rows:
        fp = n.floorplan
        bldg = fp.building if fp else None
        node_map[n.node_id] = {
            "node_id": n.node_id,
            "coord_x": float(n.coord_x),
            "coord_y": float(n.coord_y),
            "room_label": n.room_label,
            "node_type": n.node_type,
            "is_accessible": n.is_accessible,
            "floorplan_id": n.floorplan_id,
            "floor_level": fp.floor_level if fp else 0,
            "scale_ratio": float(fp.scale_ratio) if (fp and fp.scale_ratio) else 1.0,
            "building_id": bldg.building_id if bldg else None,
            "building_name": bldg.building_name if bldg else "",
            "allowed_roles": node_roles_map.get(n.node_id, []),
            "neighbors": [],
        }

    def resolve_node(ref: int | str) -> int | None:
        try:
            as_int = int(ref)
            if as_int in node_map:
                return as_int
        except (TypeError, ValueError):
            pass
        ref_lower = str(ref).strip().lower()
        for n in node_map.values():
            if n["room_label"] and n["room_label"].strip().lower() == ref_lower:
                return n["node_id"]
        return None

    start_id = resolve_node(current_location)
    end_id = resolve_node(destination_node)

    if start_id is None:
        raise NavigationEngineError(f'Start location not found: "{current_location}"', status_code=404)
    if end_id is None:
        raise NavigationEngineError(f'Destination not found: "{destination_node}"', status_code=404)
    if start_id == end_id:
        raise NavigationEngineError("Start and destination are the same location.", status_code=400)

    def role_allowed(allowed_roles: list[int]) -> bool:
        if user_role_id == 1 or not allowed_roles:
            return True
        if user_role_id in allowed_roles:
            return True
        # LECTURER (3) inherits STAFF (2) permissions
        if user_role_id == 3 and 2 in allowed_roles:
            return True
        return False

    edge_lookup: dict[str, dict] = {}
    for e in edge_rows:
        if e.is_accessible == "DENY":
            continue
        e_roles = edge_roles_map.get(e.edge_id, [])
        if not role_allowed(e_roles):
            continue

        edge_dict = {
            "edge_id": e.edge_id,
            "source_node_id": e.source_node_id,
            "destination_node_id": e.destination_node_id,
            "weight_distance": float(e.weight_distance or 0.0),
            "is_bidirectional": 1 if e.is_bidirectional else 0,
            "is_accessible": e.is_accessible,
            "custom_path": e.custom_path,
            "allowed_roles": e_roles,
        }

        src = e.source_node_id
        dest = e.destination_node_id
        if src in node_map:
            node_map[src]["neighbors"].append(
                {"target": dest, "weight": edge_dict["weight_distance"], "edge_id": e.edge_id}
            )
            edge_lookup[f"{src}-{dest}"] = edge_dict
        if e.is_bidirectional and dest in node_map:
            node_map[dest]["neighbors"].append(
                {"target": src, "weight": edge_dict["weight_distance"], "edge_id": e.edge_id}
            )
            edge_lookup[f"{dest}-{src}"] = edge_dict

    # ── A* Search ────────────────────────────────────────────────────────────
    end_node = node_map[end_id]
    g_score: dict[int, float] = {nid: float("inf") for nid in node_map}
    f_score: dict[int, float] = {nid: float("inf") for nid in node_map}
    came_from: dict[int, tuple[int, int]] = {}

    g_score[start_id] = 0.0
    f_score[start_id] = _heuristic(node_map[start_id], end_node)

    open_heap: list[tuple[float, int]] = [(f_score[start_id], start_id)]
    closed: set[int] = set()

    while open_heap:
        _, current_id = heapq.heappop(open_heap)
        if current_id in closed:
            continue
        closed.add(current_id)

        if current_id == end_id:
            node_path: list[int] = []
            edge_path: list[dict] = []
            curr = end_id
            while curr in came_from:
                node_path.append(curr)
                from_id, edge_id = came_from[curr]
                edge_path.append({"edge_id": edge_id, "from_id": from_id, "to_id": curr})
                curr = from_id
            node_path.append(start_id)
            node_path.reverse()
            edge_path.reverse()

            path_nodes = [
                {
                    "node_id": node_map[nid]["node_id"],
                    "room_label": node_map[nid]["room_label"],
                    "node_type": node_map[nid]["node_type"],
                    "coord_x": node_map[nid]["coord_x"],
                    "coord_y": node_map[nid]["coord_y"],
                    "floorplan_id": node_map[nid]["floorplan_id"],
                    "floor_level": node_map[nid]["floor_level"],
                    "building_id": node_map[nid]["building_id"],
                    "building_name": node_map[nid]["building_name"],
                }
                for nid in node_path
            ]

            edges_traversed = []
            for ep in edge_path:
                raw_edge = (
                    edge_lookup.get(f"{ep['from_id']}-{ep['to_id']}")
                    or edge_lookup.get(f"{ep['to_id']}-{ep['from_id']}")
                    or {}
                )
                edges_traversed.append(
                    {
                        "edge_id": raw_edge.get("edge_id"),
                        "from_node_id": ep["from_id"],
                        "to_node_id": ep["to_id"],
                        "source_node_id": int(raw_edge["source_node_id"])
                        if raw_edge.get("source_node_id") is not None
                        else ep["from_id"],
                        "weight_distance": float(raw_edge.get("weight_distance") or 0.0),
                        "is_cross_floor": (
                            node_map[ep["from_id"]]["floorplan_id"]
                            != node_map[ep["to_id"]]["floorplan_id"]
                        ),
                        "custom_path": raw_edge.get("custom_path"),
                    }
                )

            total_distance = round(g_score[end_id], 2)
            floor_transitions = 0
            building_transitions = 0
            elevator_transitions = 0
            stair_transitions = 0

            for i in range(len(path_nodes) - 1):
                na = path_nodes[i]
                nb = path_nodes[i + 1]
                is_cross_floor = na["floorplan_id"] != nb["floorplan_id"]
                is_cross_bldg = na["building_id"] != nb["building_id"]
                if is_cross_floor and not is_cross_bldg:
                    if na["node_type"] in ("ELEVATOR", "STAIRWELL") or nb["node_type"] in (
                        "ELEVATOR",
                        "STAIRWELL",
                    ):
                        floor_transitions += 1
                        if na["node_type"] == "ELEVATOR" or nb["node_type"] == "ELEVATOR":
                            elevator_transitions += 1
                        else:
                            stair_transitions += 1
                if is_cross_bldg:
                    if na["node_type"] == "ENTRANCE" or nb["node_type"] == "ENTRANCE":
                        building_transitions += 1

            walking_time_sec = total_distance / eff_speed
            transition_time_sec = (elevator_transitions * 30) + (stair_transitions * 15)
            estimated_time_sec = round(walking_time_sec + transition_time_sec)

            instructions = generate_instructions(path_nodes, edges_traversed, edge_lookup)

            by_floorplan: dict[str, dict[str, list[int]]] = {}
            for n in path_nodes:
                key = str(n["floorplan_id"])
                by_floorplan.setdefault(key, {"node_ids": [], "edge_ids": []})
                by_floorplan[key]["node_ids"].append(n["node_id"])
            for et in edges_traversed:
                if not et.get("edge_id"):
                    continue
                from_fp = str(node_map[et["from_node_id"]]["floorplan_id"])
                if from_fp in by_floorplan:
                    by_floorplan[from_fp]["edge_ids"].append(et["edge_id"])

            start_lbl = node_map[start_id]["room_label"] or str(start_id)
            dest_lbl = node_map[end_id]["room_label"] or str(end_id)

            return {
                "status": "success",
                "route": {
                    "start_node": start_lbl,
                    "destination_node": dest_lbl,
                    "total_distance_m": total_distance,
                    "estimated_time_seconds": estimated_time_sec,
                    "estimated_time_label": format_time(estimated_time_sec),
                    "floor_transitions": floor_transitions,
                    "building_transitions": building_transitions,
                },
                "route_summary": {
                    "start_label": start_lbl,
                    "destination_label": dest_lbl,
                    "total_distance_m": total_distance,
                    "estimated_time_seconds": estimated_time_sec,
                    "estimated_time_label": format_time(estimated_time_sec),
                    "floor_transitions": floor_transitions,
                    "building_transitions": building_transitions,
                    "step_count": len(instructions),
                },
                "path": path_nodes,
                "edges_traversed": edges_traversed,
                "instructions": instructions,
                "visualisation": {"by_floorplan": by_floorplan},
            }

        for neighbor in node_map[current_id]["neighbors"]:
            target_id = neighbor["target"]
            neighbor_node = node_map.get(target_id)
            if not neighbor_node or neighbor_node["is_accessible"] == "DENY":
                continue
            if not role_allowed(neighbor_node["allowed_roles"]):
                continue

            tentative_g = g_score[current_id] + neighbor["weight"]
            if tentative_g < g_score[target_id]:
                came_from[target_id] = (current_id, neighbor["edge_id"])
                g_score[target_id] = tentative_g
                f_score[target_id] = tentative_g + _heuristic(neighbor_node, end_node)
                heapq.heappush(open_heap, (f_score[target_id], target_id))

    raise NavigationEngineError(
        "No authorised route exists between these locations for the specified role.",
        status_code=404,
        no_route=True,
    )
