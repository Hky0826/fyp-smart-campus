"""Sanitized administrator and security audit event helpers."""

from __future__ import annotations

from typing import Any

from app.models.models import AdministratorAuditEvent


def record_audit(db, *, actor_user_id: int | None, action: str, target_type: str,
                 target_id: str | int | None, result: str, correlation_id: str | None = None,
                 source_ip: str | None = None, details: dict[str, Any] | None = None) -> None:
    safe_details = {}
    for key, value in (details or {}).items():
        if key.casefold() in {"token", "password", "secret", "biometric", "face_vector", "audio", "transcript", "path", "filesystem"}:
            continue
        safe_details[str(key)[:64]] = str(value)[:256]
    db.add(AdministratorAuditEvent(
        actor_user_id=actor_user_id, action=action[:100], target_type=target_type[:50],
        target_id=None if target_id is None else str(target_id)[:100], result=result[:32],
        correlation_id=correlation_id, source_ip=source_ip, details=safe_details,
    ))
