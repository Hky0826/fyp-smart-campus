"""Role policy and deterministic response construction for personal intents."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from RagChatbot.config import rag_settings
from RagChatbot.personalisation.repository import PersonalDataRepository
from RagChatbot.personalisation.schemas import (
    AuthenticatedChatContext, DateScope, NavigationTarget, PersonalIntent,
    PersonalResult, PersonalRoute, SafeAppointment, SafeTimetableEntry,
)


AUTH_REQUIRED_PERSONAL_ANSWER = "Please scan your face so I can confirm your identity before accessing your personal campus information."
PERSONAL_DISABLED_ANSWER = "Personal campus information is temporarily unavailable. Public university information remains available."
TERM_UNAVAILABLE_ANSWER = "I cannot look up current courses or timetable information because the active academic term is not configured."
NO_RECORDS_ANSWER = "I could not find any matching personal records."
PRIVACY_DENIED_ANSWER = "I can only provide your own personal campus information. I cannot look up another person's timetable, courses, profile, or appointments."
TEMPORARY_ERROR_ANSWER = "Personal campus information is temporarily unavailable. Please try again later."


def _result(route: PersonalRoute, answer: str, granted: bool, status: Optional[str] = None, *, auth=False, navigation=None) -> PersonalResult:
    return PersonalResult(answer=answer, access_granted=granted, status_message=status, intent=route.intent, authentication_required=auth, navigation_target=navigation)


def _format_time(value) -> str:
    return value.strftime("%H:%M")


def _day_name(value: str) -> str:
    return str(value).upper().split(".")[-1]


def _selected_entries(entries: list[SafeTimetableEntry], route: PersonalRoute, now: dt.datetime) -> list[SafeTimetableEntry]:
    day_index = {name: i for i, name in enumerate(("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"))}
    if route.date_scope in {DateScope.TODAY, DateScope.TOMORROW} and route.requested_date:
        wanted = route.requested_date.strftime("%A").upper()
        return [e for e in entries if _day_name(e.weekday) == wanted]
    if route.date_scope == DateScope.THIS_WEEK:
        return [e for e in entries if day_index.get(_day_name(e.weekday), 99) >= now.weekday()]
    if route.intent in {PersonalIntent.NEXT_CLASS, PersonalIntent.LOCATION}:
        ranked = []
        for entry in entries:
            index = day_index.get(_day_name(entry.weekday))
            if index is None:
                continue
            delta = (index - now.weekday()) % 7
            if delta == 0 and entry.start <= now.time():
                delta = 7
            ranked.append((delta, entry.start, entry))
        return [min(ranked, key=lambda item: (item[0], item[1]))[2]] if ranked else []
    return entries


def _format_timetable(entries: list[SafeTimetableEntry], *, next_only=False) -> str:
    if not entries:
        return NO_RECORDS_ANSWER
    lines = []
    for entry in entries:
        location = f" in {entry.location.display}" if entry.location.display else ""
        lines.append(f"{entry.course.code} - {entry.course.name}, {_day_name(entry.weekday).title()} {_format_time(entry.start)}-{_format_time(entry.end)}{location}.")
    return ("Your next class is " if next_only else "Your timetable is:\n") + (lines[0] if next_only else "\n".join(lines))


def _format_appointments(rows: list[SafeAppointment], *, next_only=False) -> str:
    if not rows:
        return NO_RECORDS_ANSWER
    lines = []
    for row in rows:
        when = row.scheduled_at.strftime("%A %d %B at %H:%M")
        location = f" in {row.location.display}" if row.location.display else ""
        lines.append(f"{when} with {row.participant_name} for {row.duration_minutes} minutes ({row.status.lower()}){location}.")
    return ("Your next appointment is " if next_only else "Your appointments are:\n") + (lines[0] if next_only else "\n".join(lines))


def handle_personal_request(route: PersonalRoute, context: AuthenticatedChatContext, db, *, now: Optional[dt.datetime] = None, repository: Optional[PersonalDataRepository] = None) -> Optional[PersonalResult]:
    """Handle a recognised personal route; return None for general RAG."""
    if route.intent == PersonalIntent.UNKNOWN:
        return None
    if route.intent == PersonalIntent.PRIVACY_DENIED:
        if not context.authenticated:
            return _result(route, AUTH_REQUIRED_PERSONAL_ANSWER, False, "Authentication required for personal information.", auth=True)
        return _result(route, PRIVACY_DENIED_ANSWER, False, "Personal access is self-service only.")
    if not rag_settings.RAG_PERSONALISATION_ENABLED:
        return _result(route, PERSONAL_DISABLED_ANSWER, False, "Personalisation is temporarily disabled.")
    if not context.authenticated or context.user_id is None:
        return _result(route, AUTH_REQUIRED_PERSONAL_ANSWER, False, "Authentication required for personal information.", auth=True)

    local_now = now or rag_settings.campus_now()
    repository = repository or PersonalDataRepository(db)
    roles = {role.upper() for role in context.roles}
    if route.intent == PersonalIntent.PROFILE:
        try:
            profile = repository.profile(context)
        except Exception:
            return _result(route, TEMPORARY_ERROR_ANSWER, False, "Personal data service temporarily unavailable.")
        if not profile:
            return _result(route, NO_RECORDS_ANSWER, False, "No active personal profile is available.")
        fields = [f"You are {profile.name} ({profile.role.lower()})"]
        for label, value in (("programme", profile.programme), ("faculty", profile.faculty), ("department", profile.department), ("position", profile.position), ("office", profile.office)):
            if value:
                fields.append(f"{label.title()}: {value}")
        return _result(route, ". ".join(fields) + ".", True)

    if route.intent in {PersonalIntent.COURSES, PersonalIntent.TIMETABLE, PersonalIntent.NEXT_CLASS, PersonalIntent.LOCATION}:
        if route.intent == PersonalIntent.COURSES and "STUDENT" not in roles:
            return _result(route, "Your role does not have current course enrolment records in this service.", False, "No student course context is available.")
        if route.intent != PersonalIntent.COURSES and not (roles & {"STUDENT", "LECTURER"}):
            return _result(route, "Your role does not have a personal timetable in this service.", False, "No timetable context is available.")
        term = rag_settings.active_term
        if term is None:
            return _result(route, TERM_UNAVAILABLE_ANSWER, False, "Active academic term is not configured.")
        try:
            if route.intent == PersonalIntent.COURSES:
                courses = repository.courses(context, term)
                answer = NO_RECORDS_ANSWER if not courses else "Your current courses are:\n" + "\n".join(f"{c.code} - {c.name}" for c in courses)
                return _result(route, answer, bool(courses), None if courses else "No active enrolments were found.")
            entries = repository.student_timetable(context, term) if "STUDENT" in roles else repository.lecturer_timetable(context, term)
            selected = _selected_entries(entries, route, local_now)
            next_only = route.intent in {PersonalIntent.NEXT_CLASS, PersonalIntent.LOCATION}
            target = NavigationTarget(label=selected[0].course.code, location=selected[0].location) if next_only and selected and selected[0].location.display else None
            return _result(route, _format_timetable(selected, next_only=next_only), bool(selected), None if selected else "No timetable entries were found.", navigation=target)
        except Exception:
            return _result(route, TEMPORARY_ERROR_ANSWER, False, "Personal data service temporarily unavailable.")

    if route.intent in {PersonalIntent.APPOINTMENTS, PersonalIntent.NEXT_APPOINTMENT}:
        start = local_now
        end = local_now + dt.timedelta(days=7)
        if route.date_scope in {DateScope.TODAY, DateScope.TOMORROW} and route.requested_date:
            start = local_now.replace(year=route.requested_date.year, month=route.requested_date.month, day=route.requested_date.day, hour=0, minute=0, second=0, microsecond=0)
            end = start + dt.timedelta(days=1)
        elif route.date_scope == DateScope.THIS_WEEK and route.week_start:
            start = local_now.replace(year=route.week_start.year, month=route.week_start.month, day=route.week_start.day, hour=0, minute=0, second=0, microsecond=0)
            end = start + dt.timedelta(days=7)
        try:
            rows = repository.appointments(context, start=start, end=end)
            next_only = route.intent == PersonalIntent.NEXT_APPOINTMENT
            target = NavigationTarget(label="appointment", location=rows[0].location) if next_only and rows and rows[0].location.display else None
            return _result(route, _format_appointments(rows, next_only=next_only), bool(rows), None if rows else "No appointments were found.", navigation=target)
        except Exception:
            return _result(route, TEMPORARY_ERROR_ANSWER, False, "Personal data service temporarily unavailable.")
    return None
