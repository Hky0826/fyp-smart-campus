"""Role-filtered Map Context Model Service for Kiosk and Mobile visualisations.

Exact port of mapping_and_notification/backend/services/visualisationModelService.js.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models.models import Edge, EdgeRBAC, Floorplan, Node, NodeRBAC
from app.services.mapping.navigation_engine import resolve_role_id

TRANSITION_TYPES = ("ELEVATOR", "STAIRWELL", "ENTRANCE")
PUBLIC_LANDMARK_TYPES = ("FOOD", "WASHROOM", "FACILITIES")

UNINTENDED_FACILITY_KEYWORDS = (
    "storeroom",
    "storage",
    "store",
    "server",
    "pantry",
    "electrical",
    "switchboard",
    "substation",
    "mechanical",
    "utility",
    "janitor",
    "cleaner",
    "housekeeping",
    "maintenance",
    "plant room",
    "ahu",
    "pump room",
    "equipment room",
    "boiler",
)


def is_unintended_facility_node(node_type: str | None, room_label: str | None) -> bool:
    if node_type == "FACILITIES":
        label = (room_label or "").strip().lower()
        if not label or label in ("facility", "facilities"):
            return True
        return any(kw in label for kw in UNINTENDED_FACILITY_KEYWORDS)
    return False


def is_role_permitted(
    is_accessible: str | None,
    allowed_roles: list[int] | None,
    user_role_id: int,
) -> bool:
    if is_accessible == "DENY":
        return False
    if not allowed_roles:
        return True
    return user_role_id in allowed_roles


def build_visualisation_model(
    db: Session,
    *,
    route_result: dict,
    rbac_role: Any,
) -> dict[int, dict]:
    """Build role-filtered map context keyed by floorplan_id."""
    by_floorplan = (route_result or {}).get("visualisation", {}).get("by_floorplan") or {}
    if not by_floorplan:
        return {}

    user_role_id = resolve_role_id(rbac_role)
    floorplan_ids = [int(k) for k in by_floorplan.keys()]
    if not floorplan_ids:
        return {}

    map_context: dict[int, dict] = {}

    for fp_id in floorplan_ids:
        fp = (
            db.query(Floorplan)
            .options(joinedload(Floorplan.building))
            .filter(Floorplan.floorplan_id == fp_id)
            .first()
        )
        if not fp:
            continue

        raw_nodes = db.query(Node).filter(Node.floorplan_id == fp_id).all()
        node_ids = [n.node_id for n in raw_nodes]
        from app.services.rbac_resolver import resolve_node_effective_roles
        node_roles_map: dict[int, list[int]] = resolve_node_effective_roles(db, node_ids) if node_ids else {}

        permitted_nodes = []
        permitted_node_id_set: set[int] = set()
        for node in raw_nodes:
            if not is_role_permitted(node.is_accessible, node_roles_map.get(node.node_id, []), user_role_id):
                continue
            if is_unintended_facility_node(node.node_type, node.room_label):
                continue
            permitted_nodes.append(
                {
                    "node_id": node.node_id,
                    "coord_x": float(node.coord_x),
                    "coord_y": float(node.coord_y),
                    "room_label": node.room_label,
                    "node_type": node.node_type,
                    "is_accessible": node.is_accessible,
                }
            )
            permitted_node_id_set.add(node.node_id)

        route_edge_ids = [int(eid) for eid in (by_floorplan.get(str(fp_id), {}).get("edge_ids") or [])]
        permitted_edges = []
        if route_edge_ids:
            raw_edges = db.query(Edge).filter(Edge.edge_id.in_(route_edge_ids)).all()
            edge_roles_map: dict[int, list[int]] = {}
            for er in db.query(EdgeRBAC).filter(EdgeRBAC.edge_id.in_(route_edge_ids)).all():
                edge_roles_map.setdefault(er.edge_id, []).append(er.role_id)

            for edge in raw_edges:
                if not is_role_permitted(edge.is_accessible, edge_roles_map.get(edge.edge_id, []), user_role_id):
                    continue
                if edge.source_node_id not in permitted_node_id_set or edge.destination_node_id not in permitted_node_id_set:
                    continue
                permitted_edges.append(
                    {
                        "edge_id": edge.edge_id,
                        "source_node_id": edge.source_node_id,
                        "destination_node_id": edge.destination_node_id,
                        "weight_distance": float(edge.weight_distance or 0.0),
                        "is_bidirectional": 1 if edge.is_bidirectional else 0,
                        "custom_path": edge.custom_path,
                    }
                )

        map_context[fp_id] = {
            "floorplan_id": fp.floorplan_id,
            "building_name": fp.building.building_name if fp.building else "",
            "floor_level": fp.floor_level,
            "scale_ratio": float(fp.scale_ratio) if fp.scale_ratio else 1.0,
            "wall_grid": None,
            "nodes": permitted_nodes,
            "edges": permitted_edges,
        }

    return map_context
