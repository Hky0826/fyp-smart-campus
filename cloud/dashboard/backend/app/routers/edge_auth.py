"""
Edge Authentication endpoint.

Provides a token-issuance endpoint called by edge devices after successful
face recognition. The edge device sends the verified user_id (from its
local face recognition result) along with the device_id.

The cloud verifies:
  1. The user exists and is active.
  2. The device is a registered, active edge device.

If both checks pass, a JWT is issued and stored in jwt_sessions. This
token is then used by the edge for subsequent chatbot API calls.

Security:
  - The user_id is not taken at face value — it is verified against the DB.
  - No password or face template is transmitted to this endpoint.
  - The edge must use HTTPS in production to protect this call.
  - The device_id is checked against the registered devices table.
"""

from __future__ import annotations

import hashlib
import logging
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.device_auth import decrypt_device_secret, require_signed_device_request, bind_device_id, verify_assertion_signature
from app.models.models import Device, JWTSession, User, FaceAuthChallenge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/edge-auth", tags=["Edge Device Authentication"])

_TOKEN_EXPIRE_MINUTES = 120  # 2 hours, matching the admin token lifetime


class EdgeTokenRequest(BaseModel):
    """
    Body posted by the edge device after successful face recognition.

    Fields:
        user_id: The ID of the recognized user (from local face DB lookup).
        device_id: The edge device's registered device identifier.
    """

    user_id: int
    device_id: str
    challenge_id: str
    assertion: dict
    assertion_signature: str


class EdgeTokenResponse(BaseModel):
    """JWT and session metadata returned to the edge device."""

    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    given_name: str
    full_name: str
    roles: list
    session_id: int
    expires_at: str


def create_face_challenge(
    user_id: int,
    request: Request,
    device: Device = Depends(require_signed_device_request),
    db: Session = Depends(get_db),
) -> dict:
    if not db.query(User).filter_by(user_id=user_id, is_active=True).first():
        raise HTTPException(status_code=401, detail="User not found or inactive")
    challenge_id = secrets.token_urlsafe(32)
    challenge = FaceAuthChallenge(
        challenge_id=challenge_id,
        device_id=device.device_id,
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(seconds=60),
    )
    db.add(challenge)
    db.commit()
    return {"challenge_id": challenge_id, "user_id": user_id, "expires_at": challenge.expires_at.isoformat()}


@router.post("/challenge")
def issue_face_challenge(
    body: dict,
    request: Request,
    device: Device = Depends(require_signed_device_request),
    db: Session = Depends(get_db),
) -> dict:
    return create_face_challenge(int(body.get("user_id", 0)), request, device, db)


@router.post(
    "/token",
    response_model=EdgeTokenResponse,
    summary="Issue a user JWT only after a one-time signed face-auth assertion",
)
def issue_edge_token(
    body: EdgeTokenRequest,
    request: Request,
    device: Device = Depends(require_signed_device_request),
    db: Session = Depends(get_db),
) -> EdgeTokenResponse:
    """
    Issue a user-scoped JWT for a face-recognized user on an edge device.

    Called by the edge device's face recognition pipeline after a successful
    match. The user_id must correspond to an active user in the cloud database.
    The device_id must be a registered, active edge device.

    Returns a JWT that can be used for subsequent /api/chatbot/chat calls.
    """

    # ── Verify device ─────────────────────────────────────────────────────────
    bind_device_id(body.device_id, device)

    # ── Verify user ───────────────────────────────────────────────────────────
    user = db.query(User).filter_by(user_id=body.user_id, is_active=True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account is inactive.",
        )

    challenge = db.query(FaceAuthChallenge).filter_by(
        challenge_id=body.challenge_id,
        device_id=device.device_id,
        user_id=user.user_id,
        used_at=None,
    ).first()
    if not challenge or challenge.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Face-auth challenge is invalid or expired")
    assertion = body.assertion
    required = {
        "challenge_id": body.challenge_id,
        "user_id": user.user_id,
        "match_passed": True,
        "liveness_passed": True,
    }
    if any(assertion.get(key) != value for key, value in required.items()):
        raise HTTPException(status_code=401, detail="Successful face match and liveness are required")
    if not verify_assertion_signature(decrypt_device_secret(device.device_secret_ciphertext), assertion, body.assertion_signature):
        raise HTTPException(status_code=401, detail="Invalid face-auth assertion")
    challenge.match_passed = True
    challenge.liveness_passed = True
    challenge.pad_model_version = str(assertion.get("pad_model_version", "unknown"))
    challenge.pad_score = float(assertion.get("pad_score", 0.0))
    challenge.used_at = datetime.utcnow()

    # ── Create JWT ────────────────────────────────────────────────────────────
    expire = datetime.utcnow() + timedelta(minutes=_TOKEN_EXPIRE_MINUTES)
    session_uuid = secrets.token_hex(32)
    jti = secrets.token_hex(32)
    token_payload = {
        "sub": str(user.user_id),
        "user_id": user.user_id,
        "email": user.email,
        "device_id": body.device_id,
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": jti,
        "session_id": session_uuid,
        "principal_type": "USER",
    }

    access_token = pyjwt.encode(
        token_payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

    # ── Persist session ───────────────────────────────────────────────────────
    token_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    session = JWTSession(
        user_id=user.user_id,
        token_hash=token_hash,
        issued_at=datetime.utcnow(),
        expires_at=expire,
        device_id=body.device_id,
        is_revoked=False,
        session_uuid=session_uuid,
        jti=jti,
        principal_type="USER",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info(
        "Edge token issued: user_id=%d device_id=%s session_id=%d",
        user.user_id,
        body.device_id,
        session.session_id,
    )

    roles = [role.role_name for role in user.roles]

    return EdgeTokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.user_id,
        email=user.email,
        given_name=user.given_name,
        full_name=user.full_name,
        roles=roles,
        session_id=session.session_id,
        expires_at=expire.isoformat(),
    )
