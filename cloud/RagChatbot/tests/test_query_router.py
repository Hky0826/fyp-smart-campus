import time
import json
import pytest
from RagChatbot.generation import query_router
from RagChatbot.generation.query_router import classify_query, get_capabilities_summary


def test_local_regex_greeting():
    start = time.perf_counter()
    res = classify_query("Hello there! How are you?")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert res.category == "GREETING"
    assert elapsed_ms < 10.0  # Must be fast (~2ms)


def test_local_regex_capability():
    res = classify_query("What can you do?")
    assert res.category == "CAPABILITY"


def test_local_regex_navigational():
    res = classify_query("Where is the library?")
    assert res.category == "NAVIGATIONAL"


@pytest.mark.parametrize(
    "query",
    [
        "Can you point me toward the cashier?",
        "Can you tell me where the cashier is?",
    ],
)
def test_llm_fallback_classifies_natural_navigation_phrase(monkeypatch, query):
    class FakeResponse:
        text = json.dumps({"category": "NAVIGATIONAL"})

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(query_router.genai, "Client", lambda **kwargs: FakeClient())

    res = classify_query(query)

    assert res.category == "NAVIGATIONAL"


def test_nodes_catalog_adds_dynamic_destination_to_router(monkeypatch):
    monkeypatch.setattr(
        query_router,
        "_load_destination_catalog",
        lambda db: [("Boardroom 1", "HALL")],
    )

    class FakeResponse:
        text = json.dumps({"category": "NAVIGATIONAL"})

    class FakeModels:
        def generate_content(self, **kwargs):
            assert "Boardroom 1 (HALL)" in kwargs["contents"]
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(query_router.genai, "Client", lambda **kwargs: FakeClient())

    result = classify_query("I need the Boardroom 1 location", db=object())

    assert result.category == "NAVIGATIONAL"


def test_local_regex_substantive_rag():
    res = classify_query("What are the admission requirements for Computer Science?")
    assert res.category == "UNIVERSITY_INFO"


def test_local_regex_unclear():
    res = classify_query("fees")
    assert res.category == "UNCLEAR"
    assert res.clarification_question is not None


@pytest.mark.parametrize(
    "query",
    [
        "2 + 2",
        "15 * 3",
        "100 / 4",
        "what is 5 plus 10?",
        "calculate 12 * 8",
        "what is 2 + 2",
        "50 - 25",
    ],
)
def test_math_out_of_scope_arithmetic(query):
    res = classify_query(query)
    assert res.category == "OUT_OF_SCOPE"


@pytest.mark.parametrize(
    "query",
    [
        "solve 2x + 5 = 15",
        "can you answer math questions?",
        "what is the square root of 144?",
        "can you solve my math homework",
        "what is the derivative of x^2",
    ],
)
def test_math_out_of_scope_keywords(query):
    res = classify_query(query)
    assert res.category == "OUT_OF_SCOPE"


@pytest.mark.parametrize(
    "query",
    [
        "Do I need SPM credit in mathematics for Computer Science?",
        "What is the passing mark for BCS3114?",
        "How many credits for Bachelor of Computer Science?",
        "What are the admission requirements for mathematics in engineering?",
    ],
)
def test_campus_queries_with_math_preserved(query):
    res = classify_query(query)
    assert res.category == "UNIVERSITY_INFO"


@pytest.mark.parametrize(
    "query",
    [
        "what are the programmes",
        "what courses are available",
        "list the programmes",
        "tell me about the programmes",
        "programmes and courses",
        "what can i study",
    ],
)
def test_broad_academic_programme_queries(query):
    res = classify_query(query)
    assert res.category == "UNIVERSITY_INFO"
    assert res.category_hint == "ACADEMIC"
    assert res.is_broad_overview is True

