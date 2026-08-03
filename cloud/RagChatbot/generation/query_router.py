"""
LLM-based query router for the RAG chatbot.

Classifies incoming queries to determine if they need vector database retrieval,
or if they can be answered directly (e.g., greetings, out of scope, navigational).
"""

import json
import logging
import re
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

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
    r"\b(where\s+(?:is|are|can\s+i\s+(?:find|get))|can\s+you\s+tell\s+me\s+where|how\s+(?:do\s+i|can\s+i)\s+get\s+to|directions?\s+to|map\s+of|location\s+of|find\s+the\s+building|way\s+to|take\s+me\s+to|navigate\s+to|go\s+to|show\s+me\s+where|point\s+me\s+to)\b",
    re.IGNORECASE,
)

# Only send queries that contain a plausible movement/location hint to the LLM.
# This preserves the cheap local path for ordinary document questions.
_NAVIGATION_HINT_PATTERN = re.compile(
    r"\b(where|go|going|take|navigate|destination|directions?|route|reach|arrive|head|walk|guide|point|locate|nearby|nearest|located|food|eat|canteen|cashier|toilet|washroom|restroom|bathroom|library|cafeteria|cafe|reception|office|classroom|elevator|stairwell|entrance|pharmacy)\b",
    re.IGNORECASE,
)

_ROUTE_CATEGORIES = {"GREETING", "CAPABILITY", "NAVIGATIONAL", "OUT_OF_SCOPE", "UNCLEAR", "UNIVERSITY_INFO"}
_ROUTER_SYSTEM_PROMPT = """Classify the user's request into exactly one category.

Use NAVIGATIONAL when the user wants to find, reach, visit, or get directions to a
physical campus destination such as a cashier, toilet, room, office, library, cafe,
entrance, elevator, or washroom. Use UNIVERSITY_INFO for questions asking about
documents, policies, programmes, fees, people, or other campus information without
asking to go to a physical place. Return only the requested JSON object.
"""

_UNCLEAR_WORDS = {"fees", "help", "science", "info", "test", "school"}


class RouteClassification(BaseModel):
    category: str = Field(description="The classification category of the query.")
    clarification_question: str | None = Field(
        default=None, 
        description="If category is UNCLEAR, provide a short clarifying question."
    )


def _load_destination_catalog(db) -> list[tuple[str, str]]:
    """Load navigable labels from nodes without exposing corridor waypoints."""
    if db is None:
        return []
    try:
        from cloud.mapping_and_notification.mapping.repository import MapRepository

        return [
            (str(label), str(node_type).upper())
            for label, node_type in MapRepository(db).destination_catalog()
            if label and str(node_type).upper() != "CORRIDOR"
        ]
    except Exception as exc:
        logger.warning("Could not load navigation destination catalog: %s", type(exc).__name__)
        return []


def _query_mentions_destination(query: str, destinations: list[tuple[str, str]]) -> bool:
    normalized_query = re.sub(r"[^\w]+", " ", query.casefold()).strip()
    for label, _ in destinations:
        normalized_label = re.sub(r"[^\w]+", " ", label.casefold()).strip()
        if normalized_label and re.search(rf"(?<!\w){re.escape(normalized_label)}(?!\w)", normalized_query):
            return True
    return False


def _llm_navigation_fallback(query: str, destinations: list[tuple[str, str]]) -> RouteClassification | None:
    """Use a structured LLM classification when local patterns are insufficient."""
    mentions_destination = _query_mentions_destination(query, destinations)
    if not rag_settings.GOOGLE_API_KEY or not (_NAVIGATION_HINT_PATTERN.search(query) or mentions_destination):
        return None

    try:
        client = genai.Client(api_key=rag_settings.GOOGLE_API_KEY)
        destination_context = "\n".join(
            f"- {label} ({node_type})" for label, node_type in destinations
        ) or "- No destination catalog is available"
        response = client.models.generate_content(
            model=rag_settings.LLM_MODEL,
            contents=(
                f"Known navigable destinations from the nodes table:\n{destination_context}\n\n"
                f"User request: {query}"
            ),
            config=types.GenerateContentConfig(
                system_instruction=_ROUTER_SYSTEM_PROMPT,
                max_output_tokens=64,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "category": {
                            "type": "STRING",
                            "enum": sorted(_ROUTE_CATEGORIES),
                        },
                        "clarification_question": {
                            "type": "STRING",
                            "nullable": True,
                        },
                    },
                    "required": ["category"],
                },
            ),
        )
        payload = json.loads((response.text or "").strip())
        category = str(payload.get("category", "")).upper()
        if category not in _ROUTE_CATEGORIES:
            return None
        result = RouteClassification(
            category=category,
            clarification_question=payload.get("clarification_question"),
        )
        logger.info("LLM query router classified request as %s", result.category)
        return result
    except Exception as exc:
        # Intent classification must never prevent normal RAG handling.
        logger.warning("LLM query router fallback failed: %s", type(exc).__name__)
        return None


def classify_query(query: str, db=None) -> RouteClassification:
    """
    Local Regex Guard & Intent Router (~2ms — 0 LLM calls).
    
    Classifies queries locally first, with a targeted LLM fallback for navigation hints.
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
    from RagChatbot.services.map_service import is_navigation_query
    if _NAVIGATIONAL_PATTERN.search(clean_query) or is_navigation_query(clean_query, db=db):
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

    # 5. LLM fallback for natural navigation phrases not covered by regex.
    destinations = _load_destination_catalog(db)
    if _query_mentions_destination(clean_query, destinations) and _normalise_query(clean_query) in {
        _normalise_query(label) for label, _ in destinations
    }:
        return RouteClassification(category="NAVIGATIONAL")

    llm_route = _llm_navigation_fallback(clean_query, destinations)
    if llm_route is not None:
        return llm_route

    # 6. Default: Substantive RAG Query (UNIVERSITY_INFO)
    logger.info("Query router classified '%s' as UNIVERSITY_INFO", query)
    return RouteClassification(category="UNIVERSITY_INFO")


def _normalise_query(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


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
