"""
Streaming sentence parser for breaking LLM token output into full sentences.

Accumulates text tokens from a streaming LLM response and yields complete
sentences as soon as punctuation boundaries ('.', '?', '!', '\n') are reached,
while avoiding splitting on common abbreviations or decimal numbers.
"""

from __future__ import annotations

import re
from typing import Iterator, List

# Common abbreviations to avoid splitting on (lowercase)
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "e.g", "i.e", "etc",
    "st", "ave", "rd", "blvd", "dept", "vol", "no", "approx", "min", "max",
}

# Regex to match sentence end punctuation followed by whitespace or CJK fullwidth punctuation
_SENTENCE_END_RE = re.compile(r'([.?!]+["\'\)]*\s+|[。！？]+["\'\)]*|\n+)')


class StreamingSentenceSplitter:
    """
    Stateful buffer that receives streaming text tokens and yields completed sentences.
    """

    def __init__(self, min_sentence_length: int = 15) -> None:
        self.buffer = ""
        self.min_sentence_length = min_sentence_length

    def feed(self, chunk: str) -> Iterator[str]:
        """
        Feed a chunk/token of text into the splitter. Yields completed sentences.
        """
        if not chunk:
            return

        self.buffer += chunk

        while True:
            match = _SENTENCE_END_RE.search(self.buffer)
            if not match:
                break

            end_pos = match.end()
            candidate = self.buffer[:end_pos].strip()
            delimiter = match.group(1)

            # Check if this match is an abbreviation or decimal number
            if self._is_abbreviation_or_number(self.buffer[:match.start(1) + 1]):
                # Skip this match, search further
                next_search_start = match.start(1) + 1
                sub_match = _SENTENCE_END_RE.search(self.buffer[next_search_start:])
                if not sub_match:
                    break
                end_pos = next_search_start + sub_match.end()
                candidate = self.buffer[:end_pos].strip()
                delimiter = sub_match.group(1)

            # Check minimum sentence length to prevent tiny fragments
            # unless it's a newline separator
            if len(candidate) < self.min_sentence_length and "\n" not in delimiter:
                break

            if candidate:
                yield candidate
            self.buffer = self.buffer[end_pos:]

    def flush(self) -> Iterator[str]:
        """
        Flush any remaining text in the buffer as the final sentence.
        """
        remaining = self.buffer.strip()
        self.buffer = ""
        if remaining:
            yield remaining

    def _is_abbreviation_or_number(self, text_up_to_dot: str) -> bool:
        """
        Check if the period at the end of text_up_to_dot is part of an abbreviation or number.
        """
        if not text_up_to_dot.endswith("."):
            return False

        words = text_up_to_dot[:-1].split()
        if not words:
            return False

        last_word = words[-1].lower()

        # Check if last word is a known abbreviation
        if last_word in _ABBREVIATIONS:
            return True

        # Check if last word is a single uppercase letter (e.g. "John D.")
        if len(last_word) == 1 and last_word.isalpha():
            return True

        # Check if digit precedes and succeeds the dot (e.g. "3.1")
        if text_up_to_dot[-2:-1].isdigit():
            return True

        return False
