"""
Configuration for the RAG Chatbot module.

Loads settings from the shared backend .env file. The Google AI Studio API key
is stored here and NEVER exposed to the edge device or the frontend.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Resolve path to the shared backend .env file.
# __file__ is at  cloud/RagChatbot/config.py
#   parents[0]  = cloud/RagChatbot/
#   parents[1]  = cloud/
# So the .env is at  cloud/dashboard/backend/.env  -> parents[1] / dashboard / backend / .env
_DOTENV_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "backend" / ".env"
load_dotenv(dotenv_path=_DOTENV_PATH)


class RagSettings:
    """
    Central configuration object for the RAG Chatbot.
    All values are loaded from environment variables (set in .env).
    """

    # ── Google AI Studio ──────────────────────────────────────────────────────
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    EMBEDDING_MODEL: str = os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-2")
    EMBEDDING_DIM: int = int(os.getenv("RAG_EMBEDDING_DIM", "3072"))
    # Primary LLM used by both the audio Live-API path and the migrated text path.
    LLM_MODEL: str = os.getenv("RAG_LLM_MODEL", "gemini-3.1-flash-live-preview")

    # ── Audio pipeline ────────────────────────────────────────────────────────
    # One-shot model used to extract a structured query from raw audio.
    AUDIO_EXTRACTION_MODEL: str = os.getenv(
        "RAG_AUDIO_EXTRACTION_MODEL", "gemini-3.1-flash-lite"
    )
    # Model used for the TTS fallback when the Live-API audio response is invalid.
    AUDIO_TTS_FALLBACK_MODEL: str = os.getenv(
        "RAG_AUDIO_TTS_FALLBACK_MODEL", "gemini-2.5-flash"
    )
    # Whether to enforce the structured response_schema on audio query extraction.
    AUDIO_EXTRACTION_SCHEMA_ENABLED: bool = os.getenv(
        "RAG_AUDIO_EXTRACTION_SCHEMA_ENABLED", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    # Whether the TTS fallback is enabled when Live-API audio is invalid.
    AUDIO_TTS_FALLBACK_ENABLED: bool = os.getenv(
        "RAG_AUDIO_TTS_FALLBACK_ENABLED", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}

    # ── Live-API session settings ─────────────────────────────────────────────
    # Comma-separated modalities requested from the Live-API session.
    # NOTE: Currently reserved for future use; the live service hardcodes
    # response_modalities=["TEXT", "AUDIO"] directly.
    LIVE_RESPONSE_MODALITIES: str = os.getenv(
        "RAG_LIVE_RESPONSE_MODALITIES", "AUDIO,TEXT"
    )
    # Sample rate (Hz) for audio sent to the Live-API session.
    LIVE_INPUT_SAMPLE_RATE: int = int(os.getenv("RAG_LIVE_INPUT_SAMPLE_RATE", "16000"))
    # Sample rate (Hz) for audio received from the Live-API session.
    LIVE_OUTPUT_SAMPLE_RATE: int = int(os.getenv("RAG_LIVE_OUTPUT_SAMPLE_RATE", "24000"))
    # Maximum duration (seconds) before an idle Live-API session is closed.
    LIVE_SESSION_TIMEOUT_SECONDS: int = int(
        os.getenv("RAG_LIVE_SESSION_TIMEOUT_SECONDS", "60")
    )
    # Maximum allowed audio upload size in bytes (default 10 MB).
    AUDIO_MAX_UPLOAD_BYTES: int = int(os.getenv("RAG_AUDIO_MAX_UPLOAD_BYTES", "10485760"))

    # ── Retrieval ─────────────────────────────────────────────────────────────
    # Maximum number of chunks returned from vector search before re-ranking
    TOP_K_RETRIEVAL: int = int(os.getenv("RAG_TOP_K_RETRIEVAL", "10"))
    # Number of chunks sent to the LLM as context after re-ranking
    TOP_K_CONTEXT: int = int(os.getenv("RAG_TOP_K_CONTEXT", "5"))

    # ── Generation ────────────────────────────────────────────────────────────
    MAX_OUTPUT_TOKENS: int = int(os.getenv("RAG_MAX_OUTPUT_TOKENS", "1024"))
    TEMPERATURE: float = float(os.getenv("RAG_TEMPERATURE", "0.2"))

    # ── Security ──────────────────────────────────────────────────────────────
    # Maximum character length for a user query (guards against large injections)
    MAX_QUERY_LENGTH: int = int(os.getenv("RAG_MAX_QUERY_LENGTH", "2000"))
    ENABLE_PUBLIC_SMOKE_TEST: bool = os.getenv("RAG_ENABLE_PUBLIC_SMOKE_TEST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # ── Database (inherited from shared settings) ─────────────────────────────
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "3306")
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "smart_campus_db")

    # ── JWT (inherited from shared settings) ──────────────────────────────────
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

    def validate(self) -> None:
        """Raise ValueError if any required setting is missing."""
        if not self.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY is not set. "
                "Add it to cloud/dashboard/backend/.env"
            )
        if not self.AUDIO_EXTRACTION_MODEL:
            raise ValueError("AUDIO_EXTRACTION_MODEL is not set in .env")
        if not self.JWT_SECRET:
            raise ValueError("JWT_SECRET is not set in .env")


rag_settings = RagSettings()
