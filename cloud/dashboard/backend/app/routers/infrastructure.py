from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, or_, exists
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import requests

from app.core.database import get_db
from app.core.config import settings
from app.core.audit import record_audit
from app.core.device_auth import generate_device_secret, encrypt_device_secret, require_signed_device_request, bind_device_id
from app.core.private_storage import safe_existing_path
from app.core.security import verify_super_admin, verify_system_admin, get_current_admin
from app.models.models import (
    Device, DeviceRBAC, NodeRBAC, EdgeRBAC, JWTSession, AuthenticationLog, SurveillanceLog,
    Node, Role, Edge, User, UserRole, Admin, Floorplan, Building, Course, UploadedDocument,
    UserFaceEmbedding, AdministratorAuditEvent, Visitor,
)
from app.schemas import schemas

try:
    import sys as _sys, os as _os
    _cloud_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "..", ".."))
    if _cloud_root not in _sys.path:
        _sys.path.insert(0, _cloud_root)
    from sync.cloud_to_edge.cloud_sync_service import (
        push_sync_to_all_edges,
        is_device_ws_connected,
        push_rotate_secret_to_edge,
        push_access_config_to_edge,
    )
except Exception:
    try:
        from cloud_sync_service import (
            push_sync_to_all_edges,
            is_device_ws_connected,
            push_rotate_secret_to_edge,
            push_access_config_to_edge,
        )
    except Exception:
        push_sync_to_all_edges = None
        is_device_ws_connected = None
        push_rotate_secret_to_edge = None
        push_access_config_to_edge = None

router = APIRouter(prefix="/infra", tags=["Infrastructure & Access Control"])

PAIRING_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_CODE_TTL_MINUTES = 15
_CLAIM_RATE_LIMIT_LOCK = threading.Lock()
_CLAIM_RATE_LIMIT_BUCKETS: dict[str, list[float]] = {}
_CLAIM_RATE_LIMIT_WINDOW_SEC = 60.0
_CLAIM_RATE_LIMIT_MAX_ATTEMPTS = 12


def _normalize_pairing_code(raw: str) -> str:
    cleaned = "".join(ch for ch in (raw or "").upper().strip() if ch.isalnum())
    return cleaned


def _generate_pairing_code() -> str:
    chars = "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def _hash_pairing_code(code: str) -> str:
    return hashlib.sha256(_normalize_pairing_code(code).encode("utf-8")).hexdigest()


def _public_cloud_url(request: Optional[Request]) -> str:
    configured = (os.getenv("PUBLIC_CLOUD_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    if request is None:
        return ""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    if host:
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _render_qr_svg_data_uri(payload_str: str) -> Optional[str]:
    """Encode payload_str as a crisp QR SVG data URI using OpenCV's built-in QRCodeEncoder."""
    try:
        import cv2
        encoder = cv2.QRCodeEncoder_create()
        matrix = encoder.encode(payload_str)
        if matrix is None or matrix.size == 0:
            return None
        rows, cols = matrix.shape[:2]
        quiet = 4
        total_w = cols + quiet * 2
        total_h = rows + quiet * 2
        rects = []
        for r in range(rows):
            for c in range(cols):
                if int(matrix[r, c]) == 0:
                    rects.append(f'<rect x="{c + quiet}" y="{r + quiet}" width="1" height="1"/>')
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" shape-rendering="crispEdges">'
            f'<rect width="{total_w}" height="{total_h}" fill="#ffffff"/>'
            f'<g fill="#0f172a">{"".join(rects)}</g>'
            f"</svg>"
        )
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"
    except Exception:
        return None


def _check_claim_rate_limit(client_key: str) -> None:
    now = time.monotonic()
    with _CLAIM_RATE_LIMIT_LOCK:
        bucket = [ts for ts in _CLAIM_RATE_LIMIT_BUCKETS.get(client_key, []) if now - ts < _CLAIM_RATE_LIMIT_WINDOW_SEC]
        if len(bucket) >= _CLAIM_RATE_LIMIT_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many pairing attempts; please wait a minute and try again.")
        bucket.append(now)
        _CLAIM_RATE_LIMIT_BUCKETS[client_key] = bucket


def _serialize_device_response(d: Device) -> schemas.DeviceResponse:
    resp = schemas.DeviceResponse.model_validate(d)
    resp.allowed_role_ids = [r.role_id for r in d.device_rbac]
    resp.ws_connected = bool(is_device_ws_connected(d.device_id)) if callable(is_device_ws_connected) else False
    if d.telemetry_json:
        try:
            resp.telemetry = json.loads(d.telemetry_json)
        except Exception:
            resp.telemetry = None
    return resp


def _attach_pairing_bundle(resp: schemas.DeviceResponse, pairing_code: str, expires_at: datetime, request: Optional[Request]) -> None:
    cloud_url = _public_cloud_url(request)
    qr_payload = json.dumps({"cloud_url": cloud_url, "code": pairing_code}, separators=(",", ":"))
    resp.pairing_code = pairing_code
    resp.pairing_expires_at = expires_at
    resp.pairing_qr_payload = qr_payload
    resp.pairing_qr_svg_data_uri = _render_qr_svg_data_uri(qr_payload)

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
    started = time.perf_counter()
    admin_type = current_admin.admin_type
    now = datetime.utcnow()
    online_cutoff = now - timedelta(minutes=5)
    since_24h = now - timedelta(hours=24)

    stats = {
        "users": 0,
        "active_users": 0,
        "inactive_users": 0,
        "face_enrolled_users": 0,
        "devices": 0,
        "online_devices": 0,
        "offline_devices": 0,
        "documents": 0,
        "courses": 0,
        "active_sessions": 0,
        "auth_attempts_24h": 0,
        "auth_failures_24h": 0,
        "db_latency_ms": 0.0,
    }
    if admin_type != "CONTENT_ADMIN":
        total_users = db.query(func.count(User.user_id)).scalar() or 0
        active_users = db.query(func.count(User.user_id)).filter(User.is_active.is_(True)).scalar() or 0
        face_enrolled_users = db.query(func.count(func.distinct(UserFaceEmbedding.user_id))).scalar() or 0
        total_devices = db.query(func.count(Device.device_id)).scalar() or 0
        online_devices = (
            db.query(func.count(Device.device_id))
            .filter(Device.is_active.is_(True), Device.last_heartbeat.isnot(None), Device.last_heartbeat >= online_cutoff)
            .scalar()
            or 0
        )
        stats["users"] = total_users
        stats["active_users"] = active_users
        stats["inactive_users"] = max(0, total_users - active_users)
        stats["face_enrolled_users"] = face_enrolled_users
        stats["devices"] = total_devices
        stats["online_devices"] = online_devices
        stats["offline_devices"] = max(0, total_devices - online_devices)
        stats["courses"] = db.query(func.count(Course.course_id)).scalar() or 0
        stats["active_sessions"] = (
            db.query(func.count(JWTSession.session_id))
            .filter(JWTSession.is_revoked.is_(False), JWTSession.expires_at > now)
            .scalar()
            or 0
        )
        stats["auth_attempts_24h"] = (
            db.query(func.count(AuthenticationLog.log_id))
            .filter(AuthenticationLog.timestamp >= since_24h)
            .scalar()
            or 0
        )
        stats["auth_failures_24h"] = (
            db.query(func.count(AuthenticationLog.log_id))
            .filter(AuthenticationLog.timestamp >= since_24h, AuthenticationLog.auth_status != "SUCCESS")
            .scalar()
            or 0
        )
    if admin_type != "SYSTEM_ADMIN":
        stats["documents"] = db.query(func.count(UploadedDocument.document_id)).scalar() or 0
    stats["db_latency_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
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
def list_devices(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    devices = db.query(Device).options(joinedload(Device.device_rbac)).all()
    return [_serialize_device_response(d) for d in devices]


@router.post("/devices/claim", response_model=schemas.DeviceClaimResponse)
def claim_device(
    payload: schemas.DeviceClaimRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Unauthenticated one-time pairing-code exchange for edge devices (Access Control & Surveillance)."""
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    _check_claim_rate_limit(client_ip)

    normalized = _normalize_pairing_code(payload.pairing_code)
    if len(normalized) < 6:
        raise HTTPException(status_code=400, detail="Invalid pairing code format")

    code_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    now = datetime.utcnow()
    device = (
        db.query(Device)
        .filter(
            Device.pairing_code_hash == code_hash,
            Device.is_active.is_(True),
        )
        .first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="Invalid or already used pairing code")
    if device.pairing_expires_at is None or device.pairing_expires_at < now:
        device.pairing_code_hash = None
        db.commit()
        raise HTTPException(status_code=410, detail="Pairing code has expired; generate a new code in the dashboard")

    fresh_secret = generate_device_secret()
    device.device_secret_ciphertext = encrypt_device_secret(fresh_secret)
    device.credential_rotated_at = now
    device.pairing_code_hash = None
    device.pairing_expires_at = None
    device.pairing_claimed_at = now
    device.last_heartbeat = now
    if payload.device_name and payload.device_name.strip() and not device.device_name:
        device.device_name = payload.device_name.strip()
    if payload.embedding_model or payload.app_version:
        telemetry = {}
        if device.telemetry_json:
            try:
                telemetry = json.loads(device.telemetry_json)
            except Exception:
                telemetry = {}
        if payload.embedding_model:
            telemetry["embedding_model"] = payload.embedding_model
        if payload.app_version:
            telemetry["app_version"] = payload.app_version
        telemetry["claimed_at"] = now.replace(tzinfo=timezone.utc).isoformat()
        device.telemetry_json = json.dumps(telemetry)

    db.commit()
    db.refresh(device)
    if push_sync_to_all_edges and background_tasks:
        background_tasks.add_task(push_sync_to_all_edges)

    return schemas.DeviceClaimResponse(
        device_id=device.device_id,
        device_name=device.device_name,
        device_type=getattr(device.device_type, "value", str(device.device_type)),
        node_id=device.node_id,
        device_secret=fresh_secret,
        server_utc_time=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/devices/{device_id}", response_model=schemas.DeviceResponse)
def get_device(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    device = db.query(Device).options(joinedload(Device.device_rbac)).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return _serialize_device_response(device)


@router.post("/devices", response_model=schemas.DeviceResponse)
def create_device(
    device_in: schemas.DeviceCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_system_admin),
):
    device_id = device_in.device_id or _generate_device_id(db, device_in.device_type)
    existing = db.query(Device).filter_by(device_id=device_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Device ID already registered")
        
    # Check node exists
    node = db.query(Node).filter_by(node_id=device_in.node_id).first()
    if not node:
        raise HTTPException(status_code=400, detail="Node ID does not exist")
    provisioned_secret = generate_device_secret()
    pairing_code = _generate_pairing_code()
    now = datetime.utcnow()
    pairing_expires_at = now + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)
    device = Device(
        device_id=device_id,
        device_name=device_in.device_name,
        node_id=device_in.node_id,
        device_type=device_in.device_type,
        ip_address=device_in.ip_address,
        is_active=device_in.is_active,
        installed_at=now,
        device_secret_ciphertext=encrypt_device_secret(provisioned_secret),
        credential_rotated_at=now,
        pairing_code_hash=_hash_pairing_code(pairing_code),
        pairing_expires_at=pairing_expires_at,
        pairing_claimed_at=None,
    )
    db.add(device)
    db.flush()

    if device_in.allowed_role_ids:
        for r_id in device_in.allowed_role_ids:
            role = db.query(Role).filter_by(role_id=r_id).first()
            if role:
                db.add(DeviceRBAC(device_id=device.device_id, role_id=r_id))

    db.commit()
    db.refresh(device)
    resp = _serialize_device_response(device)
    resp.provisioned_secret = provisioned_secret
    _attach_pairing_bundle(resp, pairing_code, pairing_expires_at, request)
    if push_sync_to_all_edges and background_tasks:
        background_tasks.add_task(push_sync_to_all_edges)
    return resp


@router.post("/devices/{device_id}/pairing-code", response_model=schemas.DeviceResponse)
def issue_device_pairing_code(
    device_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_system_admin),
):
    """Generate a fresh 15-minute one-time pairing code & QR payload to pair or re-pair a device."""
    device = db.query(Device).options(joinedload(Device.device_rbac)).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    pairing_code = _generate_pairing_code()
    expires_at = datetime.utcnow() + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)
    device.pairing_code_hash = _hash_pairing_code(pairing_code)
    device.pairing_expires_at = expires_at
    device.pairing_claimed_at = None
    db.commit()
    db.refresh(device)
    resp = _serialize_device_response(device)
    _attach_pairing_bundle(resp, pairing_code, expires_at, request)
    return resp


@router.get("/devices/{device_id}/access-config", response_model=schemas.AccessControlConfigSchema)
def get_device_access_config(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    """Retrieve the cloud-managed Access Control settings (merged with defaults) for a device."""
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    saved = {}
    if getattr(device, "access_config_json", None):
        try:
            saved = json.loads(device.access_config_json)
        except Exception:
            saved = {}
    return schemas.AccessControlConfigSchema(**saved)


@router.put("/devices/{device_id}/access-config")
def update_device_access_config(
    device_id: str,
    config_in: schemas.AccessControlConfigSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_system_admin),
):
    """Save per-device Access Control thresholds/variables and push them live to the edge device."""
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    config_dict = config_in.model_dump()
    device.access_config_json = json.dumps(config_dict, separators=(",", ":"))
    db.commit()
    pushed_over_ws = (
        bool(push_access_config_to_edge(device.device_id, config_dict))
        if callable(push_access_config_to_edge)
        else False
    )
    if push_sync_to_all_edges and background_tasks and not pushed_over_ws:
        background_tasks.add_task(push_sync_to_all_edges)
    return {
        "device_id": device.device_id,
        "access_config": config_dict,
        "pushed_over_ws": pushed_over_ws,
    }


@router.post("/devices/{device_id}/rotate-credential")
def rotate_device_credential(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    secret = generate_device_secret()
    device.device_secret_ciphertext = encrypt_device_secret(secret)
    device.credential_rotated_at = datetime.utcnow()
    db.commit()
    pushed_over_ws = bool(push_rotate_secret_to_edge(device.device_id, secret)) if callable(push_rotate_secret_to_edge) else False
    return {
        "device_id": device.device_id,
        "provisioned_secret": secret,
        "pushed_over_ws": pushed_over_ws,
        "warning": "Store this secret in deployment secret storage; it will not be shown again.",
    }

@router.put("/devices/{device_id}", response_model=schemas.DeviceResponse)
def update_device(device_id: str, device_in: schemas.DeviceUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
        
    # Check node if updated
    if device_in.node_id is not None:
        node = db.query(Node).filter_by(node_id=device_in.node_id).first()
        if not node:
            raise HTTPException(status_code=400, detail="Node ID does not exist")
            
    for field, val in device_in.model_dump(exclude_unset=True, exclude={"allowed_role_ids"}).items():
        setattr(device, field, val)

    if device_in.allowed_role_ids is not None:
        db.query(DeviceRBAC).filter_by(device_id=device_id).delete()
        for r_id in device_in.allowed_role_ids:
            role = db.query(Role).filter_by(role_id=r_id).first()
            if role:
                db.add(DeviceRBAC(device_id=device_id, role_id=r_id))
        
    db.commit()
    db.refresh(device)
    resp = schemas.DeviceResponse.model_validate(device)
    resp.allowed_role_ids = [r.role_id for r in device.device_rbac]
    if push_sync_to_all_edges and background_tasks:
        background_tasks.add_task(push_sync_to_all_edges)
    return resp

@router.post("/devices/{device_id}/heartbeat")
def record_heartbeat(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    now = datetime.utcnow()
    ws_online = bool(is_device_ws_connected(device_id)) if callable(is_device_ws_connected) else False
    recent_inbound = bool(device.last_heartbeat and (now - device.last_heartbeat).total_seconds() <= 120)
    if ws_online or recent_inbound:
        if ws_online:
            device.last_heartbeat = now
            db.commit()
            db.refresh(device)
        return {
            "device_id": device_id,
            "status": "active",
            "last_heartbeat": device.last_heartbeat,
            "ws_connected": ws_online,
            "mode": "websocket" if ws_online else "inbound_heartbeat",
        }

    if not (device.ip_address or "").strip():
        raise HTTPException(status_code=502, detail="Device is offline (no active WebSocket or recent heartbeat).")

    base_url = _device_base_url(device.ip_address)
    probe = _probe_device(base_url)
    if not probe["ok"]:
        raise HTTPException(
            status_code=502,
            detail="Device is offline."
        )

    device.last_heartbeat = now
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
def delete_device(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
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
# DEVICE RBAC CLEARANCE MATRIX CRUD
# ==========================================
@router.get("/device-rbac", response_model=List[schemas.DeviceRBACBase])
def list_device_rbac(device_id: Optional[str] = None, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    query = db.query(DeviceRBAC)
    if device_id:
        query = query.filter_by(device_id=device_id)
    return query.all()

@router.post("/device-rbac", response_model=schemas.DeviceRBACBase)
def grant_device_clearance(rbac_in: schemas.DeviceRBACBase, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    device = db.query(Device).filter_by(device_id=rbac_in.device_id).first()
    if not device:
        raise HTTPException(status_code=400, detail="Device not found")
    role = db.query(Role).filter_by(role_id=rbac_in.role_id).first()
    if not role:
        raise HTTPException(status_code=400, detail="Role not found")
        
    existing = db.query(DeviceRBAC).filter_by(device_id=rbac_in.device_id, role_id=rbac_in.role_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Device clearance rule already exists")
        
    rbac = DeviceRBAC(device_id=rbac_in.device_id, role_id=rbac_in.role_id)
    db.add(rbac)
    db.commit()
    if push_sync_to_all_edges and background_tasks:
        background_tasks.add_task(push_sync_to_all_edges)
    return rbac

@router.delete("/device-rbac/{device_id}/{role_id}")
def revoke_device_clearance(device_id: str, role_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    rbac = db.query(DeviceRBAC).filter_by(device_id=device_id, role_id=role_id).first()
    if not rbac:
        raise HTTPException(status_code=404, detail="Device clearance rule not found")
    db.delete(rbac)
    db.commit()
    if push_sync_to_all_edges and background_tasks:
        background_tasks.add_task(push_sync_to_all_edges)
    return {"detail": "Device clearance rule revoked successfully"}

@router.put("/devices/{device_id}/rbac", response_model=List[int])
def set_device_clearance(device_id: str, role_ids: List[int], background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    device = db.query(Device).filter_by(device_id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.query(DeviceRBAC).filter_by(device_id=device_id).delete()
    for r_id in role_ids:
        role = db.query(Role).filter_by(role_id=r_id).first()
        if role:
            db.add(DeviceRBAC(device_id=device_id, role_id=r_id))
    db.commit()
    if push_sync_to_all_edges and background_tasks:
        background_tasks.add_task(push_sync_to_all_edges)
    return role_ids

# ==========================================
# NODE RBAC CLEARANCE MATRIX CRUD
# ==========================================
@router.get("/node-rbac", response_model=List[schemas.NodeRBACBase])
def list_node_rbac(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(NodeRBAC).all()

@router.post("/node-rbac", response_model=schemas.NodeRBACBase)
def grant_node_clearance(rbac_in: schemas.NodeRBACBase, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
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
def revoke_node_clearance(node_id: int, role_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
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
def list_edge_rbac(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    return db.query(EdgeRBAC).all()

@router.post("/edge-rbac", response_model=schemas.EdgeRBACBase)
def grant_edge_clearance(rbac_in: schemas.EdgeRBACBase, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
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
def revoke_edge_clearance(edge_id: int, role_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
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
    current_admin=Depends(verify_system_admin)
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
    current_admin=Depends(verify_system_admin)
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
    current_admin=Depends(verify_system_admin)
):
    query = db.query(SurveillanceLog)
    if email is not None:
        query = query.join(User).filter(User.email == email)
    return query.order_by(SurveillanceLog.timestamp.desc()).offset(skip).limit(limit).all()


@router.get("/auth-logs/{log_id}/image", include_in_schema=False)
def download_auth_log_image(log_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    """Serve private snapshot image captured for an unknown or spoofing access attempt."""
    log = db.query(AuthenticationLog).filter_by(log_id=log_id).first()
    if not log or not log.image_path:
        raise HTTPException(status_code=404, detail="Access log snapshot not found")
    path = safe_existing_path("auth_logs", log.image_path)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@router.get("/surveillance-logs/{log_id}/image", include_in_schema=False)
def download_surveillance_image(log_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    log = db.query(SurveillanceLog).filter_by(log_id=log_id).first()
    if not log or not log.image_path:
        raise HTTPException(status_code=404, detail="Surveillance image not found")
    path = safe_existing_path("surveillance", log.image_path)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"})

@router.get("/last-known-locations", response_model=List[schemas.LastKnownLocationResponse])
def list_last_known_locations(
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_system_admin),
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
    device: Device = Depends(require_signed_device_request),
    db: Session = Depends(get_db)
):
    """Compatibility shim; signed device identity is authoritative."""
    bind_device_id(log_in.device_id, device)
    if log_in.auth_status not in {"SUCCESS", "FAILED", "SPOOFING"}:
        raise HTTPException(status_code=422, detail="Invalid authentication status")
    if log_in.user_id is not None and not db.query(User).filter_by(user_id=log_in.user_id).first():
        raise HTTPException(status_code=422, detail="Unknown user")
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
        device_id=device.device_id,
        auth_status=auth_status or "FAILED",
        confidence_score=log_in.confidence_score,
        face_count=log_in.face_count,
        reason=log_in.reason,
        spoofing_checked=log_in.spoofing_checked,
        spoofing_passed=log_in.spoofing_passed,
        image_path=log_in.image_path,
        node_id=device.node_id,
        policy_version=log_in.policy_version,
        decision_reason=log_in.decision_reason,
        correlation_id=log_in.correlation_id,
        timestamp=datetime.utcnow()
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ==========================================
# ENTERPRISE OPERATIONS: EXCEPTIONS, DEVICE DETAIL, RBAC MATRIX & PAGINATED LOGS
# ==========================================
@router.get("/overview-exceptions")
def get_overview_exceptions(db: Session = Depends(get_db), current_admin=Depends(get_current_admin)):
    now = datetime.utcnow()
    online_cutoff = now - timedelta(minutes=5)
    since_24h = now - timedelta(hours=24)
    expiry_cutoff = now + timedelta(hours=48)

    alerts = []
    if current_admin.admin_type != "CONTENT_ADMIN":
        offline_devices = (
            db.query(Device)
            .filter(Device.is_active.is_(True), or_(Device.last_heartbeat.is_(None), Device.last_heartbeat < online_cutoff))
            .limit(10)
            .all()
        )
        if offline_devices:
            alerts.append({
                "id": "offline-devices",
                "severity": "critical",
                "title": f"{len(offline_devices)} active device(s) offline",
                "description": ", ".join(d.device_name for d in offline_devices[:4]) + ("..." if len(offline_devices) > 4 else ""),
                "action_label": "Inspect Devices",
                "action_path": "/dashboard/devices",
            })

        spoof_24h = (
            db.query(func.count(AuthenticationLog.log_id))
            .filter(AuthenticationLog.timestamp >= since_24h, AuthenticationLog.auth_status == "SPOOFING")
            .scalar()
            or 0
        )
        if spoof_24h > 0:
            alerts.append({
                "id": "spoofing-alerts",
                "severity": "critical",
                "title": f"{spoof_24h} spoofing attempt(s) detected in 24h",
                "description": "Review failed liveness checks in Access Logs.",
                "action_label": "Review Spoof Logs",
                "action_path": "/dashboard/access-logs?status=SPOOFING",
            })

        face_exists = exists().where(UserFaceEmbedding.user_id == User.user_id)
        unenrolled_active = (
            db.query(func.count(User.user_id))
            .filter(User.is_active.is_(True), ~face_exists)
            .scalar()
            or 0
        )
        if unenrolled_active > 0:
            alerts.append({
                "id": "unenrolled-users",
                "severity": "warning",
                "title": f"{unenrolled_active} active user(s) missing Face ID",
                "description": "These accounts cannot unlock biometric doors until enrolled.",
                "action_label": "View Unenrolled",
                "action_path": "/dashboard/users?status=ACTIVE&face_status=NOT_ENROLLED",
            })

        expiring_visitors = (
            db.query(func.count(Visitor.visitor_id))
            .filter(Visitor.access_expiry.isnot(None), Visitor.access_expiry <= expiry_cutoff)
            .scalar()
            or 0
        )
        if expiring_visitors > 0:
            alerts.append({
                "id": "expiring-visitors",
                "severity": "info",
                "title": f"{expiring_visitors} visitor pass(es) expired or expiring within 48h",
                "description": "Verify whether temporary visitor credentials should be extended or deactivated.",
                "action_label": "Review Visitors",
                "action_path": "/dashboard/users?role_id=5",
            })

    # 7-day auth activity time series
    series = []
    if current_admin.admin_type != "CONTENT_ADMIN":
        start_day = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        logs = (
            db.query(AuthenticationLog.timestamp, AuthenticationLog.auth_status)
            .filter(AuthenticationLog.timestamp >= start_day)
            .all()
        )
        buckets = {}
        for i in range(7):
            day_key = (start_day + timedelta(days=i)).strftime("%Y-%m-%d")
            buckets[day_key] = {"date": day_key, "label": (start_day + timedelta(days=i)).strftime("%b %d"), "success": 0, "failed": 0}
        for ts, st in logs:
            if not ts:
                continue
            key = ts.strftime("%Y-%m-%d")
            if key in buckets:
                if st == "SUCCESS":
                    buckets[key]["success"] += 1
                else:
                    buckets[key]["failed"] += 1
        series = list(buckets.values())

    return {"alerts": alerts, "auth_series_7d": series}


@router.get("/devices/{device_id}/detail")
def get_device_detail(device_id: str, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    dev = (
        db.query(Device)
        .options(
            joinedload(Device.device_rbac),
            joinedload(Device.node).joinedload(Node.floorplan).joinedload(Floorplan.building),
        )
        .filter(Device.device_id == device_id)
        .first()
    )
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")

    now = datetime.utcnow()
    since_24h = now - timedelta(hours=24)
    online_cutoff = now - timedelta(minutes=5)
    is_online = bool(dev.is_active and dev.last_heartbeat and dev.last_heartbeat >= online_cutoff)

    recent_logs = (
        db.query(AuthenticationLog)
        .options(joinedload(AuthenticationLog.user))
        .filter(AuthenticationLog.device_id == device_id)
        .order_by(AuthenticationLog.timestamp.desc())
        .limit(25)
        .all()
    )
    attempts_24h = db.query(func.count(AuthenticationLog.log_id)).filter(
        AuthenticationLog.device_id == device_id, AuthenticationLog.timestamp >= since_24h
    ).scalar() or 0
    failures_24h = db.query(func.count(AuthenticationLog.log_id)).filter(
        AuthenticationLog.device_id == device_id,
        AuthenticationLog.timestamp >= since_24h,
        AuthenticationLog.auth_status != "SUCCESS",
    ).scalar() or 0

    node_rbac_ids = [r.role_id for r in db.query(NodeRBAC).filter_by(node_id=dev.node_id).all()]
    dev_rbac_ids = [r.role_id for r in (dev.device_rbac or [])]

    return {
        "device": {
            "device_id": dev.device_id,
            "device_name": dev.device_name,
            "device_type": dev.device_type,
            "node_id": dev.node_id,
            "room_label": dev.node.room_label if dev.node else None,
            "floor_level": dev.node.floorplan.floor_level if dev.node and dev.node.floorplan else None,
            "building_name": dev.node.floorplan.building.building_name if dev.node and dev.node.floorplan and dev.node.floorplan.building else None,
            "ip_address": dev.ip_address,
            "callback_url": dev.callback_url,
            "is_active": dev.is_active,
            "is_online": is_online,
            "last_heartbeat": dev.last_heartbeat.isoformat() if dev.last_heartbeat else None,
            "installed_at": dev.installed_at.isoformat() if dev.installed_at else None,
            "credential_rotated_at": dev.credential_rotated_at.isoformat() if dev.credential_rotated_at else None,
            "allowed_role_ids": dev_rbac_ids,
            "inherited_node_role_ids": node_rbac_ids,
            "uses_device_override": len(dev_rbac_ids) > 0,
        },
        "metrics_24h": {
            "attempts": attempts_24h,
            "failures": failures_24h,
            "success_rate": round(((attempts_24h - failures_24h) / attempts_24h) * 100, 1) if attempts_24h else 100.0,
        },
        "recent_logs": [
            {
                "log_id": l.log_id,
                "user_id": l.user_id,
                "email": l.user.email if l.user else None,
                "full_name": l.user.full_name if l.user else "Unknown",
                "auth_status": l.auth_status,
                "confidence_score": l.confidence_score,
                "reason": l.reason or l.decision_reason,
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            }
            for l in recent_logs
        ],
    }


class RbacMatrixToggleRequest(BaseModel):
    target_type: str  # "node" | "device"
    target_id: str
    role_id: int
    allowed: bool


@router.get("/rbac-matrix")
def get_rbac_matrix(db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    roles = db.query(Role).options(selectinload(Role.users)).order_by(Role.role_id.asc()).all()
    nodes = (
        db.query(Node)
        .options(joinedload(Node.floorplan).joinedload(Floorplan.building))
        .order_by(Node.node_id.asc())
        .all()
    )
    devices = db.query(Device).options(joinedload(Device.device_rbac)).order_by(Device.device_id.asc()).all()
    node_rbac = db.query(NodeRBAC).all()

    node_map: dict[int, list[int]] = {}
    for nr in node_rbac:
        node_map.setdefault(nr.node_id, []).append(nr.role_id)

    return {
        "roles": [
            {
                "role_id": r.role_id,
                "role_name": r.role_name,
                "user_count": len(r.users or []),
            }
            for r in roles
        ],
        "nodes": [
            {
                "node_id": n.node_id,
                "room_label": n.room_label or f"Node #{n.node_id}",
                "node_type": n.node_type,
                "floor_level": n.floorplan.floor_level if n.floorplan else None,
                "building_name": n.floorplan.building.building_name if n.floorplan and n.floorplan.building else "Unassigned",
                "role_ids": sorted(node_map.get(n.node_id, [])),
            }
            for n in nodes
        ],
        "devices": [
            {
                "device_id": d.device_id,
                "device_name": d.device_name,
                "device_type": d.device_type,
                "node_id": d.node_id,
                "is_active": d.is_active,
                "role_ids": sorted([r.role_id for r in (d.device_rbac or [])]),
                "inherited_role_ids": sorted(node_map.get(d.node_id, [])),
            }
            for d in devices
        ],
    }


@router.put("/rbac-matrix/toggle")
def toggle_rbac_matrix(
    payload: RbacMatrixToggleRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_system_admin),
):
    role = db.query(Role).filter_by(role_id=payload.role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if payload.target_type == "node":
        node_id = int(payload.target_id)
        existing = db.query(NodeRBAC).filter_by(node_id=node_id, role_id=payload.role_id).first()
        if payload.allowed and not existing:
            db.add(NodeRBAC(node_id=node_id, role_id=payload.role_id))
        elif not payload.allowed and existing:
            db.delete(existing)
    elif payload.target_type == "device":
        device_id = str(payload.target_id)
        existing = db.query(DeviceRBAC).filter_by(device_id=device_id, role_id=payload.role_id).first()
        if payload.allowed and not existing:
            db.add(DeviceRBAC(device_id=device_id, role_id=payload.role_id))
        elif not payload.allowed and existing:
            db.delete(existing)
    else:
        raise HTTPException(status_code=400, detail="target_type must be 'node' or 'device'")

    record_audit(
        db,
        actor_user_id=current_admin.user_id,
        action="rbac_matrix_toggle",
        target_type=payload.target_type,
        target_id=payload.target_id,
        result="success",
        details={"role_id": payload.role_id, "role_name": role.role_name, "allowed": payload.allowed},
    )
    db.commit()
    if push_sync_to_all_edges:
        background_tasks.add_task(push_sync_to_all_edges)
    return {"ok": True, "target_type": payload.target_type, "target_id": payload.target_id, "role_id": payload.role_id, "allowed": payload.allowed}


@router.delete("/jwt-sessions/{session_id}")
def revoke_jwt_session(session_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    session = db.query(JWTSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.is_revoked = True
    record_audit(
        db,
        actor_user_id=current_admin.user_id,
        action="jwt_session_revoked",
        target_type="jwt_session",
        target_id=session_id,
        result="success",
        details={"target_user_id": session.user_id},
    )
    db.commit()
    return {"detail": "Session revoked successfully", "session_id": session_id}


@router.get("/auth-logs/paginated")
def list_auth_logs_paginated(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    q: str = Query("", max_length=120),
    auth_status: str = Query("ALL", alias="status"),
    device_id: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    role_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_admin=Depends(verify_system_admin),
):
    query = db.query(AuthenticationLog).options(
        joinedload(AuthenticationLog.user),
        joinedload(AuthenticationLog.device),
        joinedload(AuthenticationLog.node),
    )
    term = (q or "").strip()
    if term:
        pat = f"%{term}%"
        bind = db.get_bind()
        is_sqlite = bool(bind is not None and bind.dialect.name == "sqlite")
        if is_sqlite:
            full_name_expr = func.coalesce(User.given_name, "").op("||")(" ").op("||")(func.coalesce(User.family_name, ""))
            rev_name_expr = func.coalesce(User.family_name, "").op("||")(" ").op("||")(func.coalesce(User.given_name, ""))
        else:
            full_name_expr = func.concat(func.coalesce(User.given_name, ""), " ", func.coalesce(User.family_name, ""))
            rev_name_expr = func.concat(func.coalesce(User.family_name, ""), " ", func.coalesce(User.given_name, ""))
        search_clauses = [
            User.email.ilike(pat),
            User.given_name.ilike(pat),
            User.family_name.ilike(pat),
            full_name_expr.ilike(pat),
            rev_name_expr.ilike(pat),
            AuthenticationLog.device_id.ilike(pat),
            Device.device_name.ilike(pat),
            Node.room_label.ilike(pat),
            AuthenticationLog.reason.ilike(pat),
            AuthenticationLog.decision_reason.ilike(pat),
        ]
        if term.lower() in "unknown":
            search_clauses.append(AuthenticationLog.user_id.is_(None))
        query = (
            query.outerjoin(AuthenticationLog.user)
            .outerjoin(AuthenticationLog.device)
            .outerjoin(AuthenticationLog.node)
            .filter(or_(*search_clauses))
        )
    if auth_status and auth_status.upper() != "ALL":
        query = query.filter(AuthenticationLog.auth_status == auth_status.upper())
    if device_id:
        query = query.filter(AuthenticationLog.device_id == device_id)
    if user_id is not None:
        query = query.filter(AuthenticationLog.user_id == user_id)
    if role_id is not None:
        query = query.filter(
            exists().where(
                UserRole.user_id == AuthenticationLog.user_id,
                UserRole.role_id == role_id,
            )
        )
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            if len(date_from) <= 10:
                # Interpret YYYY-MM-DD in Malaysia Time (UTC+8) -> convert to UTC
                dt_from = dt_from - timedelta(hours=8)
            query = query.filter(AuthenticationLog.timestamp >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            if len(date_to) <= 10:
                # End of Malaysia day (UTC+8) -> convert to UTC
                dt_to = dt_to + timedelta(days=1) - timedelta(hours=8)
            query = query.filter(AuthenticationLog.timestamp <= dt_to)
        except ValueError:
            pass

    total = query.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    safe_page = min(page, total_pages)
    rows = query.order_by(AuthenticationLog.timestamp.desc()).offset((safe_page - 1) * page_size).limit(page_size).all()

    user_ids = {r.user_id for r in rows if r.user_id is not None}
    roles_by_user: dict[int, list[str]] = {}
    if user_ids:
        role_rows = (
            db.query(UserRole.user_id, Role.role_name)
            .join(Role, Role.role_id == UserRole.role_id)
            .filter(UserRole.user_id.in_(user_ids))
            .all()
        )
        for uid, rname in role_rows:
            roles_by_user.setdefault(uid, []).append(rname)

    return {
        "items": [
            {
                "log_id": r.log_id,
                "user_id": r.user_id,
                "email": r.user.email if r.user else "",
                "full_name": r.user.full_name if r.user else "Unknown",
                "roles": roles_by_user.get(r.user_id, []) if r.user_id is not None else [],
                "device_id": r.device_id,
                "device_name": r.device.device_name if r.device else r.device_id,
                "node_id": r.node_id,
                "node_label": r.node.room_label if r.node else None,
                "auth_status": r.auth_status,
                "confidence_score": r.confidence_score,
                "spoofing_passed": r.spoofing_passed,
                "reason": r.reason or r.decision_reason,
                "policy_version": r.policy_version,
                "has_image": bool(r.image_path and not str(r.image_path).startswith("/") and ":" not in str(r.image_path)),
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ],
        "total": total,
        "page": safe_page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/audit-events/paginated")
def list_audit_events_paginated(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    q: str = Query("", max_length=120),
    target_type: str = Query("ALL"),
    result: str = Query("ALL"),
    db: Session = Depends(get_db),
    current_admin=Depends(verify_super_admin),
):
    query = db.query(AdministratorAuditEvent)
    term = (q or "").strip()
    if term:
        pat = f"%{term}%"
        query = query.filter(
            or_(
                AdministratorAuditEvent.action.ilike(pat),
                AdministratorAuditEvent.target_type.ilike(pat),
                AdministratorAuditEvent.target_id.ilike(pat),
                AdministratorAuditEvent.source_ip.ilike(pat),
            )
        )
    if target_type and target_type.upper() != "ALL":
        query = query.filter(AdministratorAuditEvent.target_type == target_type)
    if result and result.upper() != "ALL":
        query = query.filter(AdministratorAuditEvent.result == result.lower())

    total = query.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    safe_page = min(page, total_pages)
    events = query.order_by(AdministratorAuditEvent.created_at.desc()).offset((safe_page - 1) * page_size).limit(page_size).all()

    actor_ids = {e.actor_user_id for e in events if e.actor_user_id is not None}
    actors = {
        u.user_id: {"full_name": u.full_name, "email": u.email}
        for u in (db.query(User).filter(User.user_id.in_(actor_ids)).all() if actor_ids else [])
    }

    return {
        "items": [
            {
                "event_id": e.event_id,
                "actor_user_id": e.actor_user_id,
                "actor_name": actors.get(e.actor_user_id, {}).get("full_name", "System"),
                "actor_email": actors.get(e.actor_user_id, {}).get("email", ""),
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "result": e.result,
                "correlation_id": e.correlation_id,
                "source_ip": e.source_ip,
                "details": e.details or {},
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "total": total,
        "page": safe_page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
