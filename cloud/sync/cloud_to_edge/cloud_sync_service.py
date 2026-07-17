# sync/cloud_to_edge/cloud_sync_service.py

import os
import sys
import base64
import logging
import datetime
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import numpy as np

# Add backend directory to sys.path to allow importing from app
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import requests

from app.core.database import get_db, Base, engine
from app.core.security import verify_super_admin
from app.models.models import User, Role, NodeRBAC, Device, UserRole, DeletedUser

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CloudSyncService")

# Auto-create tables (e.g. deleted_users) if not exists
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Ensured all database tables exist (including deleted_users).")
except Exception as e:
    logger.error(f"Error ensuring database tables exist: {e}")


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

class RoleSyncResponse(BaseModel):
    role_id: int
    role_name: str
    last_synced_at: str

class NodeRbacSyncResponse(BaseModel):
    node_id: int
    role_id: int
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
    deleted_user_ids: List[int] = Field(default_factory=list)
    timestamp: str

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
    def get_delta_updates(self, db: Session, last_synced_at: Optional[datetime.datetime]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def deactivate_user_and_push(self, db: Session, user_id: int, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        pass


class EdgeNotificationDispatcher:
    """
    Handles downstream network push alerts to edge devices over the LAN.
    """

    @staticmethod
    def send_deactivation_push(ip_address: str, port: int, user_id: int) -> bool:
        """
        Dispatches an HTTP POST deactivation payload directly to the edge listener.
        """
        url = f"http://{ip_address}:{port}/api/edge/deactivate"
        payload = {"user_id": user_id, "is_active": 0}
        try:
            logger.info(f"Dispatching instant deactivation push to {url} for user {user_id}")
            response = requests.post(url, json=payload, timeout=3.0)
            if response.status_code == 200:
                logger.info(f"Successfully pushed deactivation to edge device at {ip_address}")
                return True
            else:
                logger.warning(f"Edge device returned status code {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to connect to edge device at {ip_address}:{port}: {str(e)}")
        return False

    @staticmethod
    def send_sync_push(ip_address: str, port: int) -> bool:
        """
        Signals an edge device to immediately pull a delta sync from the cloud.
        Called after any cloud-side user change (e.g. photo upload) so the edge
        picks up the update without waiting for the next polling cycle.
        """
        url = f"http://{ip_address}:{port}/api/edge/trigger-sync"
        try:
            logger.info(f"Dispatching trigger-sync push to edge at {ip_address}:{port}")
            response = requests.post(url, timeout=3.0)
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
                is_active=True,
                last_heartbeat=datetime.datetime.utcnow()
            )
            db.add(device)
            logger.info(f"Registered new device: {reg.device_id} at {reg.ip_address}:{reg.port}")
        else:
            # Update IP address and attributes
            device.ip_address = f"{reg.ip_address}:{reg.port}"
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

    def get_delta_updates(self, db: Session, last_synced_at: Optional[datetime.datetime]) -> Dict[str, Any]:
        """
        Retrieves database entries changed since last_synced_at.
        If last_synced_at is None, retrieves full dataset.
        Filters on updated_at (preferred) so photo updates and any user field
        changes are captured — not just new user enrollments.
        """
        # Fetching Users — filter on updated_at so photo uploads are picked up.
        # updated_at is set by the ORM on every UPDATE (including face_vector changes).
        user_query = db.query(User)
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
        sync_users = []
        for u in users_list:
            embeddings_payload = []
            legacy_face_vector_b64 = None
            for emb in u.embeddings:
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
            ))

        # Fetching Roles
        role_query = db.query(Role)
        if last_synced_at:
            role_query = role_query.filter(Role.created_at > last_synced_at)
        roles_list = role_query.all()
        sync_roles = [
            RoleSyncResponse(
                role_id=r.role_id,
                role_name=r.role_name,
                last_synced_at=r.created_at.isoformat() if r.created_at else datetime.datetime.utcnow().isoformat()
            ) for r in roles_list
        ]

        # Fetching RBAC Rules (Static mappings, synced in full if delta is requested)
        rbac_list = db.query(NodeRBAC).all()
        sync_rbac = [
            NodeRbacSyncResponse(
                node_id=rb.node_id,
                role_id=rb.role_id,
                last_synced_at=datetime.datetime.utcnow().isoformat()
            ) for rb in rbac_list
        ]

        # Fetching User-Role Mappings for users returned in the current delta
        sync_user_roles = []
        user_ids = [u.user_id for u in users_list]
        if user_ids:
            user_roles_list = db.query(UserRole).filter(UserRole.user_id.in_(user_ids)).all()
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
            "deleted_user_ids": deleted_user_ids,
            "timestamp": datetime.datetime.utcnow().isoformat()
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
        
        pushed_targets = []
        for dev in active_devices:
            # Parse ip and port
            if ":" in dev.ip_address:
                ip, port_str = dev.ip_address.split(":")
                try:
                    port = int(port_str)
                except ValueError:
                    port = 8001
            else:
                ip = dev.ip_address
                port = 8001
            
            # Dispatch push alert inside background task
            background_tasks.add_task(EdgeNotificationDispatcher.send_deactivation_push, ip, port, user_id)
            pushed_targets.append(dev.device_id)

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


def push_sync_to_all_edges(db: Session) -> None:
    """
    Background task helper: iterates over all active edge devices and sends
    a trigger-sync push so they immediately pull the latest delta from the cloud.
    Intended to be called via FastAPI BackgroundTasks after any user update.
    """
    try:
        active_devices = db.query(Device).filter(
            Device.is_active == True,
            Device.ip_address != None
        ).all()
        for dev in active_devices:
            if ":" in dev.ip_address:
                ip, port_str = dev.ip_address.split(":")
                try:
                    port = int(port_str)
                except ValueError:
                    port = 8001
            else:
                ip = dev.ip_address
                port = 8001
            EdgeNotificationDispatcher.send_sync_push(ip, port)
    except Exception as e:
        logger.error(f"push_sync_to_all_edges failed: {str(e)}")

@router.post("/register", status_code=status.HTTP_200_OK)
def register_edge(registration: EdgeRegistration, db: Session = Depends(get_db)):
    """
    Enrolls an edge device's LAN metadata so the cloud publisher knows where to dispatch direct pushes.
    """
    return handler.register_edge_node(db, registration)

@router.get("/delta", response_model=DeltaSyncResponse)
def get_deltas(last_synced_at: Optional[str] = None, db: Session = Depends(get_db)):
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
    
    return handler.get_delta_updates(db, parsed_time)

@router.post("/deactivate")
def administrative_deactivate(req: DeactivateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    """
    Admin control panel endpoint: Deactivates a user profile and broadcasts immediate deactivation commands to edge nodes.
    """
    return handler.deactivate_user_and_push(db, req.user_id, background_tasks)

@router.get("/user-ids", response_model=List[int])
def get_all_user_ids(db: Session = Depends(get_db)):
    """
    Retrieves the complete set of user IDs currently existing in the cloud database.
    """
    users = db.query(User.user_id).all()
    return [u.user_id for u in users]


@router.post("/push-sync")
def trigger_push_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_admin=Depends(verify_super_admin)):
    """
    Admin / internal endpoint: immediately broadcasts a trigger-sync signal to all
    registered edge devices so they pull the latest cloud delta without waiting for
    their polling interval. Useful after bulk user updates or photo enrollments.
    """
    background_tasks.add_task(push_sync_to_all_edges, db)
    return {"status": "dispatched", "message": "Trigger-sync broadcast queued for all active edge devices"}
