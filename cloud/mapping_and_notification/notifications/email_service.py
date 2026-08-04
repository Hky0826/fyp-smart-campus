from __future__ import annotations

import json
import logging
import os
import re
import smtplib
from typing import Any
from email.message import EmailMessage
from pathlib import Path

import requests

logger = logging.getLogger(__name__)
ETHEREAL_CACHE_PATH = Path(__file__).resolve().parents[3] / "runtime-data" / "ethereal_account.json"


class EmailService:
    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        email_delivery_mode: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> tuple[bool, str | None, str | None]:
        if not to:
            return False, "Recipient email unavailable", None

        mode = (email_delivery_mode or os.getenv("EMAIL_MODE", "smtp")).lower()
        try:
            if mode == "ethereal":
                account = self._get_ethereal_account()
                smtp_config = account["smtp"]
                response = self._send_smtp(
                    to=to,
                    subject=subject,
                    html=html,
                    host=smtp_config["host"],
                    port=int(smtp_config["port"]),
                    user=account["user"],
                    password=account["pass"],
                    secure=bool(smtp_config.get("secure", False)),
                    start_tls=not bool(smtp_config.get("secure", False)),
                    attachments=attachments,
                )
                return True, None, self._preview_url_from_response(response)

            if mode != "smtp":
                return False, f"Unsupported email delivery mode: {mode}", None

            host = os.getenv("SMTP_HOST")
            if not host:
                return False, "SMTP unavailable", None
            self._send_smtp(
                to=to,
                subject=subject,
                html=html,
                host=host,
                port=int(os.getenv("SMTP_PORT", "587")),
                user=os.getenv("SMTP_USER"),
                password=os.getenv("SMTP_PASSWORD"),
                secure=os.getenv("SMTP_SECURE", "false").lower() in {"1", "true", "yes"},
                start_tls=os.getenv("SMTP_TLS", "true").lower() in {"1", "true", "yes"},
                attachments=attachments,
            )
            return True, None, None
        except (OSError, ValueError, KeyError, requests.RequestException, smtplib.SMTPException) as exc:
            logger.warning("Email delivery failed in %s mode: %s", mode, type(exc).__name__)
            return False, "Email delivery unavailable", None

    @staticmethod
    def _get_ethereal_account() -> dict:
        if ETHEREAL_CACHE_PATH.is_file():
            try:
                account = json.loads(ETHEREAL_CACHE_PATH.read_text(encoding="utf-8"))
                if account.get("user") and account.get("pass") and account.get("smtp"):
                    return account
            except (OSError, ValueError):
                logger.warning("Invalid cached Ethereal account; creating a new one")

        response = requests.post(
            "https://api.nodemailer.com/user",
            json={"requestor": "smart-campus-cloud", "version": "1.0.0"},
            timeout=15,
        )
        response.raise_for_status()
        account = response.json()
        if account.get("status") != "success" or not account.get("user") or not account.get("pass"):
            raise ValueError("Ethereal account creation failed")
        account.pop("status", None)
        ETHEREAL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ETHEREAL_CACHE_PATH.write_text(json.dumps(account, indent=2), encoding="utf-8")
        return account

    @staticmethod
    def _send_smtp(*, to: str, subject: str, html: str, host: str, port: int, user: str | None, password: str | None, secure: bool, start_tls: bool, attachments: list[dict[str, Any]] | None = None) -> str:
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message["From"] = os.getenv("SMTP_FROM", "no-reply@campus.invalid")
        message.set_content("This message requires an HTML-capable mail client.")
        message.add_alternative(html, subtype="html")
        html_part = message.get_payload()[-1]
        for attachment in attachments or []:
            html_part.add_related(
                attachment["data"],
                maintype=attachment.get("maintype", "image"),
                subtype=attachment.get("subtype", "png"),
                cid=attachment["cid"],
                filename=attachment.get("filename"),
            )

        smtp = smtplib.SMTP_SSL(host, port, timeout=10) if secure else smtplib.SMTP(host, port, timeout=10)
        with smtp:
            if start_tls and not secure:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            sender = message["From"]
            code, response = smtp.mail(sender)
            if code != 250:
                raise smtplib.SMTPResponseException(code, response)
            code, response = smtp.rcpt(to)
            if code not in {250, 251}:
                raise smtplib.SMTPResponseException(code, response)
            code, response = smtp.data(message.as_bytes())
            if code != 250:
                raise smtplib.SMTPResponseException(code, response)
            return response.decode(errors="replace") if isinstance(response, bytes) else str(response)

    @staticmethod
    def _preview_url_from_response(response: str) -> str | None:
        match = re.search(r"\bMSGID=([^\s\]]+)", response or "")
        return f"https://ethereal.email/message/{match.group(1)}" if match else None
