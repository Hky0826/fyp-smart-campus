from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class NotificationPayload:
    message_id: str
    recipient_user_id: int
    event_type: str
    title: str
    body: str
    appointment_id: int | None = None
    correlation_id: str | None = None
    created_at: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def build_notification(*, recipient_user_id: int, title: str, body: str, event_type: str = "appointment_routing", appointment_id: int | None = None, correlation_id: str | None = None, message_id: str | None = None) -> NotificationPayload:
    if recipient_user_id is None:
        raise ValueError("recipient_user_id is required")
    return NotificationPayload(message_id=message_id or f"MSG-{uuid4().hex}", recipient_user_id=int(recipient_user_id), event_type=event_type, title=title, body=body, appointment_id=appointment_id, correlation_id=correlation_id, created_at=datetime.now(timezone.utc).isoformat())
