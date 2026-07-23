"""Qt state-machine controller for the native access-control GUI."""

from __future__ import annotations

import datetime as dt
import os
from typing import Any, Callable

from PySide6.QtCore import QObject, Property, QTimer, QThread, Signal, Slot

from .api_client import KioskApiClient
from .camera_controller import CameraController
from .chatbot_controller import ChatbotController
from .presence_controller import PresenceController


CAMERA_FRAME_INTERVAL_MS = int(os.getenv("EDGE_GUI_CAMERA_FRAME_INTERVAL_MS", "33"))
ACCESS_RESULT_HOLD_MS = int(os.getenv("EDGE_GUI_ACCESS_RESULT_HOLD_MS", "4000"))
CHAT_VERIFY_RETRY_MS = int(os.getenv("EDGE_GUI_CHAT_VERIFY_RETRY_MS", "350"))


class _ApiCallWorker(QThread):
    success = Signal(str, dict)
    failure = Signal(str, str, int)

    def __init__(self, name: str, func: Callable[[], dict[str, Any]]) -> None:
        super().__init__()
        self._name = name
        self._func = func

    def run(self) -> None:
        try:
            self.success.emit(self._name, self._func())
        except Exception as exc:  # pragma: no cover - runtime behavior
            status_code = int(getattr(exc, "status_code", 0) or 0)
            self.failure.emit(self._name, str(exc), status_code)


class _StateEventsWorker(QThread):
    stateReceived = Signal(dict)
    errorOccurred = Signal(str)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._running = False

    def run(self) -> None:
        self._running = True
        try:
            for state in self._api.stream_states():
                if not self._running:
                    break
                self.stateReceived.emit(state)
        except Exception as exc:  # pragma: no cover - runtime behavior
            if self._running:
                self.errorOccurred.emit(str(exc))

    def stop(self) -> None:
        self._running = False


class AccessController(QObject):
    stateChanged = Signal()
    modeChanged = Signal()
    uiChanged = Signal()
    statusChanged = Signal()
    messagesChanged = Signal()

    def __init__(
        self,
        api: KioskApiClient,
        camera: CameraController,
        chatbot: ChatbotController,
    ) -> None:
        super().__init__()
        self._api = api
        self._camera = camera
        self._chatbot = chatbot
        self._presence = PresenceController(api)
        self._state: dict[str, Any] | None = None
        self._mode = "offline"
        self._offline = False
        self._chat_expanded = False
        self._chat_verification_active = False
        self._frame_in_flight = False
        self._face_boxes: list[list[int]] = []
        self._camera_error = ""
        self._chat_error = ""
        self._now_ms = _now_ms()
        self._workers: list[QThread] = []
        self._events_worker: _StateEventsWorker | None = None

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(CAMERA_FRAME_INTERVAL_MS)
        self._frame_timer.timeout.connect(self._process_frame)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(self.refreshState)

        self._chatbot.responseReceived.connect(self._on_audio_response)
        self._chatbot.errorChanged.connect(self._on_chatbot_error)

        try:
            from access_control.audio_io.access_feedback import AccessFeedbackPlayer
            self._access_feedback: AccessFeedbackPlayer | None = AccessFeedbackPlayer()
            self.modeChanged.connect(self._play_access_feedback)
        except Exception:
            self._access_feedback = None

    @Slot()
    def start(self) -> None:
        self.refreshState()
        self._start_events()
        self._tick_timer.start()
        self._frame_timer.start()
        self._refresh_timer.start()

    @Slot()
    def stop(self) -> None:
        self._chatbot.shutdown()
        if self._events_worker:
            if self._events_worker.isRunning():
                self._events_worker.stop()
                self._events_worker.wait(1000)
            self._events_worker = None

    @Slot()
    def refreshState(self) -> None:
        self._run_worker("state", self._api.get_state)

    @Slot()
    def openChat(self) -> None:
        self._set_chat_expanded(True)
        if not self._session and not self._chat_verification_active:
            self.startChatVerification()

    @Slot()
    def startChatVerification(self) -> None:
        self._chat_error = ""
        self._camera_error = ""
        self._set_chat_verification_active(True)
        self._chatbot.stopVoiceLoop()
        self._run_worker("stop-chat-audio", self._api.stop_chat_audio)
        self._emit_all()
        self._schedule_frame(0)

    @Slot()
    def exitChat(self) -> None:
        self._chatbot.stopVoiceLoop()
        self._set_chat_expanded(False)
        self._set_chat_verification_active(False)
        self._run_worker("end-chat", self._api.end_chat)
        if self._state:
            self._state = {**self._state, "active_chat_session": None, "chat_recoverable": False}
            self._emit_all()

    @Slot(str)
    def sendMessage(self, query: str) -> None:
        cleaned = query.strip()
        if not cleaned:
            return
        self._chat_error = ""
        self.uiChanged.emit()
        self._run_worker("chat-message", lambda: self._api.send_chat_message(cleaned))

    @Slot()
    def lockChat(self) -> None:
        self._run_worker("lock-chat", self._api.lock_chat)

    @Slot()
    def toggleMute(self) -> None:
        self._chatbot.toggleMute()
        self._sync_voice_loop()
        self.uiChanged.emit()

    @Slot()
    def _process_frame(self) -> None:
        if self._frame_in_flight or self._offline or not self._camera.ready:
            return
        frame = self._camera.latest_jpeg()
        if not frame:
            return

        self._frame_in_flight = True
        if self._chat_verification_active:
            self._run_worker("chat-verify-frame", lambda: self._api.verify_chat_owner_frame(frame))
            return

        if self._session:
            self._run_worker("chat-presence-frame", lambda: self._presence.verify_owner_presence(frame))
            return

        self._run_worker("access-frame", lambda: self._api.verify_access_frame(frame))

    @Slot()
    def _on_tick(self) -> None:
        self._now_ms = _now_ms()
        self._update_mode()

    def _start_events(self) -> None:
        if self._events_worker and self._events_worker.isRunning():
            return
        worker = _StateEventsWorker(self._api)
        worker.stateReceived.connect(self._on_state_event)
        worker.errorOccurred.connect(self._on_event_error)
        worker.finished.connect(lambda: self._cleanup_events_worker(worker))
        self._events_worker = worker
        worker.start()

    def _run_worker(self, name: str, func: Callable[[], dict[str, Any]]) -> None:
        worker = _ApiCallWorker(name, func)
        worker.success.connect(self._on_worker_success)
        worker.failure.connect(self._on_worker_failure)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    @Slot(dict)
    def _on_state_event(self, state: dict[str, Any]) -> None:
        self._offline = False
        self._state = state
        self._emit_all()
        self._sync_voice_loop()

    @Slot(str)
    def _on_event_error(self, _message: str) -> None:
        self._offline = True
        self._update_mode()
        self.statusChanged.emit()

    @Slot(str, dict)
    def _on_worker_success(self, name: str, payload: dict[str, Any]) -> None:
        launched_followup_frame = False
        try:
            self._offline = False
            if name == "state":
                self._state = payload
            elif name in {"access-frame"}:
                self._merge_access_attempt(payload.get("attempt"))
                self._face_boxes = _boxes_from_attempt(payload.get("attempt"))
            elif name == "chat-verify-frame":
                self._merge_chat_session(payload.get("session"))
                self._face_boxes = _coerce_boxes(payload.get("bboxes"))
                self._set_chat_verification_active(False)
                self._chat_error = ""
            elif name == "chat-presence-frame":
                launched_followup_frame = self._handle_presence_payload(payload)
            elif name in {"chat-message", "chat-audio"}:
                self._merge_chat_session(payload.get("session"))
                self._chat_error = ""
            elif name == "lock-chat":
                self._merge_chat_session(payload.get("session"))
            elif name == "end-chat":
                if self._state:
                    self._state = {**self._state, "active_chat_session": None, "chat_recoverable": False}
            self._camera_error = "" if name.endswith("frame") else self._camera_error
        finally:
            if name.endswith("frame") and not launched_followup_frame:
                self._frame_in_flight = False
            self._emit_all()
            self._sync_voice_loop()
            if name == "access-frame" and self._chat_verification_active:
                self._schedule_frame(0)

    @Slot(str, str, int)
    def _on_worker_failure(self, name: str, message: str, _status_code: int) -> None:
        retry_chat_verification = False
        if name == "state":
            self._offline = True
        elif name == "chat-verify-frame":
            if _status_code == 401 and self._chat_expanded:
                self._chat_error = ""
                self._set_chat_verification_active(True)
                retry_chat_verification = True
            else:
                self._chat_error = message or "Face verification failed."
                self._set_chat_verification_active(False)
        elif name in {"chat-message", "chat-audio", "lock-chat"}:
            self._chat_error = message or "Chatbot request failed."
        elif name.endswith("frame"):
            self._camera_error = message or "Frame processing failed."
        if name.endswith("frame"):
            self._frame_in_flight = False
        self._emit_all()
        self._sync_voice_loop()
        if retry_chat_verification:
            self._schedule_frame(CHAT_VERIFY_RETRY_MS)

    def _handle_presence_payload(self, payload: dict[str, Any]) -> bool:
        self._face_boxes = _coerce_boxes(payload.get("bboxes"))
        if payload.get("ended"):
            if self._state:
                self._state = {**self._state, "active_chat_session": None, "chat_recoverable": False}
            self._set_chat_expanded(False)
            self._chat_error = ""
            self._chatbot.stopVoiceLoop()
            return False
        if payload.get("session"):
            self._merge_chat_session(payload.get("session"))
        if not payload.get("owner_present"):
            frame = self._camera.latest_jpeg()
            if frame:
                self._run_worker("access-frame", lambda: self._api.verify_access_frame(frame))
                return True
        return False

    @Slot(dict)
    def _on_audio_response(self, payload: dict[str, Any]) -> None:
        self._on_worker_success("chat-audio", payload)

    @Slot()
    def _on_chatbot_error(self) -> None:
        if self._chatbot.error:
            self._chat_error = self._chatbot.error
            self.uiChanged.emit()

    def _merge_access_attempt(self, attempt: dict[str, Any] | None) -> None:
        if not self._state or not attempt:
            return
        self._state = {**self._state, "active_access_attempt": attempt}

    def _merge_chat_session(self, session: dict[str, Any] | None) -> None:
        if not self._state or not session:
            return
        self._state = {**self._state, "active_chat_session": session, "chat_recoverable": False}

    def _sync_voice_loop(self) -> None:
        should_run = bool(self._chat_expanded and self._session and not self._chat_verification_active)
        if should_run:
            self._chatbot.startVoiceLoop()
        else:
            self._chatbot.stopVoiceLoop()

    def _cleanup_worker(self, worker: QThread) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _cleanup_events_worker(self, worker: _StateEventsWorker) -> None:
        if self._events_worker is worker:
            self._events_worker = None
        worker.deleteLater()

    def _schedule_frame(self, delay_ms: int) -> None:
        QTimer.singleShot(max(0, delay_ms), self._process_frame)

    def _set_chat_expanded(self, value: bool) -> None:
        if self._chat_expanded == value:
            return
        self._chat_expanded = value
        self.uiChanged.emit()

    def _set_chat_verification_active(self, value: bool) -> None:
        if self._chat_verification_active == value:
            return
        self._chat_verification_active = value
        self.uiChanged.emit()
        self._update_mode()

    def _emit_all(self) -> None:
        self.stateChanged.emit()
        self.uiChanged.emit()
        self.statusChanged.emit()
        self.messagesChanged.emit()
        self._update_mode()

    def _update_mode(self) -> None:
        mode = self._derive_mode()
        if mode == self._mode:
            return
        self._mode = mode
        self.modeChanged.emit()

    @Slot()
    def _play_access_feedback(self) -> None:
        if self._chat_expanded or self._session or self._chat_verification_active:
            return
        if self._access_feedback:
            self._access_feedback.play_for_mode(self._mode)

    def _derive_mode(self) -> str:
        if self._offline or not self._state:
            return "offline"
        if self._chat_verification_active:
            return "chat-verifying"

        attempt = self._attempt
        if attempt and not attempt.get("completed_at"):
            return "access-verifying"
        if attempt and int(attempt.get("face_count") or 0) > 0 and self._is_recent_attempt(attempt):
            if attempt.get("access_decision") == "GRANTED":
                return "access-granted"
            reason = str(attempt.get("reason") or "")
            face_count = int(attempt.get("face_count") or 0)
            if face_count > 1 or "multiple" in reason.lower() or "only one person" in reason.lower():
                return "only-one-person"
            return "access-denied"

        session = self._session
        if session and session.get("locked"):
            return "chat-locked"
        if session:
            return "chat-active"
        return "idle"

    def _is_recent_attempt(self, attempt: dict[str, Any]) -> bool:
        completed = _parse_datetime(attempt.get("completed_at"))
        if completed is None:
            return False
        hold_seconds = self._timings.get("access_result_hold_seconds") or ACCESS_RESULT_HOLD_MS / 1000
        return self._now_ms - int(completed.timestamp() * 1000) <= int(float(hold_seconds) * 1000)

    @property
    def _session(self) -> dict[str, Any] | None:
        return (self._state or {}).get("active_chat_session")

    @property
    def _attempt(self) -> dict[str, Any] | None:
        return (self._state or {}).get("active_access_attempt")

    @property
    def _device(self) -> dict[str, Any]:
        return (self._state or {}).get("device") or {}

    @property
    def _timings(self) -> dict[str, Any]:
        return (self._state or {}).get("timings") or {}

    def _get_mode(self) -> str:
        return self._mode

    def _get_offline(self) -> bool:
        return self._offline or not self._state

    def _get_chat_expanded(self) -> bool:
        return self._chat_expanded

    def _get_chat_verification_active(self) -> bool:
        return self._chat_verification_active

    def _get_chat_camera_minimized(self) -> bool:
        return bool(self._chat_expanded)

    def _get_face_boxes(self) -> list:
        return self._face_boxes

    def _get_messages(self) -> list:
        session = self._session
        if not session or session.get("locked"):
            return []
        return session.get("conversation_history") or []

    def _get_session_name(self) -> str:
        session = self._session or {}
        return str(session.get("full_name") or session.get("email") or "Visitor")

    def _get_presence_state(self) -> str:
        session = self._session or {}
        return str(session.get("presence_state") or "UNKNOWN")

    def _get_access_title(self) -> str:
        if self._mode == "access-granted":
            return "Access granted"
        if self._mode in {"access-denied", "only-one-person"}:
            return "Access denied"
        if self._mode == "access-verifying":
            return "Verifying access"
        if self._mode == "chat-verifying":
            return "Verify chatbot owner"
        return "Face the camera"

    def _get_access_subtitle(self) -> str:
        attempt = self._attempt or {}
        if self._mode == "access-granted":
            return "Door access has priority over chatbot interaction."
        if self._mode == "only-one-person":
            return "Only one person can be in the frame."
        if self._mode == "access-denied":
            reason = str(attempt.get("reason") or "Access was denied.")
            if int(attempt.get("face_count") or 0) > 1 or "multiple" in reason.lower() or "one" in reason.lower():
                return "Only one person can be in the frame."
            return reason
        if self._mode == "chat-verifying":
            return "Keep your face inside the guide to start a private chatbot session."
        if self._mode == "access-verifying":
            return "Checking identity and RBAC permissions."
        if self._mode == "chat-active":
            return f"Chat session: {self._get_session_name()}"
        return "Stand centered for access verification."

    def _get_camera_error(self) -> str:
        return self._camera_error or self._camera.error

    def _get_chat_error(self) -> str:
        return self._chat_error

    def _get_device_id(self) -> str:
        return str(self._device.get("device_id") or "")

    def _get_device_name(self) -> str:
        return str(self._device.get("device_name") or "")

    def _get_cloud_sync(self) -> str:
        return str(self._device.get("cloud_sync") or "unknown")

    def _get_cloud_chatbot(self) -> str:
        return str(self._device.get("cloud_chatbot") or "unknown")

    mode = Property(str, _get_mode, notify=modeChanged)
    offline = Property(bool, _get_offline, notify=statusChanged)
    chatExpanded = Property(bool, _get_chat_expanded, notify=uiChanged)
    chatVerificationActive = Property(bool, _get_chat_verification_active, notify=uiChanged)
    chatCameraMinimized = Property(bool, _get_chat_camera_minimized, notify=uiChanged)
    faceBoxes = Property("QVariantList", _get_face_boxes, notify=uiChanged)
    messages = Property("QVariantList", _get_messages, notify=messagesChanged)
    sessionName = Property(str, _get_session_name, notify=stateChanged)
    presenceState = Property(str, _get_presence_state, notify=stateChanged)
    accessTitle = Property(str, _get_access_title, notify=modeChanged)
    accessSubtitle = Property(str, _get_access_subtitle, notify=modeChanged)
    cameraError = Property(str, _get_camera_error, notify=uiChanged)
    chatError = Property(str, _get_chat_error, notify=uiChanged)
    deviceId = Property(str, _get_device_id, notify=statusChanged)
    deviceName = Property(str, _get_device_name, notify=statusChanged)
    cloudSync = Property(str, _get_cloud_sync, notify=statusChanged)
    cloudChatbot = Property(str, _get_cloud_chatbot, notify=statusChanged)


def _now_ms() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)


def _parse_datetime(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError:
        return None


def _coerce_boxes(value: Any) -> list[list[int]]:
    boxes: list[list[int]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, list) and len(item) >= 4:
                try:
                    boxes.append([int(item[0]), int(item[1]), int(item[2]), int(item[3])])
                except (TypeError, ValueError):
                    continue
    return boxes


def _boxes_from_attempt(attempt: dict[str, Any] | None) -> list[list[int]]:
    if not attempt:
        return []
    boxes = _coerce_boxes(attempt.get("bboxes"))
    if boxes:
        return boxes
    return _coerce_boxes([attempt.get("bbox")])
