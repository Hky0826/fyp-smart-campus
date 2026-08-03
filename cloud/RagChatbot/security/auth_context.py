"""Single trusted JWT/session/user context resolver for text and audio."""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Optional

import jwt as pyjwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from RagChatbot.config import rag_settings
from RagChatbot.personalisation.schemas import AuthenticatedChatContext


def _decode_jwt(token: str) -> dict:
    try:
        return pyjwt.decode(token, rag_settings.JWT_SECRET, algorithms=[rag_settings.JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT token has expired. Please re-authenticate.") from exc
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.") from exc


def resolve_user_session(token: str, db: Session) -> tuple[dict, int, object]:
    """Resolve edge and dashboard JWTs through one user/session check."""
    from app.models.models import Admin, JWTSession, User

    payload = _decode_jwt(token)
    raw_user_id = payload.get("user_id")
    # Keep already-issued dashboard tokens usable until they expire.
    if raw_user_id is None and payload.get("admin_type") is not None:
        admin = db.query(Admin).filter_by(admin_id=str(payload.get("sub"))).first()
        raw_user_id = admin.user_id if admin else None
    if raw_user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token payload missing user_id. Please re-authenticate.")
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user identity in authentication token.") from exc

    jti = payload.get("jti")
    session_uuid = payload.get("session_id")
    if not jti or not session_uuid or not payload.get("iat") or not payload.get("principal_type"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is missing standardized session claims.")
    session = db.query(JWTSession).filter_by(jti=jti, session_uuid=session_uuid, is_revoked=False).first()
    now_utc = dt.datetime.utcnow()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found or has been revoked.")
    if session.expires_at and session.expires_at.replace(tzinfo=None) < now_utc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has expired. Please re-authenticate.")
    if int(session.user_id) != user_id or session.principal_type not in {"USER", "ADMIN"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication session does not match the token user.")
    if not db.query(User).filter_by(user_id=user_id, is_active=True).first():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or unavailable. Please re-authenticate.")
    return payload, user_id, session


def resolve_auth_context(
    token: Optional[str],
    db: Session,
    *,
    requested_device_id: Optional[str] = None,
) -> AuthenticatedChatContext:
    """Resolve identity from verified token and active DB session only."""
    if not token:
        return AuthenticatedChatContext(user_id=None, session_id=None, authenticated=False, reason="anonymous")
    from app.models.models import Device, User
    payload, user_id, session = resolve_user_session(token, db)
    trusted_device = None
    if session.device_id:
        trusted_device = (
            db.query(Device)
            .filter(Device.device_id == session.device_id, Device.is_active.is_(True))
            .first()
        )
    if requested_device_id is not None and requested_device_id != session.device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request device_id does not match the authenticated session device.",
        )
    user = db.query(User).filter_by(user_id=user_id, is_active=True).first()
    roles = tuple(sorted({str(role.role_name).upper() for role in (user.roles or [])}))

    # Identity records are independent of role ordering. A person can hold
    # more than one role and each applicable record remains available to the
    # personalisation layer.
    student_id = getattr(getattr(user, "student", None), "student_id", None)
    lecturer_id = getattr(getattr(user, "lecturer", None), "lecturer_id", None)
    staff_id = getattr(getattr(user, "staff", None), "staff_id", None)
    visitor_id = getattr(getattr(user, "visitor", None), "visitor_id", None)
    admin_id = getattr(getattr(user, "admin", None), "admin_id", None)
    full_name = getattr(user, "full_name", None) or getattr(user, "name", None)
    given_name = getattr(user, "given_name", None)

    return AuthenticatedChatContext(
        user_id=user_id, session_id=int(session.session_id), roles=roles,
        student_id=student_id,
        lecturer_id=lecturer_id,
        staff_id=staff_id,
        visitor_id=visitor_id,
        admin_id=admin_id,
        device_id=getattr(session, "device_id", None),
        device_node_id=getattr(trusted_device, "node_id", None),
        device_label=getattr(getattr(trusted_device, "node", None), "room_label", None),
        given_name=given_name,
        full_name=full_name,
        authenticated=True,
    )
