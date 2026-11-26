"""Native FastAPI Router for Campus Mapping, Navigation, Kiosk Wayfinding & Notifications.

Replaces mapping_proxy.py and the Node.js mapping_and_notification microservice completely.
Mounted at /api/mapping (canonical) and aliased at /api/mapping-notification for
100% backward compatibility.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_admin
from app.models.models import (
    Admin,
    Building,
    Edge,
    EdgeRBAC,
    Floorplan,
    Node,
    NodeRBAC,
    Notification,
    Role,
    User,
)
from app.services.mapping.ai_bridge import (
    analyze_floorplan_image,
    detect_walls_for_floorplan,
    invalidate_floorplan_caches,
    is_ai_available,
)
from app.services.mapping.kiosk_session import (
    create_kiosk_session,
    get_kiosk_session,
    get_mobile_base_url,
    get_qr_codes_dir,
    render_mobile_route_html,
)
from app.services.mapping.navigation_engine import (
    NavigationEngineError,
    resolve_role_id,
    run_navigation,
)
from app.services.mapping.notification_service import (
    NotificationBuildError,
    build_and_dispatch_notifications,
)
from app.services.mapping.route_visualizer import (
    generate_route_visualisations,
    get_floorplan_storage_dir,
    get_visualisations_dir,
    resolve_floorplan_image_path,
)
from app.services.mapping.visualisation_model import (
    build_visualisation_model,
    is_role_permitted,
)

logger = logging.getLogger("smart-campus.mapping.router")

router = APIRouter(tags=["Campus Mapping & Notification"])
public_router = APIRouter(tags=["Campus Mobile Wayfinding & Assets"])


# ─────────────────────────────────────────────────────────────────────────────
# AUTH HELPERS (API Key / Kiosk Access)
# ─────────────────────────────────────────────────────────────────────────────


def _expected_api_keys() -> set[str]:
    keys = {
        os.getenv("NAVIGATION_API_KEY", "").strip(),
        os.getenv("MAPPING_API_KEY", "").strip(),
    }
    return {k for k in keys if k}


def verify_api_key(request: Request) -> None:
    provided = (request.headers.get("x-api-key") or "").strip()
    expected = _expected_api_keys()
    if not expected:
        # In local development without an API key configured, allow internal callers
        return
    if not provided or provided not in expected:
        raise HTTPException(status_code=403, detail="Invalid or missing x-api-key header.")


def verify_kiosk_or_admin(request: Request, db: Session = Depends(get_db)) -> None:
    provided_key = (request.headers.get("x-api-key") or "").strip()
    expected = _expected_api_keys()
    if provided_key and (not expected or provided_key in expected):
        return
    # Fall back to standard dashboard admin session / Bearer JWT
    get_current_admin(request, db)


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH & READ ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/health")
@router.get("/api/health")
def mapping_health():
    return {"status": "healthy", "service": "smart-campus-native-mapping"}


@router.get("/ai-health")
@router.get("/api/ai-health")
def check_ai_health():
    if is_ai_available():
        return {"status": "ok", "message": "AI service is available in-process."}
    raise HTTPException(status_code=503, detail="AI service is not available.")


@router.get("/roles")
@router.get("/api/roles")
def get_roles(db: Session = Depends(get_db)):
    rows = db.query(Role).order_by(Role.role_id.asc()).all()
    return [
        {
            "role_id": r.role_id,
            "role_name": r.role_name,
            "description": r.description,
        }
        for r in rows
    ]


@router.get("/floorplans")
@router.get("/api/floorplans")
def get_floorplans(db: Session = Depends(get_db)):
    rows = (
        db.query(Floorplan)
        .join(Building, Floorplan.building_id == Building.building_id)
        .options(joinedload(Floorplan.building))
        .order_by(Building.building_name.asc(), Floorplan.floor_level.asc())
        .all()
    )
    return [
        {
            "floorplan_id": fp.floorplan_id,
            "floor_level": fp.floor_level,
            "scale_ratio": float(fp.scale_ratio) if fp.scale_ratio is not None else 1.0,
            "building_name": fp.building.building_name if fp.building else "",
        }
        for fp in rows
    ]


@router.get("/global-nodes")
@router.get("/api/global-nodes")
def get_global_nodes(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    rows = (
        db.query(Node)
        .join(Floorplan, Node.floorplan_id == Floorplan.floorplan_id)
        .join(Building, Floorplan.building_id == Building.building_id)
        .options(joinedload(Node.floorplan).joinedload(Floorplan.building))
        .order_by(Building.building_name.asc(), Floorplan.floor_level.asc(), Node.room_label.asc())
        .all()
    )
    node_ids = [n.node_id for n in rows]
    roles_map: dict[int, list[int]] = {}
    if node_ids:
        for nr in db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(node_ids)).all():
            roles_map.setdefault(nr.node_id, []).append(nr.role_id)

    return [
        {
            "node_id": n.node_id,
            "room_label": n.room_label,
            "node_type": n.node_type,
            "floorplan_id": n.floorplan_id,
            "floor_level": n.floorplan.floor_level if n.floorplan else 0,
            "building_name": n.floorplan.building.building_name
            if (n.floorplan and n.floorplan.building)
            else "",
            "allowed_roles": ",".join(str(r) for r in roles_map.get(n.node_id, [])) or None,
        }
        for n in rows
    ]


@router.get("/map-data/{floorplan_id}")
@router.get("/api/map-data/{floorplan_id}")
def get_map_data(floorplan_id: int, db: Session = Depends(get_db)):
    fp = (
        db.query(Floorplan)
        .options(joinedload(Floorplan.building))
        .filter(Floorplan.floorplan_id == floorplan_id)
        .first()
    )
    if not fp:
        raise HTTPException(status_code=404, detail="Floorplan not found")

    fp_data = {
        "image_path": fp.image_path,
        "scale_ratio": float(fp.scale_ratio) if fp.scale_ratio is not None else 1.0,
        "building_id": fp.building_id,
        "floor_level": fp.floor_level,
        "building_name": fp.building.building_name if fp.building else "",
    }

    node_rows = db.query(Node).filter(Node.floorplan_id == floorplan_id).all()
    if not node_rows:
        return {"floorplan": fp_data, "nodes": [], "edges": []}

    node_ids = [n.node_id for n in node_rows]
    node_roles_map: dict[int, list[int]] = {}
    for nr in db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(node_ids)).all():
        node_roles_map.setdefault(nr.node_id, []).append(nr.role_id)

    nodes_out = [
        {
            "node_id": n.node_id,
            "floorplan_id": n.floorplan_id,
            "coord_x": float(n.coord_x),
            "coord_y": float(n.coord_y),
            "room_label": n.room_label,
            "is_accessible": n.is_accessible,
            "node_type": n.node_type,
            "allowed_roles": node_roles_map.get(n.node_id, []),
        }
        for n in node_rows
    ]

    edge_rows = db.query(Edge).filter(Edge.source_node_id.in_(node_ids)).all()
    edge_ids = [e.edge_id for e in edge_rows]
    edge_roles_map: dict[int, list[int]] = {}
    if edge_ids:
        for er in db.query(EdgeRBAC).filter(EdgeRBAC.edge_id.in_(edge_ids)).all():
            edge_roles_map.setdefault(er.edge_id, []).append(er.role_id)

    edges_out = [
        {
            "edge_id": e.edge_id,
            "source_node_id": e.source_node_id,
            "destination_node_id": e.destination_node_id,
            "weight_distance": float(e.weight_distance or 0.0),
            "is_accessible": e.is_accessible,
            "is_bidirectional": 1 if e.is_bidirectional else 0,
            "custom_path": e.custom_path,
            "allowed_roles": edge_roles_map.get(e.edge_id, []),
        }
        for e in edge_rows
    ]

    return {"floorplan": fp_data, "nodes": nodes_out, "edges": edges_out}


# ─────────────────────────────────────────────────────────────────────────────
# FLOORPLAN MANAGEMENT (UPLOAD / UPDATE / DELETE)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/floorplans")
@router.post("/api/floorplans")
async def upload_floorplan(
    floorplanImage: UploadFile = File(...),
    buildingName: str = Form(...),
    floorLevel: int = Form(...),
    scaleRatio: float = Form(1.0),
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    if not floorplanImage or not floorplanImage.filename:
        raise HTTPException(status_code=400, detail="No image file uploaded.")

    ext = Path(floorplanImage.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        raise HTTPException(status_code=400, detail="Unsupported image format. Use PNG or JPEG.")

    content = await floorplanImage.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded image file is empty.")

    filename = f"{int(time.time() * 1000)}-{secrets.randbelow(10**9)}{ext}"
    dest_path = get_floorplan_storage_dir() / filename
    dest_path.write_bytes(content)

    image_path = f"/uploads/{filename}"

    bldg = db.query(Building).filter(Building.building_name == buildingName.strip()).first()
    if not bldg:
        bldg = Building(building_name=buildingName.strip())
        db.add(bldg)
        db.flush()

    fp = Floorplan(
        building_id=bldg.building_id,
        floor_level=int(floorLevel),
        image_path=image_path,
        scale_ratio=float(scaleRatio or 1.0),
    )
    db.add(fp)
    db.commit()
    db.refresh(fp)

    return {
        "message": "Successfully saved the floorplan into the database.",
        "floorplan_id": fp.floorplan_id,
        "image_path": image_path,
    }


@router.put("/floorplans/{floorplan_id}")
@router.put("/api/floorplans/{floorplan_id}")
async def update_floorplan(
    floorplan_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    body = await request.json()
    building_name = (body.get("buildingName") or "").strip()
    floor_level = body.get("floorLevel")
    scale_ratio = body.get("scaleRatio", 1.0)

    if not building_name or floor_level in (None, ""):
        raise HTTPException(status_code=400, detail="Building Name and Floor Level required.")

    fp = db.query(Floorplan).filter(Floorplan.floorplan_id == floorplan_id).first()
    if not fp:
        raise HTTPException(status_code=404, detail="Floorplan not found.")

    old_bldg_id = fp.building_id
    bldg = db.query(Building).filter(Building.building_name == building_name).first()
    if not bldg:
        bldg = Building(building_name=building_name)
        db.add(bldg)
        db.flush()

    fp.building_id = bldg.building_id
    fp.floor_level = int(floor_level)
    fp.scale_ratio = float(scale_ratio or 1.0)
    db.flush()

    removed_old_bldg = False
    if old_bldg_id != bldg.building_id:
        remaining = db.query(Floorplan).filter(Floorplan.building_id == old_bldg_id).count()
        if remaining == 0:
            old_bldg = db.query(Building).filter(Building.building_id == old_bldg_id).first()
            if old_bldg:
                db.delete(old_bldg)
                removed_old_bldg = True

    db.commit()
    invalidate_floorplan_caches(floorplan_id)

    msg = (
        "Floorplan updated and old unused building removed."
        if removed_old_bldg
        else "Floorplan details updated successfully."
    )
    return {"message": msg}


@router.delete("/floorplans/{floorplan_id}")
@router.delete("/api/floorplans/{floorplan_id}")
def delete_floorplan(
    floorplan_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    fp = db.query(Floorplan).filter(Floorplan.floorplan_id == floorplan_id).first()
    if not fp:
        raise HTTPException(status_code=404, detail="Floorplan not found.")

    old_bldg_id = fp.building_id
    disk_path = resolve_floorplan_image_path(fp.image_path)
    if disk_path:
        try:
            disk_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to delete physical floorplan file %s: %s", disk_path, exc)

    node_rows = db.query(Node.node_id).filter(Node.floorplan_id == floorplan_id).all()
    node_ids = [r[0] for r in node_rows]
    if node_ids:
        edge_rows = (
            db.query(Edge.edge_id)
            .filter((Edge.source_node_id.in_(node_ids)) | (Edge.destination_node_id.in_(node_ids)))
            .all()
        )
        edge_ids = [r[0] for r in edge_rows]
        if edge_ids:
            db.query(EdgeRBAC).filter(EdgeRBAC.edge_id.in_(edge_ids)).delete(synchronize_session=False)
            db.query(Edge).filter(Edge.edge_id.in_(edge_ids)).delete(synchronize_session=False)
        db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(Node).filter(Node.floorplan_id == floorplan_id).delete(synchronize_session=False)

    db.delete(fp)
    db.flush()

    removed_bldg = False
    remaining = db.query(Floorplan).filter(Floorplan.building_id == old_bldg_id).count()
    if remaining == 0:
        old_bldg = db.query(Building).filter(Building.building_id == old_bldg_id).first()
        if old_bldg:
            db.delete(old_bldg)
            removed_bldg = True

    db.commit()
    invalidate_floorplan_caches(floorplan_id)

    msg = (
        "Map, file, and unused building deleted successfully."
        if removed_bldg
        else "Map and file deleted successfully."
    )
    return {"message": msg}


# ─────────────────────────────────────────────────────────────────────────────
# ATOMIC MAP DATA SAVE (DIFF-AND-SYNC UPSERT)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/map-data")
@router.post("/api/map-data")
async def save_map_data(
    request: Request,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    body = await request.json()
    floorplan_id = body.get("floorplan_id")
    nodes = body.get("nodes") or []
    edges = body.get("edges") or []

    if not floorplan_id:
        raise HTTPException(status_code=400, detail="Missing floorplan ID.")
    floorplan_id = int(floorplan_id)

    fp = db.query(Floorplan).filter(Floorplan.floorplan_id == floorplan_id).first()
    if not fp:
        raise HTTPException(status_code=404, detail="Floorplan not found.")

    # Empty nodes -> clear floorplan
    if not nodes:
        existing_node_ids = [r[0] for r in db.query(Node.node_id).filter(Node.floorplan_id == floorplan_id).all()]
        if existing_node_ids:
            edge_ids = [
                r[0]
                for r in db.query(Edge.edge_id)
                .filter((Edge.source_node_id.in_(existing_node_ids)) | (Edge.destination_node_id.in_(existing_node_ids)))
                .all()
            ]
            if edge_ids:
                db.query(EdgeRBAC).filter(EdgeRBAC.edge_id.in_(edge_ids)).delete(synchronize_session=False)
                db.query(Edge).filter(Edge.edge_id.in_(edge_ids)).delete(synchronize_session=False)
            db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(existing_node_ids)).delete(synchronize_session=False)
            db.query(Node).filter(Node.floorplan_id == floorplan_id).delete(synchronize_session=False)
        fp.graph_version = (fp.graph_version or 1) + 1
        db.commit()
        return {"message": "Map cleared successfully."}

    # Pre-validate edges before mutating DB
    for idx, e in enumerate(edges):
        start_idx = e.get("start")
        if start_idx is None or not (0 <= int(start_idx) < len(nodes)):
            raise HTTPException(
                status_code=400,
                detail=f"Edge {idx}: source node index {start_idx} is out of range (0–{len(nodes) - 1}).",
            )
        if not e.get("is_cross_floor"):
            end_idx = e.get("end")
            if end_idx is None or not (0 <= int(end_idx) < len(nodes)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Edge {idx}: destination node index {end_idx} is out of range (0–{len(nodes) - 1}).",
                )
        elif not e.get("target_node_id"):
            raise HTTPException(
                status_code=400,
                detail=f"Edge {idx}: cross-floor edge is missing target_node_id.",
            )

    try:
        # 1. Delete removed nodes
        existing_db_node_ids = [
            r[0] for r in db.query(Node.node_id).filter(Node.floorplan_id == floorplan_id).all()
        ]
        payload_node_ids = {int(n["node_id"]) for n in nodes if n.get("node_id") is not None}
        nodes_to_delete = [nid for nid in existing_db_node_ids if nid not in payload_node_ids]
        if nodes_to_delete:
            del_edge_ids = [
                r[0]
                for r in db.query(Edge.edge_id)
                .filter((Edge.source_node_id.in_(nodes_to_delete)) | (Edge.destination_node_id.in_(nodes_to_delete)))
                .all()
            ]
            if del_edge_ids:
                db.query(EdgeRBAC).filter(EdgeRBAC.edge_id.in_(del_edge_ids)).delete(synchronize_session=False)
                db.query(Edge).filter(Edge.edge_id.in_(del_edge_ids)).delete(synchronize_session=False)
            db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(nodes_to_delete)).delete(synchronize_session=False)
            db.query(Node).filter(Node.node_id.in_(nodes_to_delete)).delete(synchronize_session=False)

        # 2. UPSERT nodes
        index_to_node_id: dict[int, int] = {}
        for i, n in enumerate(nodes):
            nid = n.get("node_id")
            if nid is not None:
                node_obj = db.query(Node).filter(Node.node_id == int(nid)).first()
                if node_obj:
                    node_obj.coord_x = float(n["x"])
                    node_obj.coord_y = float(n["y"])
                    node_obj.room_label = n.get("room_label") or f"Node {i + 1}"
                    node_obj.is_accessible = n.get("is_accessible") or "ALLOW"
                    node_obj.node_type = n.get("node_type") or "OTHER"
                    index_to_node_id[i] = node_obj.node_id
                    db.query(NodeRBAC).filter(NodeRBAC.node_id == node_obj.node_id).delete(synchronize_session=False)
                else:
                    nid = None
            if nid is None:
                node_obj = Node(
                    floorplan_id=floorplan_id,
                    coord_x=float(n["x"]),
                    coord_y=float(n["y"]),
                    room_label=n.get("room_label") or f"Node {i + 1}",
                    is_accessible=n.get("is_accessible") or "ALLOW",
                    node_type=n.get("node_type") or "OTHER",
                )
                db.add(node_obj)
                db.flush()
                index_to_node_id[i] = node_obj.node_id

            for role_id in set(n.get("allowed_roles") or []):
                db.add(NodeRBAC(node_id=index_to_node_id[i], role_id=int(role_id)))

        # 3. Delete removed edges
        all_current_node_ids = list(index_to_node_id.values())
        if all_current_node_ids:
            existing_db_edge_ids = [
                r[0] for r in db.query(Edge.edge_id).filter(Edge.source_node_id.in_(all_current_node_ids)).all()
            ]
            payload_edge_ids = {int(e["edge_id"]) for e in edges if e.get("edge_id") is not None}
            edges_to_delete = [eid for eid in existing_db_edge_ids if eid not in payload_edge_ids]
            if edges_to_delete:
                db.query(EdgeRBAC).filter(EdgeRBAC.edge_id.in_(edges_to_delete)).delete(synchronize_session=False)
                db.query(Edge).filter(Edge.edge_id.in_(edges_to_delete)).delete(synchronize_session=False)

        # 4. UPSERT edges
        for idx, e in enumerate(edges):
            source_id = index_to_node_id.get(int(e["start"]))
            dest_id = int(e["target_node_id"]) if e.get("is_cross_floor") else index_to_node_id.get(int(e["end"]))

            if source_id is None or dest_id is None:
                db.rollback()
                raise HTTPException(status_code=400, detail=f"Edge {idx}: node references could not be resolved.")

            # Validate cross-floor transition rules (Elevator/Stairwell same type, same building, different floor)
            if e.get("is_cross_floor"):
                src_node = (
                    db.query(Node)
                    .options(joinedload(Node.floorplan).joinedload(Floorplan.building))
                    .filter(Node.node_id == source_id)
                    .first()
                )
                dst_node = (
                    db.query(Node)
                    .options(joinedload(Node.floorplan).joinedload(Floorplan.building))
                    .filter(Node.node_id == dest_id)
                    .first()
                )
                if not dst_node:
                    db.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail=f"Edge {idx}: cross-floor target node ID {dest_id} does not exist.",
                    )
                if src_node and dst_node:
                    s_type, d_type = src_node.node_type, dst_node.node_type
                    s_bldg = src_node.floorplan.building.building_name if (src_node.floorplan and src_node.floorplan.building) else ""
                    d_bldg = dst_node.floorplan.building.building_name if (dst_node.floorplan and dst_node.floorplan.building) else ""
                    s_flr = src_node.floorplan.floor_level if src_node.floorplan else None
                    d_flr = dst_node.floorplan.floor_level if dst_node.floorplan else None
                    if s_type in ("ELEVATOR", "STAIRWELL") or d_type in ("ELEVATOR", "STAIRWELL"):
                        if s_type != d_type or s_bldg != d_bldg or s_flr == d_flr:
                            db.rollback()
                            raise HTTPException(
                                status_code=400,
                                detail="Invalid transition: Elevator and Stairwell nodes must connect to the same type, same building, and different floors only.",
                            )

            eid = e.get("edge_id")
            if eid is not None:
                edge_obj = db.query(Edge).filter(Edge.edge_id == int(eid)).first()
                if edge_obj:
                    edge_obj.source_node_id = source_id
                    edge_obj.destination_node_id = dest_id
                    edge_obj.weight_distance = float(e.get("weight") or 0.0)
                    edge_obj.is_bidirectional = bool(e.get("is_bidirectional", True))
                    edge_obj.is_accessible = e.get("is_accessible") or "ALLOW"
                    edge_obj.custom_path = e.get("custom_path")
                    db.query(EdgeRBAC).filter(EdgeRBAC.edge_id == edge_obj.edge_id).delete(synchronize_session=False)
                else:
                    eid = None
            if eid is None:
                edge_obj = Edge(
                    source_node_id=source_id,
                    destination_node_id=dest_id,
                    weight_distance=float(e.get("weight") or 0.0),
                    is_bidirectional=bool(e.get("is_bidirectional", True)),
                    is_accessible=e.get("is_accessible") or "ALLOW",
                    custom_path=e.get("custom_path"),
                )
                db.add(edge_obj)
                db.flush()

            for role_id in set(e.get("allowed_roles") or []):
                db.add(EdgeRBAC(edge_id=edge_obj.edge_id, role_id=int(role_id)))

        fp.graph_version = (fp.graph_version or 1) + 1
        db.commit()
        return {"message": "Map data saved seamlessly."}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to save map data: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to save map data: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# AI COMPUTER VISION ENDPOINTS (IN-PROCESS)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/wall-detection")
@router.post("/api/wall-detection")
async def wall_detection(
    request: Request,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    body = await request.json()
    floorplan_id = body.get("floorplan_id")
    if not floorplan_id:
        raise HTTPException(status_code=400, detail="floorplan_id is required.")

    fp = db.query(Floorplan).filter(Floorplan.floorplan_id == int(floorplan_id)).first()
    if not fp:
        raise HTTPException(status_code=404, detail="Floorplan not found.")

    try:
        res = await detect_walls_for_floorplan(
            floorplan_id=fp.floorplan_id,
            image_path=fp.image_path,
            sensitivity=int(body.get("sensitivity", 120)),
            canvas_width=int(body.get("canvas_width", 800)),
            canvas_height=int(body.get("canvas_height", 600)),
            grid_scale=int(body.get("grid_scale", 8)),
        )
        return {"success": True, **res}
    except Exception as exc:
        logger.exception("Wall detection failed: %s", exc)
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/analyze-floorplan")
@router.post("/api/analyze-floorplan")
async def analyze_floorplan(
    request: Request,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    body = await request.json()
    floorplan_id = body.get("floorplan_id")
    if not floorplan_id:
        raise HTTPException(status_code=400, detail="floorplan_id is required.")

    fp = db.query(Floorplan).filter(Floorplan.floorplan_id == int(floorplan_id)).first()
    if not fp:
        raise HTTPException(status_code=404, detail="Floorplan not found.")

    try:
        res = await analyze_floorplan_image(
            floorplan_id=fp.floorplan_id,
            image_path=fp.image_path,
            sensitivity=int(body.get("sensitivity", 120)),
            room_gap_close_px=int(body.get("room_gap_close_px", 25)),
            min_room_area_px=int(body.get("min_room_area_px", 2000)),
            max_room_area_ratio=float(body.get("max_room_area_ratio", 0.30)),
            min_ocr_confidence=float(body.get("min_ocr_confidence", 0.60)),
            wall_clearance_px=int(body.get("wall_clearance_px", 8)),
            canvas_width=int(body.get("canvas_width", 800)),
            canvas_height=int(body.get("canvas_height", 600)),
            grid_scale=int(body.get("grid_scale", 8)),
        )
        return {"success": True, **res}
    except Exception as exc:
        logger.exception("Floorplan analysis failed: %s", exc)
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# NAVIGATION & NOTIFICATION WORKFLOW ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────


async def _handle_calculate_route(
    request: Request,
    db: Session,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    body = await request.json()
    current_location = (
        body.get("current_location")
        if body.get("current_location") is not None
        else body.get("startNodeId")
        if body.get("startNodeId") is not None
        else body.get("start_node_id")
    )
    destination_node = (
        body.get("destination_node")
        if body.get("destination_node") is not None
        else body.get("endNodeId")
        if body.get("endNodeId") is not None
        else body.get("destination_node_id")
    )
    roles_field = body.get("roles")
    rbac_role = (
        body.get("rbac_role")
        or body.get("userRoleId")
        or body.get("role")
        or (roles_field[0] if isinstance(roles_field, list) and roles_field else roles_field)
        or "VISITOR"
    )

    if current_location in (None, ""):
        return JSONResponse(
            status_code=422,
            content={
                "error": "Start location required",
                "message": "current_location (or startNodeId / start_node_id) is required.",
            },
        )
    if destination_node in (None, ""):
        return JSONResponse(
            status_code=400,
            content={
                "error": "Destination node required",
                "message": "destination_node (or endNodeId / destination_node_id) is required.",
            },
        )

    walking_speed = float(body.get("walking_speed") or request.query_params.get("walking_speed") or 1.2)

    try:
        result = run_navigation(
            db,
            current_location=current_location,
            destination_node=destination_node,
            rbac_role=rbac_role,
            walking_speed=walking_speed,
        )

        has_trigger = bool(
            body.get("notification_trigger")
            or body.get("target_host_id")
            or body.get("event_type") == "visitor_navigation"
        )
        if has_trigger:
            result["notification"] = build_and_dispatch_notifications(
                db,
                req_body=body,
                route_result=result,
                background_tasks=background_tasks,
            )

        return JSONResponse(status_code=200, content=result)
    except NavigationEngineError as exc:
        if exc.no_route:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "no_route",
                    "message": exc.message,
                    "route_summary": None,
                    "instructions": [],
                },
            )
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message, "message": exc.message})
    except NotificationBuildError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message, "message": exc.message})
    except Exception as exc:
        logger.exception("Route calculation failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/navigate")
@router.post("/api/navigate")
@router.post("/routes")
@router.post("/api/routes")
async def calculate_route_external(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    return await _handle_calculate_route(request, db, background_tasks)


@router.post("/navigate/admin-test")
@router.post("/api/navigate/admin-test")
@router.post("/routes/admin-test")
@router.post("/api/routes/admin-test")
@router.post("/notifications/test")
@router.post("/api/notifications/test")
async def calculate_route_admin(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    return await _handle_calculate_route(request, db, background_tasks)


@router.get("/notifications")
@router.get("/api/notifications")
def get_notifications(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    rows = (
        db.query(Notification, User)
        .outerjoin(User, Notification.recipient_user_id == User.user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    out = []
    for notif, user in rows:
        out.append(
            {
                "notification_id": notif.notification_id,
                "recipient_user_id": notif.recipient_user_id,
                "recipient_name": user.full_name if user else None,
                "recipient_email": user.email if user else None,
                "event_type": notif.event_type,
                "title": notif.title,
                "body": notif.body,
                "status": notif.status,
                "message_id": notif.message_id,
                "delivery_error": notif.delivery_error,
                "created_at": notif.created_at.isoformat() if notif.created_at else None,
                "sent_at": notif.sent_at.isoformat() if notif.sent_at else None,
            }
        )
    return out


@router.get("/notification-users")
@router.get("/api/notification-users")
def get_notification_users(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    users = db.query(User).options(joinedload(User.roles)).all()
    rows = []
    for u in users:
        primary_role = u.roles[0] if u.roles else None
        rows.append(
            {
                "user_id": u.user_id,
                "full_name": u.full_name,
                "email": u.email,
                "role_id": primary_role.role_id if primary_role else 5,
                "role_name": primary_role.role_name if primary_role else "VISITOR",
            }
        )
    rows.sort(key=lambda r: (r["full_name"] or "").lower())
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# KIOSK & MOBILE WAYFINDING ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/kiosk/navigate")
@router.post("/api/kiosk/navigate")
async def kiosk_navigate(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(verify_kiosk_or_admin),
):
    body = await request.json()
    current_location = body.get("current_location") or body.get("start_node_id")
    destination_node = body.get("destination_node") or body.get("destination_node_id")
    roles_field = body.get("roles")
    rbac_role = body.get("rbac_role") or (roles_field[0] if isinstance(roles_field, list) and roles_field else "visitor")
    walking_speed = float(body.get("walking_speed") or 1.2)

    if not current_location or not destination_node:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "current_location (or start_node_id) and destination_node (or destination_node_id) are required.",
            },
        )

    try:
        nav_result = run_navigation(
            db,
            current_location=current_location,
            destination_node=destination_node,
            rbac_role=rbac_role,
            walking_speed=walking_speed,
        )
        map_context = build_visualisation_model(db, route_result=nav_result, rbac_role=rbac_role)

        base_url = get_mobile_base_url(request)
        port = os.getenv("PORT", "8000")
        visualisations = []
        try:
            temp_token = f"nav_{int(time.time() * 1000)}_{secrets.token_hex(6)}"
            generated = generate_route_visualisations(db, nav_result, temp_token)
            for v in generated:
                visualisations.append(
                    {
                        "floorplan_id": v["floorplanId"],
                        "floor_level": v["floorLevel"],
                        "building_name": v["buildingName"],
                        "filename": v["filename"],
                        "image_url": f"{base_url}/uploads/visualisations/{v['filename']}",
                        "local_image_url": f"http://127.0.0.1:{port}/uploads/visualisations/{v['filename']}",
                        "file_url": f"file:///{v['filePath'].replace(os.sep, '/')}",
                    }
                )
            nav_result["visualisations"] = visualisations
        except Exception as vis_err:
            logger.warning("Kiosk route visualizer error: %s", vis_err)

        qr_session = None
        try:
            qr_session = create_kiosk_session(
                db,
                nav_result=nav_result,
                map_context=map_context,
                start_id=current_location,
                end_id=destination_node,
                role_id=rbac_role,
                walking_speed=walking_speed,
                request=request,
            )
        except Exception as sess_err:
            logger.warning("Kiosk QR session creation error: %s", sess_err)

        return {
            "status": "success",
            "navigation": nav_result,
            "map_context": map_context,
            "qr_session": qr_session,
            "visualisations": visualisations,
        }
    except NavigationEngineError as exc:
        return JSONResponse(status_code=exc.status_code, content={"status": "error", "message": exc.message})
    except Exception as exc:
        logger.exception("Kiosk navigation failed: %s", exc)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@router.get("/kiosk/global-nodes")
@router.get("/api/kiosk/global-nodes")
def kiosk_global_nodes(
    role: str = "",
    db: Session = Depends(get_db),
    _: None = Depends(verify_kiosk_or_admin),
):
    if not role.strip():
        raise HTTPException(status_code=400, detail="Role is required to fetch global nodes in kiosk view.")
    user_role_id = resolve_role_id(role)

    rows = (
        db.query(Node)
        .join(Floorplan, Node.floorplan_id == Floorplan.floorplan_id)
        .join(Building, Floorplan.building_id == Building.building_id)
        .options(joinedload(Node.floorplan).joinedload(Floorplan.building))
        .filter(Node.is_accessible != "DENY")
        .order_by(Building.building_name.asc(), Floorplan.floor_level.asc(), Node.room_label.asc())
        .all()
    )
    node_ids = [n.node_id for n in rows]
    roles_map: dict[int, list[int]] = {}
    if node_ids:
        for nr in db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(node_ids)).all():
            roles_map.setdefault(nr.node_id, []).append(nr.role_id)

    filtered = []
    for n in rows:
        if is_role_permitted(n.is_accessible, roles_map.get(n.node_id, []), user_role_id):
            filtered.append(
                {
                    "node_id": n.node_id,
                    "room_label": n.room_label,
                    "node_type": n.node_type,
                    "floorplan_id": n.floorplan_id,
                    "floor_level": n.floorplan.floor_level if n.floorplan else 0,
                    "building_name": n.floorplan.building.building_name
                    if (n.floorplan and n.floorplan.building)
                    else "",
                }
            )
    return filtered


@router.get("/kiosk/roles")
@router.get("/api/kiosk/roles")
def kiosk_roles(db: Session = Depends(get_db), _: None = Depends(verify_kiosk_or_admin)):
    return get_roles(db)


@router.get("/kiosk/session/{token}")
@router.get("/api/kiosk/session/{token}")
@router.get("/mobile-session/{token}")
@router.get("/api/mobile-session/{token}")
def get_mobile_session(token: str, db: Session = Depends(get_db)):
    session = get_kiosk_session(db, token)
    if not session:
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "error": "SESSION_EXPIRED_OR_NOT_FOUND",
                "message": "This navigation session has expired or is invalid. Please calculate a new route on the kiosk.",
            },
        )
    return {
        "status": "success",
        "navigation": session["navigation"],
        "map_context": session["map_context"],
        "session_info": {
            "start_id": session["current_location"],
            "destination_id": session["destination_node"],
            "rbac_role": session["rbac_role"],
            "walking_speed": session["walking_speed"],
            "created_at": session["created_at"],
            "expires_at": session["expires_at"],
        },
    }


@router.get("/mobile-route/{token}", response_class=HTMLResponse)
@router.get("/api/mobile-route/{token}", response_class=HTMLResponse)
@public_router.get("/mobile-route/{token}", response_class=HTMLResponse)
def mobile_route_page(token: str, db: Session = Depends(get_db)):
    session = get_kiosk_session(db, token)
    status_code, html_body = render_mobile_route_html(session, token)
    return HTMLResponse(content=html_body, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# SAFE FLOORPLAN, VISUALISATION & QR ASSET SERVING
# ─────────────────────────────────────────────────────────────────────────────


def _serve_mapping_upload(subpath: str) -> FileResponse:
    clean = subpath.lstrip("/").replace("\\", "/")
    if ".." in clean.split("/"):
        raise HTTPException(status_code=400, detail="Invalid asset path.")

    if clean.startswith("visualisations/"):
        filename = Path(clean).name
        target = get_visualisations_dir() / filename
        if target.is_file():
            return FileResponse(target)
    elif clean.startswith("qr_codes/"):
        filename = Path(clean).name
        target = get_qr_codes_dir() / filename
        if target.is_file():
            return FileResponse(target)
    else:
        target = resolve_floorplan_image_path(clean)
        if target and target.is_file():
            return FileResponse(target)

    raise HTTPException(status_code=404, detail="Mapping asset not found.")


@router.get("/uploads/{subpath:path}")
@public_router.get("/uploads/{subpath:path}")
def serve_mapping_upload(subpath: str):
    return _serve_mapping_upload(subpath)
