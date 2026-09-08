from unittest.mock import MagicMock
from PySide6.QtCore import QCoreApplication
from access_control.ui.access_control_gui.controllers.access_controller import AccessController
from access_control.ui.access_control_gui.controllers.chatbot_controller import ChatbotController

_APP = QCoreApplication.instance() or QCoreApplication([])


def controller():
    api = MagicMock()
    chat = ChatbotController(api)
    access = AccessController(api, MagicMock(), chat)
    access._sync_voice_loop = MagicMock()
    access._run_worker = MagicMock()
    access._chat_expanded = True
    access._apply_state({"active_chat_session": {"session_id": "a", "presence_state": "OWNER_PRESENT", "conversation_history": []}})
    return access, chat


def test_live_history_survives_refresh_and_repeated_questions():
    access, chat = controller()
    for reply in ("First answer", "Second answer"):
        chat._on_transcribed_text("Same question")
        chat._on_text_chunk(reply)
        chat._on_worker_response({"transcribed_input": "Same question", "text_response": reply})
        access._on_state_event({"active_chat_session": {"session_id": "a", "presence_state": "OWNER_PRESENT", "conversation_history": []}})
    assert [m["content"] for m in access.messages] == ["Same question", "First answer", "Same question", "Second answer"]
    access._handle_presence_payload({"session": {"session_id": "a", "presence_state": "OWNER_TEMPORARILY_MISSING", "conversation_history": []}, "owner_present": False})
    assert len(access.messages) == 4
    assert access.presenceState == "OWNER_TEMPORARILY_MISSING"


def test_new_session_clears_previous_history_and_late_reply_is_ignored():
    access, chat = controller()
    chat._on_worker_response({"transcribed_input": "Private", "text_response": "Secret"})
    access._on_state_event({"active_chat_session": None})
    chat._on_worker_response({"transcribed_input": "Late", "text_response": "Reply"})
    assert not access.chatExpanded
    assert access.messages == []
    access._apply_state({"active_chat_session": {"session_id": "b", "conversation_history": []}})
    assert access.messages == []


def test_received_transcript_activates_processing_feedback():
    access, chat = controller()
    chat._on_transcribed_text("Hello")
    assert chat.busy
    chat._set_busy(False)  # An idle speaker must not hide pending response feedback.
    assert chat.busy
    assert access.messages[-1]["content"] == "Hello"

    chat._on_worker_response({"transcribed_input": "Hello", "text_response": "Hi"})
    assert not chat.busy
