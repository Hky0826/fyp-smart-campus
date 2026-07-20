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
from datetime import datetime, timedelta
from typing import Optional

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Device, JWTSession, User

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


class EdgeTokenResponse(BaseModel):
    """JWT and session metadata returned to the edge device."""

    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    full_name: str
    roles: list
    session_id: int
    expires_at: str


@router.post(
    "/token",
    response_model=EdgeTokenResponse,
    summary="Issue a user JWT after successful edge face recognition",
)
def issue_edge_token(
    body: EdgeTokenRequest,
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
    device = db.query(Device).filter_by(device_id=body.device_id, is_active=True).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unrecognized or inactive device. Edge token issuance denied.",
        )

    # ── Verify user ───────────────────────────────────────────────────────────
    user = db.query(User).filter_by(user_id=body.user_id, is_active=True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account is inactive.",
        )

    # ── Create JWT ────────────────────────────────────────────────────────────
    expire = datetime.utcnow() + timedelta(minutes=_TOKEN_EXPIRE_MINUTES)
    token_payload = {
        "sub": str(user.user_id),
        "user_id": user.user_id,
        "email": user.email,
        "device_id": body.device_id,
        "exp": expire,
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
        full_name=user.full_name,
        roles=roles,
        session_id=session.session_id,
        expires_at=expire.isoformat(),
    )
