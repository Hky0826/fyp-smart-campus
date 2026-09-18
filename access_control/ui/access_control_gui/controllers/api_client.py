"""HTTP client for the existing edge kiosk API.

This module intentionally mirrors the web frontend's API client. It does not
own authentication decisions, RBAC, face matching, database writes, or cloud
chatbot behavior; those remain in the existing FastAPI/backend services.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import requests


def get_default_api_base_url() -> str:
    port = os.getenv("ACCESS_API_PORT") or os.getenv("EDGE_SYNC_LOCAL_PORT") or "8080"
    return f"http://127.0.0.1:{port}"


CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 90


class KioskApiError(RuntimeError):
    """Raised when the kiosk API returns an error or cannot be reached."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class KioskApiClient:
    """Small blocking client used only from worker threads."""

    def __init__(self, base_url: str | None = None) -> None:
        configured = (
            base_url
            or os.getenv("EDGE_GUI_API_BASE_URL")
            or os.getenv("VITE_EDGE_API_BASE_URL")
            or get_default_api_base_url()
        )
        self.base_url = configured.rstrip("/")
        self._session = requests.Session()

    def get_state(self) -> dict[str, Any]:
        return self._request_json("GET", "/kiosk/state")

    def get_live_config(self) -> dict[str, Any]:
        return self._request_json("GET", "/kiosk/chat/live-config")

    def get_database_status(self) -> dict[str, Any]:
        return self._request_json("GET", "/database/status")

    def get_models_status(self) -> dict[str, Any]:
        return self._request_json("GET", "/models/status")

    def get_setup_status(self) -> dict[str, Any]:
        return self._request_json("GET", "/setup/status")

    def complete_setup(self) -> dict[str, Any]:
        return self._request_json("POST", "/setup/complete")

    def provision_setup(self, cloud_url: str, device_id: str, device_secret: str, remote_push: bool = False) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/setup/provision",
            json_body={
                "cloud_url": cloud_url,
                "device_id": device_id,
                "device_secret": device_secret,
                "remote_push": remote_push,
            },
        )

    def request_access(self) -> dict[str, Any]:
        return self._request_json("POST", "/kiosk/access/request")

    def verify_access_frame(self, jpeg_bytes: bytes) -> dict[str, Any]:
        return self._post_frame("/kiosk/access/frame", "access-frame.jpg", jpeg_bytes)

    def verify_chat_owner_frame(self, jpeg_bytes: bytes) -> dict[str, Any]:
        return self._post_frame("/kiosk/chat/verify/frame", "chat-owner-frame.jpg", jpeg_bytes)

    def verify_chat_presence_frame(self, jpeg_bytes: bytes) -> dict[str, Any]:
        return self._post_frame("/kiosk/chat/presence/frame", "chat-presence-frame.jpg", jpeg_bytes)

    def reopen_chat_frame(self, jpeg_bytes: bytes) -> dict[str, Any]:
        return self._post_frame("/kiosk/chat/reopen/frame", "chat-reopen-frame.jpg", jpeg_bytes)

    def send_chat_message(self, query: str) -> dict[str, Any]:
        return self._request_json("POST", "/kiosk/chat/message", json_body={"query": query})

    def request_greeting_audio(self) -> dict[str, Any]:
        """Deprecated stub. All spoken greeting audio is handled by Gemini Live."""
        return {"audio_response": None, "sample_rate": 24000}

    def send_chat_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav") -> dict[str, Any]:
        files = {"audio": ("chat-audio.wav", audio_bytes, mime_type)}
        return self._request_json("POST", "/kiosk/chat/audio", files=files)

    def send_chat_audio_file(self, path: str | Path, mime_type: str = "audio/wav") -> dict[str, Any]:
        with Path(path).open("rb") as handle:
            return self._request_json(
                "POST",
                "/kiosk/chat/audio",
                files={"audio": (Path(path).name, handle, mime_type)},
            )

    def send_chat_audio_stream_file(
        self,
        path: str | Path,
        mime_type: str = "audio/wav",
        cancel_requested: Callable[[], bool] | None = None,
    ) -> Iterator[dict[str, Any]]:
        import json
        url = f"{self.base_url}/kiosk/chat/audio/stream"
        with Path(path).open("rb") as handle:
            files = {"audio": (Path(path).name, handle, mime_type)}
            with self._session.post(url, files=files, stream=True, timeout=(5, 90)) as response:
                if response.status_code >= 400:
                    raise self._error_from_response(response)
                for line in response.iter_lines(decode_unicode=True):
                    if cancel_requested and cancel_requested():
                        break
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue

    def lock_chat(self) -> dict[str, Any]:
        return self._request_json("POST", "/kiosk/chat/lock")

    def end_chat(self) -> dict[str, Any]:
        return self._request_json("POST", "/kiosk/chat/end")

    def stop_chat_audio(self) -> dict[str, Any]:
        return self._request_json("POST", "/kiosk/chat/audio/stop")

    def stream_states(self) -> Iterator[dict[str, Any]]:
        """Yield state events from the kiosk SSE endpoint."""
        url = f"{self.base_url}/kiosk/events"
        try:
            with self._session.get(
                url,
                stream=True,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    raise self._error_from_response(response)
                event_name = ""
                data_lines: list[str] = []
                for raw_line in response.iter_lines(decode_unicode=True):
                    line = raw_line or ""
                    if not line:
                        if event_name == "state" and data_lines:
                            yield json.loads("\n".join(data_lines))
                        event_name = ""
                        data_lines = []
                        continue
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].strip())
        except requests.RequestException as exc:
            raise KioskApiError(f"Cannot reach kiosk event stream: {exc}") from exc

    def _post_frame(self, path: str, filename: str, jpeg_bytes: bytes) -> dict[str, Any]:
        if not jpeg_bytes:
            raise KioskApiError("No camera frame is available.")
        return self._request_json(
            "POST",
            path,
            files={"file": (filename, jpeg_bytes, "image/jpeg")},
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = None if files else {"Content-Type": "application/json"}
        try:
            response = self._session.request(
                method,
                url,
                json=json_body,
                files=files,
                headers=headers,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
        except requests.Timeout as exc:
            raise KioskApiError("The kiosk API request timed out.") from exc
        except requests.ConnectionError as exc:
            raise KioskApiError("Cannot connect to the edge kiosk API.") from exc
        except requests.RequestException as exc:
            raise KioskApiError(f"Kiosk API request failed: {exc}") from exc

        if response.status_code >= 400:
            raise self._error_from_response(response)
        try:
            return response.json()
        except ValueError as exc:
            raise KioskApiError("Kiosk API returned an invalid JSON response.", response.status_code) from exc

    @staticmethod
    def _error_from_response(response: requests.Response) -> KioskApiError:
        message = f"Request failed with HTTP {response.status_code}"
        try:
            payload = response.json()
            detail = payload.get("detail")
            if detail:
                message = str(detail)
        except ValueError:
            if response.text:
                message = response.text[:300]
        return KioskApiError(message, response.status_code)
