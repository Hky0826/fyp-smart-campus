import time
import pytest
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


def test_local_regex_substantive_rag():
    res = classify_query("What are the admission requirements for Computer Science?")
    assert res.category == "UNIVERSITY_INFO"


def test_local_regex_unclear():
    res = classify_query("fees")
    assert res.category == "UNCLEAR"
    assert res.clarification_question is not None
