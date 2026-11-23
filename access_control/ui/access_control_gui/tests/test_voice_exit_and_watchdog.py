import datetime as dt
from unittest.mock import MagicMock
from PySide6.QtCore import QCoreApplication

from access_control.ui.access_control_gui.controllers.access_controller import (
    AccessController,
    _is_voice_exit_command,
)
from access_control.ui.access_control_gui.controllers.chatbot_controller import ChatbotController

_APP = QCoreApplication.instance() or QCoreApplication([])


def setup_controller():
    api = MagicMock()
    chat = ChatbotController(api)
    access = AccessController(api, MagicMock(), chat)
    access._sync_voice_loop = MagicMock()
    access._run_worker = MagicMock()
    access._chat_expanded = True
    access._apply_state({
        "active_chat_session": {
            "session_id": "test-session-1",
            "presence_state": "OWNER_PRESENT",
            "conversation_history": [],
        },
        "timings": {"owner_absent_terminate_seconds": 10},
    })
    return access, chat


def test_voice_exit_command_pattern():
    # Positive matches - direct commands
    assert _is_voice_exit_command("exit")
    assert _is_voice_exit_command("Exit")
    assert _is_voice_exit_command("quit")
    assert _is_voice_exit_command("goodbye")
    assert _is_voice_exit_command("keluar")
    assert _is_voice_exit_command("退出")
    assert _is_voice_exit_command("再见")
    assert _is_voice_exit_command("exit.")
    assert _is_voice_exit_command("Exit!")

    # Positive matches - conversational exit phrases
    assert _is_voice_exit_command("thank you that's all")
    assert _is_voice_exit_command("thank you that's all.")
    assert _is_voice_exit_command("that's all thank you")
    assert _is_voice_exit_command("that's all")
    assert _is_voice_exit_command("thats all")
    assert _is_voice_exit_command("thanks that's all")
    assert _is_voice_exit_command("I'm done")
    assert _is_voice_exit_command("terima kasih itu sahaja")
    assert _is_voice_exit_command("itu sahaja")
    assert _is_voice_exit_command("谢谢这样就好")
    assert _is_voice_exit_command("就这样")
    assert _is_voice_exit_command("就这样了")

    # Negative matches (must never trigger on navigational or complex queries)
    assert not _is_voice_exit_command("where is the emergency exit?")
    assert not _is_voice_exit_command("where is the exit")
    assert not _is_voice_exit_command("how do I exit the building?")
    assert not _is_voice_exit_command("can you exit")
    assert not _is_voice_exit_command("exit door")
    assert not _is_voice_exit_command("thank you for the directions, where is boardroom 1?")


def test_voice_exit_in_transcribed_text_triggers_exit_chat():
    access, chat = setup_controller()
    access.exitChat = MagicMock()

    # Normal message does not exit
    chat._transcribed_text = "Where is Boardroom 1?"
    access._on_chatbot_transcribed_text()
    access.exitChat.assert_not_called()

    # Voice exit command triggers exitChat
    chat._transcribed_text = "exit"
    access._on_chatbot_transcribed_text()
    access.exitChat.assert_called_once()


def test_voice_exit_in_send_message_triggers_exit_chat():
    access, chat = setup_controller()
    access.exitChat = MagicMock()

    # Voice exit typed / sent
    access.sendMessage("quit")
    access.exitChat.assert_called_once()


def test_exit_intent_in_worker_response_triggers_exit_chat():
    access, chat = setup_controller()
    access.exitChat = MagicMock()

    access._on_worker_success("chat-message", {
        "intent": "EXIT",
        "route": "EXIT",
        "answer": "Goodbye! Have a great day.",
    })
    access.exitChat.assert_called_once()


def test_chatbot_exit_requested_signal_triggers_exit_chat():
    access, chat = setup_controller()
    access.exitChat = MagicMock()

    # Emitting exitRequested on chat triggers exitChat on access controller
    chat.exitRequested.emit()
    access.exitChat.assert_called_once()


def test_gemini_live_tool_declaration_has_exit():
    from RagChatbot.generation.live_session_manager import _tool_declaration
    decl = _tool_declaration()
    tool_names = [f["name"] for f in decl.get("function_declarations", [])]
    assert "exit_chat_session" in tool_names


def test_options_stored_in_history_and_chatbot_controller():
    access, chat = setup_controller()

    # Worker response with options
    payload = {
        "transcribed_input": "Where is Boardroom 1?",
        "text_response": "Did you mean Boardroom 1 on Level 3?",
        "options": ["Boardroom 1", "Cancel"],
        "citations": [],
    }
    chat._on_worker_response(payload)

    # Verify options in ChatbotController
    assert chat.currentOptions == ["Boardroom 1", "Cancel"]

    # Verify options in AccessController committed messages
    assert len(access.committedMessages) == 2
    assert access.committedMessages[1]["options"] == ["Boardroom 1", "Cancel"]


def test_watchdog_auto_closes_on_unverified_trap():
    access, chat = setup_controller()
    access.exitChat = MagicMock()

    # Chat verification starts (user opened chat, but no face recognized yet)
    access._state = {"active_chat_session": None, "timings": {"owner_absent_terminate_seconds": 10}}
    access._chat_expanded = True
    access.startChatVerification()
    assert access._chat_verification_active is True
    assert access._chat_verify_started_ms > 0

    # 5 seconds pass -> still verifying, not closed yet
    access._chat_verify_started_ms = access._now_ms - 5000
    access._on_tick()
    access.exitChat.assert_not_called()

    # 11 seconds pass with no face -> watchdog triggers exitChat
    access._chat_verify_started_ms = access._now_ms - 11000
    access._on_tick()
    access.exitChat.assert_called_once()


def test_watchdog_auto_closes_on_client_side_absence():
    access, chat = setup_controller()
    access.exitChat = MagicMock()

    # Owner was seen 5 seconds ago -> not closed
    access._last_owner_seen_ms = access._now_ms - 5000
    access._on_tick()
    access.exitChat.assert_not_called()

    # Owner was seen 11 seconds ago -> watchdog auto-closes
    access._last_owner_seen_ms = access._now_ms - 11000
    access._on_tick()
    access.exitChat.assert_called_once()


def test_watchdog_auto_closes_on_server_absent_since():
    access, chat = setup_controller()
    access.exitChat = MagicMock()

    # Server reports owner_absent_since 11 seconds ago
    t_absent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=11)
    access._state["active_chat_session"]["owner_absent_since"] = t_absent.isoformat()
    access._on_tick()
    access.exitChat.assert_called_once()
