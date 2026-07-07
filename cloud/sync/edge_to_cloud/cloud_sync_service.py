# sync/edge_to_cloud/cloud_sync_service.py

import os
import sys
import base64
import binascii
import logging
import datetime
import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

# Add backend directory to sys.path to allow importing from app
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import AuthenticationLog, Device, User, SurveillanceLog

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CloudUpstreamService")

# =====================================================================
# Pydantic Validation Schemas
# =====================================================================

class EdgeLogPayload(BaseModel):
    sync_key: Optional[str] = Field(None, description="Edge-generated idempotency key")
    user_id: Optional[int] = Field(None, description="Identity reference; null on failed or spoofed checks")
    device_id: str = Field(..., description="Device ID representing the hardware node uploading the log")
    auth_status: str = Field(..., description="Outcome classification: 'SUCCESS', 'FAILED', or 'SPOOFING'")
    confidence_score: Optional[float] = Field(None, description="Similarity index vector score")
    face_count: int = 1
    reason: Optional[str] = None
    spoofing_checked: bool = True
    spoofing_passed: Optional[bool] = None
    timestamp: str = Field(..., description="Timestamp of authentication attempt in ISO 8601 format")
    image_path: Optional[str] = None

class IngestionRequest(BaseModel):
    logs: List[EdgeLogPayload]

class EdgeSurveillanceLogPayload(BaseModel):
    sync_key: Optional[str] = Field(None, description="Edge-generated idempotency key")
    user_id: Optional[int] = None
    device_id: str
    recognition_status: str = Field(..., description="Outcome classification: 'RECOGNIZED' or 'UNKNOWN'")
    confidence_score: Optional[float] = None
    matched_template: Optional[str] = None
    face_count: int = 1
    bbox: Optional[Any] = None
    timestamp: str
    image_path: Optional[str] = None
    image_b64: Optional[str] = None
    image_filename: Optional[str] = None

class SurveillanceIngestionRequest(BaseModel):
    logs: List[EdgeSurveillanceLogPayload]

class HeartbeatPayload(BaseModel):
    device_id: str
    device_name: str
    ip_address: str = Field(..., description="LAN IP address and port of the edge device listener (e.g. 192.168.1.100:8001)")

# =====================================================================
# Abstract Design / Interface for Upstream Operations
# =====================================================================

class AbstractUpstreamHandler(ABC):
    """
    Abstract Interface mapping core database transaction rules.
    Decoupled from FastAPI/HTTP layer.
    """
    @abstractmethod
    def ingest_authentication_logs(self, db: Session, logs: List[EdgeLogPayload]) -> List[int]:
        pass

    @abstractmethod
    def ingest_surveillance_logs(self, db: Session, logs: List[EdgeSurveillanceLogPayload]) -> List[int]:
        pass

    @abstractmethod
    def register_heartbeat(self, db: Session, heartbeat: HeartbeatPayload) -> Dict[str, Any]:
        pass


# =====================================================================
# Concrete Implementation (SQLAlchemy Engine)
# =====================================================================

class SQLAlchemyUpstreamHandler(AbstractUpstreamHandler):
    """
    SQLAlchemy implementation executing relational database state updates.
    Ensures rollback-safe transaction loops for location tracking hooks.
    """

    def _update_user_last_known_location(
        self,
        db: Session,
        user_id: Optional[int],
        device_id: str,
        event_time: datetime.datetime,
        source: str,
    ) -> None:
        if user_id is None:
            return

        device_record = db.query(Device).filter(Device.device_id == device_id).first()
        if not device_record:
            logger.warning("Location Mutation Failed: Device %s not registered in cloud", device_id)
            return

        user_record = db.query(User).filter(User.user_id == user_id).first()
        if not user_record:
            logger.warning("Location Mutation Failed: User %s not found in database", user_id)
            return

        if user_record.last_seen is not None and event_time < user_record.last_seen:
            logger.info(
                "Location Mutation Skipped: %s event for user %s is older than current last_seen",
                source,
                user_id,
            )
            return

        user_record.last_known_location = device_record.node_id
        user_record.last_seen = event_time
        logger.info(
            "Location Mutation: User %s last_known_location updated to Node %s from %s",
            user_id,
            device_record.node_id,
            source,
        )

    def ingest_authentication_logs(self, db: Session, logs: List[EdgeLogPayload]) -> List[int]:
        """
        Processes a batch of logs.
        Wraps log insertion and global user state mutation in a database transaction block per log.
        Returns a list of successfully ingested log identifiers.
        """
        processed_indices = []

        for idx, log in enumerate(logs):
            # Start nested checkpoint/transaction block for each log
            # to prevent one bad log entry from failing the entire batch
            db.begin_nested()
            try:
                sync_key = self._sync_key(log.sync_key)
                existing = db.query(AuthenticationLog).filter(AuthenticationLog.sync_key == sync_key).first()
                if existing:
                    db.commit()
                    processed_indices.append(idx)
                    continue

                # 1. Append log to cloud authentication_logs
                parsed_time = self._parse_timestamp(log.timestamp)
                db_log = AuthenticationLog(
                    sync_key=sync_key,
                    user_id=log.user_id,
                    device_id=log.device_id,
                    auth_status=log.auth_status,
                    confidence_score=log.confidence_score,
                    face_count=log.face_count,
                    reason=log.reason,
                    spoofing_checked=log.spoofing_checked,
                    spoofing_passed=log.spoofing_passed,
                    timestamp=parsed_time,
                    image_path=log.image_path,
                )
                db.add(db_log)
                db.flush() # Flushes so we trigger constraints and auto-increment

                if log.auth_status.upper() == "SUCCESS" and log.user_id is not None:
                    self._update_user_last_known_location(
                        db,
                        user_id=log.user_id,
                        device_id=log.device_id,
                        event_time=parsed_time,
                        source="access_control",
                    )

                # Commit log & mutation block
                db.commit()
                processed_indices.append(idx)
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to ingest log entry {idx} (device: {log.device_id}): {str(e)}")
                # Continue processing other logs in the batch
        
        # Finally commit the parent transaction
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Global commit failure during log ingestion: {str(e)}")
            raise HTTPException(status_code=500, detail="Database failure committing transactions")

        return processed_indices

    def ingest_surveillance_logs(self, db: Session, logs: List[EdgeSurveillanceLogPayload]) -> List[int]:
        processed_indices = []

        for idx, log in enumerate(logs):
            db.begin_nested()
            try:
                sync_key = self._sync_key(log.sync_key)
                existing = db.query(SurveillanceLog).filter(SurveillanceLog.sync_key == sync_key).first()
                if existing:
                    db.commit()
                    processed_indices.append(idx)
                    continue

                parsed_time = self._parse_timestamp(log.timestamp)
                image_path = self._save_surveillance_image(sync_key, log)
                db_log = SurveillanceLog(
                    sync_key=sync_key,
                    user_id=log.user_id,
                    device_id=log.device_id,
                    recognition_status=log.recognition_status.upper(),
                    confidence_score=log.confidence_score,
                    matched_template=log.matched_template,
                    face_count=log.face_count,
                    bbox=log.bbox,
                    timestamp=parsed_time,
                    image_path=image_path,
                )
                db.add(db_log)
                db.flush()

                if log.recognition_status.upper() == "RECOGNIZED" and log.user_id is not None:
                    self._update_user_last_known_location(
                        db,
                        user_id=log.user_id,
                        device_id=log.device_id,
                        event_time=parsed_time,
                        source="surveillance",
                    )

                db.commit()
                processed_indices.append(idx)
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to ingest surveillance log entry {idx} (device: {log.device_id}): {str(e)}")

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Global commit failure during surveillance log ingestion: {str(e)}")
            raise HTTPException(status_code=500, detail="Database failure committing surveillance transactions")

        return processed_indices

    @staticmethod
    def _sync_key(value: Optional[str]) -> str:
        return value or uuid.uuid4().hex[:26]

    @staticmethod
    def _parse_timestamp(value: str) -> datetime.datetime:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed

    @staticmethod
    def _save_surveillance_image(sync_key: str, log: EdgeSurveillanceLogPayload) -> Optional[str]:
        if not log.image_b64:
            return log.image_path if log.image_path and log.image_path.startswith("/static/") else None

        try:
            image_bytes = base64.b64decode(log.image_b64, validate=True)
        except (binascii.Error, ValueError):
            logger.warning("Skipping invalid surveillance image payload for sync key %s", sync_key)
            return None

        if len(image_bytes) > 10 * 1024 * 1024:
            logger.warning("Skipping oversized surveillance image payload for sync key %s", sync_key)
            return None

        ext = os.path.splitext(log.image_filename or "")[1].lower()
        if ext not in {".jpg", ".jpeg", ".png"}:
            ext = ".jpg"
        day = datetime.datetime.utcnow().strftime("%Y%m%d")
        static_dir = os.path.join(backend_dir, "app", "static")
        upload_dir = os.path.join(static_dir, "uploads", "surveillance", day)
        os.makedirs(upload_dir, exist_ok=True)
        safe_key = "".join(ch for ch in sync_key if ch.isalnum() or ch in {"-", "_"})[:64]
        filename = f"{safe_key}{ext}"
        file_path = os.path.join(upload_dir, filename)
        with open(file_path, "wb") as out:
            out.write(image_bytes)
        return f"/static/uploads/surveillance/{day}/{filename}"

    def register_heartbeat(self, db: Session, hb: HeartbeatPayload) -> Dict[str, Any]:
        """
        Registers keep-alive signal. Updates IP and last heartbeat.
        """
        device = db.query(Device).filter(Device.device_id == hb.device_id).first()
        if not device:
            # Create a fallback Device record
            device = Device(
                device_id=hb.device_id,
                device_name=hb.device_name,
                node_id=1,  # Default fallback node
                device_type="KIOSK",
                ip_address=hb.ip_address,
                is_active=True,
                last_heartbeat=datetime.datetime.utcnow()
            )
            db.add(device)
            logger.info(f"Heartbeat created new device: {hb.device_id}")
        else:
            device.ip_address = hb.ip_address
            device.last_heartbeat = datetime.datetime.utcnow()
            device.is_active = True
            logger.debug(f"Heartbeat received from device: {hb.device_id}")
            
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to register heartbeat for device {hb.device_id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Database error committing heartbeat")
            
        return {"status": "alive", "device_id": hb.device_id, "timestamp": datetime.datetime.utcnow().isoformat()}


# =====================================================================
# FastAPI Router Mounting
# =====================================================================

router = APIRouter(prefix="/sync/upstream", tags=["Database Synchronization - Upstream"])
handler: AbstractUpstreamHandler = SQLAlchemyUpstreamHandler()

@router.post("/logs")
def ingest_logs(req: IngestionRequest, db: Session = Depends(get_db)):
    """
    Ingestion streaming endpoint for offline-buffered authentication logs.
    Includes location mutation hooks and transactional confirmation.
    """
    success_indices = handler.ingest_authentication_logs(db, req.logs)
    
    # Return verification handshake confirmation. 
    # If all logs in batch succeeded, return indices array.
    return {
        "status": "processed",
        "processed_count": len(success_indices),
        "successful_indices": success_indices
    }

@router.post("/surveillance-logs")
def ingest_surveillance_logs(req: SurveillanceIngestionRequest, db: Session = Depends(get_db)):
    """
    Ingestion endpoint for offline-buffered surveillance detections and snapshots.
    """
    success_indices = handler.ingest_surveillance_logs(db, req.logs)
    return {
        "status": "processed",
        "processed_count": len(success_indices),
        "successful_indices": success_indices
    }

@router.post("/heartbeat")
def heartbeat(payload: HeartbeatPayload, db: Session = Depends(get_db)):
    """
    Periodic keep-alive API endpoint to evaluate active LAN status.
    """
    return handler.register_heartbeat(db, payload)
