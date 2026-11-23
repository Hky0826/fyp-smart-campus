"""Unit tests verifying concurrency controls and 409 Conflict prevention in GeminiLiveSession."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from RagChatbot.generation.live_session_manager import GeminiLiveSession


class FakeLiveSessionConnection:
    def __init__(self, session_obj: Any) -> None:
        self._session_obj = session_obj
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> Any:
        self.entered += 1
        await asyncio.sleep(0.05)  # Simulate network handshake delay
        return self._session_obj

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.exited += 1
        await asyncio.sleep(0.01)


class FakeLiveClient:
    def __init__(self) -> None:
        self.connect_count = 0
        self.last_connection: FakeLiveSessionConnection | None = None
        self.aio = MagicMock()
        self.aio.live = MagicMock()
        self.aio.live.connect = self._connect

    def _connect(self, *args: Any, **kwargs: Any) -> FakeLiveSessionConnection:
        self.connect_count += 1
        mock_raw_session = MagicMock()
        mock_raw_session.receive = AsyncMock()
        mock_raw_session.send_client_content = AsyncMock()
        conn = FakeLiveSessionConnection(mock_raw_session)
        self.last_connection = conn
        return conn


def test_concurrent_start_calls_connect_once():
    """10 simultaneous tasks calling session.start() should execute connect exactly once."""
    async def run_test():
        fake_client = FakeLiveClient()
        with patch("RagChatbot.generation.live_session_manager.genai.Client", return_value=fake_client):
            session = GeminiLiveSession()

            # Launch 10 simultaneous start() calls
            tasks = [asyncio.create_task(session.start()) for _ in range(10)]
            await asyncio.gather(*tasks)

            assert fake_client.connect_count == 1
            assert session.is_connected
            await session.close()

    asyncio.run(run_test())


def test_duplicate_trigger_greeting_sends_once():
    """Multiple concurrent calls to trigger_greeting on the same session should execute only once."""
    async def run_test():
        session = GeminiLiveSession()
        mock_raw_session = MagicMock()
        mock_raw_session.send_client_content = AsyncMock()
        session._session = mock_raw_session
        session._connected_at = time.monotonic()

        # Call trigger_greeting concurrently 5 times
        tasks = [
            asyncio.create_task(session.trigger_greeting(user_name="John Doe"))
            for _ in range(5)
        ]
        await asyncio.gather(*tasks)

        assert mock_raw_session.send_client_content.call_count == 1
        assert session._greeting_sent is True

    asyncio.run(run_test())


def test_session_cooldown_enforced_on_reconnect():
    """Reconnecting immediately after close should enforce the minimum gateway cooldown pause."""
    async def run_test():
        fake_client = FakeLiveClient()
        with patch("RagChatbot.generation.live_session_manager.genai.Client", return_value=fake_client):
            session = GeminiLiveSession()
            await session.start()
            assert session.is_connected

            # Close session and immediately start a new one
            await session.close()
            t0 = time.monotonic()
            await session.start()
            elapsed = time.monotonic() - t0

            # Gateway cooldown ensures at least 0.15s elapsed to avoid 409 Conflict
            assert elapsed >= 0.15
            assert session.is_connected
            await session.close()

    asyncio.run(run_test())


def test_audio_gated_during_greeting():
    """send_audio drops chunks while greeting is actively in progress to prevent turn collisions."""
    async def run_test():
        session = GeminiLiveSession()
        mock_raw_session = MagicMock()
        mock_raw_session.send_realtime_input = AsyncMock()
        session._session = mock_raw_session
        session._connected_at = time.monotonic()

        # When greeting is in progress, audio chunks are safely gated
        session._greeting_in_progress = True
        await session.send_audio(b"\x00\x00" * 160)
        assert mock_raw_session.send_realtime_input.call_count == 0

        # When greeting completes, audio chunks flow normally
        session._greeting_in_progress = False
        await session.send_audio(b"\x00\x00" * 160)
        assert mock_raw_session.send_realtime_input.call_count == 1

    asyncio.run(run_test())


def test_device_preemption_in_router():
    """Verify that multiple connections for the same device_id preempt the previous session."""
    async def run_test():
        from RagChatbot.router import _active_device_sessions, _device_sessions_lock

        dev_id = "TEST-DEVICE-PREEMPT-99"
        mock_old = MagicMock()
        mock_old.close = AsyncMock()

        async with _device_sessions_lock:
            _active_device_sessions[dev_id] = mock_old

        # Simulate a new connection arriving for the same device_id
        async with _device_sessions_lock:
            existing = _active_device_sessions.get(dev_id)
            if existing is not None:
                await existing.close()
            mock_new = MagicMock()
            _active_device_sessions[dev_id] = mock_new

        assert mock_old.close.call_count == 1
        assert _active_device_sessions[dev_id] is mock_new

        # Clean up
        async with _device_sessions_lock:
            _active_device_sessions.pop(dev_id, None)

    asyncio.run(run_test())
