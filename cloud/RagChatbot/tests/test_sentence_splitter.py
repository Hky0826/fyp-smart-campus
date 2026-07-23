"""
Unit tests for StreamingSentenceSplitter.
"""

from __future__ import annotations

import pytest
from RagChatbot.generation.sentence_splitter import StreamingSentenceSplitter


class TestStreamingSentenceSplitter:
    """Test suite for sentence boundary splitting on streamed tokens."""

    def test_single_sentence(self):
        splitter = StreamingSentenceSplitter(min_sentence_length=5)
        tokens = ["The ", "library ", "is ", "open ", "until ", "10 ", "PM. "]
        sentences = []
        for token in tokens:
            sentences.extend(list(splitter.feed(token)))
        sentences.extend(list(splitter.flush()))

        assert len(sentences) == 1
        assert sentences[0] == "The library is open until 10 PM."

    def test_multiple_sentences(self):
        splitter = StreamingSentenceSplitter(min_sentence_length=5)
        tokens = [
            "Welcome ", "to ", "the ", "campus! ",
            "The ", "library ", "is ", "on ", "the ", "second ", "floor. ",
            "Have ", "a ", "nice ", "day."
        ]
        sentences = []
        for token in tokens:
            sentences.extend(list(splitter.feed(token)))
        sentences.extend(list(splitter.flush()))

        assert len(sentences) == 3
        assert sentences[0] == "Welcome to the campus!"
        assert sentences[1] == "The library is on the second floor."
        assert sentences[2] == "Have a nice day."

    def test_abbreviations_and_decimals(self):
        splitter = StreamingSentenceSplitter(min_sentence_length=5)
        tokens = [
            "Dr. ", "Smith ", "is ", "in ", "room ", "3.1 ", "at ", "10:00 ", "a.m. ",
            "Please ", "visit ", "him."
        ]
        sentences = []
        for token in tokens:
            sentences.extend(list(splitter.feed(token)))
        sentences.extend(list(splitter.flush()))

        assert len(sentences) == 2
        assert sentences[0] == "Dr. Smith is in room 3.1 at 10:00 a.m."
        assert sentences[1] == "Please visit him."
