"""Deterministic personal-intent and local-date parsing."""

from __future__ import annotations

import re
from datetime import date, timedelta

from RagChatbot.config import rag_settings
from RagChatbot.personalisation.schemas import DateScope, PersonalIntent, PersonalRoute


_OTHER_PERSON_RE = re.compile(
    r"\b(?:student|lecturer|staff|visitor|user|person)\s*(?:id\s*)?[#:\-]?\s*[A-Za-z0-9_-]+\b|\b[A-Za-z][A-Za-z -]{1,40}'s\s+(?:timetable|schedule|classes|courses|appointments?)\b",
    re.IGNORECASE,
)


def _scope(text: str, today: date) -> tuple[DateScope, date | None, date | None]:
    if re.search(r"\b(today|tonight|this\s+day)\b", text):
        return DateScope.TODAY, today, None
    if re.search(r"\b(tomorrow|next\s+day)\b", text):
        return DateScope.TOMORROW, today + timedelta(days=1), None
    if re.search(r"\b(this\s+week|weekly|week)\b", text):
        return DateScope.THIS_WEEK, None, today - timedelta(days=today.weekday())
    if re.search(r"\b(next)\b", text):
        return DateScope.NEXT, None, None
    return DateScope.NONE, None, None


def parse_personal_intent(query: str, *, now=None) -> PersonalRoute:
    """Parse only self-service domain/date intent; never select an owner."""
    text = " ".join((query or "").lower().split())
    if not text:
        return PersonalRoute()
    local_now = now or rag_settings.campus_now()
    today = local_now.date()
    if _OTHER_PERSON_RE.search(text) and re.search(r"\b(timetable|schedule|class(?:es)?|course(?:s)?|appointment(?:s)?)\b", text):
        return PersonalRoute(intent=PersonalIntent.PRIVACY_DENIED, requires_authentication=True)
    has_self_pronoun = bool(re.search(r"\b(my|me|i|mine)\b", text))
    has_implicit_personal_query = bool(re.search(
        r"\b(have\s+any\s+class(?:es)?|any\s+class(?:es)?|got\s+class(?:es)?|next\s+class|upcoming\s+class|today'?s\s+class(?:es)?|today'?s\s+schedule|classes\s+today|schedule\s+today|enrolled\s+in)\b",
        text,
    ))
    if not (has_self_pronoun or has_implicit_personal_query):
        return PersonalRoute()

    scope, requested_date, week_start = _scope(text, today)
    location = bool(re.search(r"\b(where|location|room|which\s+room)\b", text))
    if re.search(r"\b(profile|about\s+me|my\s+details|my\s+information)\b", text):
        intent = PersonalIntent.PROFILE
    elif re.search(r"\b(course|courses|cause|causes|enrol|enrolled|classes?\s+am\s+i\s+taking)\b", text) and not re.search(r"\b(class|timetable|schedule|lecture)\b", text):
        intent = PersonalIntent.COURSES
    elif re.search(r"\b(appointment|appointments|meeting|meetings)\b", text):
        intent = PersonalIntent.NEXT_APPOINTMENT if (scope == DateScope.NEXT or location) else PersonalIntent.APPOINTMENTS
    elif re.search(r"\b(next\s+class|next\s+lecture|upcoming\s+class|upcoming\s+lecture)\b", text):
        intent = PersonalIntent.LOCATION if location else PersonalIntent.NEXT_CLASS
        scope = DateScope.NEXT
    elif re.search(r"\b(timetable|schedule|class(?:es)?|lecture(?:s)?)\b", text):
        intent = PersonalIntent.LOCATION if location and scope == DateScope.NEXT else PersonalIntent.TIMETABLE
    else:
        return PersonalRoute()
    if location and intent in {PersonalIntent.APPOINTMENTS, PersonalIntent.NEXT_APPOINTMENT}:
        intent = PersonalIntent.NEXT_APPOINTMENT
    return PersonalRoute(intent=intent, date_scope=scope, requested_date=requested_date, week_start=week_start, requires_authentication=True)
