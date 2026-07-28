"""Cost-aware audio for the post-verification chatbot greeting.

Deployments may provide three short, prerecorded PCM WAV files under
``cloud/RagChatbot/audio`` (or ``RAG_GREETING_AUDIO_DIR``):

* ``greeting_generic.wav`` - the complete visitor greeting;
* ``greeting_hi.wav`` - the spoken prefix (for example, ``Hi``);
* ``greeting_suffix.wav`` - the spoken remainder after the name.

For an authenticated user, only the given name is sent to TTS and the result
is concatenated with the two recordings. If the recordings are not installed,
the existing full-greeting TTS path remains the safe fallback.
"""

from __future__ import annotations

import os
import wave
from pathlib import Path
from typing import Optional

from RagChatbot.generation.response_validator import generate_audio_from_text


_AUDIO_DIR = Path(
    os.getenv("RAG_GREETING_AUDIO_DIR", str(Path(__file__).resolve().parents[1] / "audio"))
)
_SAMPLE_RATE = 24_000
_SAMPLE_WIDTH = 2
_CHANNELS = 1
_JOIN_SILENCE = b"\x00" * int(_SAMPLE_RATE * _SAMPLE_WIDTH * 0.08)


def _read_pcm_wav(filename: str) -> Optional[bytes]:
    path = _AUDIO_DIR / filename
    if not path.is_file():
        return None
    try:
        with wave.open(str(path), "rb") as wav_file:
            if (
                wav_file.getframerate() != _SAMPLE_RATE
                or wav_file.getsampwidth() != _SAMPLE_WIDTH
                or wav_file.getnchannels() != _CHANNELS
            ):
                return None
            return wav_file.readframes(wav_file.getnframes())
    except (OSError, wave.Error):
        return None


def generate_greeting_audio(greeting_text: str, given_name: str | None = None) -> Optional[bytes]:
    """Build greeting PCM while minimizing paid synthesis.

    With recordings installed, anonymous greetings require zero TTS calls and
    personalized greetings synthesize only the name. Without recordings this
    behaves exactly like the previous implementation.
    """
    normalized_name = " ".join((given_name or "").split())
    if not normalized_name:
        generic = _read_pcm_wav("greeting_generic.wav")
        return generic if generic is not None else generate_audio_from_text(greeting_text)

    prefix = _read_pcm_wav("greeting_hi.wav")
    suffix = _read_pcm_wav("greeting_suffix.wav")
    if prefix is None or suffix is None:
        return generate_audio_from_text(greeting_text)

    name_audio = generate_audio_from_text(normalized_name)
    if not name_audio:
        return None
    return prefix + _JOIN_SILENCE + name_audio + _JOIN_SILENCE + suffix
