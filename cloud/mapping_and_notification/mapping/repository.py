"""SQLAlchemy read/write adapter for the canonical cloud map tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session, joinedload

from .pathfinding import GraphEdge, GraphNode


@dataclass(frozen=True)
class GraphSnapshot:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


class MapRepository:
    def __init__(self, db: Session):
        self.db = db

    def snapshot(self, floorplan_id: int | None = None) -> GraphSnapshot:
        from app.models.models import Edge, EdgeRBAC, Floorplan, Node, NodeRBAC

        query = self.db.query(Node).options(joinedload(Node.floorplan)).order_by(Node.node_id)
        if floorplan_id is not None:
            query = query.filter(Node.floorplan_id == floorplan_id)
        db_nodes = query.all()
        ids = [n.node_id for n in db_nodes]
        if not ids:
            return GraphSnapshot((), ())
        node_roles = {}
        node_role_ids = {}
        for row in self.db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(ids)).all():
            node_roles.setdefault(row.node_id, set()).add(str(row.role.role_name).upper())
            node_role_ids.setdefault(row.node_id, set()).add(int(row.role_id))
        nodes = tuple(GraphNode(
            node_id=n.node_id,
            floorplan_id=n.floorplan_id,
            x=n.coord_x,
            y=n.coord_y,
            label=n.room_label,
            node_type=str(n.node_type),
            accessible=str(n.is_accessible).upper() != "DENY",
            allowed_roles=frozenset(node_roles.get(n.node_id, set())),
            allowed_role_ids=frozenset(node_role_ids.get(n.node_id, set())),
            scale_ratio=float(getattr(n.floorplan, "scale_ratio", None) or 1.0),
            building=getattr(getattr(n.floorplan, "building", None), "building_name", None),
            floor=getattr(n.floorplan, "floor_level", None),
        ) for n in db_nodes)
        edge_query = self.db.query(Edge).options(joinedload(Edge.source_node), joinedload(Edge.destination_node))
        edge_query = edge_query.filter(Edge.source_node_id.in_(ids), Edge.destination_node_id.in_(ids))
        db_edges = edge_query.order_by(Edge.edge_id).all()
        edge_roles = {}
        edge_role_ids = {}
        for row in self.db.query(EdgeRBAC).filter(EdgeRBAC.edge_id.in_([e.edge_id for e in db_edges])).all():
            edge_roles.setdefault(row.edge_id, set()).add(str(row.role.role_name).upper())
            edge_role_ids.setdefault(row.edge_id, set()).add(int(row.role_id))
        edges = tuple(GraphEdge(
            edge_id=e.edge_id,
            source=e.source_node_id,
            destination=e.destination_node_id,
            distance=e.weight_distance,
            bidirectional=e.is_bidirectional,
            accessible=str(e.is_accessible).upper() != "DENY",
            custom_path=e.custom_path,
            allowed_roles=frozenset(edge_roles.get(e.edge_id, set())),
            allowed_role_ids=frozenset(edge_role_ids.get(e.edge_id, set())),
        ) for e in db_edges)
        return GraphSnapshot(nodes, edges)

    def resolve_node(self, node_id: int | None = None, label: str | None = None):
        from app.models.models import Node
        if node_id is not None:
            return self.db.query(Node).filter(Node.node_id == node_id).first()
        if not label:
            return None
        return self.db.query(Node).filter(Node.room_label == label.strip()).order_by(Node.node_id).all()

    def destination_catalog(self):
        """Return user-facing destinations, excluding routing-only corridors."""
        from app.models.models import Node

        return (
            self.db.query(Node.room_label, Node.node_type)
            .filter(Node.room_label.isnot(None))
            .filter(Node.node_type != "CORRIDOR")
            .order_by(Node.room_label, Node.node_type)
            .all()
        )

    def floorplans(self):
        from app.models.models import Floorplan
        return self.db.query(Floorplan).options(joinedload(Floorplan.building)).order_by(Floorplan.building_id, Floorplan.floor_level).all()

    def floorplan(self, floorplan_id: int):
        from app.models.models import Floorplan
        return self.db.query(Floorplan).options(joinedload(Floorplan.building)).filter(Floorplan.floorplan_id == floorplan_id).first()
