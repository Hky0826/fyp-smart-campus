"""Streaming client for the cloud FastAPI RAG chatbot endpoint."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import requests

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)


class CloudClientError(RuntimeError):
    """Raised when the cloud chatbot stream cannot be consumed."""


class CloudChatClient:
    """POST transcribed text to FastAPI and yield streamed response chunks."""

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()
        self.last_response: dict[str, Any] | None = None

    def stream_chat(self, text: str) -> Iterator[str]:
        """Yield text chunks from the configured cloud chatbot streaming endpoint."""
        if not text.strip():
            return

        yielded = False
        for attempt in range(self.config.cloud_retries + 1):
            try:
                for chunk in self._stream_once(text):
                    yielded = True
                    yield chunk
                return
            except CloudClientError:
                if yielded or attempt >= self.config.cloud_retries:
                    raise
                delay = self.config.cloud_retry_backoff_seconds * (attempt + 1)
                logger.warning("Cloud stream failed; retrying in %.1fs", delay)
                time.sleep(delay)

    def _stream_once(self, text: str) -> Iterator[str]:
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        if self.config.cloud_bearer_token:
            headers["Authorization"] = f"Bearer {self.config.cloud_bearer_token}"

        payload: dict[str, Any] = {"query": text, "device_id": self.config.cloud_device_id}
        if self.config.cloud_session_id is not None:
            payload["session_id"] = self.config.cloud_session_id

        timeout = (self.config.cloud_connect_timeout_seconds, self.config.cloud_read_timeout_seconds)
        try:
            with requests.post(
                self.config.cloud_api_url,
                json=payload,
                headers=headers,
                timeout=timeout,
                stream=True,
            ) as response:
                if response.status_code >= 400:
                    raise CloudClientError(self._error_message(response))
                yield from self._iter_sse(response)
        except requests.Timeout as exc:
            raise CloudClientError("Cloud chatbot request timed out") from exc
        except requests.ConnectionError as exc:
            raise CloudClientError("Could not connect to cloud chatbot endpoint") from exc
        except requests.RequestException as exc:
            raise CloudClientError(f"Cloud chatbot request failed: {exc}") from exc

    def _iter_sse(self, response: requests.Response) -> Iterator[str]:
        event_name = "message"
        data_lines: list[str] = []
        for line in response.iter_lines(decode_unicode=True):
            if line is None:
                continue
            if line == "":
                yield from self._handle_event(event_name, "\n".join(data_lines))
                event_name = "message"
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.partition(":")[2].strip() or "message"
            elif line.startswith("data:"):
                data_lines.append(line.partition(":")[2].lstrip())

        if data_lines:
            yield from self._handle_event(event_name, "\n".join(data_lines))

    def _handle_event(self, event_name: str, data: str) -> Iterator[str]:
        if not data:
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise CloudClientError(f"Malformed SSE payload from cloud: {data[:120]}") from exc

        if event_name == "chunk":
            text = payload.get("text") if isinstance(payload, dict) else None
            if isinstance(text, str) and text.strip():
                yield text
            return
        if event_name == "done":
            if isinstance(payload, dict):
                self.last_response = payload
            return
        if event_name == "error":
            message = payload.get("detail") if isinstance(payload, dict) else str(payload)
            raise CloudClientError(f"Cloud chatbot stream error: {message}")

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text.strip()
        return f"Cloud chatbot HTTP {response.status_code}: {detail or 'no error details'}"
