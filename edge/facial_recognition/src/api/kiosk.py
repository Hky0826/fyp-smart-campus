"""Kiosk-facing API facade for the edge access-control UI.

The browser frontend is intentionally kept as a presentation layer. This module
owns short-lived UI state, keeps chatbot JWTs server-side, and delegates face
matching, token issuance, and RAG calls to existing backend services.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import RuntimeConfig
from ..pipelines.access_audio import EdgeAuthToken, EdgeAuthTokenClient
from .chatbot_client import ChatbotClient, ChatbotClientError

try:
    import cv2
except Exception:  # pragma: no cover - depends on runtime image
    cv2 = None


logger = logging.getLogger(__name__)

PresenceState = Literal[
    "OWNER_PRESENT",
    "OWNER_TEMPORARILY_MISSING",
    "OWNER_LEFT",
    "DIFFERENT_PERSON_PRESENT",
    "UNKNOWN",
]
AccessDecision = Literal["PENDING", "VERIFYING", "GRANTED", "DENIED", "ERROR"]


class KioskTimingConfig(BaseModel):
    owner_missing_grace_seconds: int = Field(default=2)
    owner_absent_lock_seconds: int = Field(default=2)
    owner_absent_terminate_seconds: int = Field(default=2)
    access_result_hold_seconds: int = Field(default=4)


class KioskDeviceStatus(BaseModel):
    edge_api: str
    cloud_sync: str
    cloud_chatbot: str
    sync_cloud_url: str
    device_id: str
    device_name: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str
    citations: list[dict[str, Any]] = Field(default_factory=list)


class ChatSessionView(BaseModel):
    session_id: str
    authenticated_user_id: Optional[int] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    roles: list[str] = Field(default_factory=list)
    cloud_session_id: Optional[int] = None
    owner_face_track_id: Optional[str] = None
    owner_absent_since: Optional[str] = None
    last_owner_seen_at: Optional[str] = None
    last_interaction_at: str
    presence_state: PresenceState
    expires_at: Optional[str] = None
    locked: bool = False
    conversation_history: list[ChatMessage] = Field(default_factory=list)


class AccessAttemptView(BaseModel):
    attempt_id: str
    detected_user_id: Optional[int] = None
    door_id: str
    access_decision: AccessDecision
    reason: Optional[str] = None
    similarity: Optional[float] = None
    face_count: int = 0
    bbox: Optional[list[int]] = None
    bboxes: list[list[int]] = Field(default_factory=list)
    created_at: str
    completed_at: Optional[str] = None


class KioskStateResponse(BaseModel):
    device: KioskDeviceStatus
    timings: KioskTimingConfig
    active_chat_session: Optional[ChatSessionView] = None
    active_access_attempt: Optional[AccessAttemptView] = None
    chat_recoverable: bool = False


class AccessRequestResponse(BaseModel):
    attempt: AccessAttemptView


class ChatVerifyResponse(BaseModel):
    session: ChatSessionView
    bboxes: list[list[int]] = Field(default_factory=list)
    reopened: bool = False


class ChatPresenceResponse(BaseModel):
    session: Optional[ChatSessionView] = None
    owner_present: bool
    ended: bool = False
    bboxes: list[list[int]] = Field(default_factory=list)


class ChatMessageRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)


class ChatMessageResponse(BaseModel):
    session: ChatSessionView
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    access_granted: bool
    status_message: Optional[str] = None
    response_time_ms: Optional[int] = None
    query_id: Optional[int] = None


@dataclass
class _StoredChatSession:
    view: ChatSessionView
    token: EdgeAuthToken | None = None
    owner_embedding: np.ndarray | None = None
    history: list[ChatMessage] = field(default_factory=list)
    owner_absent_since: dt.datetime | None = None


class KioskStateStore:
    """Thread-safe in-memory kiosk state.

    This state is deliberately short-lived. Durable auth, RBAC, face templates,
    access logs, sync state, and chatbot audit records remain in the existing
    backend/database layers.
    """

    def __init__(self, config: RuntimeConfig, timings: KioskTimingConfig | None = None) -> None:
        self.config = config
        self.timings = timings or KioskTimingConfig()
        self._lock = threading.Lock()
        self._access_attempt: AccessAttemptView | None = None
        self._chat_session: _StoredChatSession | None = None
        self._recoverable_chat_session: _StoredChatSession | None = None

    def state(self, cloud_status: str, sync_status: str = "unknown") -> KioskStateResponse:
        with self._lock:
            return KioskStateResponse(
                device=KioskDeviceStatus(
                    edge_api="ok",
                    cloud_sync=sync_status,
                    cloud_chatbot=cloud_status,
                    sync_cloud_url=self.config.sync_cloud_url,
                    device_id=self.config.sync_device_id,
                    device_name=self.config.sync_device_name,
                ),
                timings=self.timings,
                active_chat_session=self._safe_chat_view_locked(),
                active_access_attempt=self._access_attempt,
                chat_recoverable=self._recoverable_chat_session is not None,
            )

    def start_access_attempt(self) -> AccessAttemptView:
        now = _utc_now()
        with self._lock:
            self._access_attempt = AccessAttemptView(
                attempt_id=str(uuid.uuid4()),
                door_id=self.config.sync_device_id,
                access_decision="VERIFYING",
                created_at=now,
            )
            return self._access_attempt

    def complete_access_attempt(self, result: dict[str, Any]) -> AccessAttemptView:
        now = _utc_now()
        with self._lock:
            attempt = self._access_attempt or AccessAttemptView(
                attempt_id=str(uuid.uuid4()),
                door_id=self.config.sync_device_id,
                access_decision="VERIFYING",
                created_at=now,
            )
            granted = bool(result.get("access_granted"))
            detected_user_id = _optional_int(result.get("user_id")) if granted else None
            attempt.detected_user_id = detected_user_id
            attempt.access_decision = "GRANTED" if granted else "DENIED"
            attempt.reason = None if granted else str(result.get("reason") or "Access denied")
            attempt.similarity = _optional_float(result.get("similarity"))
            attempt.face_count = int(result.get("face_count") or 0)
            attempt.bbox = _coerce_bbox(result.get("bbox"))
            attempt.bboxes = _coerce_bboxes(result.get("bboxes"), attempt.bbox)
            attempt.completed_at = now
            self._access_attempt = attempt

            if self._chat_session is not None and granted:
                chat_user_id = self._chat_session.view.authenticated_user_id
                if detected_user_id == chat_user_id:
                    self._chat_session.owner_absent_since = None
                    self._chat_session.view.owner_absent_since = None
                    self._chat_session.view.presence_state = "OWNER_PRESENT"
                    self._chat_session.view.last_owner_seen_at = now
                    self._chat_session.view.locked = False
                else:
                    self._chat_session.owner_absent_since = dt.datetime.now(dt.timezone.utc)
                    self._chat_session.view.owner_absent_since = now
                    self._chat_session.view.presence_state = "DIFFERENT_PERSON_PRESENT"
                    self._chat_session.view.locked = True

            return attempt

    def start_chat_session(
        self,
        token: EdgeAuthToken | None = None,
        full_name: str | None = None,
        owner_embedding: np.ndarray | None = None,
    ) -> ChatSessionView:
        now = _utc_now()
        view = ChatSessionView(
            session_id=str(uuid.uuid4()),
            authenticated_user_id=token.user_id if token else None,
            username=token.username if token else None,
            full_name=full_name,
            roles=list(token.roles) if token else [],
            cloud_session_id=token.session_id if token else None,
            owner_absent_since=None,
            last_owner_seen_at=now,
            last_interaction_at=now,
            presence_state="OWNER_PRESENT",
            expires_at=_format_datetime(token.expires_at) if token else None,
            locked=False,
        )
        history = [ChatMessage(role="assistant", content="Hi, how may I help you?", created_at=now)]
        with self._lock:
            self._chat_session = _StoredChatSession(
                view=view,
                token=token,
                owner_embedding=_copy_embedding(owner_embedding),
                history=history,
            )
            self._recoverable_chat_session = None
            return self._safe_chat_view_locked() or view

    def lock_chat_session(self, presence_state: PresenceState = "OWNER_TEMPORARILY_MISSING") -> ChatSessionView | None:
        with self._lock:
            if self._chat_session is None:
                return None
            now = dt.datetime.now(dt.timezone.utc)
            if self._chat_session.owner_absent_since is None:
                self._chat_session.owner_absent_since = now
                self._chat_session.view.owner_absent_since = now.isoformat()
            self._chat_session.view.presence_state = presence_state
            self._chat_session.view.locked = True
            return self._safe_chat_view_locked()

    def end_chat_session(self) -> None:
        with self._lock:
            self._chat_session = None

    def append_chat_exchange(
        self,
        user_text: str,
        answer: str,
        citations: list[dict[str, Any]],
    ) -> ChatSessionView:
        now = _utc_now()
        with self._lock:
            if self._chat_session is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active chatbot session.")
            if self._chat_session.view.locked:
                raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Chatbot session is locked.")
            self._chat_session.history.append(ChatMessage(role="user", content=user_text, created_at=now))
            self._chat_session.history.append(
                ChatMessage(role="assistant", content=answer, created_at=now, citations=citations)
            )
            self._chat_session.view.last_interaction_at = now
            self._chat_session.owner_absent_since = None
            self._chat_session.view.owner_absent_since = None
            self._chat_session.view.presence_state = "OWNER_PRESENT"
            self._chat_session.view.last_owner_seen_at = now
            return self._safe_chat_view_locked() or self._chat_session.view

    def current_token(self) -> EdgeAuthToken | None:
        with self._lock:
            if self._chat_session is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active chatbot session.")
            if self._chat_session.view.locked:
                raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Chatbot session is locked.")
            return self._chat_session.token

    def current_chat_user_id(self) -> int | None:
        with self._lock:
            if self._chat_session is None:
                return None
            return self._chat_session.view.authenticated_user_id

    def current_owner_embedding(self) -> np.ndarray | None:
        with self._lock:
            if self._chat_session is None:
                return None
            return _copy_embedding(self._chat_session.owner_embedding)

    def recoverable_owner_embedding(self) -> np.ndarray | None:
        with self._lock:
            if self._recoverable_chat_session is None:
                return None
            return _copy_embedding(self._recoverable_chat_session.owner_embedding)

    def update_owner_presence(self, owner_present: bool, bboxes: list[list[int]] | None = None) -> ChatPresenceResponse:
        now = dt.datetime.now(dt.timezone.utc)
        now_text = now.isoformat()
        frame_bboxes = bboxes or []
        with self._lock:
            if self._chat_session is None:
                return ChatPresenceResponse(owner_present=False, ended=True, bboxes=frame_bboxes)

            if owner_present:
                self._chat_session.owner_absent_since = None
                self._chat_session.view.owner_absent_since = None
                self._chat_session.view.presence_state = "OWNER_PRESENT"
                self._chat_session.view.last_owner_seen_at = now_text
                self._chat_session.view.locked = False
                return ChatPresenceResponse(
                    session=self._safe_chat_view_locked(),
                    owner_present=True,
                    ended=False,
                    bboxes=frame_bboxes,
                )

            if self._chat_session.owner_absent_since is None:
                self._chat_session.owner_absent_since = now
                self._chat_session.view.owner_absent_since = now_text

            elapsed = (now - self._chat_session.owner_absent_since).total_seconds()
            if elapsed >= self.timings.owner_absent_terminate_seconds:
                self._recoverable_chat_session = self._chat_session
                self._recoverable_chat_session.view.owner_absent_since = now_text
                self._recoverable_chat_session.view.presence_state = "OWNER_LEFT"
                self._recoverable_chat_session.view.locked = False
                self._chat_session = None
                return ChatPresenceResponse(owner_present=False, ended=True, bboxes=frame_bboxes)

            self._chat_session.view.presence_state = "OWNER_TEMPORARILY_MISSING"
            self._chat_session.view.locked = False
            return ChatPresenceResponse(
                session=self._safe_chat_view_locked(),
                owner_present=False,
                ended=False,
                bboxes=frame_bboxes,
            )

    def reopen_chat_session(self, bboxes: list[list[int]] | None = None) -> ChatPresenceResponse:
        now = dt.datetime.now(dt.timezone.utc)
        now_text = now.isoformat()
        with self._lock:
            if self._recoverable_chat_session is None:
                return ChatPresenceResponse(owner_present=False, ended=True, bboxes=bboxes or [])

            self._chat_session = self._recoverable_chat_session
            self._recoverable_chat_session = None
            self._chat_session.owner_absent_since = None
            self._chat_session.view.owner_absent_since = None
            self._chat_session.view.presence_state = "OWNER_PRESENT"
            self._chat_session.view.last_owner_seen_at = now_text
            self._chat_session.view.locked = False
            return ChatPresenceResponse(
                session=self._safe_chat_view_locked(),
                owner_present=True,
                ended=False,
                bboxes=bboxes or [],
            )

    def _safe_chat_view_locked(self) -> ChatSessionView | None:
        if self._chat_session is None:
            return None
        view = self._chat_session.view.model_copy(deep=True)
        view.conversation_history = [] if view.locked else list(self._chat_session.history)
        if view.locked:
            view.username = None
            view.full_name = None
            view.roles = []
            view.expires_at = None
        return view


def create_kiosk_router(
    *,
    runtime_config: Callable[[], RuntimeConfig],
    access_pipeline: Callable[[], Any],
    chatbot_client: Callable[[], ChatbotClient],
    sync_status: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/kiosk", tags=["Edge Kiosk UI"])
    store = KioskStateStore(runtime_config())

    @router.get("/state", response_model=KioskStateResponse)
    def get_state() -> KioskStateResponse:
        return store.state(_cloud_status(chatbot_client), _sync_status(sync_status))

    @router.get("/events")
    async def events() -> StreamingResponse:
        async def stream():
            while True:
                state = store.state(_cloud_status(chatbot_client), _sync_status(sync_status))
                yield f"event: state\ndata: {state.model_dump_json()}\n\n"
                await asyncio.sleep(2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/access/request", response_model=AccessRequestResponse)
    def request_access() -> AccessRequestResponse:
        return AccessRequestResponse(attempt=store.start_access_attempt())

    @router.post("/access/frame", response_model=AccessRequestResponse)
    async def verify_access_frame(file: UploadFile = File(...)) -> AccessRequestResponse:
        frame = await _decode_upload(file)
        try:
            result = access_pipeline().process_frame(frame)
        except Exception as exc:
            logger.exception("Kiosk access verification failed")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return AccessRequestResponse(attempt=store.complete_access_attempt(result))

    @router.post("/chat/verify/frame", response_model=ChatVerifyResponse)
    async def verify_chat_owner(file: UploadFile = File(...)) -> ChatVerifyResponse:
        frame = await _decode_upload(file)
        try:
            pipeline = access_pipeline()
            result = pipeline.describe_faces(frame, include_embeddings=True)
        except Exception as exc:
            logger.exception("Kiosk chatbot owner verification failed")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

        owner_face = _first_face_with_embedding(result)
        if owner_face is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No usable face detected.")

        owner_embedding = owner_face["embedding"]
        token = _try_issue_registered_token(pipeline, owner_embedding, runtime_config())
        return ChatVerifyResponse(
            session=store.start_chat_session(token=token, owner_embedding=owner_embedding),
            bboxes=_result_bboxes(result),
        )

    @router.post("/chat/presence/frame", response_model=ChatPresenceResponse)
    async def verify_chat_owner_presence(file: UploadFile = File(...)) -> ChatPresenceResponse:
        owner_embedding = store.current_owner_embedding()
        if owner_embedding is None:
            return ChatPresenceResponse(owner_present=False, ended=True)

        frame = await _decode_upload(file)
        try:
            owner_present, bboxes = _detect_owner_presence(access_pipeline(), frame, owner_embedding)
        except Exception as exc:
            logger.exception("Kiosk chatbot owner presence check failed")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

        return store.update_owner_presence(owner_present, bboxes)

    @router.post("/chat/reopen/frame", response_model=ChatPresenceResponse)
    async def reopen_chat_owner(file: UploadFile = File(...)) -> ChatPresenceResponse:
        owner_embedding = store.recoverable_owner_embedding()
        if owner_embedding is None:
            return ChatPresenceResponse(owner_present=False, ended=True)

        frame = await _decode_upload(file)
        try:
            owner_present, bboxes = _detect_owner_presence(access_pipeline(), frame, owner_embedding)
        except Exception as exc:
            logger.exception("Kiosk chatbot owner recovery check failed")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

        if owner_present:
            return store.reopen_chat_session(bboxes)
        return ChatPresenceResponse(owner_present=False, ended=False, bboxes=bboxes)

    @router.post("/chat/message", response_model=ChatMessageResponse)
    def send_chat_message(body: ChatMessageRequest) -> ChatMessageResponse:
        token = store.current_token()
        try:
            response = chatbot_client().chat(
                query=body.query,
                jwt_token=token.access_token if token else None,
                device_id=runtime_config().sync_device_id,
                session_id=token.session_id if token else None,
            )
        except ChatbotClientError as exc:
            status_code = exc.status_code or status.HTTP_502_BAD_GATEWAY
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

        citations = response.get("citations", [])
        session = store.append_chat_exchange(
            body.query,
            str(response.get("answer") or ""),
            citations,
        )
        return ChatMessageResponse(
            session=session,
            answer=str(response.get("answer") or ""),
            citations=citations,
            access_granted=bool(response.get("access_granted")),
            status_message=response.get("status_message"),
            response_time_ms=response.get("response_time_ms"),
            query_id=response.get("query_id"),
        )

    @router.post("/chat/lock", response_model=ChatVerifyResponse)
    def lock_chat() -> ChatVerifyResponse:
        session = store.lock_chat_session("OWNER_TEMPORARILY_MISSING")
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active chatbot session.")
        return ChatVerifyResponse(session=session)

    @router.post("/chat/end")
    def end_chat() -> dict[str, bool]:
        store.end_chat_session()
        return {"success": True}

    @router.post("/chat/audio/stop")
    def stop_chat_audio() -> dict[str, bool]:
        # Browser playback is controlled by the frontend. The endpoint exists so
        # kiosk orchestration can treat audio interruption as a backend action.
        return {"success": True}

    return router


async def _decode_upload(file: UploadFile) -> np.ndarray:
    if cv2 is None:
        raise HTTPException(status_code=500, detail="OpenCV is required to decode uploaded images")
    data = await file.read()
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image")
    return frame


def _cloud_status(chatbot_client: Callable[[], ChatbotClient]) -> str:
    try:
        result = chatbot_client().health_check()
    except Exception:
        return "unreachable"
    return str(result.get("status") or "ok")


def _sync_status(provider: Callable[[], str] | None) -> str:
    if provider is None:
        return "unknown"
    try:
        return provider()
    except Exception:
        logger.exception("Could not read kiosk sync status")
        return "unknown"


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _format_datetime(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _copy_embedding(value: np.ndarray | None) -> np.ndarray | None:
    if value is None:
        return None
    return np.asarray(value, dtype=np.float32).copy()


def _first_face_with_embedding(result: dict[str, Any]) -> dict[str, Any] | None:
    faces = result.get("faces")
    if not isinstance(faces, list):
        return None
    for face in faces:
        if isinstance(face, dict) and face.get("embedding") is not None:
            return face
    return None


def _try_issue_registered_token(pipeline: Any, owner_embedding: np.ndarray, config: RuntimeConfig) -> EdgeAuthToken | None:
    try:
        templates = pipeline.repository.load_templates()
        match = pipeline.matcher.match(
            owner_embedding,
            templates,
            threshold=pipeline.config.recognition_threshold,
            include_inactive=True,
        )
    except Exception as exc:
        logger.warning("Could not match chatbot owner against registered templates: %s", exc)
        return None

    if not match.matched or not match.is_active or match.user_id is None:
        return None

    token_client = EdgeAuthTokenClient(config.sync_cloud_url, config.sync_device_id)
    try:
        return token_client.issue_token(match.user_id)
    except Exception as exc:
        logger.warning("Chatbot token issuance failed for user_id=%s: %s", match.user_id, exc)
        return None


def _detect_owner_presence(pipeline: Any, frame: np.ndarray, owner_embedding: np.ndarray) -> tuple[bool, list[list[int]]]:
    result = pipeline.describe_faces(frame, include_embeddings=True)
    threshold = float(getattr(pipeline.config, "recognition_threshold", 0.55))
    owner_present = False
    for face in result.get("faces", []):
        if not isinstance(face, dict) or face.get("embedding") is None:
            continue
        similarity = pipeline.matcher.cosine_similarity(owner_embedding, face["embedding"])
        if similarity >= threshold:
            owner_present = True
            break
    return owner_present, _result_bboxes(result)


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        return [int(value[0]), int(value[1]), int(value[2]), int(value[3])]
    except (TypeError, ValueError):
        return None


def _coerce_bboxes(value: Any, fallback: list[int] | None = None) -> list[list[int]]:
    boxes: list[list[int]] = []
    if isinstance(value, list):
        for item in value:
            box = _coerce_bbox(item)
            if box is not None:
                boxes.append(box)
    if not boxes and fallback is not None:
        boxes.append(fallback)
    return boxes


def _result_bboxes(result: dict[str, Any]) -> list[list[int]]:
    return _coerce_bboxes(result.get("bboxes"), _coerce_bbox(result.get("bbox")))
