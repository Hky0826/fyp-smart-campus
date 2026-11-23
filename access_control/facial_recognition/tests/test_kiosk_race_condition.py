"""Tests verifying race-condition resilience in the kiosk state store."""

from __future__ import annotations

import datetime as dt
import unittest

from access_control.facial_recognition.src.api.kiosk import (
    EdgeAuthToken,
    KioskStateStore,
    KioskTimingConfig,
    RuntimeConfig,
)


class KioskRaceConditionTests(unittest.TestCase):
    def setUp(self):
        self.store = KioskStateStore(
            RuntimeConfig(sync_device_id="door-1", sync_device_name="Door 1"),
            timings=KioskTimingConfig(
                owner_missing_grace_seconds=1,
                owner_absent_terminate_seconds=5,
            ),
        )

    def test_append_chat_exchange_survives_temporary_lock_without_409(self):
        """When presence frame momentarily locks a session, append_chat_exchange must not raise 409."""
        token = EdgeAuthToken(
            access_token="secret-jwt",
            session_id=101,
            user_id=42,
            email="student@qiu.edu.my",
            roles=("STUDENT",),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        )
        self.store.start_chat_session(token, full_name="John Doe")
        
        # Simulate presence frame check locking the session while LLM was processing
        self.store.lock_chat_session(presence_state="OWNER_TEMPORARILY_MISSING")
        self.assertIsNone(self.store.current_chat_session())

        # When LLM finishes and appends the exchange, it should succeed without 409 Conflict
        view = self.store.append_chat_exchange(
            user_text="Where is the library?",
            answer="The library is on level 2.",
            citations=[],
        )
        self.assertIsNotNone(view)
        # Recoverable view should preserve the conversation history
        rec_view = self.store.recoverable_chat_session_view()
        self.assertIsNotNone(rec_view)
        history_contents = [msg.content for msg in rec_view.conversation_history]
        self.assertIn("Where is the library?", history_contents)
        self.assertIn("The library is on level 2.", history_contents)

    def test_append_chat_exchange_creates_fallback_visitor_session_if_none_active(self):
        """When no session was ever started, append_chat_exchange creates a visitor session instead of 409."""
        view = self.store.append_chat_exchange(
            user_text="What programmes are offered?",
            answer="We offer Computer Science, Medicine, and Pharmacy.",
            citations=[],
        )
        self.assertIsNotNone(view)
        self.assertIsNone(view.authenticated_user_id)
        self.assertEqual(view.roles, [])
        self.assertFalse(view.locked)
        history_contents = [msg.content for msg in view.conversation_history]
        self.assertIn("What programmes are offered?", history_contents)
        self.assertIn("We offer Computer Science, Medicine, and Pharmacy.", history_contents)

    def test_current_token_returns_none_or_recoverable_instead_of_409(self):
        """current_token should not raise 409 when no session or recoverable session exists."""
        # No session: returns None
        self.assertIsNone(self.store.current_token())

        # Start session: returns token
        token = EdgeAuthToken(
            access_token="secret-jwt",
            session_id=101,
            user_id=42,
            email="student@qiu.edu.my",
            roles=("STUDENT",),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        )
        self.store.start_chat_session(token, full_name="John Doe")
        self.assertEqual(self.store.current_token(), token)

        # Lock session: current_token still recovers the token
        self.store.lock_chat_session()
        self.assertEqual(self.store.current_token(), token)

    def test_chat_greeting_audio_fallback_logic(self):
        """Verify recoverable or visitor session view retrieval."""
        self.assertIsNone(self.store.current_chat_session())
        self.assertIsNone(self.store.recoverable_chat_session_view())

        # Start visitor session
        view = self.store.start_chat_session(None)
        self.assertIsNotNone(view)
        self.assertIsNone(view.authenticated_user_id)
        self.assertEqual(view.roles, [])
        self.assertFalse(view.locked)
