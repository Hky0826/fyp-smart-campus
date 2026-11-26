"""Native Python Campus Notification Builder, Email Sender, and Dispatcher.

Replaces mapping_and_notification/backend/services/{notificationBuilder,notificationService,emailService}.js
and consumer.js.

Features:
- Host & Visitor payload construction with CID-embedded route visualization PNGs (visitor-only)
- All 4 event types: appointment_routing, visitor_arrival, emergency_alert, visitor_navigation
- Ethereal Sandbox (auto-provisioned & cached) + Real SMTP delivery with 3x retry & error classification
- Dual dispatch: publishes to RabbitMQ (pika) when RABBITMQ_URL is configured and reachable,
  and executes seamlessly via FastAPI BackgroundTasks in-process otherwise
- Atomic idempotency (PENDING/QUEUED -> RETRYING -> SENT/FAILED) in MySQL `notifications` table
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import secrets
import smtplib
import time
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Notification, User
from app.services.mapping.route_visualizer import generate_route_visualisations

logger = logging.getLogger("smart-campus.mapping.notifications")


class NotificationBuildError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _ethereal_cache_path() -> Path:
    d = settings.PRIVATE_STORAGE_ROOT / "notifications"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ethereal_account.json"


def _get_ethereal_account() -> dict[str, Any]:
    cache_path = _ethereal_cache_path()
    if cache_path.is_file():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    resp = httpx.post(
        "https://api.nodemailer.com/user",
        json={"requestor": "smart-campus-dashboard", "version": "1.0.0"},
        timeout=15.0,
    )
    resp.raise_for_status()
    acct = resp.json()
    cache_path.write_text(json.dumps(acct, indent=2), encoding="utf-8")
    return acct


def _format_walking_time(seconds: Any) -> str:
    if seconds is None or seconds == "":
        return "0 seconds"
    secs = int(seconds)
    if secs < 60:
        return f"{secs} second{'s' if secs != 1 else ''}"
    mins = secs // 60
    rem = secs % 60
    out = f"{mins} minute{'s' if mins != 1 else ''}"
    if rem > 0:
        out += f" {rem} second{'s' if rem != 1 else ''}"
    return out


def _format_floor(level: Any) -> str:
    if level is None or level == "":
        return "N/A"
    lvl = int(level)
    return "Ground Floor" if lvl in (0, 1) else f"Level {lvl}"


def _build_per_floor_html(visualizations: list[dict], instructions: list[dict]) -> str:
    if not visualizations and not instructions:
        return ""
    floor_order: list[str] = []
    floor_steps: dict[str, list[dict]] = {}
    floor_meta: dict[str, dict] = {}

    for step in instructions or []:
        fp_id = step.get("floorplan_id")
        if fp_id is None:
            continue
        key = str(fp_id)
        if key not in floor_steps:
            floor_steps[key] = []
            floor_order.append(key)
            floor_meta[key] = {
                "building_name": step.get("building_name") or "Building",
                "floor_level": step.get("floor_level", "N/A"),
            }
        floor_steps[key].append(step)

    viz_by_fp: dict[str, dict] = {}
    for viz in visualizations or []:
        key = str(viz["floorplanId"])
        viz_by_fp[key] = viz
        if key not in floor_steps:
            floor_steps[key] = []
            floor_order.append(key)
            floor_meta[key] = {
                "building_name": viz.get("buildingName") or "Building",
                "floor_level": viz.get("floorLevel", "N/A"),
            }

    parts = []
    for key in floor_order:
        meta = floor_meta.get(key, {})
        viz = viz_by_fp.get(key)
        steps = floor_steps.get(key, [])
        bldg = meta.get("building_name", "Building")
        lvl = meta.get("floor_level", "N/A")

        img_html = (
            f'<img src="cid:{viz["cid"]}" alt="{bldg} Floor {lvl} route map" '
            f'style="max-width:100%;border-radius:8px;border:1px solid #e2e8f0;display:block;margin-bottom:14px;" />'
            if viz
            else ""
        )
        steps_html = ""
        if steps:
            step_divs = []
            for s in steps:
                dist_span = (
                    f' <span style="color:#64748b;font-size:11px;">({s.get("distance_m")}m)</span>'
                    if s.get("type") == "walk"
                    else ""
                )
                step_divs.append(
                    f'<div style="margin-bottom:6px;padding:10px 12px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;font-size:13px;color:#334155;">'
                    f'{s.get("description", "")}{dist_span}</div>'
                )
            items = "".join(step_divs)
            steps_html = f'<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;margin:0 0 8px 0;">Turn-by-Turn Directions</p>{items}'

        parts.append(
            f'<div style="border:1px solid #e2e8f0;border-radius:8px;margin-bottom:16px;overflow:hidden;">'
            f'<div style="background:#f8fafc;padding:10px 16px;border-bottom:1px solid #e2e8f0;">'
            f'<h3 style="margin:0;font-size:12px;font-weight:700;color:#4f46e5;text-transform:uppercase;">{bldg} — Floor {lvl}</h3>'
            f'</div><div style="padding:12px 16px;">{img_html}{steps_html}</div></div>'
        )
    return "".join(parts)


def _send_email_smtp(
    *,
    to_email: str,
    subject: str,
    html_content: str,
    attachments: list[dict] | None = None,
    delivery_mode: str = "ethereal",
    max_retries: int = 3,
) -> dict[str, Any]:
    mode = (delivery_mode or os.getenv("EMAIL_MODE") or "ethereal").lower()
    sender = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "noreply@campusnavigation.com"

    if mode == "smtp":
        host = os.getenv("SMTP_HOST", "")
        port = int(os.getenv("SMTP_PORT", "587") or 587)
        user = os.getenv("SMTP_USER", "")
        password = os.getenv("SMTP_PASSWORD", "")
        use_ssl = os.getenv("SMTP_SECURE", "").lower() == "true" or port == 465
        if not host or not user or not password:
            return {"success": False, "error": "SMTP configuration is incomplete (SMTP_HOST/USER/PASSWORD)."}
        ethereal_web = None
    else:
        try:
            acct = _get_ethereal_account()
            host = acct["smtp"]["host"]
            port = int(acct["smtp"]["port"])
            user = acct["user"]
            password = acct["pass"]
            use_ssl = bool(acct["smtp"].get("secure"))
            ethereal_web = acct.get("web", "https://ethereal.email")
        except Exception as exc:
            return {"success": False, "error": f"Ethereal account setup failed: {exc}"}

    msg = MIMEMultipart("related")
    msg["From"] = f'"Campus Navigation Hub" <{sender}>'
    msg["To"] = to_email
    msg["Subject"] = subject
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_content, "html", "utf-8"))
    msg.attach(alt)

    for att in attachments or []:
        fp = Path(att["filePath"])
        if fp.is_file():
            img = MIMEImage(fp.read_bytes(), _subtype="png")
            img.add_header("Content-ID", f"<{att['cid']}>")
            img.add_header("Content-Disposition", "inline", filename=att["filename"])
            msg.attach(img)

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            if use_ssl:
                server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=15)
            else:
                server = smtplib.SMTP(host, port, timeout=15)
                server.starttls()
            with server:
                server.login(user, password)
                # Use low-level mail/rcpt/data so we capture Ethereal's 250 response containing MSGID=...
                code, resp = server.mail(sender)
                if code != 250:
                    raise smtplib.SMTPSenderRefused(code, resp, sender)
                code, resp = server.rcpt(to_email)
                if code not in (250, 251):
                    raise smtplib.SMTPRecipientsRefused({to_email: (code, resp)})
                code, resp = server.data(msg.as_bytes())
                if code != 250:
                    raise smtplib.SMTPDataError(code, resp)
            resp_text = resp.decode("utf-8", errors="ignore") if isinstance(resp, (bytes, bytearray)) else str(resp)
            preview_url = None
            if ethereal_web:
                m = re.search(r"MSGID=([^\s\]]+)", resp_text)
                if m:
                    preview_url = f"{ethereal_web.rstrip('/')}/message/{m.group(1)}"
                else:
                    preview_url = f"{ethereal_web.rstrip('/')}/messages"
            return {"success": True, "previewUrl": preview_url}
        except Exception as exc:
            last_err = exc
            if attempt < max_retries:
                time.sleep(1.5)

    err_str = str(last_err or "SMTP unavailable")
    lower = err_str.lower()
    if "auth" in lower or isinstance(last_err, smtplib.SMTPAuthenticationError):
        classified = "Authentication failure"
    elif "timeout" in lower or isinstance(last_err, TimeoutError):
        classified = "Timeout"
    elif "recipient" in lower or "envelope" in lower or isinstance(last_err, smtplib.SMTPRecipientsRefused):
        classified = "Invalid email"
    else:
        classified = "SMTP unavailable"
    return {"success": False, "error": classified}


def _render_host_email(payload: dict) -> tuple[str, str]:
    event_type = payload.get("event_type", "appointment_routing")
    host_name = payload.get("host_name") or "Host"
    visitor_name = payload.get("visitor_name") or "Visitor"
    visitor_role = payload.get("rbac_role") or "Visitor"
    rs = payload.get("route_summary") or {}
    start_lbl = rs.get("start_label") or payload.get("current_location") or "Start"
    dest_lbl = rs.get("destination_label") or payload.get("destination_node") or "Destination"
    walk_time = _format_walking_time(rs.get("estimated_time_seconds"))
    dist_str = f"{float(rs.get('total_distance_m') or 0):.2f} metres"
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    if event_type == "emergency_alert":
        subject = f"Campus Emergency Alert: {visitor_name}"
        header_bg = "#dc2626"
        headline = f"An emergency has been detected involving your visitor <strong>{visitor_name}</strong>."
    elif event_type == "visitor_arrival":
        subject = f"Campus Visitor Arrival Notification: {visitor_name}"
        header_bg = "#059669"
        headline = f"Your visitor <strong>{visitor_name}</strong> has arrived at <strong>{dest_lbl}</strong>."
    else:
        subject = f"Campus Host Notification: {visitor_name}"
        header_bg = "#4f46e5"
        headline = f"Your visitor <strong>{visitor_name}</strong> has arrived at <strong>{start_lbl}</strong> and is navigating to <strong>{dest_lbl}</strong>."

    body = (
        f'<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e2e8f0;padding:24px;border-radius:12px;background:#fff;color:#1e293b;">'
        f'<div style="background:{header_bg};padding:16px;border-radius:8px;margin-bottom:20px;text-align:center;"><h2 style="color:#fff;margin:0;font-size:18px;">{subject}</h2></div>'
        f'<p>Dear <strong>{host_name}</strong>,</p><p>{headline}</p>'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0;">'
        f'<tr><td style="padding:4px 0;color:#64748b;">Visitor Role:</td><td style="font-weight:600;">{visitor_role}</td></tr>'
        f'<tr><td style="padding:4px 0;color:#64748b;">Start:</td><td style="font-weight:600;">{start_lbl}</td></tr>'
        f'<tr><td style="padding:4px 0;color:#64748b;">Destination:</td><td style="font-weight:600;">{dest_lbl}</td></tr>'
        f'<tr><td style="padding:4px 0;color:#64748b;">Est. Walking Time:</td><td style="font-weight:700;color:#0d9488;">{walk_time} ({dist_str})</td></tr>'
        f'</table><div style="font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:12px;">Generated {now_str} · Smart Campus Navigation</div></div>'
    )
    return subject, body


def _render_visitor_email(payload: dict) -> tuple[str, str, list[dict]]:
    event_type = payload.get("event_type", "appointment_routing")
    visitor_name = payload.get("visitor_name") or "Visitor"
    rs = payload.get("route_summary") or {}
    start_lbl = rs.get("start_label") or payload.get("current_location") or "Start"
    dest_lbl = rs.get("destination_label") or payload.get("destination_node") or "Destination"
    walk_time = _format_walking_time(rs.get("estimated_time_seconds"))
    dist_str = f"{float(rs.get('total_distance_m') or 0):.2f} metres"
    visualizations = payload.get("routeVisualizations") or []
    instructions = payload.get("instructions") or []

    if event_type == "visitor_arrival":
        subject = f"Destination Reached: {dest_lbl}"
        body = (
            f'<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e2e8f0;padding:24px;border-radius:12px;background:#fff;color:#1e293b;">'
            f'<div style="background:#059669;padding:16px;border-radius:8px;margin-bottom:20px;text-align:center;"><h2 style="color:#fff;margin:0;">Destination Reached</h2></div>'
            f'<p>Dear <strong>{visitor_name}</strong>,</p><p>You have arrived at <strong>{dest_lbl}</strong>.</p></div>'
        )
        return subject, body, []

    if event_type == "emergency_alert":
        subject = "Emergency Alert: Action Required"
        body = (
            f'<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;border:1px solid #fecaca;padding:24px;border-radius:12px;background:#fff;color:#1e293b;">'
            f'<div style="background:#dc2626;padding:16px;border-radius:8px;margin-bottom:20px;text-align:center;"><h2 style="color:#fff;margin:0;">Emergency Alert</h2></div>'
            f'<p>Dear <strong>{visitor_name}</strong>,</p><p style="color:#991b1b;font-weight:600;">An emergency has been reported near {start_lbl}. Please follow campus safety instructions immediately.</p></div>'
        )
        return subject, body, []

    subject = f"Campus Navigation Guide: Route to {dest_lbl}"
    per_floor = _build_per_floor_html(visualizations, instructions)
    start_bldg = rs.get("start_building_name") or "Main Campus"
    dest_bldg = rs.get("destination_building_name") or "Main Campus"
    body = (
        f'<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e2e8f0;padding:24px;border-radius:12px;background:#fff;color:#1e293b;">'
        f'<div style="background:#4f46e5;padding:16px;border-radius:8px;margin-bottom:20px;text-align:center;"><h2 style="color:#fff;margin:0;">Campus Navigation Guide</h2></div>'
        f'<p>Dear <strong>{visitor_name}</strong>,</p>'
        f'<p>Your route from <strong>{start_lbl}</strong> ({start_bldg}, {_format_floor(rs.get("start_floor_level"))}) to '
        f'<strong>{dest_lbl}</strong> ({dest_bldg}, {_format_floor(rs.get("destination_floor_level"))}) is ready.</p>'
        f'<p style="color:#0d9488;font-weight:700;">Estimated Time: {walk_time} · Total Distance: {dist_str}</p>'
        f'{per_floor}'
        f'<div style="font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:12px;text-align:center;">Smart Campus Navigation System</div></div>'
    )
    return subject, body, visualizations


def process_notification_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Idempotently deliver one HOST or VISITOR notification and update the MySQL audit trail."""
    message_id = payload.get("message_id")
    if not message_id:
        return {"success": False, "error": "Missing message_id"}

    db = SessionLocal()
    try:
        rec = db.query(Notification).filter(Notification.message_id == message_id).first()
        if rec and rec.status not in ("PENDING", "QUEUED"):
            return {"success": True, "status": rec.status, "skipped": True}

        if rec is None:
            return {"success": False, "error": "Audit record missing"}

        rec.status = "RETRYING"
        db.commit()

        notif_type = payload.get("notification_type", "HOST")
        mode = payload.get("email_delivery_mode") or os.getenv("EMAIL_MODE") or "ethereal"

        if notif_type == "VISITOR":
            to_email = payload.get("visitor_email")
            if not to_email:
                rec.status = "FAILED"
                rec.delivery_error = "Target user missing"
                db.commit()
                return {"success": False, "error": "Visitor email unavailable"}
            subject, html_body, attachments = _render_visitor_email(payload)
            result = _send_email_smtp(
                to_email=to_email,
                subject=subject,
                html_content=html_body,
                attachments=attachments,
                delivery_mode=mode,
            )
        else:
            host_email = payload.get("host_email")
            if not host_email:
                rec.status = "FAILED"
                rec.delivery_error = "Target user missing"
                db.commit()
                return {"success": False, "error": "Host email unavailable"}
            subject, html_body = _render_host_email(payload)
            result = _send_email_smtp(
                to_email=host_email,
                subject=subject,
                html_content=html_body,
                attachments=[],
                delivery_mode=mode,
            )

        if result.get("success"):
            rec.status = "SENT"
            rec.sent_at = datetime.datetime.utcnow()
            rec.delivery_error = None
            if result.get("previewUrl"):
                rec.body = f"{rec.body}\n\nPreview Link: {result['previewUrl']}"
        else:
            rec.status = "FAILED"
            rec.delivery_error = result.get("error") or "SMTP unavailable"
        db.commit()
        return result
    except Exception as exc:
        logger.exception("Notification delivery failed for %s: %s", message_id, exc)
        try:
            rec = db.query(Notification).filter(Notification.message_id == message_id).first()
            if rec:
                rec.status = "FAILED"
                rec.delivery_error = "SMTP unavailable"
                db.commit()
        except Exception:
            pass
        return {"success": False, "error": str(exc)}
    finally:
        db.close()


def _try_publish_rabbitmq(payload: dict[str, Any]) -> bool:
    url = os.getenv("RABBITMQ_URL", "").strip()
    if not url:
        return False
    try:
        import pika

        params = pika.URLParameters(url)
        params.socket_timeout = 2
        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        q = ch.queue_declare(queue="campus.notifications.queue", durable=True)
        if getattr(q.method, "consumer_count", 0) <= 0:
            conn.close()
            logger.info("RabbitMQ has no active notification consumer; dispatching via FastAPI BackgroundTasks.")
            return False
        ch.basic_publish(
            exchange="",
            routing_key="campus.notifications.queue",
            body=json.dumps(payload),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        conn.close()
        return True
    except Exception as exc:
        logger.info("RabbitMQ unavailable (%s); falling back to FastAPI BackgroundTasks.", exc)
        return False


def build_and_dispatch_notifications(
    db: Session,
    *,
    req_body: dict[str, Any],
    route_result: dict[str, Any],
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    trigger = req_body.get("notification_trigger") or {}
    raw_host_id = trigger.get("target_host_id") if trigger.get("target_host_id") is not None else req_body.get("target_host_id")
    host_id = int(raw_host_id) if raw_host_id not in (None, "") else None
    alert_msg = trigger.get("alert_message") or req_body.get("alert_message")
    event_type = req_body.get("event_type") or "appointment_routing"

    if host_id and not alert_msg:
        raise NotificationBuildError(
            "Missing alert_message for the provided target_host_id in notification_trigger.", 400
        )
    if not host_id and event_type != "visitor_navigation":
        raise NotificationBuildError("Target host ID is required for this event type.", 400)

    try:
        visitor_id = int(req_body.get("user_id"))
    except (TypeError, ValueError):
        raise NotificationBuildError("user_id must be a numeric user ID.", 400)

    user_ids = [visitor_id] + ([host_id] if host_id else [])
    users = db.query(User).options(joinedload(User.roles)).filter(User.user_id.in_(user_ids)).all()
    user_map = {u.user_id: u for u in users}

    resolved_visitor = user_map.get(visitor_id)
    if not resolved_visitor:
        raise NotificationBuildError(f"Visitor user ID {visitor_id} does not exist in the database.", 404)

    resolved_host = None
    if host_id:
        resolved_host = user_map.get(host_id)
        if not resolved_host:
            raise NotificationBuildError(f"Target host ID {host_id} does not exist in the database.", 404)

    ts_ms = int(time.time() * 1000)
    visitor_msg_id = f"MSG-VISITOR-{ts_ms}-{secrets.token_hex(2)}"
    host_msg_id = f"MSG-HOST-{ts_ms}-{secrets.token_hex(2)}" if resolved_host else None

    route_visualizations: list[dict] = []
    if event_type in ("appointment_routing", "visitor_navigation"):
        try:
            route_visualizations = generate_route_visualisations(db, route_result, visitor_msg_id)
        except Exception as exc:
            logger.warning("Route visualization generation failed (non-fatal): %s", exc)

    path = route_result.get("path") or []
    rs = route_result.get("route_summary") or {}
    enriched_summary = {
        **rs,
        "start_building_name": path[0].get("building_name", "") if path else "",
        "start_floor_level": path[0].get("floor_level", 0) if path else 0,
        "destination_building_name": path[-1].get("building_name", "") if path else "",
        "destination_floor_level": path[-1].get("floor_level", 0) if path else 0,
    }

    visitor_role_name = (
        resolved_visitor.roles[0].role_name if resolved_visitor.roles else "VISITOR"
    )
    delivery_mode = req_body.get("email_delivery_mode") or os.getenv("EMAIL_MODE") or "ethereal"

    host_payload = None
    if resolved_host and host_msg_id:
        host_payload = {
            "message_id": host_msg_id,
            "notification_type": "HOST",
            "host_name": resolved_host.full_name,
            "host_email": resolved_host.email,
            "event_type": event_type,
            "user_id": resolved_visitor.user_id,
            "visitor_name": resolved_visitor.full_name,
            "rbac_role": visitor_role_name,
            "current_location": rs.get("start_label"),
            "destination_node": rs.get("destination_label"),
            "route_summary": enriched_summary,
            "instructions": route_result.get("instructions") or [],
            "notification_trigger": {"target_host_id": host_id, "alert_message": alert_msg},
            "email_delivery_mode": delivery_mode,
        }
        db.add(
            Notification(
                recipient_user_id=resolved_host.user_id,
                event_type=event_type,
                title=f"Campus Visitor Alert: {resolved_visitor.full_name}",
                body=alert_msg or "Visitor is en route",
                status="PENDING",
                message_id=host_msg_id,
            )
        )

    visitor_email_available = bool(resolved_visitor.email and resolved_visitor.email.strip())
    visitor_payload = None
    visitor_error = None if visitor_email_available else "Visitor email unavailable"

    db.add(
        Notification(
            recipient_user_id=resolved_visitor.user_id,
            event_type=event_type,
            title=f"Campus Visitor Journey: {resolved_visitor.full_name}",
            body=f"Journey instructions to {rs.get('destination_label', 'Destination')}",
            status="PENDING" if visitor_email_available else "FAILED",
            message_id=visitor_msg_id,
            delivery_error=visitor_error,
        )
    )
    db.commit()

    if visitor_email_available:
        visitor_payload = {
            "message_id": visitor_msg_id,
            "notification_type": "VISITOR",
            "visitor_email": resolved_visitor.email.strip(),
            "event_type": event_type,
            "user_id": resolved_visitor.user_id,
            "visitor_name": resolved_visitor.full_name,
            "rbac_role": visitor_role_name,
            "current_location": rs.get("start_label"),
            "destination_node": rs.get("destination_label"),
            "route_summary": enriched_summary,
            "instructions": route_result.get("instructions") or [],
            "routeVisualizations": route_visualizations,
            "email_delivery_mode": delivery_mode,
        }

    for p in (host_payload, visitor_payload):
        if p is None:
            continue
        if not _try_publish_rabbitmq(p):
            if background_tasks is not None:
                background_tasks.add_task(process_notification_payload, p)
            else:
                process_notification_payload(p)

    return {
        "message_id": host_msg_id,
        "status": "QUEUED",
        "published_at": datetime.datetime.utcnow().isoformat() + "Z",
        "target_host_id": resolved_host.user_id if resolved_host else None,
        "host": {"message_id": host_msg_id, "status": "QUEUED"} if host_payload else None,
        "visitor": {
            "message_id": visitor_msg_id,
            "status": "QUEUED" if visitor_email_available else "FAILED",
            "delivery_error": visitor_error,
        },
    }
