"""
Unit tests for kiosk conversational history extraction and forwarding to cloud chatbot.

Tests:
- KioskStateStore.recent_chat_history extracts sequential turns accurately.
- /chat/message passes recent_chat_history to chatbot_client().chat.
"""

from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from access_control.facial_recognition.src.api.kiosk import (
    KioskStateStore,
    create_kiosk_router,
    RuntimeConfig,
)
from access_control.facial_recognition.src.api.chatbot_client import ChatbotClient


def test_kiosk_state_store_recent_chat_history():
    """Verify KioskStateStore converts alternating ChatMessage records into turn pairs."""
    store = KioskStateStore(RuntimeConfig(sync_device_id="kiosk-test"))
    assert store.recent_chat_history() == []

    # Add turn 1
    store.append_chat_exchange("What programmes are available?", "We offer BCS, MBBS, and Pharmacy.", [])
    history = store.recent_chat_history()
    assert len(history) == 1
    assert history[0]["user"] == "What programmes are available?"
    assert history[0]["assistant"] == "We offer BCS, MBBS, and Pharmacy."

    # Add turn 2
    store.append_chat_exchange("What are the entry requirements for it?", "SPM 3 credits with Math.", [])
    history = store.recent_chat_history()
    assert len(history) == 2
    assert history[1]["user"] == "What are the entry requirements for it?"
    assert history[1]["assistant"] == "SPM 3 credits with Math."

    # Add turn 3 and turn 4, limit to 3
    store.append_chat_exchange("How much is it?", "Tuition is RM 60,000.", [])
    store.append_chat_exchange("Are there scholarships?", "Yes, up to 100% merit scholarships.", [])

    history_limited = store.recent_chat_history(limit=3)
    assert len(history_limited) == 3
    assert history_limited[0]["user"] == "What are the entry requirements for it?"
    assert history_limited[2]["user"] == "Are there scholarships?"


def test_kiosk_chat_message_forwards_history():
    """Verify /chat/message sends recent_chat_history in the client chat call."""
    mock_client = MagicMock(spec=ChatbotClient)
    mock_client.chat.return_value = {
        "answer": "Test answer",
        "citations": [],
        "access_granted": True,
        "status_message": None,
        "response_time_ms": 100,
        "query_id": 1,
    }

    router = create_kiosk_router(
        runtime_config=lambda: RuntimeConfig(sync_device_id="kiosk-test"),
        access_pipeline=lambda: MagicMock(),
        chatbot_client=lambda: mock_client,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Turn 1
    resp1 = client.post("/kiosk/chat/message", json={"query": "Tell me about Computer Science"})
    assert resp1.status_code == 200
    mock_client.chat.assert_called_with(
        query="Tell me about Computer Science",
        jwt_token=None,
        device_id="kiosk-test",
        session_id=None,
        chat_history=None,
    )

    # Turn 2
    resp2 = client.post("/kiosk/chat/message", json={"query": "What are the entry requirements for it?"})
    assert resp2.status_code == 200
    # Turn 2 must include Turn 1 in chat_history
    assert mock_client.chat.call_count == 2
    last_call = mock_client.chat.call_args
    assert last_call.kwargs["chat_history"] == [
        {"user": "Tell me about Computer Science", "assistant": "Test answer"}
    ]
