from __future__ import annotations

from datetime import datetime

from .broker import Broker
from .builder import NotificationPayload


class NotificationService:
    def __init__(self, db, *, broker: Broker | None = None):
        self.db = db
        self.broker = broker or Broker()

    def create_and_publish(self, payload: NotificationPayload):
        from app.models.models import Notification
        row = Notification(recipient_user_id=payload.recipient_user_id, event_type=payload.event_type, title=payload.title, body=payload.body, status="PENDING", message_id=payload.message_id, appointment_id=payload.appointment_id, correlation_id=payload.correlation_id, attempt_count=0)
        self.db.add(row)
        # Commit before publishing so a separate worker transaction can see the
        # audit row when the RabbitMQ message arrives.
        self.db.commit()
        try:
            published = self.broker.publish(payload.as_dict())
        except Exception:
            published = False

        current = self.db.query(Notification).filter(Notification.notification_id == row.notification_id).first()
        if published:
            # A fast worker may already have delivered the message while the
            # publisher was returning. Never overwrite that terminal status.
            if current and current.status == "PENDING":
                current.status = "QUEUED"
            self.db.commit()
            return current or row
        if not current:
            return row
        current.status = "RETRYING"
        current.delivery_error = "Broker unavailable"
        current.attempt_count = int(current.attempt_count or 0) + 1
        self.db.commit()
        return current

    def mark_delivery(self, message_id: str, *, status: str, error: str | None = None, preview_url: str | None = None):
        from app.models.models import Notification
        if status not in {"SENT", "FAILED", "SKIPPED", "RETRYING"}:
            raise ValueError("invalid notification terminal state")
        row = self.db.query(Notification).filter(Notification.message_id == message_id).with_for_update().first()
        if not row:
            return None
        row.status, row.delivery_error = status, error
        if status == "SENT":
            row.sent_at = datetime.utcnow()
            if preview_url and preview_url not in (row.body or ""):
                row.body = f"{row.body}\n\nEthereal preview: {preview_url}"
        self.db.commit()
        return row
