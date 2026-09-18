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


def test_interrupted_response_commits_and_persists_in_history():
    access, chat = controller()

    # User speaks, assistant streams partial response
    chat._on_transcribed_text("Where is the lab?")
    chat._on_text_chunk("The lab is located on ")
    chat._on_text_chunk("the second floor.")

    assert chat.assistantSpeaking is True
    # Before interrupt, partial text is visible in messages
    msgs = access.messages
    assert len(msgs) == 2
    assert msgs[0]["content"] == "Where is the lab?"
    assert msgs[1]["content"] == "The lab is located on the second floor."

    # User clicks Interrupt button (calls stopAudioPlayback)
    chat.stopAudioPlayback()

    assert chat.assistantSpeaking is False
    # After interrupt, messages must STILL contain both user query and partial response
    msgs_after = access.messages
    assert len(msgs_after) == 2
    assert msgs_after[0]["content"] == "Where is the lab?"
    assert msgs_after[1]["content"] == "The lab is located on the second floor."

    # Subsequent background state sync or presence frame must NOT wipe the interrupted bubble
    access._on_state_event({"active_chat_session": {"session_id": "a", "presence_state": "OWNER_PRESENT", "conversation_history": []}})
    assert len(access.messages) == 2
    assert access.messages[1]["content"] == "The lab is located on the second floor."


def test_barge_in_preserves_previous_interrupted_assistant_response():
    access, chat = controller()

    # Turn 1 begins and streams partially
    chat._on_transcribed_text("First question")
    chat._on_text_chunk("Partial answer 1...")

    # User barges in by speaking Turn 2 without waiting
    chat._on_transcribed_text("Second question")
    chat._on_text_chunk("Complete answer 2")
    chat._on_worker_response({"transcribed_input": "Second question", "text_response": "Complete answer 2"})

    msgs = access.messages
    # Both turns must be present: 4 messages in total
    assert len(msgs) == 4
    assert msgs[0]["content"] == "First question"
    assert msgs[1]["content"] == "Partial answer 1..."
    assert msgs[2]["content"] == "Second question"
    assert msgs[3]["content"] == "Complete answer 2"
