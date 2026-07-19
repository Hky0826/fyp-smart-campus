"""Owner-presence API wrapper used by the access orchestrator."""

from __future__ import annotations

from .api_client import KioskApiClient


class PresenceController:
    """Thin wrapper that keeps owner-presence calls named separately."""

    def __init__(self, api: KioskApiClient) -> None:
        self._api = api

    def verify_owner_presence(self, jpeg_bytes: bytes) -> dict:
        return self._api.verify_chat_presence_frame(jpeg_bytes)

    def reopen_owner_session(self, jpeg_bytes: bytes) -> dict:
        return self._api.reopen_chat_frame(jpeg_bytes)

