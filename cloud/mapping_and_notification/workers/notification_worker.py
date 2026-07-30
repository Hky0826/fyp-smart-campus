"""RabbitMQ worker entry point.

The worker is intentionally not imported or started by Uvicorn. Deployment should
run ``python -m cloud.mapping_and_notification.workers.notification_worker`` as a
separate process with its own lifecycle and dead-letter policy.
"""

from __future__ import annotations

import logging
import json
import os

logger = logging.getLogger(__name__)


def process_message(db, payload: dict, *, email_service=None):
    from ..notifications.service import NotificationService
    service = NotificationService(db)
    message_id = payload.get("message_id")
    if not message_id:
        return {"status": "SKIPPED", "error": "missing message_id"}
    # Idempotency: only PENDING/RETRYING messages can be delivered.
    from app.models.models import Notification
    row = db.query(Notification).filter(Notification.message_id == message_id).first()
    if not row or row.status in {"SENT", "FAILED", "SKIPPED"}:
        return {"status": getattr(row, "status", "SKIPPED"), "skipped": True}
    if email_service is None:
        from ..notifications.email_service import EmailService
        email_service = EmailService()
    recipient = db.query(__import__("app.models.models", fromlist=["User"]).User).filter_by(user_id=row.recipient_user_id, is_active=True).first()
    recipient_email = getattr(recipient, "email", None)
    if not recipient_email:
        service.mark_delivery(message_id, status="SKIPPED", error="Recipient email unavailable")
        return {"status": "SKIPPED", "error": "Recipient email unavailable"}
    ok, error = email_service.send(to=recipient_email, subject=payload.get("title", row.title), html=payload.get("html", row.body))
    service.mark_delivery(message_id, status="SENT" if ok else "FAILED", error=error)
    return {"status": "SENT" if ok else "FAILED", "error": error}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import pika
    from app.core.database import SessionLocal
    from ..notifications.broker import EXCHANGE, QUEUE, ROUTING_KEY

    connection = pika.BlockingConnection(pika.URLParameters(os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")))
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    channel.queue_declare(queue=QUEUE, durable=True)
    channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=ROUTING_KEY)
    channel.basic_qos(prefetch_count=1)

    def on_message(ch, method, properties, body):
        db = SessionLocal()
        try:
            result = process_message(db, json.loads(body))
            # Messages are acknowledged only after the audit row reaches a
            # terminal state. Malformed/transient messages remain available.
            if result.get("status") in {"SENT", "FAILED", "SKIPPED"}:
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception:
            logger.exception("notification worker message failed")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        finally:
            db.close()

    channel.basic_consume(queue=QUEUE, on_message_callback=on_message)
    logger.info("Notification worker consuming %s", QUEUE)
    channel.start_consuming()
