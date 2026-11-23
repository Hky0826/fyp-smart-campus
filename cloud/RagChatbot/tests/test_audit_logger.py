from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.models import ChatbotQuery
from RagChatbot.security.audit_logger import log_chatbot_interaction


def test_anonymous_chat_audit_persists_with_nullable_session_id():
    engine = create_engine("sqlite:///:memory:")
    ChatbotQuery.__table__.create(engine)

    with Session(engine) as db:
        query_id = log_chatbot_interaction(
            db,
            session_id=None,
            user_id=None,
            query_text="anonymous visitor query",
            response_text="test response",
            retrieved_chunk_ids=[],
            response_time_ms=1,
        )
        record = db.execute(
            select(ChatbotQuery).where(ChatbotQuery.query_id == query_id)
        ).scalar_one()

    assert record.session_id is None
    assert record.user_id is None
