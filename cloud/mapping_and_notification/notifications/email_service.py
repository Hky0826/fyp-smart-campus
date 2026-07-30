from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class EmailService:
    def send(self, *, to: str, subject: str, html: str) -> tuple[bool, str | None]:
        if not to:
            return False, "Recipient email unavailable"
        import os
        host = os.getenv("SMTP_HOST")
        if not host:
            return False, "SMTP unavailable"
        message = EmailMessage()
        message["To"], message["Subject"], message["From"] = to, subject, os.getenv("SMTP_FROM", "no-reply@campus.invalid")
        message.set_content("This message requires an HTML-capable mail client.")
        message.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
                if os.getenv("SMTP_TLS", "true").lower() in {"1", "true", "yes"}:
                    smtp.starttls()
                user, password = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(message)
            return True, None
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning("SMTP delivery failed: %s", type(exc).__name__)
            return False, "SMTP unavailable"
