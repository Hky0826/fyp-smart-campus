from __future__ import annotations

from html import escape


def visitor_email(*, visitor_name: str, destination: str, instructions: list[str] = ()) -> str:
    safe_steps = "".join(f"<li>{escape(str(step))}</li>" for step in instructions)
    return f"<html><body><p>Hello {escape(visitor_name)},</p><p>Your destination is <strong>{escape(destination)}</strong>.</p><ol>{safe_steps}</ol></body></html>"


def host_email(*, host_name: str, visitor_name: str, alert: str, instructions: list[str] = ()) -> str:
    safe_steps = "".join(f"<li>{escape(str(step))}</li>" for step in instructions)
    return f"<html><body><p>Hello {escape(host_name)},</p><p>{escape(visitor_name)} has an appointment with you.</p><p>{escape(alert)}</p><ol>{safe_steps}</ol></body></html>"
