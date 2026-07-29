from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from datetime import datetime
from urllib.parse import urlparse
import os
import secrets
import requests

from app.core.database import get_db
from app.core.config import settings
from app.core.device_auth import generate_device_secret, encrypt_device_secret
from app.core.private_storage import safe_existing_path
from app.core.security import verify_super_admin, get_current_admin
from app.models.models import Device, NodeRBAC, EdgeRBAC, JWTSession, AuthenticationLog, SurveillanceLog, Node, Role, Edge, User, Admin, Floorplan, Course, UploadedDocument
from app.schemas import schemas

router = APIRouter(prefix="/infra", tags=["Infrastructure & Access Control"])

def _device_base_url(ip_address: str) -> str:
    target = (ip_address or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="Device has no IP address configured")
    if "://" not in target:
        target = f"https://{target}"

    parsed = urlparse(target)
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Device IP address is invalid")

    host = parsed.hostname
    if parsed.scheme != "https":
        loopback = host in {"127.0.0.1", "localhost", "::1"}
        allow = settings.APP_ENV != "production" and os.getenv("ALLOW_INSECURE_LOOPBACK", "false").lower() == "true"
        if not (loopback and allow):
            raise HTTPException(status_code=400, detail="Device control URLs must use HTTPS")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port or 8001
    return f"{parsed.scheme}://{host}:{port}"

def _probe_device(base_url: str) -> dict:
    probes = [
        ("GET", f"{base_url}/health"),
        ("POST", f"{base_url}/api/edge/trigger-sync"),
    ]
    last_error = "No response from device"
    for method, url in probes:
        try:
            if method == "GET":
                response = requests.get(url, timeout=3.0)
            else:
                response = requests.post(url, timeout=3.0)
            if 200 <= response.status_code < 300:
                return {"ok": True, "url": url, "status_code": response.status_code}
            last_error = f"{url} returned HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
    return {"ok": False, "error": last_error}

@router.get("/dashboard-stats")
def get_dashboard_stats(db: Session = Depends(get_db), current_admin=Depends(get_current_admin)):
    admin_type = current_admin.admin_type
    stats = {"users": 0, "devices": 0, "documents": 0, "courses": 0}
    if admin_type != "CONTENT_ADMIN":
        stats["users"] = db.query(User).count()
        stats["devices"] = db.query(Device).count()
        stats["courses"] = db.query(Course).count()
    if admin_type != "SYSTEM_ADMIN":
        stats["documents"] = db.query(UploadedDocument).count()
    return stats

# ==========================================
# DEVICES CRUD (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
def _generate_device_id(db: Session, device_type: schemas.DeviceTypeEnum) -> str:
    prefixes = {
        "ENTRY_GATE": "ENTRY",
        "KIOSK": "KIOSK",
        "CLASSROOM": "CLASS",
        "OFFICE": "OFFICE",
        "OTHER": "EDGE",
    }
    type_name = getattr(device_type, "value", str(device_type))
    prefix = prefixes.get(type_name, "EDGE")
    for _ in range(20):
        candidate = f"{prefix}-{secrets.token_hex(4).upper()}"
        if not db.query(Device).filter_by(device_id=candidate).first():
            return candidate
    raise HTTPException(status_code=500, detail="Unable to allocate a unique device ID")


@router.get("/devices", response_model=List[schemas.DeviceResponse])
def list_devices(db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    return db.query(Device).all()

@router.post("/devices", response_model=schemas.DeviceResponse)
def create_device(device_in: schemas.DeviceCreate, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    device_id = device_in.device_id or _generate_device_id(db, device_in.device_type)
    existing = db.query(Device).filter_by(device_id=device_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Device ID already registered")
        
    # Check node exists
    node = db.query(Node).filter_by(node_id=device_in.node_id).first()
    if not node:
        raise HTTPException(status_code=400, detail="Node ID does not exist")
    provisioned_secret = generate_device_secret()
    device = Device(
        device_id=device_id,
        device_name=device_in.device_name,
        node_id=device_in.node_id,
        device_type=device_in.device_type,
        ip_address=device_in.ip_address,
        is_active=device_in.is_active,
        installed_at=datetime.utcnow(),
        device_secret_ciphertext=encrypt_device_secret(provisioned_secret),
        credential_rotated_at=datetime.utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return {**schemas.DeviceResponse.model_validate(device).model_dump(), "provisioned_secret": provisioned_secret}


@router.post("/devices/{device_id}/rotate-credential")
def rotate_device_credential(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    secret = generate_device_secret()
    device.device_secret_ciphertext = encrypt_device_secret(secret)
    device.credential_rotated_at = datetime.utcnow()
    db.commit()
    return {"device_id": device.device_id, "provisioned_secret": secret, "warning": "Store this secret in deployment secret storage; it will not be shown again."}

@router.put("/devices/{device_id}", response_model=schemas.DeviceResponse)
def update_device(device_id: str, device_in: schemas.DeviceUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
        
    # Check node if updated
    if device_in.node_id is not None:
        node = db.query(Node).filter_by(node_id=device_in.node_id).first()
        if not node:
            raise HTTPException(status_code=400, detail="Node ID does not exist")
            
    for field, val in device_in.model_dump(exclude_unset=True).items():
        setattr(device, field, val)
        
    db.commit()
    db.refresh(device)
    return device

@router.post("/devices/{device_id}/heartbeat")
def record_heartbeat(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    base_url = _device_base_url(device.ip_address)
    probe = _probe_device(base_url)
    if not probe["ok"]:
        raise HTTPException(
            status_code=502,
            detail="Device is offline."
        )

    device.last_heartbeat = datetime.utcnow()
    db.commit()
    db.refresh(device)
    return {
        "device_id": device_id,
        "status": "active",
        "last_heartbeat": device.last_heartbeat,
        "checked_url": probe["url"],
        "status_code": probe["status_code"],
    }

@router.delete("/devices/{device_id}")
def delete_device(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Authentication and surveillance logs are audit records and deliberately
    # retain their device reference. Preserve those records by deactivating a
    # device instead of deleting it when history exists.
    auth_log_count = db.query(AuthenticationLog).filter_by(device_id=device_id).count()
    surveillance_log_count = db.query(SurveillanceLog).filter_by(device_id=device_id).count()
    if auth_log_count or surveillance_log_count:
        device.is_active = False
        db.commit()
        return {
            "detail": "Device deactivated because audit logs reference it; audit history was preserved.",
            "device_id": device_id,
            "deleted": False,
            "deactivated": True,
        }

    try:
        db.delete(device)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Device cannot be deleted because another record references it. Deactivate it instead.",
        ) from exc
    return {"detail": "Device deleted successfully"}

# ==========================================
# NODE RBAC CLEARANCE MATRIX CRUD
# ==========================================
@router.get("/node-rbac", response_model=List[schemas.NodeRBACBase])
def list_node_rbac(db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    return db.query(NodeRBAC).all()

@router.post("/node-rbac", response_model=schemas.NodeRBACBase)
def grant_node_clearance(rbac_in: schemas.NodeRBACBase, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    # Verify node and role exist
    node = db.query(Node).filter_by(node_id=rbac_in.node_id).first()
    if not node:
        raise HTTPException(status_code=400, detail="Node not found")
    role = db.query(Role).filter_by(role_id=rbac_in.role_id).first()
    if not role:
        raise HTTPException(status_code=400, detail="Role not found")
        
    existing = db.query(NodeRBAC).filter_by(node_id=rbac_in.node_id, role_id=rbac_in.role_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Clearance rule already exists")
        
    rbac = NodeRBAC(node_id=rbac_in.node_id, role_id=rbac_in.role_id)
    db.add(rbac)
    db.commit()
    return rbac

@router.delete("/node-rbac/{node_id}/{role_id}")
def revoke_node_clearance(node_id: int, role_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    rbac = db.query(NodeRBAC).filter_by(node_id=node_id, role_id=role_id).first()
    if not rbac:
        raise HTTPException(status_code=404, detail="Clearance rule not found")
    db.delete(rbac)
    db.commit()
    return {"detail": "Clearance rule revoked successfully"}

# ==========================================
# EDGE RBAC CLEARANCE MATRIX CRUD
# ==========================================
@router.get("/edge-rbac", response_model=List[schemas.EdgeRBACBase])
def list_edge_rbac(db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    return db.query(EdgeRBAC).all()

@router.post("/edge-rbac", response_model=schemas.EdgeRBACBase)
def grant_edge_clearance(rbac_in: schemas.EdgeRBACBase, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    # Verify edge and role exist
    edge = db.query(Edge).filter_by(edge_id=rbac_in.edge_id).first()
    if not edge:
        raise HTTPException(status_code=400, detail="Edge not found")
    role = db.query(Role).filter_by(role_id=rbac_in.role_id).first()
    if not role:
        raise HTTPException(status_code=400, detail="Role not found")
        
    existing = db.query(EdgeRBAC).filter_by(edge_id=rbac_in.edge_id, role_id=rbac_in.role_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Path Clearance rule already exists")
        
    rbac = EdgeRBAC(edge_id=rbac_in.edge_id, role_id=rbac_in.role_id)
    db.add(rbac)
    db.commit()
    return rbac

@router.delete("/edge-rbac/{edge_id}/{role_id}")
def revoke_edge_clearance(edge_id: int, role_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    rbac = db.query(EdgeRBAC).filter_by(edge_id=edge_id, role_id=role_id).first()
    if not rbac:
        raise HTTPException(status_code=404, detail="Clearance rule not found")
    db.delete(rbac)
    db.commit()
    return {"detail": "Clearance rule revoked successfully"}

# ==========================================
# SECURITY AUDIT LOGS (SYSTEM_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/jwt-sessions", response_model=List[schemas.JWTSessionResponse])
def list_jwt_sessions(
    skip: int = 0, 
    limit: int = 50, 
    admin_id: Optional[str] = None,
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_super_admin)
):
    query = db.query(JWTSession)
    if admin_id is not None:
        query = query.join(User).join(Admin).filter(Admin.admin_id == admin_id)
    return query.order_by(JWTSession.issued_at.desc()).offset(skip).limit(limit).all()

@router.get("/auth-logs", response_model=List[schemas.AuthenticationLogResponse])
def list_auth_logs(
    skip: int = 0, 
    limit: int = 50, 
    email: Optional[str] = None,
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_super_admin)
):
    query = db.query(AuthenticationLog)
    if email is not None:
        query = query.join(User).filter(User.email == email)
    return query.order_by(AuthenticationLog.timestamp.desc()).offset(skip).limit(limit).all()

@router.get("/surveillance-logs", response_model=List[schemas.SurveillanceLogResponse])
def list_surveillance_logs(
    skip: int = 0,
    limit: int = 50,
    email: Optional[str] = None,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin)
):
    query = db.query(SurveillanceLog)
    if email is not None:
        query = query.join(User).filter(User.email == email)
    return query.order_by(SurveillanceLog.timestamp.desc()).offset(skip).limit(limit).all()


@router.get("/surveillance-logs/{log_id}/image", include_in_schema=False)
def download_surveillance_image(log_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    log = db.query(SurveillanceLog).filter_by(log_id=log_id).first()
    if not log or not log.image_path:
        raise HTTPException(status_code=404, detail="Surveillance image not found")
    path = safe_existing_path("surveillance", log.image_path)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"})

@router.get("/last-known-locations", response_model=List[schemas.LastKnownLocationResponse])
def list_last_known_locations(
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin),
):
    query = db.query(User).options(
        joinedload(User.location).joinedload(Node.floorplan).joinedload(Floorplan.building)
    )
    if active_only:
        query = query.filter(User.is_active == True)

    users = query.order_by(User.last_seen.is_(None), User.last_seen.desc(), User.user_id.asc()).all()
    results = []
    for user in users:
        node = user.location
        floorplan = node.floorplan if node is not None else None
        building = floorplan.building if floorplan is not None else None
        results.append(
            schemas.LastKnownLocationResponse(
                user_id=user.user_id,
                email=user.email,
                full_name=user.full_name,
                is_active=user.is_active,
                last_seen=user.last_seen,
                last_known_location=user.last_known_location,
                room_label=node.room_label if node is not None else None,
                floor_level=floorplan.floor_level if floorplan is not None else None,
                building_name=building.building_name if building is not None else None,
            )
        )
    return results

@router.post("/auth-logs", response_model=schemas.AuthenticationLogResponse)
def create_auth_log(
    log_in: schemas.AuthenticationLogCreate, 
    db: Session = Depends(get_db)
):
    existing = db.query(AuthenticationLog).filter_by(sync_key=log_in.sync_key).first()
    if existing:
        return existing

    user_id = log_in.user_id
    if user_id is None and log_in.email:
        user = db.query(User).filter_by(email=log_in.email).first()
        if user:
            user_id = user.user_id
            
    auth_status = log_in.auth_status
    if not auth_status and log_in.status:
        auth_status = log_in.status
        
    log = AuthenticationLog(
        sync_key=log_in.sync_key,
        user_id=user_id,
        device_id=log_in.device_id,
        auth_status=auth_status or "SUCCESS",
        confidence_score=log_in.confidence_score,
        face_count=log_in.face_count,
        reason=log_in.reason,
        spoofing_checked=log_in.spoofing_checked,
        spoofing_passed=log_in.spoofing_passed,
        image_path=log_in.image_path,
        timestamp=datetime.utcnow()
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
