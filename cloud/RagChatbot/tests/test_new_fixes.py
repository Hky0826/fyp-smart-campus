import pytest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from RagChatbot.generation.response_validator import sanitize_text_for_speech
from RagChatbot.generation.prompt_builder import _SYSTEM_PROMPT, build_prompt
from RagChatbot.retrieval.ranking import RankedChunk
from RagChatbot.generation.live_session_manager import _LIVE_SYSTEM_INSTRUCTION
from RagChatbot.generation.live_fast_rag import _VOICE_SYSTEM_PROMPT
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
    assert "Responses appear on a 5-inch screen:" in _SYSTEM_PROMPT
    assert "Use only the provided context." in _SYSTEM_PROMPT
    assert "You are the voice interface for" in _LIVE_SYSTEM_INSTRUCTION
    assert "Language Matching:" in _LIVE_SYSTEM_INSTRUCTION
    assert "Professional Accent, Pronunciation, and Tone:" in _LIVE_SYSTEM_INSTRUCTION
    assert "Tone and Professional Accent:" in _VOICE_SYSTEM_PROMPT
    assert "never mirror informal colloquialisms, regional slang" in _SYSTEM_PROMPT



def test_programme_prompt_keeps_complete_finite_context():
    chunks = [
        RankedChunk(1, 10, "Programmes", 0, "Faculty A: Bachelor of Science", "PUBLIC", 0.9),
        RankedChunk(2, 10, "Programmes", 1, "Faculty B: Bachelor of Arts", "PUBLIC", 0.8),
        RankedChunk(3, 10, "Programmes", 2, "Faculty C: Diploma in Computing", "PUBLIC", 0.7),
    ]
    _, user_message = build_prompt("What programmes does QIU offer?", chunks)
    assert all(item in user_message for item in ("Bachelor of Science", "Bachelor of Arts", "Diploma in Computing"))


def test_authenticated_chat_context_full_name():
    ctx = AuthenticatedChatContext(
        user_id=1,
        session_id=100,
        full_name="John Doe",
        authenticated=True,
    )
    assert ctx.full_name == "John Doe"
    assert ctx.authenticated is True


def test_greeting_uses_complete_name():
    from RagChatbot.generation.llm_planner import PlannerResult, _fixed_operation
    from RagChatbot.services.chat_service import _greeting_name

    ctx = AuthenticatedChatContext(
        user_id=1,
        session_id=100,
        given_name="John",
        full_name="  John   Doe  ",
        authenticated=True,
    )

    assert _greeting_name(ctx) == "John Doe"
    result = _fixed_operation(PlannerResult(route="GREETING"), context=ctx)
    assert result.answer == "Hi John Doe, how may I help you today?"


def test_authenticated_context_preserves_roles_identities_and_device_origin():
    from RagChatbot.security import auth_context

    session = SimpleNamespace(session_id=100, device_id="registered-kiosk")
    user = SimpleNamespace(
        roles=[SimpleNamespace(role_name="ADMIN")],
        student=SimpleNamespace(student_id="S1"),
        lecturer=SimpleNamespace(lecturer_id="L1"),
        staff=SimpleNamespace(staff_id="ST1"),
        visitor=SimpleNamespace(visitor_id="V1"),
        admin=SimpleNamespace(admin_id="A1"),
        full_name="Multi Role User",
        given_name="Multi",
    )
    device = SimpleNamespace(device_id="registered-kiosk", node_id=77, node=SimpleNamespace(room_label="Main entrance"))

    class Query:
        def __init__(self, result):
            self.result = result

        def filter(self, *args, **kwargs):
            return self

        def filter_by(self, *args, **kwargs):
            return self

        def first(self):
            return self.result

    class Db:
        def query(self, model):
            return Query(device if model.__name__ == "Device" else user)

    with patch.object(auth_context, "resolve_user_session", return_value=({}, 1, session)):
        context = auth_context.resolve_auth_context("jwt", Db(), requested_device_id="registered-kiosk")

    assert context.roles == ("ADMIN", "LECTURER", "STAFF", "STUDENT", "VISITOR")
    assert (context.student_id, context.lecturer_id, context.staff_id, context.visitor_id, context.admin_id) == ("S1", "L1", "ST1", "V1", "A1")
    assert context.device_id == "registered-kiosk"
    assert context.device_node_id == 77
    assert context.device_label == "Main entrance"


def test_authenticated_device_mismatch_is_rejected():
    from RagChatbot.security import auth_context

    session = SimpleNamespace(session_id=100, device_id="registered-kiosk")
    user = SimpleNamespace(roles=[], full_name="User", given_name=None, student=None, lecturer=None, staff=None, visitor=None, admin=None)

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def filter_by(self, *args, **kwargs):
            return self

        def first(self):
            return user

    class Db:
        def query(self, model):
            return Query()

    with patch.object(auth_context, "resolve_user_session", return_value=({}, 1, session)):
        with pytest.raises(HTTPException) as exc_info:
            auth_context.resolve_auth_context("jwt", Db(), requested_device_id="spoofed-kiosk")

    assert exc_info.value.status_code == 403


def test_language_switch_detection():
    from RagChatbot.generation.query_router import detect_language_switch, classify_query

    # English / Latin phrases
    assert detect_language_switch("Can we speak in Japanese?") == ("ja", "Japanese")
    assert detect_language_switch("Can we speak in Japanese please") == ("ja", "Japanese")
    assert detect_language_switch("Please converse in Arabic") == ("ar", "Arabic")
    assert detect_language_switch("Tamil please") == ("ta", "Tamil")
    assert detect_language_switch("Switch to Chinese") == ("zh", "Chinese")
    assert detect_language_switch("Let's speak in French") == ("fr", "French")

    # Malay phrases
    assert detect_language_switch("Boleh cakap bahasa melayu?") == ("ms", "Bahasa Melayu")
    assert detect_language_switch("Bercakap dalam bahasa melayu") == ("ms", "Bahasa Melayu")

    # Chinese phrases
    assert detect_language_switch("讲华语") == ("zh", "Chinese")
    assert detect_language_switch("可以用中文吗") == ("zh", "Chinese")
    assert detect_language_switch("讲广东话") == ("yue", "Cantonese")
    assert detect_language_switch("用粤语交流") == ("yue", "Cantonese")

    # Non-switches should return None
    assert detect_language_switch("What is the fee for computer science?") is None
    assert detect_language_switch("Fees please") is None
    assert detect_language_switch("Help please") is None
    assert detect_language_switch("Where is the reception?") is None

    # Routing
    r_ja = classify_query("Can we speak in Japanese?")
    assert r_ja.category == "LANGUAGE_SWITCH"
    assert r_ja.category_hint == "ja"

    r_ta = classify_query("Tamil please")
    assert r_ta.category == "LANGUAGE_SWITCH"
    assert r_ta.category_hint == "ta"


def test_live_session_language_rules_and_normalization():
    from RagChatbot.generation.live_session_manager import (
        normalize_language_code,
        _LIVE_SYSTEM_INSTRUCTION,
        _tool_declaration,
    )

    # Normalization
    assert normalize_language_code("Japanese") == "ja"
    assert normalize_language_code("Bahasa Melayu") == "ms"
    assert normalize_language_code("cantonese") == "yue"
    assert normalize_language_code("en") == "en"
    assert normalize_language_code("zh") == "zh"

    # Prompt rules
    assert "9. Conversational Language Switching:" in _LIVE_SYSTEM_INSTRUCTION
    assert "set_session_language" in _LIVE_SYSTEM_INSTRUCTION
    assert "10. Speech Recognition & Audio Fidelity:" in _LIVE_SYSTEM_INSTRUCTION

    # Tool declaration
    tools = _tool_declaration()
    assert any(d.get("name") == "set_session_language" for d in tools.get("function_declarations", []))

