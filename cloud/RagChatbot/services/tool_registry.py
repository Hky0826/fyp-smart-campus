"""Backend-owned chatbot tool registry and dispatcher.

The planner is deliberately not a function-calling authority.  It may name one
of the tools in this module, but this registry owns the schemas, role policy,
and handlers.  In particular, no tool accepts an owner id, a role, a device,
or a graph node id from the model.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Callable

from RagChatbot.config import rag_settings
from RagChatbot.personalisation.intents import parse_personal_intent
from RagChatbot.personalisation.schemas import (
    AuthenticatedChatContext,
    DateScope,
    PersonalIntent,
    PersonalRoute,
)
from RagChatbot.personalisation.service import handle_personal_request
from RagChatbot.services.map_service import calculate_navigation


class ToolValidationError(ValueError):
    """The planner supplied an unknown tool or unsafe/invalid arguments."""


class ToolAuthorizationError(PermissionError):
    """The authenticated context is not allowed to use a tool."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    roles: frozenset[str] = frozenset()
    requires_authentication: bool = False
    handler: Callable[..., "ToolResult"] | None = None

    def declaration(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(frozen=True)
class ToolResult:
    kind: str
    answer: str | None = None
    navigation: dict[str, Any] | None = None
    personal_result: Any = None
    query: str | None = None
    intent: str | None = None
    status: str = "ok"
    access_granted: bool = True
    status_message: str | None = None
    authentication_required: bool = False
    response_scope: str = "DOCUMENT"


_FORBIDDEN_ARGUMENT_NAMES = {
    "user_id", "student_id", "lecturer_id", "role", "roles", "access_level",
    "device_id", "start_node_id", "destination_node_id", "node_id", "node_ids",
    "sql", "url", "file_path", "path", "backend_function", "function_name",
}
_UNSAFE_VALUE = re.compile(
    r"(?:https?://|file://|\\\\|(?:^|\s)(?:select|insert|update|delete|drop)\s+.+\s+from\b|\.\./)",
    re.IGNORECASE,
)


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


_DATE_SCOPE = {"NONE", "TODAY", "TOMORROW", "THIS_WEEK", "NEXT"}


def _personal_spec(name: str, description: str, intent: str, roles: frozenset[str]) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters=_schema({
            "date_scope": {"type": "string", "enum": sorted(_DATE_SCOPE)},
        }),
        roles=roles,
        requires_authentication=True,
        handler=lambda **kwargs: _handle_personal(intent=intent, **kwargs),
    )


_TOOLS: dict[str, ToolSpec] = {
    "navigate_to_destination": ToolSpec(
        "navigate_to_destination",
        "Resolve a natural campus destination against the current accessible map and calculate directions from the trusted session device.",
        _schema({
            "destination_description": {"type": "string", "minLength": 1, "maxLength": 240},
            "category": {"type": "string", "maxLength": 40},
            "nearest": {"type": "boolean"},
        }, ["destination_description"]),
        roles=frozenset(),
        handler=lambda **kwargs: _handle_navigation(**kwargs),
    ),
    "get_my_profile": _personal_spec("get_my_profile", "Read the authenticated user's applicable identity records.", "PROFILE", frozenset({"STUDENT", "LECTURER", "STAFF", "ADMIN", "SUPER_ADMIN", "SYSTEM_ADMIN", "CONTENT_ADMIN"})),
    "get_my_courses": _personal_spec("get_my_courses", "Read courses owned by the authenticated student.", "COURSES", frozenset({"STUDENT"})),
    "get_my_timetable": _personal_spec("get_my_timetable", "Read the authenticated user's timetable; student and lecturer entries are combined when both roles are present.", "TIMETABLE", frozenset({"STUDENT", "LECTURER"})),
    "get_my_next_class": _personal_spec("get_my_next_class", "Read the authenticated user's next class and its room.", "NEXT_CLASS", frozenset({"STUDENT", "LECTURER"})),
    "get_my_appointments": _personal_spec("get_my_appointments", "Read appointments owned by the authenticated user.", "APPOINTMENTS", frozenset({"STUDENT", "LECTURER", "STAFF", "ADMIN", "SUPER_ADMIN", "SYSTEM_ADMIN", "CONTENT_ADMIN"})),
    "get_my_next_appointment": _personal_spec("get_my_next_appointment", "Read the authenticated user's next appointment and location.", "NEXT_APPOINTMENT", frozenset({"STUDENT", "LECTURER", "STAFF", "ADMIN", "SUPER_ADMIN", "SYSTEM_ADMIN", "CONTENT_ADMIN"})),
    "retrieve_authorized_university_information": ToolSpec(
        "retrieve_authorized_university_information",
        "Retrieve ordinary university information using only documents authorized for the authenticated context.",
        _schema({"query": {"type": "string", "minLength": 1, "maxLength": 2000}}, ["query"]),
        roles=frozenset(),
        handler=lambda **kwargs: ToolResult(kind="rag", query=kwargs["query"]),
    ),
}

# Public read-only-by-convention name for integrations that inspect the fixed
# backend registry.  Callers should use ``tool_registry()`` for a copy.
TOOL_REGISTRY = _TOOLS


def tool_registry() -> dict[str, ToolSpec]:
    """Return the immutable-by-convention backend registry."""
    return dict(_TOOLS)


get_tool_registry = tool_registry


def visible_tools(context: AuthenticatedChatContext) -> list[ToolSpec]:
    """Return tools visible for the full authenticated role set."""
    roles = {str(r).upper() for r in (context.roles or ())}
    visible: list[ToolSpec] = []
    for spec in _TOOLS.values():
        if spec.requires_authentication and not context.authenticated:
            continue
        if spec.roles and not (roles & spec.roles):
            continue
        visible.append(spec)
    return visible


def tool_declarations(context: AuthenticatedChatContext) -> list[dict[str, Any]]:
    return [spec.declaration() for spec in visible_tools(context)]


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key).lower()
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _validate_arguments(spec: ToolSpec, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolValidationError("Tool arguments must be an object")
    keys = set(_walk_keys(arguments))
    if keys & _FORBIDDEN_ARGUMENT_NAMES:
        raise ToolValidationError("Tool arguments contain a protected field")
    if any(_UNSAFE_VALUE.search(str(value)) for value in arguments.values() if isinstance(value, str)):
        raise ToolValidationError("Tool arguments contain an unsafe value")
    allowed = set(spec.parameters.get("properties", {}))
    unknown = set(arguments) - allowed
    if unknown:
        raise ToolValidationError("Tool arguments contain an unknown field")
    for field in spec.parameters.get("required", []):
        if not str(arguments.get(field, "")).strip():
            raise ToolValidationError(f"Missing required argument: {field}")
    if "date_scope" in arguments and str(arguments["date_scope"]).upper() not in _DATE_SCOPE:
        raise ToolValidationError("Invalid date scope")
    return dict(arguments)


def _authorize(spec: ToolSpec, context: AuthenticatedChatContext) -> None:
    if spec.requires_authentication and not context.authenticated:
        raise ToolAuthorizationError("Authentication is required for this tool")
    roles = {str(r).upper() for r in (context.roles or ())}
    if spec.roles and not roles.intersection(spec.roles):
        raise ToolAuthorizationError("The authenticated role set cannot use this tool")


def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    context: AuthenticatedChatContext,
    db,
    original_query: str | None = None,
) -> ToolResult:
    """Validate, authorize, and execute exactly one backend-owned tool."""
    spec = _TOOLS.get(str(name))
    if spec is None or spec.handler is None:
        raise ToolValidationError("Unknown chatbot tool")
    args = _validate_arguments(spec, arguments)
    _authorize(spec, context)

    # This check is independent of the model's selected tool.  It prevents a
    # malicious or mistaken planner from turning a request about another
    # person into a self-scoped lookup.
    if original_query and spec.name.startswith("get_my_"):
        personal_route = parse_personal_intent(original_query)
        if personal_route.intent == PersonalIntent.PRIVACY_DENIED:
            return _privacy_result(context)
        if re.search(r"\b(?:student|lecturer|staff|visitor|user|person)\s*(?:id\s*)?[#:\-]?[A-Za-z0-9_-]+\b", original_query, re.I) and re.search(r"\b(?:timetable|schedule|class(?:es)?|course(?:s)?|appointment(?:s)?)\b", original_query, re.I):
            return _privacy_result(context)
    return spec.handler(context=context, db=db, **args)


def _privacy_result(context: AuthenticatedChatContext) -> ToolResult:
    if not context.authenticated:
        return ToolResult(kind="personal", answer="Please scan your face so I can confirm your identity before accessing your personal campus information.", status="auth_required", access_granted=False, status_message="Authentication required for personal information.", authentication_required=True, response_scope="PERSONAL", intent=PersonalIntent.PRIVACY_DENIED.value)
    return ToolResult(kind="personal", answer="I can only provide your own personal campus information. I cannot look up another person's timetable, courses, profile, or appointments.", status="no_access", access_granted=False, status_message="Personal access is self-service only.", response_scope="PERSONAL", intent=PersonalIntent.PRIVACY_DENIED.value)


def _scope(value: str | None) -> tuple[DateScope, dt.date | None, dt.date | None]:
    scope = str(value or "NONE").upper()
    now = rag_settings.campus_now()
    if scope == "TODAY":
        return DateScope.TODAY, now.date(), None
    if scope == "TOMORROW":
        return DateScope.TOMORROW, now.date() + dt.timedelta(days=1), None
    if scope == "THIS_WEEK":
        return DateScope.THIS_WEEK, None, now.date() - dt.timedelta(days=now.weekday())
    if scope == "NEXT":
        return DateScope.NEXT, None, None
    return DateScope.NONE, None, None


def _handle_personal(*, intent: str, date_scope: str | None = None, context, db) -> ToolResult:
    scope, requested_date, week_start = _scope(date_scope)
    route = PersonalRoute(
        intent=PersonalIntent(intent),
        date_scope=scope,
        requested_date=requested_date,
        week_start=week_start,
        requires_authentication=True,
    )
    result = handle_personal_request(route, context, db)
    if result is None:
        return ToolResult(kind="error", answer="Personal campus information is temporarily unavailable. Please try again later.", status="error", access_granted=False, response_scope="PERSONAL", intent=intent)
    navigation = None
    if result.navigation_target:
        navigation = {"label": result.navigation_target.label, "location": result.navigation_target.location.display}
    return ToolResult(
        kind="personal",
        answer=result.answer,
        personal_result=result,
        navigation=navigation,
        intent=result.intent.value,
        status="ok" if result.access_granted else ("auth_required" if result.authentication_required else "no_access"),
        access_granted=result.access_granted,
        status_message=result.status_message,
        authentication_required=result.authentication_required,
        response_scope=result.response_scope,
    )


def _handle_navigation(*, destination_description: str, category: str | None = None, nearest: bool = False, context, db) -> ToolResult:
    destination = str(destination_description).strip()
    if category and category.casefold() not in destination.casefold():
        destination = f"{destination} {category}"
    if nearest and "nearest" not in destination.casefold() and "closest" not in destination.casefold():
        destination = f"nearest {destination}"
    try:
        data = calculate_navigation(f"where is {destination}", db=db, context=context)
    except Exception:
        data = {
            "intent": "NAVIGATIONAL",
            "navigation_target": {"candidates": []},
            "answer": "The navigation service is temporarily unavailable. Please try again.",
        }
    return ToolResult(
        kind="navigation",
        answer=(data or {}).get("answer") or "Please tell me the unique destination you want to reach.",
        navigation=data,
        intent="NAVIGATION_CONFIRMATION" if (data or {}).get("confirmation_required") else "NAVIGATIONAL",
        access_granted=True,
    )
