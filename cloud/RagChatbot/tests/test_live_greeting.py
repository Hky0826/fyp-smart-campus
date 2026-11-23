"""Unit tests for Gemini Live greeting triggers."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch

import pytest
from google.genai import types

from RagChatbot.generation.live_session_manager import GeminiLiveSession


def test_trigger_greeting_sends_client_content():
    """trigger_greeting should invoke send_client_content with system greeting instruction."""
    async def run_test():
        mock_session = Mock()
        mock_session.send_client_content = Mock(return_value=asyncio.sleep(0))

        session = GeminiLiveSession()
        session._session = mock_session
        session._connected_at = 1000000.0

        # Personalized greeting
        await session.trigger_greeting(user_name="Alice Tan")
        assert mock_session.send_client_content.call_count == 1
        call_kwargs = mock_session.send_client_content.call_args.kwargs
        turns = call_kwargs.get("turns")
        assert isinstance(turns, list) and len(turns) == 1
        assert "Alice Tan" in turns[0].parts[0].text
        assert "[SYSTEM GREETING TRIGGER]" in turns[0].parts[0].text

        # Duplicate greeting invocation is safely ignored to prevent 409 ABORTED
        await session.trigger_greeting(user_name="Alice Tan")
        assert mock_session.send_client_content.call_count == 1

        # Visitor greeting after session reset
        session.reset_greeting()
        mock_session.send_client_content.reset_mock()
        await session.trigger_greeting(user_name=None)
        assert mock_session.send_client_content.call_count == 1
        visitor_call = mock_session.send_client_content.call_args.kwargs
        visitor_turns = visitor_call.get("turns")
        assert "visitor" in visitor_turns[0].parts[0].text.lower()

    asyncio.run(run_test())
