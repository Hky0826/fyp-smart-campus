# sync/cloud_to_edge/cloud_sync_service.py

import asyncio
import os
import sys
import base64
import hmac
import json
import logging
import datetime
import secrets
import threading
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Set
from urllib.parse import urlsplit
import numpy as np

# Add backend directory to sys.path to allow importing from app
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
import requests

from app.core.database import get_db, SessionLocal
from app.core.security import verify_super_admin, verify_system_admin
from app.models.models import User, Role, NodeRBAC, Device, DeviceRBAC, UserRole, DeletedUser, DeviceRequestNonce
from app.core.device_auth import (
    DEVICE_ID_HEADER,
    MAX_CLOCK_SKEW_SECONDS,
    NONCE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    decrypt_device_secret,
    require_signed_device_request,
    bind_device_id,
    sign_request,
)
from sync.callback_security import validate_callback_url

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CloudSyncService")


# =====================================================================
# Pydantic Schemas for API Validation
# =====================================================================

class EdgeRegistration(BaseModel):
    device_id: str = Field(..., description="Unique hardware identifier of the edge device")
    device_name: str = Field(..., description="Human-readable name of the edge device")
    node_id: int = Field(..., description="Core physical campus node ID")
    ip_address: str = Field(..., description="Local LAN IP address of the edge device")
    port: int = Field(8001, description="Port the edge device listens on for push alerts")

class UserSyncResponse(BaseModel):
    user_id: int
    face_vector_b64: Optional[str] = None
    is_active: int
    last_synced_at: str
    embeddings: Optional[List[Dict[str, Any]]] = None
    visitor_start: Optional[str] = None
    visitor_expiry: Optional[str] = None

class RoleSyncResponse(BaseModel):
    role_id: int
    role_name: str
    last_synced_at: str

class DeviceRbacSyncResponse(BaseModel):
    device_id: str
    role_id: int
    last_synced_at: str

class NodeRbacSyncResponse(BaseModel):
    node_id: int
    role_id: int
    last_synced_at: str

class NodeUserAccessSyncResponse(BaseModel):
    node_id: int
    user_id: int
    last_synced_at: str

class DeviceUserAccessSyncResponse(BaseModel):
    device_id: str
    user_id: int
    last_synced_at: str

class UserRoleSyncResponse(BaseModel):
    user_id: int
    role_id: int
    last_synced_at: str

class DeltaSyncResponse(BaseModel):
    users: List[UserSyncResponse]
    roles: List[RoleSyncResponse]
    user_roles: List[UserRoleSyncResponse]
    node_rbac: List[NodeRbacSyncResponse]
    device_rbac: List[DeviceRbacSyncResponse] = Field(default_factory=list)
    node_user_access: List[NodeUserAccessSyncResponse] = Field(default_factory=list)
    device_user_access: List[DeviceUserAccessSyncResponse] = Field(default_factory=list)
    deleted_user_ids: List[int] = Field(default_factory=list)
    timestamp: str
    node_id: Optional[int] = None
    policy_version: Optional[str] = None
    policy_synced_at: Optional[str] = None
    access_config: Optional[Dict[str, Any]] = None

class DeactivateRequest(BaseModel):
    user_id: int

# =====================================================================
# Abstract Design / Interfaces for Clean Transport Boundary Separation
# =====================================================================

class AbstractDownstreamHandler(ABC):
    """
    Abstract interface for downstream data retrieval and push dispatcher.
    Decouples database engines and transport frameworks.
    """

    @abstractmethod
    def register_edge_node(self, db: Session, registration: EdgeRegistration) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_delta_updates(self, db: Session, last_synced_at: Optional[datetime.datetime], embedding_models: Optional[Set[str]] = None) -> Dict[str, Any]:
        pass

    @abstractmethod
    def deactivate_user_and_push(self, db: Session, user_id: int, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        pass


class EdgeWebSocketRegistry:
    """Thread-safe registry of outbound edge WebSocket connections with optional Redis Pub/Sub fan-out."""

    _REDIS_CHANNEL = "edge:ws:push"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: Dict[str, tuple[WebSocket, asyncio.AbstractEventLoop]] = {}
        self._redis_started = False

    def _ensure_redis_subscriber(self) -> None:
        if self._redis_started:
            return
        redis_url = os.getenv("REDIS_URL", "").strip()
        if not redis_url:
            return
        self._redis_started = True

        def _listen() -> None:
            try:
                import redis as redis_lib
                client = redis_lib.from_url(redis_url, decode_responses=True)
                pubsub = client.pubsub()
                pubsub.subscribe(self._REDIS_CHANNEL)
                for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        envelope = json.loads(message["data"])
                        target = envelope.get("device_id")
                        payload = envelope.get("payload")
                        if target and isinstance(payload, dict):
                            self._send_local_sync(str(target), payload)
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("Redis WebSocket fan-out listener unavailable: %s", exc)

        threading.Thread(target=_listen, daemon=True, name="edge-ws-redis-sub").start()

    def register(self, device_id: str, websocket: WebSocket, loop: asyncio.AbstractEventLoop) -> None:
        self._ensure_redis_subscriber()
        with self._lock:
            self._connections[device_id] = (websocket, loop)

    def unregister(self, device_id: str, websocket: WebSocket) -> None:
        with self._lock:
            current = self._connections.get(device_id)
            if current and current[0] is websocket:
                self._connections.pop(device_id, None)

    def is_connected(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._connections

    def _send_local_sync(self, device_id: str, payload: Dict[str, Any], timeout: float = 3.0) -> bool:
        with self._lock:
            entry = self._connections.get(device_id)
        if not entry:
            return False
        websocket, loop = entry
        try:
            future = asyncio.run_coroutine_threadsafe(websocket.send_json(payload), loop)
            future.result(timeout=timeout)
            return True
        except Exception as exc:
            logger.warning("WebSocket push to %s failed: %s", device_id, exc)
            self.unregister(device_id, websocket)
            return False

    def send_json_sync(self, device_id: str, payload: Dict[str, Any], timeout: float = 3.0) -> bool:
        if self._send_local_sync(device_id, payload, timeout=timeout):
            return True
        redis_url = os.getenv("REDIS_URL", "").strip()
        if redis_url:
            try:
                import redis as redis_lib
                client = redis_lib.from_url(redis_url, decode_responses=True)
                published = client.publish(
                    self._REDIS_CHANNEL,
                    json.dumps({"device_id": device_id, "payload": payload}, separators=(",", ":")),
                )
                return bool(published)
            except Exception as exc:
                logger.warning("Redis WebSocket publish failed: %s", exc)
        return False


_WS_REGISTRY = EdgeWebSocketRegistry()


def is_device_ws_connected(device_id: str) -> bool:
    return _WS_REGISTRY.is_connected(device_id)


def push_rotate_secret_to_edge(device_id: str, new_secret: str) -> bool:
    """Push a rotated device secret over an active WebSocket so online devices update without physical re-pairing."""
    return _WS_REGISTRY.send_json_sync(device_id, {"type": "rotate_secret", "device_secret": new_secret})


def push_access_config_to_edge(device_id: str, access_config: Dict[str, Any]) -> bool:
    """Push updated Access Control thresholds/settings over an active WebSocket."""
    return _WS_REGISTRY.send_json_sync(device_id, {"type": "config_update", "access_config": access_config})


def _authenticate_device_websocket(websocket: WebSocket, db: Session) -> Optional[Device]:
    device_id = websocket.headers.get(DEVICE_ID_HEADER)
    timestamp = websocket.headers.get(TIMESTAMP_HEADER)
    nonce = websocket.headers.get(NONCE_HEADER)
    signature = websocket.headers.get(SIGNATURE_HEADER)
    if not all((device_id, timestamp, nonce, signature)):
        return None
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return None
    if abs(time.time() - timestamp_value) > MAX_CLOCK_SKEW_SECONDS:
        return None
    if len(nonce) < 16 or len(nonce) > 128:
        return None
    device = db.query(Device).filter_by(device_id=device_id, is_active=True).first()
    if not device or not device.device_secret_ciphertext:
        return None
    expected = sign_request(
        decrypt_device_secret(device.device_secret_ciphertext),
        "GET",
        websocket.url.path,
        websocket.url.query,
        timestamp,
        nonce,
        b"",
    )
    if not hmac.compare_digest(expected, signature):
        return None
    now = datetime.datetime.utcnow()
    db.query(DeviceRequestNonce).filter(DeviceRequestNonce.expires_at < now).delete(synchronize_session=False)
    if db.query(DeviceRequestNonce).filter_by(device_id=device_id, nonce=nonce).first():
        return None
    db.add(DeviceRequestNonce(device_id=device_id, nonce=nonce, expires_at=now + datetime.timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)))
    device.last_heartbeat = now
    try:
        db.commit()
    except Exception:
        db.rollback()
        return None
    return device


class EdgeNotificationDispatcher:
    """
    Handles downstream push alerts to edge devices (WebSocket-first, LAN HTTPS fallback).
    """

    @staticmethod
    def _signed_headers(device: Device, method: str, url: str, body: bytes = b"") -> Dict[str, str]:
        if not device.device_secret_ciphertext:
            raise ValueError("Device has no provisioned secret")
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        parsed = urlsplit(url)
        signature = sign_request(
            decrypt_device_secret(device.device_secret_ciphertext),
            method,
            parsed.path or "/",
            parsed.query,
            timestamp,
            nonce,
            body,
        )
        return {
            "X-Device-ID": device.device_id,
            "X-Device-Timestamp": timestamp,
            "X-Device-Nonce": nonce,
            "X-Device-Signature": signature,
        }

    @staticmethod
    def _device_target(device: Device) -> tuple[str, int]:
        if not device.callback_url:
            raise ValueError("Device has no administratively provisioned callback URL")
        parsed = urlsplit(validate_callback_url(device.callback_url))
        return parsed.hostname or "", parsed.port or 443

    @staticmethod
    def send_deactivation_push(device: Device, user_id: int) -> bool:
        """
        Dispatches an instant user deactivation command via WebSocket first,
        falling back to legacy LAN HTTPS callback if configured.
        """
        if _WS_REGISTRY.send_json_sync(device.device_id, {"type": "deactivate", "user_id": user_id, "is_active": 0}):
            logger.info("Successfully pushed deactivation via WebSocket to %s for user %s", device.device_id, user_id)
            return True
        try:
            ip_address, port = EdgeNotificationDispatcher._device_target(device)
        except ValueError as exc:
            logger.debug("Skipping legacy HTTP deactivation push for %s: %s", device.device_id, exc)
            return False
        url = f"https://{ip_address}:{port}/api/edge/deactivate"
        payload = {"user_id": user_id, "is_active": 0}
        body = json.dumps(payload, separators=(",", ":")).encode()
        try:
            logger.info(f"Dispatching instant deactivation push to {url} for user {user_id}")
            response = requests.post(url, data=body, headers={**EdgeNotificationDispatcher._signed_headers(device, "POST", url, body), "Content-Type": "application/json"}, timeout=3.0, allow_redirects=False)
            if response.status_code == 200:
                logger.info(f"Successfully pushed deactivation to edge device at {ip_address}")
                return True
            else:
                logger.warning(f"Edge device returned status code {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to connect to edge device at {ip_address}:{port}: {str(e)}")
        return False

    @staticmethod
    def send_sync_push(device: Device) -> bool:
        """
        Signals an edge device to immediately pull a delta sync from the cloud
        via WebSocket first, falling back to legacy LAN HTTPS callback.
        """
        if _WS_REGISTRY.send_json_sync(device.device_id, {"type": "trigger_sync"}):
            logger.info("Successfully pushed trigger-sync via WebSocket to %s", device.device_id)
            return True
        try:
            ip_address, port = EdgeNotificationDispatcher._device_target(device)
        except ValueError as exc:
            logger.debug("Skipping legacy HTTP sync push for %s: %s", device.device_id, exc)
            return False
        url = f"https://{ip_address}:{port}/api/edge/trigger-sync"
        try:
            logger.info(f"Dispatching trigger-sync push to edge at {ip_address}:{port}")
            response = requests.post(url, headers=EdgeNotificationDispatcher._signed_headers(device, "POST", url), timeout=3.0, allow_redirects=False)
            if response.status_code == 200:
                logger.info(f"Edge device at {ip_address}:{port} acknowledged trigger-sync.")
                return True
            else:
                logger.warning(f"Edge device at {ip_address}:{port} returned {response.status_code} for trigger-sync")
        except Exception as e:
            logger.error(f"Could not reach edge device at {ip_address}:{port} for trigger-sync: {str(e)}")
        return False


# =====================================================================
# Concrete Implementation (SQLAlchemy Database Handler)
# =====================================================================

class SQLAlchemyDownstreamHandler(AbstractDownstreamHandler):
    """
    SQLAlchemy-driven downstream synchronization handler.
    Contains transaction logic for cloud database state access.
    """

    def register_edge_node(self, db: Session, reg: EdgeRegistration) -> Dict[str, Any]:
        try:
            callback_url = validate_callback_url(f"https://{reg.ip_address}:{reg.port}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Edge callback must be an approved HTTPS destination") from exc
        # Query device by device_id
        device = db.query(Device).filter(Device.device_id == reg.device_id).first()
        if not device:
            # Create a new Device entry if not found
            device = Device(
                device_id=reg.device_id,
                device_name=reg.device_name,
                node_id=reg.node_id,
                device_type="KIOSK",
                ip_address=f"{reg.ip_address}:{reg.port}",
                callback_url=callback_url,
                is_active=True,
                last_heartbeat=datetime.datetime.utcnow()
            )
            db.add(device)
            logger.info(f"Registered new device: {reg.device_id} at {reg.ip_address}:{reg.port}")
        else:
            # Update IP address and attributes
            device.ip_address = f"{reg.ip_address}:{reg.port}"
            device.callback_url = callback_url
            device.device_name = reg.device_name
            device.node_id = reg.node_id
            device.last_heartbeat = datetime.datetime.utcnow()
            logger.info(f"Updated registered device: {reg.device_id} to {reg.ip_address}:{reg.port}")
        
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Database error registering device: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to save edge device registration metadata")
        
        return {"status": "registered", "device_id": reg.device_id}

    def _serialize_vector(self, face_vector_val: Any) -> Optional[str]:
        """
        Helper method to normalize and convert a MySQL vector database column value
        to a base64-encoded string representing float32 bytes.
        """
        if face_vector_val is None:
            return None
        
        try:
            # If the database type handler returns a JSON string representation of a list
            if isinstance(face_vector_val, str):
                import json
                cleaned = face_vector_val.strip()
                if cleaned.startswith("[") and cleaned.endswith("]"):
                    lst = json.loads(cleaned)
                    return base64.b64encode(np.array(lst, dtype=np.float32).tobytes()).decode('utf-8')
                else:
                    # Comma-separated list fallback
                    lst = [float(x) for x in cleaned.split(",") if x.strip()]
                    return base64.b64encode(np.array(lst, dtype=np.float32).tobytes()).decode('utf-8')
            # If it's a direct list
            elif isinstance(face_vector_val, list):
                return base64.b64encode(np.array(face_vector_val, dtype=np.float32).tobytes()).decode('utf-8')
            # If it's a numpy array or supports tolist
            elif hasattr(face_vector_val, "tolist"):
                return base64.b64encode(np.array(face_vector_val.tolist(), dtype=np.float32).tobytes()).decode('utf-8')
        except Exception as ex:
            logger.error(f"Failed to serialize face vector: {str(ex)}")
            
        return None

    def get_delta_updates(self, db: Session, last_synced_at: Optional[datetime.datetime], embedding_models: Optional[Set[str]] = None) -> Dict[str, Any]:
        """
        Retrieves database entries changed since last_synced_at.
        If last_synced_at is None, retrieves full dataset.
        Filters on updated_at (preferred) so photo updates and any user field
        changes are captured — not just new user enrollments.
        """
        if last_synced_at is not None and last_synced_at.tzinfo is not None:
            last_synced_at = last_synced_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        # Fetching Users — filter on updated_at so photo uploads are picked up.
        # updated_at is set by the ORM on every UPDATE (including face_vector changes).
        user_query = db.query(User).options(
            joinedload(User.embeddings),
            joinedload(User.visitor),
        )
        if last_synced_at:
            from sqlalchemy import or_
            user_query = user_query.filter(
                or_(
                    User.updated_at > last_synced_at,
                    # Safety fallback: include users whose updated_at is NULL but
                    # were enrolled after the last sync (pre-migration rows).
                    (User.updated_at == None) & (User.enrolled_at > last_synced_at)
                )
            )
        
        users_list = user_query.all()
        policy_synced_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        policy_version = policy_synced_at
        sync_users = []
        for u in users_list:
            embeddings_payload = []
            legacy_face_vector_b64 = None
            for emb in u.embeddings:
                if embedding_models is not None and emb.model_name not in embedding_models:
                    continue
                b64 = base64.b64encode(emb.embedding).decode('utf-8')
                embeddings_payload.append({
                    "template_name": emb.template_name,
                    "model_name": emb.model_name,
                    "embedding": b64
                })
                if emb.template_name == "front" and emb.model_name == "arcface_r50":
                    legacy_face_vector_b64 = b64
                elif legacy_face_vector_b64 is None:
                    legacy_face_vector_b64 = b64
            
            sync_users.append(UserSyncResponse(
                user_id=u.user_id,
                face_vector_b64=legacy_face_vector_b64,
                is_active=1 if u.is_active else 0,
                last_synced_at=u.enrolled_at.isoformat() if u.enrolled_at else datetime.datetime.utcnow().isoformat(),
                embeddings=embeddings_payload
                ,visitor_start=(u.visitor.access_start.isoformat() if u.visitor and u.visitor.access_start else (u.enrolled_at.isoformat() if u.visitor and u.enrolled_at else None))
                ,visitor_expiry=u.visitor.access_expiry.isoformat() if u.visitor else None
            ))

        # Roles and assignments are deliberately returned as complete snapshots.
        # They have no tombstone/change-sequence columns, and filtering them by a
        # user timestamp leaves the edge with stale authorization after a rename,
        # deletion, or role-only assignment edit.
        roles_list = db.query(Role).all()
        sync_roles = [
            RoleSyncResponse(
                role_id=r.role_id,
                role_name=r.role_name,
                last_synced_at=r.created_at.isoformat() if r.created_at else datetime.datetime.utcnow().isoformat()
            ) for r in roles_list
        ]

        # Fetching Resolved RBAC Rules (direct roles + access group roles + direct/group users)
        from app.services.rbac_resolver import resolve_all_device_policies, resolve_all_node_policies

        now_iso = datetime.datetime.utcnow().isoformat()
        node_policies = resolve_all_node_policies(db)
        device_policies = resolve_all_device_policies(db)

        sync_rbac = [
            NodeRbacSyncResponse(
                node_id=node_id,
                role_id=role_id,
                last_synced_at=now_iso,
            )
            for node_id, pol in sorted(node_policies.items())
            for role_id in sorted(pol["effective_role_ids"])
        ]

        sync_device_rbac = [
            DeviceRbacSyncResponse(
                device_id=device_id,
                role_id=role_id,
                last_synced_at=now_iso,
            )
            for device_id, pol in sorted(device_policies.items())
            for role_id in sorted(pol["effective_role_ids"])
        ]

        sync_node_user_access = [
            NodeUserAccessSyncResponse(
                node_id=node_id,
                user_id=user_id,
                last_synced_at=now_iso,
            )
            for node_id, pol in sorted(node_policies.items())
            for user_id in sorted(pol["effective_user_ids"])
        ]

        sync_device_user_access = [
            DeviceUserAccessSyncResponse(
                device_id=device_id,
                user_id=user_id,
                last_synced_at=now_iso,
            )
            for device_id, pol in sorted(device_policies.items())
            for user_id in sorted(pol["effective_user_ids"])
        ]

        # Assignment mappings are also a complete snapshot, independent of the
        # user delta.  This captures role-only edits and assignment removals.
        user_roles_list = db.query(UserRole).all()
        sync_user_roles = [
            UserRoleSyncResponse(
                user_id=ur.user_id,
                role_id=ur.role_id,
                last_synced_at=datetime.datetime.utcnow().isoformat()
            ) for ur in user_roles_list
        ]

        # Fetching Deleted User IDs
        deleted_query = db.query(DeletedUser)
        if last_synced_at:
            deleted_query = deleted_query.filter(DeletedUser.deleted_at > last_synced_at)
        deleted_users_list = deleted_query.all()
        deleted_user_ids = [du.user_id for du in deleted_users_list]

        return {
            "users": sync_users,
            "roles": sync_roles,
            "user_roles": sync_user_roles,
            "node_rbac": sync_rbac,
            "device_rbac": sync_device_rbac,
            "node_user_access": sync_node_user_access,
            "device_user_access": sync_device_user_access,
            "deleted_user_ids": deleted_user_ids,
            "timestamp": policy_synced_at,
            "node_id": None,
            "policy_version": policy_version,
            "policy_synced_at": policy_synced_at,
        }

    def deactivate_user_and_push(self, db: Session, user_id: int, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        """
        Administrative hook: Deactivates a user in the cloud DB and schedules LAN pushes to active edge devices.
        """
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Modify active state
        user.is_active = False
        
        try:
            db.commit()
            logger.info(f"User {user_id} successfully deactivated in cloud DB. Initializing downstream LAN pushes.")
        except Exception as e:
            db.rollback()
            logger.error(f"Error committing user deactivation: {str(e)}")
            raise HTTPException(status_code=500, detail="Database error during deactivation commit")

        # Discover active edge devices
        active_devices = db.query(Device).filter(Device.is_active == True, Device.ip_address != None).all()
        
        pushed_targets = [dev.device_id for dev in active_devices]
        if pushed_targets:
            background_tasks.add_task(push_deactivation_to_edges, pushed_targets, user_id)

        return {
            "status": "deactivated",
            "user_id": user_id,
            "pushed_to_devices": pushed_targets
        }


# =====================================================================
# FastAPI Router Mount & Injection
# =====================================================================

router = APIRouter(prefix="/sync/downstream", tags=["Database Synchronization - Downstream"])
handler: AbstractDownstreamHandler = SQLAlchemyDownstreamHandler()


def push_deactivation_to_edges(device_ids: List[str], user_id: int) -> None:
    """Background task helper: opens a fresh DB session and sends deactivation pushes."""
    if not device_ids:
        return
    db = SessionLocal()
    try:
        devices = db.query(Device).filter(
            Device.device_id.in_(device_ids),
            Device.is_active == True,
        ).all()
        for dev in devices:
            EdgeNotificationDispatcher.send_deactivation_push(dev, user_id)
    except Exception as e:
        logger.error(f"push_deactivation_to_edges failed: {str(e)}")
    finally:
        db.close()


def push_sync_to_all_edges(db: Optional[Session] = None) -> None:
    """
    Background task helper: iterates over all active edge devices and sends
    a trigger-sync push so they immediately pull the latest delta from the cloud.
    Intended to be called via FastAPI BackgroundTasks after any user update.
    """
    own_session = db is None
    session = SessionLocal() if own_session else db
    try:
        active_devices = session.query(Device).filter(
            Device.is_active == True,
        ).all()
        for dev in active_devices:
            EdgeNotificationDispatcher.send_sync_push(dev)
    except Exception as e:
        logger.error(f"push_sync_to_all_edges failed: {str(e)}")
    finally:
        if own_session:
            session.close()


@router.websocket("/ws")
async def edge_control_websocket(websocket: WebSocket):
    """Outbound device-initiated WebSocket for NAT-friendly instant revocations and sync triggers."""
    db = SessionLocal()
    device = None
    try:
        device = _authenticate_device_websocket(websocket, db)
    finally:
        db.close()

    if device is None:
        await websocket.close(code=4401, reason="Unauthorized device")
        return

    device_id = device.device_id
    await websocket.accept()
    loop = asyncio.get_running_loop()
    _WS_REGISTRY.register(device_id, websocket, loop)
    logger.info("Edge WebSocket registered for device %s", device_id)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {}
            if msg.get("type") == "ping":
                now = datetime.datetime.utcnow()
                db_hb = SessionLocal()
                try:
                    dev_row = db_hb.query(Device).filter_by(device_id=device_id).first()
                    if dev_row:
                        dev_row.last_heartbeat = now
                        db_hb.commit()
                finally:
                    db_hb.close()
                await websocket.send_json({
                    "type": "pong",
                    "server_utc_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
    except WebSocketDisconnect:
        logger.info("Edge WebSocket disconnected for device %s", device_id)
    except Exception as exc:
        logger.debug("Edge WebSocket closed for %s: %s", device_id, exc)
    finally:
        _WS_REGISTRY.unregister(device_id, websocket)

@router.post("/register", status_code=status.HTTP_200_OK)
def register_edge(registration: EdgeRegistration, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    """
    Enrolls an edge device's LAN metadata so the cloud publisher knows where to dispatch direct pushes.
    """

    return handler.register_edge_node(db, registration)

@router.get("/delta", response_model=DeltaSyncResponse)
def get_deltas(last_synced_at: Optional[str] = None, module: Optional[str] = None, device: Device = Depends(require_signed_device_request), db: Session = Depends(get_db)):
    """
    Retrieves database deltas (users, roles, permissions) modified since last_synced_at.
    Input format: ISO datetime string (e.g. 2026-06-10T00:00:00).
    """
    parsed_time = None
    if last_synced_at:
        try:
            parsed_time = datetime.datetime.fromisoformat(last_synced_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid datetime format. Please use ISO 8601 string.")
    
    model_by_module = {"access_control": {"openvc_sface"}, "surveillance": {"arcface_r50"}, "edge": {"arcface_r50"}}
    if module is not None and module not in model_by_module:
        raise HTTPException(status_code=400, detail="module must be access_control, surveillance, or edge")
    payload = handler.get_delta_updates(db, parsed_time, model_by_module.get(module))
    payload["node_id"] = device.node_id
    if getattr(device, "access_config_json", None):
        try:
            payload["access_config"] = json.loads(device.access_config_json)
        except Exception:
            payload["access_config"] = None
    return payload

@router.post("/deactivate")
def administrative_deactivate(req: DeactivateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    """
    Admin control panel endpoint: Deactivates a user profile and broadcasts immediate deactivation commands to edge nodes.
    """
    return handler.deactivate_user_and_push(db, req.user_id, background_tasks)

@router.get("/user-ids", response_model=List[int])
def get_all_user_ids(device: Device = Depends(require_signed_device_request), db: Session = Depends(get_db)):
    """
    Retrieves the complete set of user IDs currently existing in the cloud database.
    """
    users = db.query(User.user_id).all()
    return [u.user_id for u in users]


@router.post("/push-sync")
def trigger_push_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    """
    Admin / internal endpoint: immediately broadcasts a trigger-sync signal to all
    registered edge devices so they pull the latest cloud delta without waiting for
    their polling interval. Useful after bulk user updates or photo enrollments.
    """
    background_tasks.add_task(push_sync_to_all_edges)
    return {"status": "dispatched", "message": "Trigger-sync broadcast queued for all active edge devices"}
