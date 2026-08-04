from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_system_admin
from ..notifications.builder import build_notification
from ..notifications.service import NotificationService
from .schemas import NotificationTestRequest

router = APIRouter(tags=["Mapping and notification notifications"])


@router.get("/notifications")
def list_notifications(db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    from app.models.models import Notification
    rows = db.query(Notification).order_by(Notification.created_at.desc()).limit(200).all()
    return [{"notification_id": r.notification_id, "recipient_user_id": r.recipient_user_id, "event_type": r.event_type, "title": r.title, "body": r.body, "status": r.status, "message_id": r.message_id, "delivery_error": r.delivery_error, "created_at": r.created_at, "sent_at": r.sent_at} for r in rows]


@router.get("/notification-recipients")
def notification_recipients(db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    from app.models.models import User
    users = db.query(User).filter(User.is_active.is_(True)).order_by(User.family_name, User.given_name).all()
    result = []
    for u in users:
        first_role = u.roles[0] if u.roles else None
        result.append({
            "user_id": u.user_id,
            "full_name": u.full_name,
            "name": u.full_name,
            "email": u.email,
            "role_name": first_role.role_name if first_role else "User",
            "role_id": first_role.role_id if first_role else None
        })
    return result


@router.post("/notifications/test")
def test_notification(payload: NotificationTestRequest, db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    row = NotificationService(db).create_and_publish(build_notification(**payload.model_dump()))
    return {"notification_id": row.notification_id, "message_id": row.message_id, "status": row.status}
