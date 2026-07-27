import pytest
from RagChatbot.generation.response_validator import sanitize_text_for_speech
from RagChatbot.generation.prompt_builder import _SYSTEM_PROMPT
from RagChatbot.services.audio_chat_service import _LIVE_SYSTEM_INSTRUCTION
from RagChatbot.personalisation.schemas import AuthenticatedChatContext


def test_sanitize_text_for_speech_removes_punctuation():
    input_text = "Here is **important** info: * item 1, * item 2. See `# header` and `code`."
    result = sanitize_text_for_speech(input_text)
    assert "*" not in result
    assert "#" not in result
    assert "`" not in result
    assert "important info: item 1, item 2. See header and code." in result


def test_sanitize_text_for_speech_empty():
    assert sanitize_text_for_speech("") == ""
    assert sanitize_text_for_speech(None) == ""


def test_system_prompt_rules_exist():
    assert "Keep responses short, direct, and compact" in _SYSTEM_PROMPT
    assert "ask a short clarifying question presenting 2 to 3 specific sub-topic options" in _SYSTEM_PROMPT
    assert "HOWEVER, if the user has ALREADY selected an option or answered a previous clarification" in _SYSTEM_PROMPT
    assert "Keep responses short, direct, and compact" in _LIVE_SYSTEM_INSTRUCTION
    assert "ask a short clarifying question presenting 2 to 3 specific sub-topic options" in _LIVE_SYSTEM_INSTRUCTION
    assert "HOWEVER, if the user has ALREADY selected an option or answered a previous clarification" in _LIVE_SYSTEM_INSTRUCTION


def test_authenticated_chat_context_full_name():
    ctx = AuthenticatedChatContext(
        user_id=1,
        session_id=100,
        full_name="John Doe",
        authenticated=True,
    )
    assert ctx.full_name == "John Doe"
    assert ctx.authenticated is True
    first_name = ctx.full_name.strip().split()[0]
    assert first_name == "John"
