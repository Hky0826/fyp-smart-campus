"""Unit tests for navigation card persistence and chat bubble separation."""

from unittest.mock import MagicMock
from PySide6.QtCore import QCoreApplication
from access_control.ui.access_control_gui.controllers.access_controller import AccessController
from access_control.ui.access_control_gui.controllers.chatbot_controller import ChatbotController

_APP = QCoreApplication.instance() or QCoreApplication([])


def setup_controllers():
    api = MagicMock()
    chat = ChatbotController(api)
    access = AccessController(api, MagicMock(), chat)
    access._sync_voice_loop = MagicMock()
    access._run_worker = MagicMock()
    access._chat_expanded = True
    access._apply_state({
        "active_chat_session": {
            "session_id": "sess-1",
            "presence_state": "OWNER_PRESENT",
            "conversation_history": [],
        }
    })
    return access, chat


def test_clear_navigation_and_reset_session_state():
    access, chat = setup_controllers()

    # Simulate received navigation and citations
    nav_payload = {
        "route_summary": {"destination_label": "Delta Lab", "total_distance_m": 45},
        "instructions": [{"instruction": "Turn left at corridor"}],
    }
    chat._on_navigation(nav_payload)
    chat._on_citations([{"document_title": "Campus Map"}])
    chat._on_transcribed_text("Where is Delta Lab?")
    chat._on_text_chunk("Turn left")

    assert chat.currentNavigation == nav_payload
    assert len(chat.citations) == 1
    assert chat.transcribedText == "Where is Delta Lab?"
    assert chat.partialText == "Turn left"

    # Call clearNavigation
    chat.clearNavigation()
    assert chat.currentNavigation == {}

    # Re-populate and test resetSessionState
    chat._on_navigation(nav_payload)
    chat._on_citations([{"document_title": "Campus Map"}])
    chat.resetSessionState()
    assert chat.currentNavigation == {}
    assert chat.citations == []
    assert chat.partialText == ""
    assert chat.transcribedText == ""
    assert chat.ragStatus == ""


def test_exit_chat_clears_navigation_and_resets_state():
    access, chat = setup_controllers()

    nav_payload = {"destination": "Library"}
    chat._on_navigation(nav_payload)
    assert chat.currentNavigation == nav_payload

    # User clicks Exit Session
    access.exitChat()

    assert not access.chatExpanded
    assert chat.currentNavigation == {}
    assert chat.citations == []


def test_start_chat_verification_clears_stale_navigation():
    access, chat = setup_controllers()

    nav_payload = {"destination": "Cafeteria"}
    chat._on_navigation(nav_payload)
    assert chat.currentNavigation == nav_payload

    access.startChatVerification()
    assert chat.currentNavigation == {}


def test_consecutive_turns_do_not_concatenate_bubbles():
    access, chat = setup_controllers()

    # Turn 1: User asks, bot answers
    chat._on_transcribed_text("First question")
    chat._on_text_chunk("First answer")
    chat._on_worker_response({"transcribed_input": "First question", "text_response": "First answer"})

    assert len(access.messages) == 2
    assert access.messages[0]["content"] == "First question"
    assert access.messages[1]["content"] == "First answer"

    # Turn 2 begins: new speech arrives
    chat._on_transcribed_text("Second question")
    # Streaming assistant chunk begins for turn 2
    chat._on_text_chunk("Second answer chunk 1 ")
    chat._on_text_chunk("chunk 2")

    messages = access.messages
    # Must have 4 messages: Turn 1 (user, bot), Turn 2 (user, streaming bot)
    assert len(messages) == 4
    assert messages[0]["content"] == "First question"
    assert messages[1]["content"] == "First answer"
    assert messages[2]["content"] == "Second question"
    assert messages[3]["content"] == "Second answer chunk 1 chunk 2"

    # Turn 2 completes cleanly
    chat._on_worker_response({
        "transcribed_input": "Second question",
        "text_response": "Second answer chunk 1 chunk 2",
    })

    final_messages = access.messages
    assert len(final_messages) == 4
    assert final_messages[1]["content"] == "First answer"
    assert final_messages[3]["content"] == "Second answer chunk 1 chunk 2"
    assert "First answer" not in final_messages[3]["content"]


def test_consecutive_turns_with_prefix_overlap_do_not_falsely_merge():
    access, chat = setup_controllers()

    # Turn 1: "Hello"
    chat._on_transcribed_text("Hi")
    chat._on_text_chunk("Hello")
    chat._on_worker_response({"transcribed_input": "Hi", "text_response": "Hello"})

    # Turn 2: "Hello world" (starts with "Hello")
    chat._on_transcribed_text("Who are you?")
    chat._on_text_chunk("Hello world")

    messages = access.messages
    # Even though "Hello" is a prefix/substring of "Hello world", they must NOT merge
    assert len(messages) == 4
    assert messages[0]["content"] == "Hi"
    assert messages[1]["content"] == "Hello"
    assert messages[2]["content"] == "Who are you?"
    assert messages[3]["content"] == "Hello world"
