"""Access-control-only bridge between face authentication and audio I/O."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ..config import AccessControlConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdgeAuthToken:
    """JWT metadata issued by the cloud edge-auth endpoint."""

    access_token: str
    session_id: int | None
    user_id: int
    username: str | None = None
    roles: tuple[str, ...] = ()
    expires_at: dt.datetime | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EdgeAuthToken":
        expires_at = _parse_timestamp(payload.get("expires_at"))
        return cls(
            access_token=str(payload["access_token"]),
            session_id=_optional_int(payload.get("session_id")),
            user_id=int(payload["user_id"]),
            username=str(payload["username"]) if payload.get("username") else None,
            roles=tuple(str(role) for role in payload.get("roles", [])),
            expires_at=expires_at,
        )

    def is_fresh(self, now: dt.datetime | None = None, margin_seconds: int = 60) -> bool:
        if self.expires_at is None:
            return True
        expires_at = self.expires_at
        if now is not None:
            current = now
        elif expires_at.tzinfo is not None:
            current = dt.datetime.now(expires_at.tzinfo)
        else:
            current = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        return current + dt.timedelta(seconds=margin_seconds) < expires_at


class EdgeAuthTokenClient:
    """Requests user-scoped JWTs after local face recognition succeeds."""

    def __init__(self, cloud_url: str, device_id: str, timeout_seconds: float = 8.0) -> None:
        self.cloud_url = cloud_url.rstrip("/")
        self.device_id = device_id
        self.timeout_seconds = timeout_seconds
        self.endpoint = f"{self.cloud_url}/api/edge-auth/token"

    def issue_token(self, user_id: int | str) -> EdgeAuthToken:
        payload = {"user_id": int(user_id), "device_id": self.device_id}
        response = requests.post(self.endpoint, json=payload, timeout=self.timeout_seconds)
        if response.status_code >= 400:
            raise RuntimeError(self._error_message(response))
        return EdgeAuthToken.from_payload(response.json())

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text.strip()
        return f"edge-auth token request failed with HTTP {response.status_code}: {detail or 'no details'}"


class AccessControlAudioCoordinator:
    """Starts audio I/O and shares access-control JWTs with it."""

    def __init__(self, config: AccessControlConfig) -> None:
        self.config = config
        self.token_client = EdgeAuthTokenClient(config.sync_cloud_url, config.sync_device_id)
        self._lock = threading.Lock()
        self._authenticated_token: EdgeAuthToken | None = None
        self._visitor_token: EdgeAuthToken | None = None
        self._last_authenticated_refresh: float = 0.0
        self._last_token_attempts: dict[int, float] = {}
        self._auth_event = threading.Event()
        self._chatbot_activation_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.audio_enabled:
            logger.info("Access-control audio I/O is disabled")
            return
        if self._thread and self._thread.is_alive():
            return

        self._maybe_issue_visitor_token()
        self._stop_event.clear()
        self._chatbot_activation_event.clear()
        self._thread = threading.Thread(target=self._run_audio, daemon=True, name="access-control-audio")
        self._thread.start()
        logger.info("Access-control audio I/O started")

    def stop(self) -> None:
        self._stop_event.set()
        self._chatbot_activation_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def activate_chatbot(self) -> None:
        """Request one audio chatbot interaction."""
        if not self.config.audio_enabled:
            return
        self._chatbot_activation_event.set()
        logger.info("Chatbot activation requested from space bar")

    def handle_access_result(self, result: dict[str, Any]) -> None:
        if not result.get("access_granted"):
            return
        user_id = result.get("user_id")
        if user_id is None:
            return
        if not self._should_attempt_authenticated_token(int(user_id)):
            return
        try:
            token = self.token_client.issue_token(user_id)
        except Exception as exc:
            logger.warning("Face matched user %s, but JWT issuance failed: %s", user_id, exc)
            return

        with self._lock:
            self._authenticated_token = token
            self._last_authenticated_refresh = time.monotonic()
            self._auth_event.set()
        logger.info("Received chatbot JWT for user_id=%s session_id=%s", token.user_id, token.session_id)

    def credential_provider(self) -> dict[str, Any] | None:
        with self._lock:
            token = self._authenticated_token
            if token is not None and token.is_fresh():
                return self._credentials(token)

            visitor_token = self._visitor_token
            if visitor_token is not None and visitor_token.is_fresh():
                return self._credentials(visitor_token)
        return None

    def wait_for_face_authentication(self, _: str) -> bool:
        with self._lock:
            token = self._authenticated_token
            if token is not None and token.is_fresh():
                return True
            self._auth_event.clear()
        return self._auth_event.wait(self.config.audio_auth_timeout_seconds)

    def _run_audio(self) -> None:
        try:
            from edge.audio_io.config import AudioIOConfig
            from edge.audio_io.main import AudioInteractionPipeline

            audio_config = AudioIOConfig(
                cloud_api_url=f"{self.config.sync_cloud_url.rstrip('/')}/api/chatbot/chat/audio",
                cloud_device_id=self.config.sync_device_id,
            )
            pipeline = AudioInteractionPipeline(
                audio_config,
                credential_provider=self.credential_provider,
                auth_required_handler=self.wait_for_face_authentication,
                activation_event=self._chatbot_activation_event,
            )
            pipeline.run_forever(stop_event=self._stop_event)
        except Exception:
            logger.exception("Access-control audio I/O stopped unexpectedly")

    def _maybe_issue_visitor_token(self) -> None:
        if not self.config.audio_auto_visitor_token:
            return
        visitor_user_id = self.config.audio_visitor_user_id or self._find_local_visitor_user_id()
        if visitor_user_id is None:
            logger.info("No visitor user configured or cached; audio will request face auth for protected chat")
            return
        try:
            token = self.token_client.issue_token(visitor_user_id)
        except Exception as exc:
            logger.warning("Could not issue visitor chatbot JWT for user_id=%s: %s", visitor_user_id, exc)
            return
        with self._lock:
            self._visitor_token = token
        logger.info("Received visitor chatbot JWT for user_id=%s session_id=%s", token.user_id, token.session_id)

    def _find_local_visitor_user_id(self) -> int | None:
        db_path = Path(self.config.database_path)
        if not db_path.exists():
            return None
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(db_path))
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            required = {"device_users", "device_roles", "device_user_roles"}
            if not required.issubset(tables):
                return None
            row = conn.execute(
                """
                SELECT u.user_id
                FROM device_users u
                INNER JOIN device_user_roles ur ON ur.user_id = u.user_id
                INNER JOIN device_roles r ON r.role_id = ur.role_id
                WHERE u.is_active = 1 AND UPPER(r.role_name) = 'VISITOR'
                ORDER BY u.user_id
                LIMIT 1
                """
            ).fetchone()
        except sqlite3.Error as exc:
            logger.warning("Could not inspect local visitor user cache: %s", exc)
            return None
        finally:
            if conn is not None:
                conn.close()
        return int(row[0]) if row else None

    def _should_attempt_authenticated_token(self, user_id: int) -> bool:
        with self._lock:
            now = time.monotonic()
            last_attempt = self._last_token_attempts.get(user_id, 0.0)
            if now - last_attempt < self.config.audio_token_retry_seconds:
                return False

            token = self._authenticated_token
            if token is None or token.user_id != user_id:
                self._last_token_attempts[user_id] = now
                return True
            if not token.is_fresh():
                self._last_token_attempts[user_id] = now
                return True
            elapsed = now - self._last_authenticated_refresh
            if elapsed >= self.config.audio_token_refresh_seconds:
                self._last_token_attempts[user_id] = now
                return True
            return False

    @staticmethod
    def _credentials(token: EdgeAuthToken) -> dict[str, Any]:
        return {"bearer_token": token.access_token, "session_id": token.session_id}


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        logger.warning("Could not parse edge-auth token expiry: %s", value)
        return None
