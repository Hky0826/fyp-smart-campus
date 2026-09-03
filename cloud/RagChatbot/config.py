"""
Configuration for the RAG Chatbot module.

Loads settings from the shared backend .env file. The Google AI Studio API key
is stored here and NEVER exposed to the edge device or the frontend.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# Resolve path to the shared backend .env file.
# __file__ is at  cloud/RagChatbot/config.py
#   parents[0]  = cloud/RagChatbot/
#   parents[1]  = cloud/
# So the .env is at  cloud/dashboard/backend/.env  -> parents[1] / dashboard / backend / .env
_DOTENV_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "backend" / ".env"
# Keep deployment-provided environment variables authoritative.  The dashboard
# backend loads the same settings with ``override=False``; overriding them here
# can make the JWT issuer and chatbot validator use different secrets after a
# restart, which turns every authenticated greeting into HTTP 401.
load_dotenv(dotenv_path=_DOTENV_PATH, override=False)


class RagSettings:
    """
    Central configuration object for the RAG Chatbot.
    All values are loaded from environment variables (set in .env).
    """

    # The Google API key for the AI Studio API. This is used for LLM and embedding calls.
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_CLOUD_STT_API_KEY: str = os.getenv("GOOGLE_CLOUD_STT_API_KEY", "")
    GOOGLE_CLOUD_TTS_API_KEY: str = os.getenv("GOOGLE_CLOUD_TTS_API_KEY", "")
    GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("GCP_PROJECT", "")).strip()
    RAG_PERSONALISATION_ENABLED: bool = os.getenv("RAG_PERSONALISATION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    RAG_ACTIVE_SEMESTER: str = os.getenv("RAG_ACTIVE_SEMESTER", "").strip()
    RAG_ACTIVE_ACADEMIC_YEAR: str = os.getenv("RAG_ACTIVE_ACADEMIC_YEAR", "").strip()
    RAG_CAMPUS_TIMEZONE: str = os.getenv("RAG_CAMPUS_TIMEZONE", "Asia/Kuala_Lumpur").strip() or "Asia/Kuala_Lumpur"
    EMBEDDING_MODEL: str = os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-2")
    EMBEDDING_DIM: int = int(os.getenv("RAG_EMBEDDING_DIM", "3072"))
    # Primary LLM used by both the audio path and the migrated text path.
    LLM_MODEL: str = os.getenv("RAG_LLM_MODEL", "gemini-3.1-flash-lite")
    # Shared structured planner.  Keep the defaults on the existing lightweight
    # model so deployments can roll this out without a new model dependency.
    PLANNER_MODEL: str = os.getenv("RAG_PLANNER_MODEL", LLM_MODEL)
    # Gemini rejects manually supplied deadlines below 10 seconds.  Keep a
    # small buffer above that provider minimum by default.
    PLANNER_TIMEOUT_SECONDS: float = float(os.getenv("RAG_PLANNER_TIMEOUT_SECONDS", "12"))
    PLANNER_CATALOG_CANDIDATE_LIMIT: int = int(os.getenv("RAG_PLANNER_CATALOG_CANDIDATE_LIMIT", "8"))

    AUDIO_STT_MODEL: str = os.getenv("RAG_AUDIO_STT_MODEL", "gemini-3.1-flash-lite")

    # One-shot model used to extract a structured query from raw audio.
    AUDIO_EXTRACTION_MODEL: str = os.getenv(
        "RAG_AUDIO_EXTRACTION_MODEL", "gemini-3.1-flash-lite"
    )
    # Model used for text-to-speech audio output.
    AUDIO_TTS_MODEL: str = os.getenv(
        "RAG_AUDIO_TTS_MODEL",
        os.getenv("RAG_AUDIO_TTS_FALLBACK_MODEL", "gemini-3.1-flash-tts-preview"),
    )
    AUDIO_TTS_VOICE: str = os.getenv("RAG_AUDIO_TTS_VOICE", "Kore")
    AUDIO_TTS_FALLBACK_MODELS: str = os.getenv(
        "RAG_AUDIO_TTS_FALLBACK_MODELS",
        "gemini-2.5-flash-preview-tts,gemini-2.5-pro-preview-tts",
    )
    # Whether to enforce the structured response_schema on audio query extraction.
    AUDIO_EXTRACTION_SCHEMA_ENABLED: bool = os.getenv(
        "RAG_AUDIO_EXTRACTION_SCHEMA_ENABLED", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    # Whether cloud TTS is enabled for audio chatbot responses.
    AUDIO_TTS_ENABLED: bool = os.getenv(
        "RAG_AUDIO_TTS_ENABLED",
        os.getenv("RAG_AUDIO_TTS_FALLBACK_ENABLED", "true"),
    ).strip().lower() in {"1", "true", "yes", "on"}
    AUDIO_TTS_TIMEOUT_SECONDS: float = float(os.getenv("RAG_AUDIO_TTS_TIMEOUT_SECONDS", "30"))
    AUDIO_TTS_WORKERS: int = int(os.getenv("RAG_AUDIO_TTS_WORKERS", "2"))

    # Live-API session settings 
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
    LIVE_ROUTING_MODEL: str = os.getenv(
        "RAG_LIVE_ROUTING_MODEL", "gemini-3.1-flash-lite"
    )
    LIVE_MODEL: str = os.getenv("RAG_LIVE_MODEL", "gemini-3.1-flash-live-preview")
    LIVE_MANUAL_ACTIVITY: bool = os.getenv("RAG_LIVE_MANUAL_ACTIVITY", "false").strip().lower() in {"1", "true", "yes", "on"}
    LIVE_THINKING_LEVEL: str = os.getenv("RAG_LIVE_THINKING_LEVEL", "low")
    LIVE_CONNECT_TIMEOUT_SECONDS: float = float(os.getenv("RAG_LIVE_CONNECT_TIMEOUT_SECONDS", "10"))
    LIVE_IO_TIMEOUT_SECONDS: float = float(os.getenv("RAG_LIVE_IO_TIMEOUT_SECONDS", "30"))
    LIVE_TURN_TIMEOUT_SECONDS: float = float(os.getenv("RAG_LIVE_TURN_TIMEOUT_SECONDS", "30"))
    LIVE_BACKEND_TIMEOUT_SECONDS: float = float(os.getenv("RAG_LIVE_BACKEND_TIMEOUT_SECONDS", "30"))

    # Retrieval 
    # Maximum number of chunks returned from vector search before re-ranking
    TOP_K_RETRIEVAL: int = int(os.getenv("RAG_TOP_K_RETRIEVAL", "10"))
    # Number of chunks sent to the LLM as context after re-ranking
    TOP_K_CONTEXT: int = int(os.getenv("RAG_TOP_K_CONTEXT", "5"))
    # Minimum similarity threshold cutoff for retrieved chunks
    RAG_SIMILARITY_THRESHOLD: float = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.50"))
    # Hybrid search settings (dense vector + BM25/lexical token matching)
    RAG_HYBRID_SEARCH_ENABLED: bool = os.getenv("RAG_HYBRID_SEARCH_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    RAG_HYBRID_DENSE_WEIGHT: float = float(os.getenv("RAG_HYBRID_DENSE_WEIGHT", "0.7"))
    RAG_HYBRID_LEXICAL_WEIGHT: float = float(os.getenv("RAG_HYBRID_LEXICAL_WEIGHT", "0.3"))
    # Structured cross-scoring reranker using lightweight Gemini Flash-Lite (disabled by default for <5ms in-memory retrieval)
    RAG_RERANKER_ENABLED: bool = os.getenv("RAG_RERANKER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    # Multi-turn conversational query rewrite/condensation
    RAG_QUERY_REWRITE_ENABLED: bool = os.getenv("RAG_QUERY_REWRITE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

    # Agentic RAG settings (All using gemini-3.1-flash-lite)
    AGENT_GRADER_MODEL: str = os.getenv("RAG_AGENT_GRADER_MODEL", "gemini-3.1-flash-lite")
    AGENT_DECOMPOSER_MODEL: str = os.getenv("RAG_AGENT_DECOMPOSER_MODEL", "gemini-3.1-flash-lite")
    AGENT_CRITIC_MODEL: str = os.getenv("RAG_AGENT_CRITIC_MODEL", "gemini-3.1-flash-lite")
    AGENT_REWRITER_MODEL: str = os.getenv("RAG_AGENT_REWRITER_MODEL", "gemini-3.1-flash-lite")
    AGENT_MAX_REWRITE_LOOPS: int = int(os.getenv("RAG_AGENT_MAX_REWRITE_LOOPS", "1"))
    AGENT_GROUNDEDNESS_CHECK_ENABLED: bool = os.getenv("RAG_AGENT_GROUNDEDNESS_CHECK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    AGENT_FAST_PATH_ENABLED: bool = os.getenv("RAG_AGENT_FAST_PATH_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    LIVE_ACOUSTIC_BRIDGE_ENABLED: bool = os.getenv("RAG_LIVE_ACOUSTIC_BRIDGE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    LIVE_IDLE_TIMEOUT_SECONDS: float = float(os.getenv("RAG_LIVE_IDLE_TIMEOUT_SECONDS", "15.0"))

    # LLM generation parameters
    MAX_OUTPUT_TOKENS: int = int(os.getenv("RAG_MAX_OUTPUT_TOKENS", "384"))
    TEMPERATURE: float = float(os.getenv("RAG_TEMPERATURE", "0.2"))

    # Caching settings
    EMBEDDING_CACHE_SIZE: int = int(os.getenv("RAG_EMBEDDING_CACHE_SIZE", "512"))
    RESPONSE_CACHE_SIZE: int = int(os.getenv("RAG_RESPONSE_CACHE_SIZE", "256"))
    RESPONSE_CACHE_TTL_SECONDS: float = float(os.getenv("RAG_RESPONSE_CACHE_TTL", "300.0"))

    # Maximum character length for a user query (guards against large injections)
    MAX_QUERY_LENGTH: int = int(os.getenv("RAG_MAX_QUERY_LENGTH", "2000"))
    ENABLE_PUBLIC_SMOKE_TEST: bool = os.getenv("RAG_ENABLE_PUBLIC_SMOKE_TEST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # Database settings
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "3306")
    DB_USER: str = os.getenv("DB_USER", "smart_campus_app")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "smart_campus_db")

    # JWT settings for session authentication
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

    # Mapping & Navigation Microservice settings
    MAPPING_MICROSERVICE_URL: str = os.getenv("MAPPING_MICROSERVICE_URL", "http://127.0.0.1:5000")
    NAVIGATION_API_KEY: str = os.getenv("NAVIGATION_API_KEY", "campus_navigation_api_key_2026")

    # Inference Timing Logging
    RAG_INFERENCE_LOG_ENABLED: bool = os.getenv("RAG_INFERENCE_LOG_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    RAG_INFERENCE_LOG_FILE: str = os.getenv("RAG_INFERENCE_LOG_FILE", str(Path.home() / ".smart-campus-cloud" / "logs" / "chatbot_inference.log")).strip()

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
        if self.RAG_PERSONALISATION_ENABLED:
            self.validate_personalisation()

    def validate_personalisation(self) -> None:
        """Validate settings that govern deterministic personal lookups."""
        try:
            ZoneInfo(self.RAG_CAMPUS_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            if self.RAG_CAMPUS_TIMEZONE == "Asia/Kuala_Lumpur":
                return
            raise ValueError(f"RAG_CAMPUS_TIMEZONE is not a valid timezone: {self.RAG_CAMPUS_TIMEZONE}") from exc
        if self.RAG_ACTIVE_SEMESTER and not re.fullmatch(r"\d{1,8}", self.RAG_ACTIVE_SEMESTER):
            raise ValueError("RAG_ACTIVE_SEMESTER must contain only 1-8 digits")
        if self.RAG_ACTIVE_ACADEMIC_YEAR and not re.fullmatch(r"\d{4}/\d{4}", self.RAG_ACTIVE_ACADEMIC_YEAR):
            raise ValueError("RAG_ACTIVE_ACADEMIC_YEAR must use the YYYY/YYYY format")

    @property
    def campus_timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.RAG_CAMPUS_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError):
            # Minimal test images may not ship tzdata; Malaysia is UTC+8.
            return timezone(timedelta(hours=8), name="Asia/Kuala_Lumpur")

    @property
    def active_term(self) -> tuple[int, str] | None:
        if not self.RAG_ACTIVE_SEMESTER or not self.RAG_ACTIVE_ACADEMIC_YEAR:
            return None
        if not re.fullmatch(r"\d{1,8}", self.RAG_ACTIVE_SEMESTER) or not re.fullmatch(r"\d{4}/\d{4}", self.RAG_ACTIVE_ACADEMIC_YEAR):
            return None
        try:
            return int(self.RAG_ACTIVE_SEMESTER), self.RAG_ACTIVE_ACADEMIC_YEAR
        except (TypeError, ValueError):
            return None

    def campus_now(self) -> datetime:
        return datetime.now(self.campus_timezone)

rag_settings = RagSettings()
