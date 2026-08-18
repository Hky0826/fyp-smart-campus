"""Single structured planner shared by text and non-Live audio requests."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from google import genai
from google.genai import types

from RagChatbot.config import rag_settings
from RagChatbot.generation.query_router import (
    _CAPABILITY_PATTERN,
    _GREETING_PATTERN,
    classify_query,
    get_capabilities_summary,
)
from RagChatbot.personalisation.intents import parse_personal_intent
from RagChatbot.personalisation.schemas import AuthenticatedChatContext, PersonalIntent
from RagChatbot.services.map_service import (
    _candidate_nodes,
    _normalise_label,
    _score_destination,
    is_navigation_query,
)
from RagChatbot.services.tool_registry import (
    ToolAuthorizationError,
    ToolResult,
    ToolValidationError,
    dispatch_tool,
    tool_registry,
    tool_declarations,
)

logger = logging.getLogger(__name__)

ROUTES = {"NAVIGATION", "PERSONAL", "UNIVERSITY_INFORMATION", "UNIVERSITY_INFO", "NAVIGATIONAL", "GREETING", "CAPABILITY", "UNCLEAR", "OUT_OF_SCOPE"}
_ROUTE_ALIASES = {
    "UNIVERSITY_INFO": "UNIVERSITY_INFORMATION",
    "NAVIGATIONAL": "NAVIGATION",
}


class PlannerError(RuntimeError):
    pass


class PlannerUnavailable(PlannerError):
    pass


class PlannerInvalid(PlannerError):
    pass


@dataclass(frozen=True)
class PlannerToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class PlannerResult:
    route: str
    tool_call: PlannerToolCall | None = None
    clarification_question: str | None = None
    safe: bool = True
    confidence: float | None = None
    reasoning: str | None = None


@dataclass(frozen=True)
class PlannedOperation:
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


def _catalog_candidates(query: str, context: AuthenticatedChatContext, db) -> list[dict[str, Any]]:
    """Retrieve a small live, role-filtered catalog context for the planner."""
    try:
        from RagChatbot.services.map_service import get_map_snapshot
        snapshot = get_map_snapshot(db)
        nodes = _candidate_nodes(snapshot.nodes, context.roles)
        if not nodes:
            return []
        # The map database does not currently store destination embeddings.
        # Use semantic scoring only when a deployment supplies per-node
        # embeddings; otherwise use deterministic label similarity immediately.
        # Never issue one remote embedding request per label on the request
        # path. The backend still re-resolves the natural description against
        # the full live catalog after planning.
        nodes = sorted(nodes, key=lambda node: (-_score_destination(query, str(getattr(node, "label", ""))), str(getattr(node, "label", "")).casefold()))[:64]
        scores: list[tuple[Any, float]] = []
        embedded_nodes = [node for node in nodes if getattr(node, "embedding", None)]
        if embedded_nodes:
            try:
                from RagChatbot.embeddings.google_embedding_service import embed_text
                qv = embed_text(query)
                import math
                qnorm = math.sqrt(sum(float(x) * float(x) for x in qv)) or 1.0
                for node in embedded_nodes:
                    lv = getattr(node, "embedding")
                    lnorm = math.sqrt(sum(float(x) * float(x) for x in lv)) or 1.0
                    sim = sum(float(a) * float(b) for a, b in zip(qv, lv)) / (qnorm * lnorm)
                    scores.append((node, sim))
            except Exception:
                scores = []
        if not scores:
            scores = [(node, _score_destination(query, str(getattr(node, "label", "")))) for node in nodes]
        scores.sort(key=lambda item: (-item[1], str(getattr(item[0], "label", "")).casefold()))
        result = []
        for node, _ in scores[: max(1, int(rag_settings.PLANNER_CATALOG_CANDIDATE_LIMIT))]:
            result.append({
                "label": str(getattr(node, "label", "")),
                "node_type": str(getattr(node, "node_type", "")),
                "building": getattr(node, "building", None),
                "floor": getattr(node, "floor", getattr(node, "floor_level", None)),
                "accessible": bool(getattr(node, "accessible", True)),
                "role_restricted": bool(getattr(node, "allowed_roles", ())),
            })
        return result
    except Exception as exc:
        logger.info("Navigation catalog retrieval unavailable: %s", type(exc).__name__)
        return []


_SYSTEM_PROMPT = """You are a structured operation planner for a university assistant.
Never answer the user and never invent facts. Return JSON only. Select at most one
tool from the approved declarations. Tools are requests to a trusted backend; the
backend owns identity, authorization, personal-data ownership, map resolution,
device origin, and route calculation.

Use get_my_* only for the authenticated user's own data. Do not put user IDs,
student IDs, lecturer IDs, roles, access levels, device IDs, node IDs, URLs, file
paths, SQL, or backend function names in arguments. Use the natural destination
description for navigation. If a request is unsafe, privacy-invasive, unrelated,
or cannot be safely mapped, set safe=false or route=UNCLEAR as appropriate. The
tool name must exactly match one of the approved declarations.
"""

# Keep this schema to the subset accepted by the installed google-genai
# ``Schema`` model.  In particular, the SDK does not accept JSON-Schema union
# arrays for ``type``.  Non-operational routes use an empty tool call and empty
# metadata strings instead of nullable fields.
_PLANNER_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "safe": {"type": "BOOLEAN"},
        "route": {"type": "STRING", "enum": sorted(ROUTES)},
                "tool_call": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "enum": sorted(tool_registry())},
                "arguments": {"type": "OBJECT"},
            },
            "required": ["name", "arguments"],
        },
        "clarification_question": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "reasoning": {"type": "STRING"},
    },
    "required": [
        "safe", "route", "tool_call", "clarification_question",
        "confidence", "reasoning",
    ],
}


def plan_turn(text: str, *, context: AuthenticatedChatContext, db, confirmation_context: str | None = None) -> PlannerResult:
    """Make the one planner call for one active text/audio turn."""
    query = " ".join(str(text or "").split())
    if not query:
        return PlannerResult(route="UNCLEAR", clarification_question="No speech detected. Please try again.")
    if not rag_settings.GOOGLE_API_KEY:
        raise PlannerUnavailable("planner provider is not configured")

    # Public university-information questions should not receive a different
    # planner prompt merely because the authenticated user has additional
    # personal roles. Keep the original context for final authorization and
    # dispatch, but hide personal role capabilities from this planning call.
    planner_context = context
    if parse_personal_intent(query).intent == PersonalIntent.UNKNOWN:
        try:
            is_public_information = classify_query(query, db=db).category == "UNIVERSITY_INFO"
        except Exception:
            is_public_information = False
        if is_public_information:
            planner_context = replace(context, roles=())

    candidates = _catalog_candidates(query, planner_context, db)
    payload = {
        "user_text": query,
        "authenticated": bool(planner_context.authenticated),
        "roles": list(planner_context.roles),
        "capabilities": [tool["name"] for tool in tool_declarations(planner_context)],
        "navigation_candidates": candidates,
        "confirmation_context": confirmation_context or None,
    }
    try:
        client = genai.Client(
            api_key=rag_settings.GOOGLE_API_KEY,
            # The Gemini API rejects manually supplied deadlines below 10s.
            # Clamp operator-provided values as well as the default.
            http_options=types.HttpOptions(timeout=max(10000, int(rag_settings.PLANNER_TIMEOUT_SECONDS * 1000))),
        )
        response = client.models.generate_content(
            model=rag_settings.PLANNER_MODEL,
            contents=json.dumps(payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT + "\nApproved tool declarations:\n" + json.dumps(tool_declarations(planner_context), ensure_ascii=False),
                temperature=0.0,
                max_output_tokens=400,
                response_mime_type="application/json",
                response_schema=_PLANNER_RESPONSE_SCHEMA,
            ),
        )
        raw = json.loads((response.text or "").strip())
    except PlannerError:
        raise
    except Exception as exc:
        # Keep the provider reason in server logs without exposing credentials
        # or the full request payload to the client.
        logger.warning("Planner provider request failed for model=%s: %s", rag_settings.PLANNER_MODEL, str(exc)[:300])
        raise PlannerUnavailable(str(exc)) from exc
    if not isinstance(raw, dict):
        raise PlannerInvalid("planner output is not an object")
    if not isinstance(raw.get("safe"), bool):
        raise PlannerInvalid("planner returned an invalid safety flag")
    route = str(raw.get("route") or "").upper()
    route = _ROUTE_ALIASES.get(route, route)
    if route not in ROUTES:
        raise PlannerInvalid("planner returned an unknown route")
    call = raw.get("tool_call")
    if isinstance(call, dict) and not call.get("name") and not call.get("arguments"):
        call = None
    if call is not None:
        if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not isinstance(call.get("arguments"), dict):
            raise PlannerInvalid("planner returned an invalid tool call")
        tool_call = PlannerToolCall(call["name"], call["arguments"])
    else:
        tool_call = None
    if tool_call and route not in {"NAVIGATION", "PERSONAL", "UNIVERSITY_INFORMATION"}:
        # The response schema must contain a tool-call object for SDK
        # compatibility, and models occasionally populate it even for a
        # greeting/capability answer.  Never execute that call; discard it
        # when its name is an approved tool. Unknown names remain invalid.
        if tool_call.name not in tool_registry():
            raise PlannerInvalid("non-operational route returned an unknown tool")
        tool_call = None
    if route in {"NAVIGATION", "PERSONAL", "UNIVERSITY_INFORMATION"} and tool_call is None and raw.get("safe", True):
        raise PlannerInvalid("operational route returned no tool")
    confidence = raw.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return PlannerResult(
        route=route,
        tool_call=tool_call,
        clarification_question=str(raw.get("clarification_question") or "")[:240] or None,
        safe=raw.get("safe") is True,
        confidence=confidence,
        reasoning=str(raw.get("reasoning") or "")[:240] or None,
    )


def _fallback_plan(query: str, context: AuthenticatedChatContext, db) -> PlannerResult:
    """Safe deterministic recovery for provider timeout/failure."""
    personal = parse_personal_intent(query)
    if personal.intent != PersonalIntent.UNKNOWN:
        names = {
            PersonalIntent.PROFILE: "get_my_profile",
            PersonalIntent.COURSES: "get_my_courses",
            PersonalIntent.TIMETABLE: "get_my_timetable",
            PersonalIntent.NEXT_CLASS: "get_my_next_class",
            PersonalIntent.LOCATION: "get_my_next_class",
            PersonalIntent.APPOINTMENTS: "get_my_appointments",
            PersonalIntent.NEXT_APPOINTMENT: "get_my_next_appointment",
            PersonalIntent.PRIVACY_DENIED: "get_my_timetable",
        }
        return PlannerResult("PERSONAL", PlannerToolCall(names.get(personal.intent, "get_my_profile"), {"date_scope": personal.date_scope.value}))
    if is_navigation_query(query, db=db):
        return PlannerResult("NAVIGATION", PlannerToolCall("navigate_to_destination", {"destination_description": query}))
    if _GREETING_PATTERN.search(query):
        return PlannerResult("GREETING")
    if _CAPABILITY_PATTERN.search(query):
        return PlannerResult("CAPABILITY")
    return PlannerResult("UNIVERSITY_INFORMATION", PlannerToolCall("retrieve_authorized_university_information", {"query": query}))


def _fixed_operation(result: PlannerResult, *, context: AuthenticatedChatContext) -> PlannedOperation:
    if not result.safe:
        return PlannedOperation(kind="blocked", answer="I'm not able to process that request. Please ask a straightforward question about campus services or documents.", status="blocked", access_granted=False, status_message="Request blocked by the backend safety policy.", intent="BLOCKED")
    if result.route == "GREETING":
        name = " ".join(str(context.full_name or "").split()) if context.authenticated else ""
        if not name and context.authenticated:
            name = " ".join(str(context.given_name or "").split())
        return PlannedOperation(kind="fixed", answer=f"Hi {name}, how may I help you today?" if name else "Hi, how may I help you today?", intent="GREETING")
    if result.route == "CAPABILITY":
        return PlannedOperation(kind="fixed", answer=get_capabilities_summary(authenticated=context.authenticated, personalisation_enabled=rag_settings.RAG_PERSONALISATION_ENABLED), intent="CAPABILITY")
    if result.route == "OUT_OF_SCOPE":
        return PlannedOperation(kind="blocked", answer="I'm designed to answer questions based on the university information I have. I may not have reliable information about outside topics.", status="blocked", access_granted=False, status_message="Request is outside the supported university assistant scope.", intent="OUT_OF_SCOPE")
    return PlannedOperation(kind="fixed", answer=result.clarification_question or "Could you please clarify what university information you are looking for?", intent="UNCLEAR")


def execute_planned_turn(query: str, *, context: AuthenticatedChatContext, db, confirmation_context: str | None = None) -> PlannedOperation:
    """Plan and dispatch one turn; return ``kind=rag`` for authorized RAG."""
    try:
        planned = plan_turn(query, context=context, db=db, confirmation_context=confirmation_context)
    except (PlannerUnavailable, PlannerInvalid) as exc:
        logger.warning("Shared planner unavailable; using safe deterministic fallback: %s: %s", type(exc).__name__, str(exc)[:240])
        planned = _fallback_plan(query, context, db)
    if planned.route in {"GREETING", "CAPABILITY", "UNCLEAR", "OUT_OF_SCOPE"}:
        return _fixed_operation(planned, context=context)
    if not planned.tool_call:
        raise PlannerInvalid("operation route has no tool")
    try:
        tool_arguments = dict(planned.tool_call.arguments)
        # If the model selected an operational tool but emitted an empty
        # argument object, recover using the guarded user text. This does not
        # bypass validation: navigation is still re-resolved against the live
        # catalog and RAG still applies the authenticated access levels.
        if not tool_arguments and planned.tool_call.name == "navigate_to_destination":
            tool_arguments = {"destination_description": query}
        elif not tool_arguments and planned.tool_call.name == "retrieve_authorized_university_information":
            tool_arguments = {"query": query}
        result = dispatch_tool(planned.tool_call.name, tool_arguments, context=context, db=db, original_query=query)
    except ToolAuthorizationError:
        if not context.authenticated:
            return PlannedOperation(kind="personal", answer="Please scan your face so I can confirm your identity before accessing your personal campus information.", status="auth_required", access_granted=False, status_message="Authentication required for personal information.", response_scope="PERSONAL", intent=planned.tool_call.name, authentication_required=True)
        return PlannedOperation(kind="personal", answer="Your authenticated role does not have access to that personal service.", status="no_access", access_granted=False, status_message="Personal tool authorization denied.", response_scope="PERSONAL", intent=planned.tool_call.name)
    except ToolValidationError as exc:
        logger.warning(
            "Planner tool rejected name=%s argument_keys=%s reason=%s",
            planned.tool_call.name,
            sorted(str(key) for key in tool_arguments),
            str(exc)[:240],
        )
        return PlannedOperation(kind="blocked", answer="I could not safely process that request. Please ask for a campus destination, your own campus information, or university documents.", status="blocked", access_granted=False, status_message="Planner tool request failed validation.", intent="INVALID_TOOL")
    return PlannedOperation(
        kind=result.kind,
        answer=result.answer,
        navigation=result.navigation,
        personal_result=result.personal_result,
        query=result.query,
        intent=result.intent,
        status=result.status,
        access_granted=result.access_granted,
        status_message=result.status_message,
        authentication_required=result.authentication_required,
        response_scope=result.response_scope,
    )


class LLMPlanner:
    """Small object wrapper for callers that prefer dependency injection."""

    def plan(self, text: str, *, context: AuthenticatedChatContext, db, confirmation_context: str | None = None) -> PlannerResult:
        return plan_turn(text, context=context, db=db, confirmation_context=confirmation_context)

    __call__ = plan


SharedLLMPlanner = LLMPlanner
dispatch_planned_tool = dispatch_tool
