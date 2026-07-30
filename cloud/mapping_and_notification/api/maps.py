from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.private_storage import ALLOWED_IMAGE_EXTENSIONS, safe_existing_path, save_upload
from app.core.security import verify_super_admin, verify_system_admin
from ..config import settings
from ..mapping.repository import MapRepository
from .schemas import FloorplanPatch, GraphUpdate

router = APIRouter(tags=["Mapping and notification maps"])


def _floorplan_payload(row):
    return {"floorplan_id": row.floorplan_id, "building_id": row.building_id, "building_name": getattr(getattr(row, "building", None), "building_name", None), "floor_level": row.floor_level, "image_available": bool(row.image_path), "scale_ratio": row.scale_ratio, "graph_version": getattr(row, "graph_version", 1)}


@router.get("/floorplans")
def list_floorplans(db: Session = Depends(get_db)):
    return [_floorplan_payload(row) for row in MapRepository(db).floorplans()]


@router.get("/nodes")
def list_global_nodes(db: Session = Depends(get_db)):
    from app.models.models import Node, Floorplan, Building
    query = (
        db.query(Node, Floorplan.floor_level, Building.building_name)
        .join(Floorplan, Node.floorplan_id == Floorplan.floorplan_id)
        .join(Building, Floorplan.building_id == Building.building_id)
        .all()
    )
    return [
        {
            "node_id": n.node_id,
            "floorplan_id": n.floorplan_id,
            "room_label": n.room_label,
            "node_type": n.node_type,
            "coord_x": n.coord_x,
            "coord_y": n.coord_y,
            "is_accessible": n.is_accessible,
            "floor_level": floor_level,
            "building_name": building_name,
        }
        for n, floor_level, building_name in query
    ]


@router.post("/floorplans")
async def create_floorplan(building_id: int = Form(...), floor_level: int = Form(...), scale_ratio: float | None = Form(None), image: UploadFile | None = File(None), db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    from app.models.models import Floorplan
    if image is None:
        raise HTTPException(422, "A floorplan image is required")
    object_key, _ = await save_upload(image, "floorplans", ALLOWED_IMAGE_EXTENSIONS, settings.floorplan_max_bytes)
    try:
        from PIL import Image
        with Image.open(safe_existing_path("floorplans", object_key)) as checked:
            checked.verify()
    except Exception as exc:
        safe_existing_path("floorplans", object_key).unlink(missing_ok=True)
        raise HTTPException(415, "Uploaded file is not a valid image") from exc
    row = Floorplan(building_id=building_id, floor_level=floor_level, image_path=object_key, scale_ratio=scale_ratio, graph_version=1)
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return _floorplan_payload(row)


@router.patch("/floorplans/{floorplan_id}")
def patch_floorplan(floorplan_id: int, payload: FloorplanPatch, db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    row = MapRepository(db).floorplan(floorplan_id)
    if not row:
        raise HTTPException(404, "Floorplan not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit(); db.refresh(row)
    return _floorplan_payload(row)


@router.delete("/floorplans/{floorplan_id}")
def delete_floorplan(floorplan_id: int, db: Session = Depends(get_db), _admin=Depends(verify_super_admin)):
    from app.models.models import Appointment, Device, Floorplan, Node, User
    row = MapRepository(db).floorplan(floorplan_id)
    if not row:
        raise HTTPException(404, "Floorplan not found")
    node_ids = [n.node_id for n in db.query(Node.node_id).filter(Node.floorplan_id == floorplan_id).all()]
    blockers = []
    if node_ids:
        if db.query(Device).filter(Device.node_id.in_(node_ids)).count(): blockers.append("devices")
        if db.query(User).filter(User.last_known_location.in_(node_ids)).count(): blockers.append("users")
        if db.query(Appointment).filter(Appointment.node_id.in_(node_ids)).count(): blockers.append("appointments")
    if blockers:
        raise HTTPException(409, {"message": "Floorplan is still referenced", "references": blockers})
    db.delete(row); db.commit()
    return {"deleted": floorplan_id}


@router.get("/floorplans/{floorplan_id}/graph")
def get_graph(floorplan_id: int, db: Session = Depends(get_db)):
    if not MapRepository(db).floorplan(floorplan_id):
        raise HTTPException(404, "Floorplan not found")
    snapshot = MapRepository(db).snapshot(floorplan_id)
    return {"floorplan_id": floorplan_id, "nodes": [{"node_id": n.node_id, "floorplan_id": n.floorplan_id, "coord_x": n.x, "coord_y": n.y, "room_label": n.label, "node_type": n.node_type, "is_accessible": "ALLOW" if n.accessible else "DENY", "allowed_roles": sorted(n.allowed_roles), "role_ids": sorted(n.allowed_role_ids)} for n in snapshot.nodes], "edges": [{"edge_id": e.edge_id, "source_node_id": e.source, "destination_node_id": e.destination, "weight_distance": e.distance, "is_accessible": "ALLOW" if e.accessible else "DENY", "is_bidirectional": e.bidirectional, "custom_path": e.custom_path, "allowed_roles": sorted(e.allowed_roles), "role_ids": sorted(e.allowed_role_ids)} for e in snapshot.edges], "graph_version": getattr(MapRepository(db).floorplan(floorplan_id), "graph_version", 1)}


@router.put("/floorplans/{floorplan_id}/graph")
def update_graph(floorplan_id: int, payload: GraphUpdate, db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    """Replace one floorplan graph atomically while preserving supplied IDs."""
    from app.models.models import Edge, EdgeRBAC, Node, NodeRBAC, Floorplan, Device, User, Appointment, AuthenticationLog, SurveillanceLog
    row = db.query(Floorplan).filter(Floorplan.floorplan_id == floorplan_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Floorplan not found")
    current_version = int(getattr(row, "graph_version", 1) or 1)
    if payload.graph_version is not None and payload.graph_version != current_version:
        raise HTTPException(409, {"message": "Graph version is stale", "graph_version": current_version})
    existing = {n.node_id: n for n in db.query(Node).filter(Node.floorplan_id == floorplan_id).with_for_update().all()}
    incoming_ids = {n.node_id for n in payload.nodes if n.node_id is not None}
    unknown = incoming_ids - set(existing)
    if unknown:
        raise HTTPException(409, {"message": "Graph references nodes from another floorplan", "node_ids": sorted(unknown)})
    deleted_ids = set(existing) - incoming_ids
    if deleted_ids:
        blockers = []
        if db.query(Device).filter(Device.node_id.in_(deleted_ids)).count(): blockers.append("devices")
        if db.query(User).filter(User.last_known_location.in_(deleted_ids)).count(): blockers.append("users")
        if db.query(Appointment).filter(Appointment.node_id.in_(deleted_ids)).count(): blockers.append("appointments")
        if db.query(AuthenticationLog).filter(AuthenticationLog.node_id.in_(deleted_ids)).count(): blockers.append("authentication_logs")
        if db.query(SurveillanceLog).filter(SurveillanceLog.user_id.isnot(None), SurveillanceLog.user_id.in_(db.query(User.user_id).filter(User.last_known_location.in_(deleted_ids)))).count(): blockers.append("surveillance_logs")
        if blockers:
            raise HTTPException(409, {"message": "Graph deletion has protected references", "references": blockers})
    all_nodes = {}
    for item in payload.nodes:
        node = existing.get(item.node_id) if item.node_id is not None else Node(floorplan_id=floorplan_id)
        if node is None:
            raise HTTPException(409, "Invalid node identity")
        node.floorplan_id = floorplan_id
        node.coord_x, node.coord_y, node.room_label, node.node_type, node.is_accessible = item.coord_x, item.coord_y, item.room_label, item.node_type, item.is_accessible
        db.add(node); db.flush()
        all_nodes[node.node_id] = node
    for edge in payload.edges:
        if edge.source_node_id not in all_nodes or edge.destination_node_id not in all_nodes:
            raise HTTPException(422, "Every edge endpoint must be in the submitted graph")
    existing_edges = {e.edge_id: e for e in db.query(Edge).filter(Edge.source_node_id.in_(set(existing)), Edge.destination_node_id.in_(set(existing))).with_for_update().all()}
    incoming_edge_ids = {e.edge_id for e in payload.edges if e.edge_id is not None}
    if incoming_edge_ids - set(existing_edges):
        raise HTTPException(409, "Graph references an unknown edge")
    for edge in existing_edges.values():
        if edge.edge_id not in incoming_edge_ids:
            db.delete(edge)
    for item in payload.edges:
        edge = existing_edges.get(item.edge_id) if item.edge_id is not None else Edge()
        edge.source_node_id, edge.destination_node_id, edge.weight_distance, edge.is_accessible, edge.is_bidirectional = item.source_node_id, item.destination_node_id, item.weight_distance, item.is_accessible, item.is_bidirectional
        edge.custom_path = item.custom_path if isinstance(item.custom_path, str) else (None if item.custom_path is None else __import__("json").dumps(item.custom_path))
        db.add(edge)
    for node_id in deleted_ids:
        db.query(NodeRBAC).filter(NodeRBAC.node_id == node_id).delete(synchronize_session=False)
        db.delete(existing[node_id])
    db.flush()
    # RBAC is replaced only after the complete topology has validated.
    for node_id, item in [(n.node_id, n) for n in payload.nodes]:
        db.query(NodeRBAC).filter(NodeRBAC.node_id == node_id).delete(synchronize_session=False)
        for role_id in item.role_ids:
            db.add(NodeRBAC(node_id=node_id, role_id=role_id))
    for edge in payload.edges:
        if edge.edge_id is not None:
            db.query(EdgeRBAC).filter(EdgeRBAC.edge_id == edge.edge_id).delete(synchronize_session=False)
            for role_id in edge.role_ids:
                db.add(EdgeRBAC(edge_id=edge.edge_id, role_id=role_id))
    row.graph_version = current_version + 1
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"floorplan_id": floorplan_id, "graph_version": row.graph_version, "node_ids": sorted(all_nodes), "edge_count": len(payload.edges)}


@router.get("/floorplans/{floorplan_id}/image")
def get_floorplan_image(floorplan_id: int, db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    row = MapRepository(db).floorplan(floorplan_id)
    if not row:
        raise HTTPException(404, "Floorplan not found")
    path = safe_existing_path("floorplans", row.image_path)
    return FileResponse(path)
