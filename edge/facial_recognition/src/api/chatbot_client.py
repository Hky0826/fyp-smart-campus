"""
Chatbot client for the edge device.

Forwards user chat queries to the Smart Campus cloud RAG chatbot API.
The edge device acts as a transparent proxy:
  - It attaches the user's JWT to the request.
  - It handles network and authentication errors.
  - It returns the structured response to the local kiosk/UI.

Security note: The Google AI Studio API key is NEVER present on the
edge device. All LLM calls happen on the cloud backend.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from ..config import RuntimeConfig

logger = logging.getLogger(__name__)

# Cloud API timeout in seconds
_CONNECT_TIMEOUT = 5
_READ_TIMEOUT = 60  # RAG generation can take several seconds


class ChatbotClientError(Exception):
    """Raised when the cloud chatbot API returns an error."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ChatbotClient:
    """
    HTTP client for calling the cloud RAG chatbot endpoint.

    Usage:
        config = RuntimeConfig()
        client = ChatbotClient(config)
        response = client.chat(query="Where is the library?", jwt_token="eyJ...")
    """

    def __init__(self, config: RuntimeConfig):
        self._base_url = config.sync_cloud_url.rstrip("/")
        self._chat_endpoint = f"{self._base_url}/api/chatbot/chat"
        self._audio_chat_endpoint = f"{self._base_url}/api/chatbot/chat/audio"
        self._health_endpoint = f"{self._base_url}/api/chatbot/health"

    def health_check(self) -> Dict[str, Any]:
        """
        Check if the cloud chatbot service is reachable and configured.

        Returns:
            Dict with 'status' and 'google_api_configured' keys.

        Raises:
            ChatbotClientError: If the cloud is unreachable.
        """
        try:
            resp = requests.get(
                self._health_endpoint,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            )
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            raise ChatbotClientError("Cloud chatbot health check timed out.")
        except requests.ConnectionError:
            raise ChatbotClientError("Cannot connect to cloud chatbot service.")
        except requests.HTTPError as exc:
            raise ChatbotClientError(
                f"Cloud chatbot health check failed: {exc}",
                status_code=exc.response.status_code if exc.response else None,
            )

    def chat(
        self,
        query: str,
        jwt_token: Optional[str] = None,
        device_id: Optional[str] = None,
        session_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Send a user query to the cloud RAG chatbot and return the response.

        Args:
            query: The user's natural-language question.
            jwt_token: The face-recognition JWT issued after authentication.
            device_id: Optional edge device identifier for audit logging.
            session_id: Optional session ID from the JWT session record.

        Returns:
            Dict matching the cloud ChatResponse schema:
            {
                "answer": str,
                "citations": [...],
                "access_granted": bool,
                "status_message": str | null,
                "response_time_ms": int | null,
                "query_id": int | null,
            }

        Raises:
            ChatbotClientError: On network failure, auth error, or server error.
        """
        headers = {"Content-Type": "application/json"}
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"

        payload: Dict[str, Any] = {"query": query}
        if device_id:
            payload["device_id"] = device_id
        if session_id is not None:
            payload["session_id"] = session_id

        try:
            resp = requests.post(
                self._chat_endpoint,
                json=payload,
                headers=headers,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            )

            if resp.status_code == 401:
                raise ChatbotClientError(
                    "Authentication failed: JWT is invalid or expired. "
                    "Please re-authenticate using face recognition.",
                    status_code=401,
                )

            if resp.status_code == 403:
                raise ChatbotClientError(
                    "Access denied: you do not have permission to use the chatbot.",
                    status_code=403,
                )

            if resp.status_code == 422:
                detail = resp.json().get("detail", "Invalid request format.")
                raise ChatbotClientError(
                    f"Request validation error: {detail}",
                    status_code=422,
                )

            if resp.status_code == 503:
                detail = resp.json().get("detail", "Service unavailable.")
                raise ChatbotClientError(
                    f"Cloud service temporarily unavailable: {detail}",
                    status_code=503,
                )

            resp.raise_for_status()
            return resp.json()

        except requests.Timeout:
            raise ChatbotClientError(
                "The cloud chatbot took too long to respond. Please try again.",
                status_code=None,
            )
        except requests.ConnectionError:
            raise ChatbotClientError(
                "Cannot reach the cloud chatbot service. Check network connectivity.",
                status_code=None,
            )
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else None
            raise ChatbotClientError(
                f"Unexpected cloud error (HTTP {status_code}): {exc}",
                status_code=status_code,
            )

    def audio_chat(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
        jwt_token: Optional[str] = None,
        device_id: Optional[str] = None,
        session_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Send user audio to the cloud audio RAG chatbot and return its response.

        Returns a dict matching the cloud AudioChatResponse schema:
        {
            "transcribed_input": str | null,
            "text_response": str | null,
            "audio_response": str | null,
            "sources": [...],
            "status": str,
            "access_granted": bool,
            "error_message": str | null,
            "response_time_ms": int | null,
            "query_id": int | null,
        }
        """
        if not audio_bytes:
            raise ChatbotClientError("Audio recording is empty.", status_code=400)

        headers = {"Accept": "application/json"}
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"

        files = {"audio": ("recording.webm", audio_bytes, mime_type)}
        data: Dict[str, Any] = {}
        if device_id:
            data["device_id"] = device_id
        if session_id is not None:
            data["session_id"] = session_id

        try:
            resp = requests.post(
                self._audio_chat_endpoint,
                files=files,
                data=data,
                headers=headers,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            )

            if resp.status_code == 401:
                raise ChatbotClientError(
                    "Authentication failed: JWT is invalid or expired. "
                    "Please re-authenticate using face recognition.",
                    status_code=401,
                )

            if resp.status_code == 403:
                raise ChatbotClientError(
                    "Access denied: you do not have permission to use the chatbot.",
                    status_code=403,
                )

            if resp.status_code == 422:
                detail = resp.json().get("detail", "Invalid request format.")
                raise ChatbotClientError(
                    f"Request validation error: {detail}",
                    status_code=422,
                )

            if resp.status_code == 503:
                detail = resp.json().get("detail", "Service unavailable.")
                raise ChatbotClientError(
                    f"Cloud service temporarily unavailable: {detail}",
                    status_code=503,
                )

            resp.raise_for_status()
            return resp.json()

        except requests.Timeout:
            raise ChatbotClientError(
                "The cloud chatbot took too long to process the audio. Please try again.",
                status_code=None,
            )
        except requests.ConnectionError:
            raise ChatbotClientError(
                "Cannot reach the cloud chatbot service. Check network connectivity.",
                status_code=None,
            )
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else None
            raise ChatbotClientError(
                f"Unexpected cloud error (HTTP {status_code}): {exc}",
                status_code=status_code,
            )
