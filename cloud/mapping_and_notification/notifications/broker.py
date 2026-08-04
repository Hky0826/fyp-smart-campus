from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)
logging.getLogger("pika").setLevel(logging.WARNING)
EXCHANGE = "campus.notifications.exchange"
QUEUE = "campus.notifications.queue"
ROUTING_KEY = "appointment_routing"


class Broker:
    def publish(self, payload: dict) -> bool:
        """Publish with publisher confirmation; false means it was not queued."""
        try:
            import pika
            url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672/")
            connection = pika.BlockingConnection(pika.URLParameters(url))
            channel = connection.channel()
            channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=ROUTING_KEY)
            channel.confirm_delivery()
            # Pika returns None after a successful publisher confirmation;
            # failed confirmations raise NackError or UnroutableError.
            channel.basic_publish(exchange=EXCHANGE, routing_key=ROUTING_KEY, body=json.dumps(payload), properties=pika.BasicProperties(delivery_mode=2, content_type="application/json", message_id=payload["message_id"]))
            connection.close()
            return True
        except Exception as exc:
            logger.warning("notification broker publish failed: %s", type(exc).__name__)
            return False
