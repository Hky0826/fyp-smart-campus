"""
Pydantic schemas for RAG Chatbot request and response validation.
"""

from __future__ import annotations

import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """
    Request body sent by the edge device (or any API consumer) to the
    cloud chatbot endpoint.
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's natural-language question.",
    )
    # Device ID is informational for audit logging only; role is never
    # resolved from this field. Missing JWT uses visitor/PUBLIC access;
    # authenticated access comes from the trusted JWT.
    device_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Edge device identifier for audit logging.",
    )
    session_id: Optional[int] = Field(
        None,
        description=(
            "The JWT session_id from jwt_sessions. "
            "Used to associate the query with an existing session."
        ),
    )


class CitationSchema(BaseModel):
    """A single document chunk cited in the chatbot response."""

    chunk_id: int
    document_id: int
    document_title: str
    chunk_index: int
    access_level: str
    excerpt: str = Field(description="A short excerpt (first 200 chars) of the chunk text.")

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    """
    Response returned by the cloud chatbot endpoint to the edge device.
    """

    answer: str = Field(description="The LLM-generated answer based on authorized context.")
    citations: List[CitationSchema] = Field(
        default_factory=list,
        description="Document chunks used to generate the answer.",
    )
    access_granted: bool = Field(
        description="Whether the user had access to any relevant documents."
    )
    # Human-readable status shown to the user when access is restricted
    status_message: Optional[str] = Field(
        None, description="Set when access is denied or retrieval is empty."
    )
    response_time_ms: Optional[int] = Field(
        None, description="Server-side response latency in milliseconds."
    )
    query_id: Optional[int] = Field(
        None, description="Audit log ID stored in chatbot_queries."
    )


class IngestionRequest(BaseModel):
    """Request body for triggering document ingestion/re-indexing."""

    document_id: int = Field(description="ID of an existing uploaded_document to (re-)index.")
    force_reindex: bool = Field(
        False, description="If True, existing embeddings are deleted and regenerated."
    )


class IngestionResponse(BaseModel):
    """Response from the ingestion endpoint."""

    document_id: int
    chunks_created: int
    embeddings_created: int
    skipped: int
    message: str


class HealthResponse(BaseModel):
    """Simple health-check payload."""

    status: str
    google_api_configured: bool
    timestamp: datetime.datetime


class AudioChatResponse(BaseModel):
    """
    Response returned by the cloud audio chatbot endpoint to the edge device.

    Contains optional text and/or audio response, sources, and access status.
    """

    text_response: Optional[str] = None
    audio_response: Optional[str] = Field(
        None, description="Base64-encoded PCM audio data."
    )
    sources: List[CitationSchema] = Field(
        default_factory=list,
        description="Document chunks used to generate the response.",
    )
    status: str = Field(
        "error",
        description=(
            "One of: ok | blocked | no_access | error | auth_required | "
            "validation_failed"
        ),
    )
    access_granted: bool = False
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = Field(
        None, description="Server-side response latency in milliseconds."
    )
    query_id: Optional[int] = Field(
        None, description="Audit log ID stored in chatbot_queries."
    )


class ExtractedQuery(BaseModel):
    """
    Structured query extracted from raw audio by the audio query extractor.
    """

    user_query: str = Field(description="The extracted spoken request text.")
    detected_language: str = Field(
        "en", description="Detected language code (e.g. 'en', 'zh')."
    )
    possible_prompt_injection: bool = Field(
        False,
        description="True if the audio may contain a prompt injection attempt.",
    )
    unsafe_instruction_summary: Optional[str] = Field(
        None,
        description="If injection is suspected, a summary of the unsafe instruction.",
    )
