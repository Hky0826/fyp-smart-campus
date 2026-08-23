import datetime as dt
import unittest

from RagChatbot.config import rag_settings
from RagChatbot.personalisation.intents import parse_personal_intent
from RagChatbot.personalisation.schemas import (
    AuthenticatedChatContext, SafeCourse, SafeLocation, SafeTimetableEntry,
    PersonalIntent, DateScope,
)
from RagChatbot.personalisation.service import handle_personal_request


class FakeRepository:
    def __init__(self):
        self.calls = []

    def courses(self, context, term):
        self.calls.append(("courses", context.user_id, term))
        return [SafeCourse("CS101", "Secure Systems", 3)]

    def student_timetable(self, context, term):
        self.calls.append(("student_timetable", context.user_id, term))
        return [SafeTimetableEntry(SafeCourse("CS101", "Secure Systems"), "THURSDAY", dt.time(9), dt.time(11), SafeLocation("R-1", "Main Block", 2))]

    def lecturer_timetable(self, context, term):
        self.calls.append(("lecturer_timetable", context.user_id, term))
        return []

    def appointments(self, context, start=None, end=None):
        self.calls.append(("appointments", context.user_id))
        return []

    def profile(self, context):
        self.calls.append(("profile", context.user_id))
        return None


class PersonalisationTests(unittest.TestCase):
    def setUp(self):
        self.old_enabled = rag_settings.RAG_PERSONALISATION_ENABLED
        self.old_term = (rag_settings.RAG_ACTIVE_SEMESTER, rag_settings.RAG_ACTIVE_ACADEMIC_YEAR)
        rag_settings.RAG_PERSONALISATION_ENABLED = True
        rag_settings.RAG_ACTIVE_SEMESTER = "202607"
        rag_settings.RAG_ACTIVE_ACADEMIC_YEAR = "2025/2026"

    def tearDown(self):
        rag_settings.RAG_PERSONALISATION_ENABLED = self.old_enabled
        rag_settings.RAG_ACTIVE_SEMESTER, rag_settings.RAG_ACTIVE_ACADEMIC_YEAR = self.old_term

    def test_deterministic_parser_scopes_today(self):
        route = parse_personal_intent("What classes do I have today?", now=dt.datetime(2026, 7, 16, 8, tzinfo=dt.timezone.utc))
        self.assertEqual(route.intent, PersonalIntent.TIMETABLE)
        self.assertEqual(route.date_scope, DateScope.TODAY)
        self.assertEqual(route.requested_date, dt.date(2026, 7, 16))

    def test_other_person_is_privacy_denied(self):
        route = parse_personal_intent("Show student 42's timetable")
        self.assertEqual(route.intent, PersonalIntent.PRIVACY_DENIED)

    def test_unknown_general_query_is_not_personal(self):
        self.assertEqual(parse_personal_intent("What is the library opening time?").intent, PersonalIntent.UNKNOWN)

    def test_anonymous_personal_request_does_not_query_repository(self):
        repo = FakeRepository()
        route = parse_personal_intent("What are my courses?")
        result = handle_personal_request(route, AuthenticatedChatContext(None, None), None, repository=repo)
        self.assertTrue(result.authentication_required)
        self.assertFalse(repo.calls)

    def test_student_query_is_scoped_to_context_user(self):
        repo = FakeRepository()
        context = AuthenticatedChatContext(7, 9, roles=("STUDENT",), student_id="S7", authenticated=True)
        result = handle_personal_request(parse_personal_intent("Which courses am I enrolled in?"), context, None, repository=repo)
        self.assertTrue(result.access_granted)
        self.assertEqual(repo.calls, [("courses", 7, (202607, "2025/2026"))])
        self.assertNotIn("S7", result.answer)

    def test_missing_term_is_safe(self):
        rag_settings.RAG_ACTIVE_SEMESTER = ""
        rag_settings.RAG_ACTIVE_ACADEMIC_YEAR = ""
        repo = FakeRepository()
        context = AuthenticatedChatContext(7, 9, roles=("STUDENT",), student_id="S7", authenticated=True)
        result = handle_personal_request(parse_personal_intent("What is my timetable?"), context, None, repository=repo)
        self.assertFalse(result.access_granted)
        self.assertFalse(repo.calls)

    def test_courses_can_use_latest_enrolment_when_active_term_is_missing(self):
        rag_settings.RAG_ACTIVE_SEMESTER = ""
        rag_settings.RAG_ACTIVE_ACADEMIC_YEAR = ""
        repo = FakeRepository()
        context = AuthenticatedChatContext(7, 9, roles=("STUDENT",), student_id="S7", authenticated=True)
        result = handle_personal_request(parse_personal_intent("What courses am I enrolled in?"), context, None, repository=repo)
        self.assertTrue(result.access_granted)
        self.assertEqual(repo.calls, [("courses", 7, None)])

    def test_multiple_roles_union_permissions_and_personal_contexts(self):
        from RagChatbot.security.rbac import resolve_allowed_access_levels

        self.assertEqual(set(resolve_allowed_access_levels(["STUDENT", "LECTURER"])), {"VISITOR", "STUDENT", "LECTURER"})
        self.assertEqual(set(resolve_allowed_access_levels(["VISITOR", "STUDENT"])), {"VISITOR", "STUDENT"})

        repo = FakeRepository()
        context = AuthenticatedChatContext(7, 9, roles=("STUDENT", "LECTURER"), student_id="S7", lecturer_id="L7", staff_id="ST7", authenticated=True)
        result = handle_personal_request(parse_personal_intent("What is my timetable?"), context, None, repository=repo)

        self.assertTrue(result.access_granted)
        self.assertIn("lecturer_timetable", [call[0] for call in repo.calls])
        self.assertIn("student_timetable", [call[0] for call in repo.calls])

    def test_admin_student_user_keeps_student_timetable_context(self):
        repo = FakeRepository()
        context = AuthenticatedChatContext(
            7,
            9,
            roles=("ADMIN", "STUDENT"),
            student_id="S7",
            admin_id="A7",
            authenticated=True,
        )

        result = handle_personal_request(parse_personal_intent("What is my timetable?"), context, None, repository=repo)

        self.assertTrue(result.access_granted)
        self.assertIn("student_timetable", [call[0] for call in repo.calls])

    def test_implicit_schedule_query_without_my(self):
        route = parse_personal_intent("have any classes today")
        self.assertEqual(route.intent, PersonalIntent.TIMETABLE)
        self.assertEqual(route.date_scope, DateScope.TODAY)

    def test_who_am_i_parses_to_profile_intent(self):
        for phrase in ("who am i", "who i am", "what is my name", "what is my role", "my profile", "tell me who i am"):
            route = parse_personal_intent(phrase)
            self.assertEqual(route.intent, PersonalIntent.PROFILE, f"Failed for query: {phrase}")

    def test_who_am_i_returns_profile_information(self):
        from RagChatbot.personalisation.schemas import SafeProfile
        repo = FakeRepository()
        repo.profiles = lambda ctx: [SafeProfile(name="Dr. Smith", role="LECTURER", faculty="Computing", department="AI", position="Professor")]
        context = AuthenticatedChatContext(3, 10, roles=("LECTURER",), lecturer_id="L3", full_name="Dr. Smith", authenticated=True)
        result = handle_personal_request(parse_personal_intent("who am i"), context, None, repository=repo)
        self.assertTrue(result.access_granted)
        self.assertIn("Dr. Smith", result.answer)
        self.assertIn("lecturer", result.answer)


if __name__ == "__main__":
    unittest.main()
