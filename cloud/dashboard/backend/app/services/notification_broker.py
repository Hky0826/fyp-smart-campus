from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

EXCHANGE = os.getenv("NOTIFICATION_EXCHANGE", "campus.notifications.exchange")
QUEUE = os.getenv("NOTIFICATION_QUEUE", "campus.notifications.queue")
ROUTING_KEY = os.getenv("NOTIFICATION_ROUTING_KEY", "appointment_routing")


@dataclass(frozen=True)
class NotificationPayload:
    message_id: str
    recipient_user_id: int
    event_type: str
    title: str
    body: str
    appointment_id: int | None = None
    correlation_id: str | None = None
    email_delivery_mode: str | None = None
    route_context: dict | None = None
    created_at: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def build_notification(
    *,
    recipient_user_id: int,
    title: str,
    body: str,
    event_type: str = "appointment_routing",
    appointment_id: int | None = None,
    correlation_id: str | None = None,
    message_id: str | None = None,
    email_delivery_mode: str | None = None,
    route_context: dict | None = None,
) -> NotificationPayload:
    if recipient_user_id is None:
        raise ValueError("recipient_user_id is required")
    return NotificationPayload(
        message_id=message_id or f"MSG-{uuid4().hex}",
        recipient_user_id=int(recipient_user_id),
        event_type=event_type,
        title=title,
        body=body,
        appointment_id=appointment_id,
        correlation_id=correlation_id,
        email_delivery_mode=email_delivery_mode,
        route_context=route_context,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class Broker:
    def publish(self, payload: dict) -> bool:
        """Publish message to RabbitMQ exchange."""
        try:
            import pika
            url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672/")
            connection = pika.BlockingConnection(pika.URLParameters(url))
            channel = connection.channel()
            channel.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=ROUTING_KEY)
            channel.confirm_delivery()
            channel.basic_publish(
                exchange=EXCHANGE,
                routing_key=ROUTING_KEY,
                body=json.dumps(payload),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json",
                    message_id=payload.get("message_id", ""),
                ),
            )
            connection.close()
            return True
        except Exception as exc:
            logger.warning("Notification broker publish failed: %s", type(exc).__name__)
            return False
