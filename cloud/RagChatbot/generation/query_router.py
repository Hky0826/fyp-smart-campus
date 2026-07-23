"""
LLM-based query router for the RAG chatbot.

Classifies incoming queries to determine if they need vector database retrieval,
or if they can be answered directly (e.g., greetings, out of scope, navigational).
"""

import json
import logging
import re
from pydantic import BaseModel, Field

from RagChatbot.config import rag_settings

logger = logging.getLogger(__name__)

# The manifest of information we actually have in the database.
KNOWLEDGE_BASE_MANIFEST = [
    "Admissions",
    "Programmes and courses",
    "Fees and scholarships",
    "Student life",
    "Contact information",
    "FAQs",
    "International students",
    "Faculties and schools",
    "Academic policies",
    "News and events"
]

_GREETING_PATTERN = re.compile(
    r"\b(hi|hello|hey|good\s+(morning|afternoon|evening|day)|greetings|howdy|sup|yo|how\s+are\s+you|who\s+are\s+you|what\s+is\s+your\s+name|nice\s+to\s+meet\s+you)\b",
    re.IGNORECASE,
)

_CAPABILITY_PATTERN = re.compile(
    r"\b(what\s+can\s+you\s+do|how\s+can\s+you\s+help|what\s+are\s+your\s+capabilities|what\s+do\s+you\s+know|features)\b",
    re.IGNORECASE,
)

_NAVIGATIONAL_PATTERN = re.compile(
    r"\b(where\s+is|how\s+to\s+get\s+to|directions?\s+to|map\s+of|location\s+of|find\s+the\s+building|way\s+to)\b",
    re.IGNORECASE,
)

_UNCLEAR_WORDS = {"fees", "help", "science", "info", "test", "school"}


class RouteClassification(BaseModel):
    category: str = Field(description="The classification category of the query.")
    clarification_question: str | None = Field(
        default=None, 
        description="If category is UNCLEAR, provide a short clarifying question."
    )


def classify_query(query: str) -> RouteClassification:
    """
    Local Regex Guard & Intent Router (~2ms — 0 LLM calls).
    
    Classifies queries locally using pattern matching without invoking any LLM API.
    """
    clean_query = query.strip()
    if not clean_query:
        return RouteClassification(
            category="UNCLEAR",
            clarification_question="Could you please ask a question about campus services or documents?",
        )

    # 1. GREETING Fast-Path
    if _GREETING_PATTERN.match(clean_query):
        logger.info("Local Regex Router classified '%s' as GREETING (0 LLM calls)", query)
        return RouteClassification(category="GREETING")

    # 2. CAPABILITY Fast-Path
    if _CAPABILITY_PATTERN.search(clean_query):
        logger.info("Local Regex Router classified '%s' as CAPABILITY (0 LLM calls)", query)
        return RouteClassification(category="CAPABILITY")

    # 3. NAVIGATIONAL Fast-Path
    if _NAVIGATIONAL_PATTERN.search(clean_query):
        logger.info("Local Regex Router classified '%s' as NAVIGATIONAL (0 LLM calls)", query)
        return RouteClassification(category="NAVIGATIONAL")

    # 4. UNCLEAR check
    query_words = clean_query.lower().split()
    if len(query_words) == 1 and (query_words[0] in _UNCLEAR_WORDS or len(query_words[0]) < 3):
        logger.info("Local Regex Router classified '%s' as UNCLEAR (0 LLM calls)", query)
        return RouteClassification(
            category="UNCLEAR",
            clarification_question=f"Could you please specify what information about {query_words[0]} you are looking for?",
        )

    # 5. Default: Substantive RAG Query (UNIVERSITY_INFO)
    logger.info("Local Regex Router classified '%s' as UNIVERSITY_INFO (0 LLM calls)", query)
    return RouteClassification(category="UNIVERSITY_INFO")


def get_capabilities_summary(*, authenticated: bool = False, personalisation_enabled: bool = False) -> str:
    """Return capabilities without claiming disabled personal features."""
    topics = ", ".join([t.lower() for t in KNOWLEDGE_BASE_MANIFEST[:-1]])
    last_topic = KNOWLEDGE_BASE_MANIFEST[-1].lower()
    answer = f"I can help answer questions about {topics}, and {last_topic} available in the university documents."
    if personalisation_enabled:
        if authenticated:
            answer += " I can also show your own profile, current courses, timetable, next class, and appointments."
        else:
            answer += " Personal profile, course, timetable, and appointment questions require face authentication."
    return answer
