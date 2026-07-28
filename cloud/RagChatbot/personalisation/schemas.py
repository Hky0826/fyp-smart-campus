"""Safe internal DTOs for the personal chatbot path."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Optional


class PersonalIntent(str, Enum):
    UNKNOWN = "UNKNOWN"
    PROFILE = "PROFILE"
    COURSES = "COURSES"
    TIMETABLE = "TIMETABLE"
    NEXT_CLASS = "NEXT_CLASS"
    APPOINTMENTS = "APPOINTMENTS"
    NEXT_APPOINTMENT = "NEXT_APPOINTMENT"
    LOCATION = "LOCATION"
    PRIVACY_DENIED = "PRIVACY_DENIED"


class DateScope(str, Enum):
    NONE = "NONE"
    TODAY = "TODAY"
    TOMORROW = "TOMORROW"
    THIS_WEEK = "THIS_WEEK"
    NEXT = "NEXT"


@dataclass(frozen=True)
class PersonalRoute:
    intent: PersonalIntent = PersonalIntent.UNKNOWN
    date_scope: DateScope = DateScope.NONE
    requested_date: Optional[date] = None
    week_start: Optional[date] = None
    requires_authentication: bool = True
    clarification_question: Optional[str] = None


@dataclass(frozen=True)
class AuthenticatedChatContext:
    user_id: Optional[int]
    session_id: Optional[int]
    roles: tuple[str, ...] = ()
    student_id: Optional[str] = None
    lecturer_id: Optional[str] = None
    staff_id: Optional[str] = None
    visitor_id: Optional[str] = None
    admin_id: Optional[str] = None
    given_name: Optional[str] = None
    full_name: Optional[str] = None
    authenticated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class SafeProfile:
    name: str
    role: str
    programme: Optional[str] = None
    faculty: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    office: Optional[str] = None


@dataclass(frozen=True)
class SafeCourse:
    code: str
    name: str
    credits: Optional[int] = None


@dataclass(frozen=True)
class SafeLocation:
    room: Optional[str] = None
    building: Optional[str] = None
    floor: Optional[int] = None

    @property
    def display(self) -> str:
        parts = [p for p in (self.room, self.building) if p]
        if self.floor is not None:
            parts.append(f"floor {self.floor}")
        return ", ".join(parts)


@dataclass(frozen=True)
class SafeTimetableEntry:
    course: SafeCourse
    weekday: str
    start: time
    end: time
    location: SafeLocation = field(default_factory=SafeLocation)

    @property
    def start_text(self) -> str:
        return self.start.strftime("%H:%M")

    @property
    def end_text(self) -> str:
        return self.end.strftime("%H:%M")


@dataclass(frozen=True)
class SafeAppointment:
    participant_name: str
    scheduled_at: datetime
    duration_minutes: int
    status: str
    location: SafeLocation = field(default_factory=SafeLocation)


@dataclass(frozen=True)
class NavigationTarget:
    label: str
    location: SafeLocation


@dataclass(frozen=True)
class PersonalResult:
    answer: str
    access_granted: bool
    status_message: Optional[str]
    intent: PersonalIntent
    response_scope: str = "PERSONAL"
    authentication_required: bool = False
    navigation_target: Optional[NavigationTarget] = None
    audit_marker: str = "PERSONAL_RESPONSE_REDACTED"
