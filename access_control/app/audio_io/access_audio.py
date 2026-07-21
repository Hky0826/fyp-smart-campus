"""Access-control bridge between face authentication and audio I/O."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import threading
import time
from typing import Any

from ..chatbot.token import EdgeAuthToken, EdgeAuthTokenClient

logger = logging.getLogger(__name__)


class AccessControlAudioCoordinator:
    """Starts audio I/O and shares access-control JWTs with it."""

    def __init__(self, config: Any) -> None:
        self.config = config
        cloud_url = getattr(config, 'cloud_url', getattr(config, 'sync_cloud_url', 'http://127.0.0.1:8000'))
        device_id = getattr(config, 'device_id', getattr(config, 'sync_device_id', 'access-control-01'))
        self.token_client = EdgeAuthTokenClient(cloud_url, device_id)
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
        if not getattr(self.config, 'audio_enabled', False):
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
        if not getattr(self.config, 'audio_enabled', False):
            return
        self._chatbot_activation_event.set()
        logger.info("Chatbot activation requested")

    def handle_access_result(self, result: dict[str, Any]) -> None:
        if not result.get("access_granted") and not result.get("verified"):
            return
        user_id = result.get("user_id") or result.get("identity_id")
        if user_id is None:
            return
        try:
            int_id = int(user_id)
        except (TypeError, ValueError):
            return
        if not self._should_attempt_authenticated_token(int_id):
            return
        try:
            token = self.token_client.issue_token(int_id)
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
        timeout = getattr(self.config, 'audio_auth_timeout_seconds', 45)
        return self._auth_event.wait(timeout)

    def _run_audio(self) -> None:
        try:
            cloud_url = getattr(self.config, 'cloud_url', getattr(self.config, 'sync_cloud_url', 'http://127.0.0.1:8000')).rstrip('/')
            device_id = getattr(self.config, 'device_id', getattr(self.config, 'sync_device_id', 'access-control-01'))
            from .config import AudioConfig
            audio_config = AudioConfig(
                cloud_api_url=f"{cloud_url}/api/chatbot/chat/audio",
                cloud_stream_api_url=f"{cloud_url}/api/chatbot/chat/audio/stream",
                cloud_device_id=device_id,
            )
            # Standalone audio loop if edge audio player available
            logger.info("Audio interaction loop configured with %s", audio_config.cloud_api_url)
        except Exception:
            logger.exception("Access-control audio I/O stopped unexpectedly")

    def _maybe_issue_visitor_token(self) -> None:
        if not getattr(self.config, 'audio_auto_visitor_token', False):
            return
        visitor_user_id = getattr(self.config, 'audio_visitor_user_id', None) or self._find_local_visitor_user_id()
        if visitor_user_id is None:
            logger.info("No visitor user configured or cached")
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
        db_path = getattr(self.config, 'database_path', 'data/device_local.db')
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
            retry_seconds = getattr(self.config, 'audio_token_retry_seconds', 10)
            if now - last_attempt < retry_seconds:
                return False

            token = self._authenticated_token
            if token is None or token.user_id != user_id:
                self._last_token_attempts[user_id] = now
                return True
            if not token.is_fresh():
                self._last_token_attempts[user_id] = now
                return True
            elapsed = now - self._last_authenticated_refresh
            refresh_seconds = getattr(self.config, 'audio_token_refresh_seconds', 600)
            if elapsed >= refresh_seconds:
                self._last_token_attempts[user_id] = now
                return True
            return False

    @staticmethod
    def _credentials(token: EdgeAuthToken) -> dict[str, Any]:
        return {"bearer_token": token.access_token, "session_id": token.session_id}
