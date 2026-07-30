"""HTTP client for the cloud chatbot audio API.

Uploads a WAV file to the cloud endpoint via multipart form data and
receives a JSON response with optional text and/or base64-encoded audio.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests
from urllib.parse import urlsplit

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)


class CloudAudioClientError(RuntimeError):
    """Raised when the cloud audio API request fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class CloudChatCredentials:
    """Runtime cloud chatbot credentials."""

    bearer_token: str | None = None
    session_id: int | None = None


@dataclass
class AudioResponseData:
    """Parsed response from the cloud audio API."""

    transcribed_input: Optional[str] = None
    text: Optional[str] = None
    audio_bytes: Optional[bytes] = None  # decoded from base64
    sources: list = field(default_factory=list)
    status: str = "error"
    access_granted: bool = False
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None
    query_id: Optional[int] = None
    audio_streamed: bool = False


class CloudAudioClient:
    """Upload audio WAV to cloud chatbot API and receive text + audio response.

    Sends a multipart POST with the WAV file, device_id, and session_id.
    Expects a JSON response matching the AudioChatResponse schema.
    """

    def __init__(
        self,
        config: AudioIOConfig | None = None,
        credential_provider: Callable[[], CloudChatCredentials | Mapping[str, Any] | str | None] | None = None,
    ) -> None:
        self.config = config or AudioIOConfig()
        for endpoint in (self.config.cloud_api_url, self.config.cloud_stream_api_url):
            parsed = urlsplit(endpoint)
            allow_loopback = os.getenv("EDGE_ALLOW_INSECURE_LOOPBACK", "false").lower() in {"1", "true", "yes", "on"}
            if parsed.scheme != "https" and not (allow_loopback and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
                raise ValueError("Cloud audio endpoints must use HTTPS")
        self.credential_provider = credential_provider

    def send_audio(self, audio_path: str | Path) -> AudioResponseData:
        """Upload a WAV file to the cloud audio endpoint.

        Args:
            audio_path: Path to the WAV file to upload.

        Returns:
            AudioResponseData with parsed response fields.
        """
        path = Path(audio_path)
        if not path.exists():
            return AudioResponseData(
                status="error",
                error_message=f"Audio file not found: {path}",
            )

        with open(path, "rb") as f:
            audio_bytes = f.read()

        return self.send_audio_bytes(audio_bytes, mime_type="audio/wav")

    def send_audio_bytes(self, audio_bytes: bytes, mime_type: str = "audio/wav") -> AudioResponseData:
        """Upload raw audio bytes to the cloud audio endpoint.

        Args:
            audio_bytes: Raw audio data.
            mime_type: MIME type of the audio data (default: audio/wav).

        Returns:
            AudioResponseData with parsed response fields.
        """
        if not audio_bytes:
            return AudioResponseData(
                status="error",
                error_message="Empty audio data",
            )

        for attempt in range(self.config.cloud_retries + 1):
            try:
                return self._send_once(audio_bytes, mime_type)
            except CloudAudioClientError as exc:
                if attempt >= self.config.cloud_retries:
                    raise
                delay = self.config.cloud_retry_backoff_seconds * (attempt + 1)
                logger.warning("Cloud audio upload failed (attempt %d/%d); retrying in %.1fs: %s",
                               attempt + 1, self.config.cloud_retries + 1, delay, exc)
                time.sleep(delay)

        # Should not be reached
        return AudioResponseData(status="error", error_message="Max retries exceeded")

    def send_audio_stream(
        self,
        audio_path: str | Path,
        audio_consumer: Callable[[Iterator[bytes]], None] | None = None,
    ) -> AudioResponseData:
        """Upload a WAV file and consume streamed PCM response chunks."""
        path = Path(audio_path)
        if not path.exists():
            return AudioResponseData(
                status="error",
                error_message=f"Audio file not found: {path}",
            )

        with open(path, "rb") as f:
            audio_bytes = f.read()

        return self.send_audio_bytes_stream(audio_bytes, mime_type="audio/wav", audio_consumer=audio_consumer)

    def send_audio_bytes_stream(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/wav",
        audio_consumer: Callable[[Iterator[bytes]], None] | None = None,
    ) -> AudioResponseData:
        """Upload raw audio bytes and consume streamed PCM response chunks."""
        if not audio_bytes:
            return AudioResponseData(
                status="error",
                error_message="Empty audio data",
            )

        for attempt in range(self.config.cloud_retries + 1):
            try:
                return self._send_stream_once(audio_bytes, mime_type, audio_consumer)
            except CloudAudioClientError as exc:
                if attempt >= self.config.cloud_retries:
                    raise
                delay = self.config.cloud_retry_backoff_seconds * (attempt + 1)
                logger.warning(
                    "Cloud audio stream failed (attempt %d/%d); retrying in %.1fs: %s",
                    attempt + 1,
                    self.config.cloud_retries + 1,
                    delay,
                    exc,
                )
                time.sleep(delay)

        return AudioResponseData(status="error", error_message="Max retries exceeded")

    def _send_once(self, audio_bytes: bytes, mime_type: str) -> AudioResponseData:
        """Send a single audio upload request without retry logic."""
        credentials = self._credentials()
        headers: dict[str, str] = {"Accept": "application/json"}
        if credentials.bearer_token:
            headers["Authorization"] = f"Bearer {credentials.bearer_token}"

        # Build multipart form data
        files = {"audio": ("recording.wav", audio_bytes, mime_type)}
        data: dict[str, Any] = {"device_id": self.config.cloud_device_id}
        if credentials.session_id is not None:
            data["session_id"] = credentials.session_id

        timeout = (self.config.cloud_connect_timeout_seconds, self.config.cloud_read_timeout_seconds)
        start = time.monotonic()

        try:
            response = requests.post(
                self.config.cloud_api_url,
                files=files,
                data=data,
                headers=headers,
                timeout=timeout,
            )
        except requests.Timeout as exc:
            raise CloudAudioClientError("Cloud audio request timed out") from exc
        except requests.ConnectionError as exc:
            raise CloudAudioClientError("Could not connect to cloud audio endpoint") from exc
        except requests.RequestException as exc:
            raise CloudAudioClientError(f"Cloud audio request failed: {exc}") from exc

        elapsed_ms = int((time.monotonic() - start) * 1000)

        if response.status_code >= 400:
            error_detail = self._error_message(response)
            raise CloudAudioClientError(
                error_detail,
                status_code=response.status_code,
            )

        return self._parse_response(response, elapsed_ms)

    def _send_stream_once(
        self,
        audio_bytes: bytes,
        mime_type: str,
        audio_consumer: Callable[[Iterator[bytes]], None] | None,
    ) -> AudioResponseData:
        """Send one streaming audio upload request without retry logic."""
        credentials = self._credentials()
        headers: dict[str, str] = {"Accept": "application/x-ndjson"}
        if credentials.bearer_token:
            headers["Authorization"] = f"Bearer {credentials.bearer_token}"

        files = {"audio": ("recording.wav", audio_bytes, mime_type)}
        data: dict[str, Any] = {"device_id": self.config.cloud_device_id}
        if credentials.session_id is not None:
            data["session_id"] = credentials.session_id

        timeout = (self.config.cloud_connect_timeout_seconds, self.config.cloud_read_timeout_seconds)
        start = time.monotonic()

        try:
            response = requests.post(
                self.config.cloud_stream_api_url,
                files=files,
                data=data,
                headers=headers,
                timeout=timeout,
                stream=True,
            )
        except requests.Timeout as exc:
            raise CloudAudioClientError("Cloud audio stream timed out") from exc
        except requests.ConnectionError as exc:
            raise CloudAudioClientError("Could not connect to cloud audio stream endpoint") from exc
        except requests.RequestException as exc:
            raise CloudAudioClientError(f"Cloud audio stream request failed: {exc}") from exc

        if response.status_code >= 400:
            error_detail = self._error_message(response)
            response.close()
            raise CloudAudioClientError(
                error_detail,
                status_code=response.status_code,
            )

        metadata = AudioResponseData(status="error")
        collected_audio = bytearray()
        streamed_any = False
        elapsed_ms = lambda: int((time.monotonic() - start) * 1000)

        def audio_chunks() -> Iterator[bytes]:
            nonlocal metadata, streamed_any
            try:
                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    try:
                        event_payload = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        raise CloudAudioClientError(
                            f"Invalid streaming JSON from cloud: {raw_line[:200]}"
                        ) from exc

                    event = event_payload.get("event")
                    data_payload = event_payload.get("data") or {}
                    logger.info("STREAM_DEBUG [%.3f]: Edge received event %s", time.time(), event)
                    if event == "metadata":
                        metadata = self._parse_stream_payload(data_payload, elapsed_ms())
                    elif event == "audio":
                        chunk_b64 = data_payload.get("chunk")
                        if not chunk_b64:
                            continue
                        try:
                            chunk = base64.b64decode(chunk_b64)
                        except (ValueError, TypeError) as exc:
                            raise CloudAudioClientError("Invalid base64 audio chunk from cloud") from exc
                        streamed_any = True
                        yield chunk
                    elif event == "done":
                        metadata = self._parse_stream_payload(data_payload, elapsed_ms())
                    elif event in {"tts_error", "error"}:
                        message = data_payload.get("message") or "cloud audio stream reported an error"
                        logger.warning("Cloud audio stream event %s: %s", event, message)
                        if event == "error":
                            metadata.status = "error"
                            metadata.error_message = message
                    else:
                        logger.debug("Ignoring unknown cloud audio stream event: %s", event)
            finally:
                response.close()

        if audio_consumer is None:
            for chunk in audio_chunks():
                collected_audio.extend(chunk)
            if collected_audio:
                metadata.audio_bytes = bytes(collected_audio)
        else:
            try:
                audio_consumer(audio_chunks())
            finally:
                response.close()

        metadata.audio_streamed = streamed_any
        if metadata.response_time_ms is None:
            metadata.response_time_ms = elapsed_ms()
        return metadata

    def _parse_response(self, response: requests.Response, elapsed_ms: int) -> AudioResponseData:
        """Parse the JSON response into an AudioResponseData instance."""
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise CloudAudioClientError(
                f"Invalid JSON response from cloud: {response.text[:200]}"
            ) from exc

        if not isinstance(payload, dict):
            raise CloudAudioClientError(
                f"Unexpected response type from cloud: {type(payload).__name__}"
            )

        # Extract fields matching the AudioChatResponse schema
        transcribed_input = payload.get("transcribed_input")
        text = payload.get("text_response")
        audio_b64 = payload.get("audio_response")
        sources = payload.get("sources", [])
        status = payload.get("status", "error")
        access_granted = bool(payload.get("access_granted", False))
        error_message = payload.get("error_message")
        response_time_ms = payload.get("response_time_ms") or elapsed_ms
        query_id = payload.get("query_id")

        # Decode base64 audio if present
        audio_bytes: Optional[bytes] = None
        if audio_b64:
            try:
                audio_bytes = base64.b64decode(audio_b64)
            except (ValueError, TypeError) as exc:
                logger.warning("Failed to decode base64 audio response: %s", exc)

        return AudioResponseData(
            transcribed_input=transcribed_input,
            text=text,
            audio_bytes=audio_bytes,
            sources=sources,
            status=status,
            access_granted=access_granted,
            error_message=error_message,
            response_time_ms=response_time_ms,
            query_id=query_id,
        )

    def _parse_stream_payload(self, payload: Mapping[str, Any], elapsed_ms: int) -> AudioResponseData:
        """Parse one metadata/done NDJSON payload into AudioResponseData."""
        return AudioResponseData(
            transcribed_input=payload.get("transcribed_input"),
            text=payload.get("text_response"),
            audio_bytes=None,
            sources=payload.get("sources", []),
            status=payload.get("status", "error"),
            access_granted=bool(payload.get("access_granted", False)),
            error_message=payload.get("error_message"),
            response_time_ms=payload.get("response_time_ms") or elapsed_ms,
            query_id=payload.get("query_id"),
        )

    def _credentials(self) -> CloudChatCredentials:
        """Resolve credentials from the provider or config defaults."""
        if self.credential_provider is not None:
            provided = self.credential_provider()
            credentials = self._coerce_credentials(provided)
            if credentials.bearer_token or credentials.session_id is not None:
                return credentials
        return CloudChatCredentials(
            bearer_token=self.config.cloud_bearer_token,
            session_id=self.config.cloud_session_id,
        )

    @staticmethod
    def _coerce_credentials(
        value: CloudChatCredentials | Mapping[str, Any] | str | None,
    ) -> CloudChatCredentials:
        """Normalize various credential formats to CloudChatCredentials."""
        if value is None:
            return CloudChatCredentials()
        if isinstance(value, CloudChatCredentials):
            return value
        if isinstance(value, str):
            return CloudChatCredentials(bearer_token=value)
        token = value.get("bearer_token") or value.get("access_token") or value.get("token")
        session_id = value.get("session_id")
        return CloudChatCredentials(
            bearer_token=str(token) if token else None,
            session_id=int(session_id) if session_id is not None else None,
        )

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        """Extract a human-readable error message from the HTTP response."""
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text.strip()
        return f"Cloud audio API HTTP {response.status_code}: {detail or 'no error details'}"
