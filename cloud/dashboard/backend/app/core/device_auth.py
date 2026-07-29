from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_development_device_credential_key, settings
from app.core.database import get_db
from app.models.models import Device, DeviceRequestNonce

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - deployment dependency
    Fernet = None
    InvalidToken = Exception

TIMESTAMP_HEADER = "x-device-timestamp"
NONCE_HEADER = "x-device-nonce"
SIGNATURE_HEADER = "x-device-signature"
DEVICE_ID_HEADER = "x-device-id"
MAX_CLOCK_SKEW_SECONDS = 300


def _fernet() -> Fernet:
    if Fernet is None:
        raise RuntimeError("Encrypted device credential storage is not configured")
    key = settings.DEVICE_CREDENTIAL_KEY or get_development_device_credential_key()
    if not key:
        raise RuntimeError("Encrypted device credential storage is not configured")
    return Fernet(key.encode())


def generate_device_secret() -> str:
    return secrets.token_urlsafe(48)


def encrypt_device_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_device_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(status_code=401, detail="Device credential is unavailable") from exc


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_request(method: str, path: str, query: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    # query is preserved in the exact received order to prevent signature
    # confusion between equivalent but differently serialized requests.
    return "\n".join((method.upper(), path, query, timestamp, nonce, body_hash(body))).encode()


def sign_request(secret: str, method: str, path: str, query: str, timestamp: str, nonce: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), canonical_request(method, path, query, timestamp, nonce, body), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def require_signed_device_request(request: Request, db: Session = Depends(get_db)) -> Device:
    device_id = request.headers.get(DEVICE_ID_HEADER)
    timestamp = request.headers.get(TIMESTAMP_HEADER)
    nonce = request.headers.get(NONCE_HEADER)
    signature = request.headers.get(SIGNATURE_HEADER)
    if not all((device_id, timestamp, nonce, signature)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signed device authentication required")
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid device timestamp")
    if abs(time.time() - timestamp_value) > MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Expired device request")
    if len(nonce) < 16 or len(nonce) > 128:
        raise HTTPException(status_code=401, detail="Invalid device nonce")
    device = db.query(Device).filter_by(device_id=device_id, is_active=True).first()
    if not device or not device.device_secret_ciphertext:
        raise HTTPException(status_code=401, detail="Unrecognized device")
    body = await request.body()
    expected = sign_request(decrypt_device_secret(device.device_secret_ciphertext), request.method, request.url.path, request.url.query, timestamp, nonce, body)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid device signature")
    db.query(DeviceRequestNonce).filter(DeviceRequestNonce.expires_at < datetime.utcnow()).delete(synchronize_session=False)
    if db.query(DeviceRequestNonce).filter_by(device_id=device_id, nonce=nonce).first():
        raise HTTPException(status_code=401, detail="Replayed device request")
    db.add(DeviceRequestNonce(device_id=device_id, nonce=nonce, expires_at=datetime.utcnow() + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=401, detail="Replayed device request")
    request.state.authenticated_device_id = device_id
    return device


def bind_device_id(requested_device_id: str | None, device: Device) -> str:
    if requested_device_id is not None and requested_device_id != device.device_id:
        raise HTTPException(status_code=403, detail="Request device_id does not match authenticated device")
    return device.device_id


def sign_assertion(secret: str, assertion: dict) -> str:
    encoded = json.dumps(assertion, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(hmac.new(secret.encode(), encoded, hashlib.sha256).digest()).decode().rstrip("=")


def verify_assertion_signature(secret: str, assertion: dict, signature: str) -> bool:
    return hmac.compare_digest(sign_assertion(secret, assertion), signature)
