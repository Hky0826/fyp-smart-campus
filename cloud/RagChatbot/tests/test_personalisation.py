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


if __name__ == "__main__":
    unittest.main()
