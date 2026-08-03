from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .instructions import build_instructions
from .pathfinding import NavigationError, NoRouteError, find_path
from .repository import MapRepository
from ..config import settings


class DestinationAmbiguous(NavigationError):
    def __init__(self, candidates):
        self.candidates = candidates
        super().__init__("Destination label matches more than one node")


class StartLocationRequired(NavigationError):
    pass


def _roles(user) -> set[str]:
    roles = {str(getattr(role, "role_name", role)).upper() for role in (getattr(user, "roles", None) or ())}
    admin = getattr(user, "admin", None)
    if admin:
        roles.add(str(admin.admin_type).upper())
    return roles


class NavigationService:
    def __init__(self, db, *, repository: MapRepository | None = None):
        self.db = db
        self.repository = repository or MapRepository(db)

    def _destination(self, destination_node_id: int | None, destination_label: str | None):
        if destination_node_id is not None:
            node = self.repository.resolve_node(node_id=destination_node_id)
            if node is None:
                raise NoRouteError("Destination node does not exist")
            return node
        matches = self.repository.resolve_node(label=destination_label)
        if not matches:
            raise NoRouteError("Destination label does not match a node")
        if not isinstance(matches, list):
            matches = [matches]
        if len(matches) != 1:
            raise DestinationAmbiguous([{"node_id": n.node_id, "label": n.room_label, "floorplan_id": n.floorplan_id} for n in matches])
        return matches[0]

    def _start(self, *, start_node_id: int | None, user=None, device=None, allow_explicit: bool):
        from app.models.models import Node
        if start_node_id is not None and allow_explicit:
            node = self.db.query(Node).filter(Node.node_id == start_node_id).first()
            if node:
                return node
        # A JWT-bound device is the most authoritative origin for chatbot
        # navigation. User location is only a fallback when that binding is
        # unavailable or its node has been removed.
        if device is not None and getattr(device, "node_id", None):
            node = self.db.query(Node).filter(Node.node_id == device.node_id).first()
            if node:
                return node
        if user is not None and getattr(user, "last_known_location", None):
            last_seen = getattr(user, "last_seen", None)
            if last_seen and datetime.utcnow() - last_seen <= timedelta(minutes=settings.stale_location_minutes):
                node = self.db.query(Node).filter(Node.node_id == user.last_known_location).first()
                if node:
                    return node
        raise StartLocationRequired("A fresh starting location is required")

    def calculate(self, *, destination_node_id: int | None = None, destination_label: str | None = None, start_node_id: int | None = None, user=None, device=None, roles=(), walking_speed: float = settings.default_walking_speed, allow_explicit_start: bool = False):
        if walking_speed <= 0:
            raise NavigationError("walking_speed must be greater than zero")
        start = self._start(start_node_id=start_node_id, user=user, device=device, allow_explicit=allow_explicit_start)
        destination = self._destination(destination_node_id, destination_label)
        role_set = set(roles) or _roles(user)
        graph = self.repository.snapshot()
        result = find_path(graph.nodes, graph.edges, start.node_id, destination.node_id, roles=role_set, transition_penalty=settings.transition_seconds)
        instructions = build_instructions(result.nodes, result.edges)
        path = [{"node_id": n.node_id, "floorplan_id": n.floorplan_id, "coord_x": n.x, "coord_y": n.y, "room_label": n.label, "node_type": n.node_type} for n in result.nodes]
        traversed = [{"edge_id": e.edge_id, "from_node_id": a.node_id, "to_node_id": b.node_id, "distance": e.distance, "is_cross_floor": a.floorplan_id != b.floorplan_id, "custom_path": e.custom_path} for e, a, b in zip(result.edges, result.nodes, result.nodes[1:])]
        floors: dict[str, dict[str, list[int]]] = {}
        for node in result.nodes:
            entry = floors.setdefault(str(node.floorplan_id), {"node_ids": [], "edge_ids": []})
            entry["node_ids"].append(node.node_id)
        for edge, a, b in zip(result.edges, result.nodes, result.nodes[1:]):
            if a.floorplan_id == b.floorplan_id:
                floors[str(a.floorplan_id)]["edge_ids"].append(edge.edge_id)
        return {
            "route": path,
            "path": path,
            "edges_traversed": traversed,
            "instructions": instructions,
            "route_summary": {
                "start_node_id": start.node_id,
                "start_label": start.room_label,
                "destination_node_id": destination.node_id,
                "destination_label": destination.room_label,
                "total_distance_m": round(result.distance, 2),
                "estimated_time_seconds": round(result.distance / walking_speed),
                "floor_transitions": sum(a.floorplan_id != b.floorplan_id for a, b in zip(result.nodes, result.nodes[1:])),
                "step_count": len(instructions),
            },
            "visualisation": {"by_floorplan": floors},
        }
