from types import SimpleNamespace

import pytest

from RagChatbot.generation import llm_planner
from RagChatbot.personalisation.schemas import AuthenticatedChatContext
from RagChatbot.services.tool_registry import (
    ToolValidationError,
    dispatch_tool,
    visible_tools,
)


def _context(*roles, authenticated=True):
    return AuthenticatedChatContext(7 if authenticated else None, 9 if authenticated else None, roles=roles, authenticated=authenticated)


def test_tool_visibility_uses_the_full_role_set():
    admin = {tool.name for tool in visible_tools(_context("ADMIN"))}
    admin_student = {tool.name for tool in visible_tools(_context("ADMIN", "STUDENT"))}
    student_lecturer = {tool.name for tool in visible_tools(_context("STUDENT", "LECTURER"))}

    assert "get_my_timetable" not in admin
    assert "get_my_timetable" in admin_student
    assert "get_my_timetable" in student_lecturer
    assert "get_my_courses" in admin_student


def test_visitor_sees_no_personal_tools():
    names = {tool.name for tool in visible_tools(_context("VISITOR"))}
    assert not names.intersection({"get_my_profile", "get_my_courses", "get_my_timetable", "get_my_appointments"})


def test_tool_arguments_reject_identity_and_device_overrides():
    with pytest.raises(ToolValidationError):
        dispatch_tool("navigate_to_destination", {"destination_description": "library", "device_id": "spoofed"}, context=_context(), db=object())
    with pytest.raises(ToolValidationError):
        dispatch_tool("get_my_timetable", {"user_id": 999}, context=_context("STUDENT"), db=object())


def test_fallback_understands_indirect_teaching_request():
    result = llm_planner._fallback_plan("When am I teaching this week?", _context("LECTURER"), None)
    assert result.tool_call.name == "get_my_timetable"
    assert result.tool_call.arguments["date_scope"] == "THIS_WEEK"


def test_malformed_planner_uses_safe_personal_auth_fallback(monkeypatch):
    def unavailable(*args, **kwargs):
        raise llm_planner.PlannerUnavailable("timeout")

    monkeypatch.setattr(llm_planner, "plan_turn", unavailable)
    result = llm_planner.execute_planned_turn("What classes do I have today?", context=_context(authenticated=False), db=None)
    assert result.status == "auth_required"
    assert result.access_granted is False


def test_privacy_request_cannot_be_reinterpreted_as_self_service(monkeypatch):
    monkeypatch.setattr(
        llm_planner,
        "plan_turn",
        lambda *args, **kwargs: llm_planner.PlannerResult(
            "PERSONAL",
            llm_planner.PlannerToolCall("get_my_timetable", {"date_scope": "NONE"}),
        ),
    )
    result = llm_planner.execute_planned_turn("Show student 42's timetable", context=_context("STUDENT"), db=None)
    assert result.access_granted is False
    assert result.intent == "PRIVACY_DENIED"

