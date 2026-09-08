"""
LLM-based query router for the RAG chatbot.

Classifies incoming queries to determine if they need vector database retrieval,
or if they can be answered directly (e.g., greetings, out of scope, navigational).
Extracts query facets (category, faculty, target audience) and overview hints for faceted RAG retrieval.
"""

import json
import logging
import re
from typing import Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from RagChatbot.config import rag_settings
from RagChatbot.gemini_client import get_gemini_client
from RagChatbot.utils.language_detection import detect_query_language

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

_NAVIGATION_HINT_PATTERN = re.compile(
    r"\b(where|go|going|take|navigate|destination|directions?|route|reach|arrive|head|walk|guide|point|locate|nearby|nearest|located|food|eat|canteen|cashier|toilet|washroom|restroom|bathroom|library|cafeteria|cafe|reception|office|classroom|elevator|stairwell|entrance|pharmacy)\b",
    re.IGNORECASE,
)

_BROAD_OVERVIEW_PATTERN = re.compile(
    r"\b("
    r"what\s+(?:are\s+(?:the\s+)?)?(?:programmes?|programs?|courses?|degrees?|faculties|schools?|scholarships?)"
    r"|what\s+(?:programmes?|programs?|courses?|degrees?|faculties|schools?|scholarships?)\s+(?:are|do\s+you)\s*(?:offered|available|have)?"
    r"|list\s+(?:all|some|the)?\s*(?:of\s+the\s+)?(?:programmes?|programs?|courses?|degrees?|faculties|schools?|scholarships?)"
    r"|overview\s+of\s+(?:the\s+)?(?:programmes?|programs?|courses?|degrees?|faculties|schools?)"
    r"|all\s+(?:degree|undergraduate|postgraduate|programmes?|programs?|faculties|courses?)"
    r"|what\s+can\s+i\s+study"
    r"|tell\s+me\s+about\s+(?:the\s+)?(?:programmes?|programs?|courses?|degrees?)"
    r"|(?:programmes?|programs?)\s+(?:and|or)\s+courses?"
    r")\b",
    re.IGNORECASE,
)

_CATEGORY_FEES_PATTERN = re.compile(r"\b(fees?|tuition|scholarships?|financial\s+aid|ptptn|cost|pricing|discount|coverage)\b", re.IGNORECASE)
_CATEGORY_ADMISSIONS_PATTERN = re.compile(r"\b(entry\s+requirements?|requirements?|eligibility|intakes?|apply|admission|deadline|qualifications?)\b", re.IGNORECASE)
_CATEGORY_POLICIES_PATTERN = re.compile(r"\b(polic(?:y|ies)|plagiarism|appeals?|disciplinary|grading|attendance|deferment|withdrawal)\b", re.IGNORECASE)
_CATEGORY_FACILITIES_PATTERN = re.compile(r"\b(facilit(?:y|ies)|hostel|accommodation|library|lab|laboratory|parking|bus|transport)\b", re.IGNORECASE)
_CATEGORY_ACADEMIC_PATTERN = re.compile(r"\b(programmes?|programs?|courses?|degrees?|curriculum|diplomas?|majors?|study|fields?\s+of\s+study|syllabus)\b", re.IGNORECASE)

_MATH_ARITHMETIC_PATTERN = re.compile(
    r"^\s*(?:what\s+is\s+|calculate\s+|evaluate\s+)?(?:\(?\s*-?\d+(?:\.\d+)?\s*\)?\s*[\+\-\*\/x×÷\^]\s*)+\(?\s*-?\d+(?:\.\d+)?\s*\)?\s*\??\s*$",
    re.IGNORECASE,
)

_MATH_KEYWORDS_PATTERN = re.compile(
    r"\b("
    r"math(?:s|ematics)?\s+(?:questions?|problems?|homework|equations?)"
    r"|can\s+you\s+(?:do|answer|solve)\s+(?:my\s+)?math\b"
    r"|answer\s+(?:a\s+)?math\s+question"
    r"|solve\s+[-0-9a-z\s\(\)\+\*\/\^\.]*=[^?]*"
    r"|solve\s+for\s+[a-z]"
    r"|solve\s+(?:the\s+)?(?:equation|algebra|calculus|trigonometry|quadratic)"
    r"|calculate\s+(?:the\s+)?(?:square\s+root|derivative|integral|sum|product|difference|logarithm)\s+of"
    r"|what\s+is\s+(?:the\s+)?(?:square\s+root|derivative|integral)\s+of"
    r"|\d+\s*(?:plus|minus|times|multiplied\s+by|divided\s+by)\s*\d+"
    r")",
    re.IGNORECASE,
)

_CAMPUS_CONTEXT_PATTERN = re.compile(
    r"\b("
    r"admission|admissions|entry|requirement|requirements|eligibility|intake|intakes|deadline"
    r"|spm|stpm|uec|igcse|o-level|a-level|foundation|matriculation"
    r"|fee|fees|tuition|cost|scholarship|scholarships|discount|ptptn|financial"
    r"|course|courses|programme|programmes|degree|degrees|diploma|diplomas|bachelor|master|masters|phd"
    r"|faculty|faculties|department|school|subject|subjects|credit|credits|grade|grades|grading|gpa|cgpa"
    r"|mark|marks|passing|exam|examination|assessment|attendance|timetable|schedule|lecture|lecturer|student"
    r"|campus|university|qiu|quest|hostel|accommodation|library|lab|canteen|toilet|room|building"
    r"|focs|fohs|fest|fobp"
    r")\b",
    re.IGNORECASE,
)

_FACULTY_PATTERNS = {
    "FOCS": re.compile(r"\b(computer\s+science|computing|software|information\s+technology|it\b|bcs|bit)\b", re.IGNORECASE),
    "FOHS": re.compile(r"\b(pharmacy|medicine|mbbs|biomedical|nursing|health)\b", re.IGNORECASE),
    "FEST": re.compile(r"\b(engineering|mechatronics|electronic|biotechnology|environmental)\b", re.IGNORECASE),
    "FOBP": re.compile(r"\b(business|finance|accountancy|accounting|bba|management)\b", re.IGNORECASE),
}

_LANGUAGE_NAME_TO_CODE: dict[str, tuple[str, str]] = {
    # English names
    "english": ("en", "English"),
    "chinese": ("zh", "Chinese"),
    "mandarin": ("zh", "Mandarin"),
    "cantonese": ("yue", "Cantonese"),
    "malay": ("ms", "Malay"),
    "bahasa melayu": ("ms", "Bahasa Melayu"),
    "bahasa malaysia": ("ms", "Bahasa Melayu"),
    "bahasa inggeris": ("en", "English"),
    "bahasa cina": ("zh", "Chinese"),
    "bahasa tamil": ("ta", "Tamil"),
    "bahasa arab": ("ar", "Arabic"),
    "bahasa jepun": ("ja", "Japanese"),
    "bahasa korea": ("ko", "Korean"),
    "tamil": ("ta", "Tamil"),
    "arabic": ("ar", "Arabic"),
    "japanese": ("ja", "Japanese"),
    "korean": ("ko", "Korean"),
    "french": ("fr", "French"),
    "german": ("de", "German"),
    "hindi": ("hi", "Hindi"),
    "spanish": ("es", "Spanish"),
    "indonesian": ("id", "Indonesian"),
    "russian": ("ru", "Russian"),
    "italian": ("it", "Italian"),
    "thai": ("th", "Thai"),
    "vietnamese": ("vi", "Vietnamese"),
    # Chinese names
    "华语": ("zh", "Chinese"),
    "中文": ("zh", "Chinese"),
    "普通话": ("zh", "Chinese"),
    "国语": ("zh", "Chinese"),
    "广东话": ("yue", "Cantonese"),
    "粤语": ("yue", "Cantonese"),
    "白话": ("yue", "Cantonese"),
    "英文": ("en", "English"),
    "英语": ("en", "English"),
    "马来语": ("ms", "Malay"),
    "马来文": ("ms", "Malay"),
    "日文": ("ja", "Japanese"),
    "日语": ("ja", "Japanese"),
    "韩文": ("ko", "Korean"),
    "韩语": ("ko", "Korean"),
    "阿拉伯语": ("ar", "Arabic"),
    "淡米尔语": ("ta", "Tamil"),
    "泰米尔语": ("ta", "Tamil"),
    "法语": ("fr", "French"),
    "德语": ("de", "German"),
    "西班牙语": ("es", "Spanish"),
}

_LANG_SWITCH_EN_PATTERN = re.compile(
    r"^(?:(?:can|could)\s+(?:we|you)\s+|please\s+|let'?s\s+)?(?:speak|converse|talk|switch\s+to)\s+(?:in\s+)?([a-z\s]+?)(?:\s+please)?[.?!]*$",
    re.IGNORECASE,
)
_LANG_SWITCH_PLEASE_PATTERN = re.compile(
    r"^([a-z\s]+)\s+please[.?!]*$",
    re.IGNORECASE,
)
_LANG_SWITCH_MS_PATTERN = re.compile(
    r"^(?:boleh\s+)?(?:cakap|guna|tukar\s+(?:ke|kepada)|bercakap)\s+(?:dalam\s+)?bahasa\s+([a-z\s]+?)(?:\s+tak|\s+boleh)?[.?!]*$",
    re.IGNORECASE,
)
_LANG_SWITCH_ZH_PATTERN = re.compile(
    r"^(?:可以)?(?:用|讲|说|换成|切换(?:成|到)?)\s*(华语|中文|普通话|国语|广东话|粤语|白话|英文|英语|马来语|马来文|日文|日语|韩文|韩语|阿拉伯语|淡米尔语|泰米尔语|法语|德语|西班牙语)\s*(?:交流|沟通|吗|吧|好吗|可以吗)?[.?!]*$",
)


def detect_language_switch(query: str) -> Optional[tuple[str, str]]:
    """Detect voice or text requests to switch conversation language.
    Returns (language_code, language_name) if matched, else None.
    """
    clean = query.strip()
    if not clean:
        return None

    # Check English/Latin patterns
    m = _LANG_SWITCH_EN_PATTERN.match(clean)
    if m:
        target = m.group(1).strip().lower()
        if target in _LANGUAGE_NAME_TO_CODE:
            return _LANGUAGE_NAME_TO_CODE[target]

    m_please = _LANG_SWITCH_PLEASE_PATTERN.match(clean)
    if m_please:
        target = m_please.group(1).strip().lower()
        if target in _LANGUAGE_NAME_TO_CODE:
            return _LANGUAGE_NAME_TO_CODE[target]

    # Check Malay patterns
    m_ms = _LANG_SWITCH_MS_PATTERN.match(clean)
    if m_ms:
        target_sub = f"bahasa {m_ms.group(1).strip().lower()}"
        if target_sub in _LANGUAGE_NAME_TO_CODE:
            return _LANGUAGE_NAME_TO_CODE[target_sub]
        raw_target = m_ms.group(1).strip().lower()
        if raw_target in _LANGUAGE_NAME_TO_CODE:
            return _LANGUAGE_NAME_TO_CODE[raw_target]

    # Check Chinese patterns
    m_zh = _LANG_SWITCH_ZH_PATTERN.match(clean)
    if m_zh:
        target_zh = m_zh.group(1).strip()
        if target_zh in _LANGUAGE_NAME_TO_CODE:
            return _LANGUAGE_NAME_TO_CODE[target_zh]

    return None


_ROUTE_CATEGORIES = {"GREETING", "CAPABILITY", "NAVIGATIONAL", "OUT_OF_SCOPE", "UNCLEAR", "UNIVERSITY_INFO", "LANGUAGE_SWITCH"}
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
    category_hint: Optional[str] = None
    faculty_hint: Optional[str] = None
    is_broad_overview: bool = False


def _extract_facets_from_query(query: str) -> tuple[Optional[str], Optional[str], bool]:
    """Extract category hint, faculty hint, and overview flag using fast local regex matching."""
    category_hint = None
    if _CATEGORY_FEES_PATTERN.search(query):
        category_hint = "FEES_SCHOLARSHIPS"
    elif _CATEGORY_ADMISSIONS_PATTERN.search(query):
        category_hint = "ADMISSIONS"
    elif _CATEGORY_POLICIES_PATTERN.search(query):
        category_hint = "POLICIES"
    elif _CATEGORY_FACILITIES_PATTERN.search(query):
        category_hint = "FACILITIES"
    elif _CATEGORY_ACADEMIC_PATTERN.search(query):
        category_hint = "ACADEMIC"

    faculty_hint = None
    for fac_code, pat in _FACULTY_PATTERNS.items():
        if pat.search(query):
            faculty_hint = fac_code
            break

    is_broad = bool(_BROAD_OVERVIEW_PATTERN.search(query))
    return category_hint, faculty_hint, is_broad


def _load_destination_catalog(db) -> list[tuple[str, str]]:
    """Load navigable labels from nodes without exposing corridor waypoints."""
    if db is None:
        return []
    try:
        from app.models.models import Node

        rows = (
            db.query(Node.room_label, Node.node_type)
            .filter(Node.room_label.isnot(None))
            .filter(Node.node_type != "CORRIDOR")
            .order_by(Node.room_label, Node.node_type)
            .all()
        )
        return [
            (str(label), str(node_type).upper())
            for label, node_type in rows
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
    is_non_english = detect_query_language(query) != "en"
    if not rag_settings.GOOGLE_API_KEY or not (_NAVIGATION_HINT_PATTERN.search(query) or mentions_destination or is_non_english):
        return None

    try:
        client = get_gemini_client()
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
        
        cat_hint, fac_hint, is_broad = _extract_facets_from_query(query)
        result = RouteClassification(
            category=category,
            clarification_question=payload.get("clarification_question"),
            category_hint=cat_hint,
            faculty_hint=fac_hint,
            is_broad_overview=is_broad,
        )
        logger.info("LLM query router classified request as %s", result.category)
        return result
    except Exception as exc:
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

    cat_hint, fac_hint, is_broad = _extract_facets_from_query(clean_query)

    # 1. GREETING Fast-Path
    if _GREETING_PATTERN.match(clean_query):
        logger.info("Local Regex Router classified '%s' as GREETING (0 LLM calls)", query)
        return RouteClassification(category="GREETING")

    # 1.5. LANGUAGE_SWITCH Fast-Path
    lang_switch = detect_language_switch(clean_query)
    if lang_switch:
        lang_code, lang_name = lang_switch
        logger.info("Local Regex Router classified '%s' as LANGUAGE_SWITCH (%s, 0 LLM calls)", query, lang_code)
        return RouteClassification(
            category="LANGUAGE_SWITCH",
            category_hint=lang_code,
        )

    # 2. CAPABILITY Fast-Path
    if _CAPABILITY_PATTERN.search(clean_query):
        logger.info("Local Regex Router classified '%s' as CAPABILITY (0 LLM calls)", query)
        return RouteClassification(category="CAPABILITY")

    # 2.5. OUT_OF_SCOPE Fast-Path: Math, Arithmetic, and Non-Campus Calculations (0 LLM calls)
    if (_MATH_ARITHMETIC_PATTERN.search(clean_query) or _MATH_KEYWORDS_PATTERN.search(clean_query)) and not _CAMPUS_CONTEXT_PATTERN.search(clean_query):
        logger.info("Local Regex Router classified '%s' as OUT_OF_SCOPE (math/calculation detected)", query)
        return RouteClassification(category="OUT_OF_SCOPE")

    # 3. NAVIGATIONAL Fast-Path
    from RagChatbot.services.map_service import is_navigation_query
    if _NAVIGATIONAL_PATTERN.search(clean_query) or is_navigation_query(clean_query, db=db):
        logger.info("Local Regex Router classified '%s' as NAVIGATIONAL (0 LLM calls)", query)
        return RouteClassification(
            category="NAVIGATIONAL",
            category_hint=cat_hint,
            faculty_hint=fac_hint,
            is_broad_overview=is_broad,
        )

    # 4. UNCLEAR check
    is_en = detect_query_language(clean_query) == "en"
    query_words = clean_query.lower().split()
    if len(query_words) == 1 and (query_words[0] in _UNCLEAR_WORDS or (is_en and len(query_words[0]) < 3)):
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
        return RouteClassification(
            category="NAVIGATIONAL",
            category_hint=cat_hint,
            faculty_hint=fac_hint,
            is_broad_overview=is_broad,
        )

    llm_route = _llm_navigation_fallback(clean_query, destinations)
    if llm_route is not None:
        return llm_route

    # 6. Default: Substantive RAG Query (UNIVERSITY_INFO)
    logger.info("Query router classified '%s' as UNIVERSITY_INFO (category_hint=%s, faculty_hint=%s, broad=%s)",
                query, cat_hint, fac_hint, is_broad)
    return RouteClassification(
        category="UNIVERSITY_INFO",
        category_hint=cat_hint,
        faculty_hint=fac_hint,
        is_broad_overview=is_broad,
    )


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
