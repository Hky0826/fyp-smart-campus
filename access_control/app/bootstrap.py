"""Construct every standalone component once and own its lifecycle."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from time import monotonic

from .access_control import GPIOAccessController, MockAccessController
from .api.state import KioskStateStore
from .api.schemas import KioskTimingConfig
from .authentication import AuthenticationPolicy, AuthenticationService, IdentityVerificationService, VerificationPolicy
from .chatbot import ChatbotClient, EdgeAuthTokenClient
from .config import AppConfig
from .database import SQLiteIdentityRepository
from .detection import YuNetDetector
from .domain import FramePacket
from .processing import DetectionScheduler, RealTimeAccessPipeline
from .quality import FaceQualityConfig, FaceQualityEvaluator
from .recognition import SFaceRecognizer
from .services import BiometricWorker
from .synchronization import BackgroundDatabaseSyncService, SyncConfig
from .tracking.kcf import KCFTracker
from .tracking.validation import TrackerValidationConfig
from .utilities import RuntimeMetrics


@dataclass
class AppRuntime:
    config: AppConfig
    repository: object
    detector: object
    recognizer: object
    quality: object
    access_controller: object
    authentication: object
    identity_verifier: object
    worker: object
    pipeline: object
    metrics: object
    sync: object
    chatbot: object
    token_client: object
    kiosk: object

    def __post_init__(self):
        self._frame_lock = threading.Lock()
        self._frame_id = 0
        self._started = False
        self._last_access_frame_at = None

    def start(self):
        if self._started:
            return
        self.pipeline.start()
        self.sync.start()
        self._started = True

    def stop(self):
        if not self._started:
            return
        self.sync.stop()
        self.pipeline.stop()
        close = getattr(self.access_controller, 'close', None)
        if close:
            close()
        self._started = False
        self._last_access_frame_at = None

    def packet(self, image):
        with self._frame_lock:
            self._frame_id += 1
            frame_id = self._frame_id
        return FramePacket.create(frame_id, image)

    def process_access(self, image):
        return self.pipeline.process(self.packet(image))

    def biometric_command(self, image, mode, payload=None, timeout=10):
        self.start()
        return self.worker.request(mode, self.packet(image), payload, timeout)


def build_runtime(config=None):
    config = config or AppConfig()
    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO), format='%(asctime)s %(levelname)s %(name)s %(message)s')
    repository = SQLiteIdentityRepository(config.database_path)
    detector = YuNetDetector(config.yunet_model, (config.width, config.height), config.yunet_confidence, config.yunet_nms, config.min_face_size)
    recognizer = SFaceRecognizer(config.sface_model)
    quality = FaceQualityEvaluator(FaceQualityConfig(
        min_confidence=config.yunet_confidence,
        min_width=config.min_face_size,
        min_height=config.min_face_size,
        min_sharpness=config.quality_min_sharpness,
        min_brightness=config.quality_min_brightness,
        max_brightness=config.quality_max_brightness,
    ))
    access = GPIOAccessController(config.gpio_pin, config.gpio_active_high) if config.hardware_mode == 'gpio' else MockAccessController()
    auth = AuthenticationService(recognizer, quality, repository, access, AuthenticationPolicy(config.sface_threshold, config.confirmations, config.max_result_age_seconds, config.unlock_seconds, config.cooldown_seconds, config.max_faces, config.max_similarity_drop))
    verifier = IdentityVerificationService(recognizer, quality, repository, VerificationPolicy(config.sface_threshold, config.confirmations, config.max_result_age_seconds, config.max_faces))
    worker = BiometricWorker(detector, auth, verifier)
    tracker = KCFTracker()
    scheduler = DetectionScheduler(config.detector_interval, config.max_tracker_age)
    validation = TrackerValidationConfig(config.tracker_area_change, config.tracker_width_change, config.tracker_height_change, config.tracker_aspect_change, config.tracker_position_change, config.max_tracker_age)
    metrics = RuntimeMetrics(config.debug_metrics)
    pipeline = RealTimeAccessPipeline(worker, tracker, scheduler, validation, metrics)
    sync = BackgroundDatabaseSyncService(repository, SyncConfig(config.cloud_url, config.device_id, config.device_name, config.local_ip, config.api_port, config.sync_interval, config.sync_interval, 30, config.offline_retry_max))
    chatbot = ChatbotClient(config.cloud_url)
    tokens = EdgeAuthTokenClient(config.cloud_url, config.device_id)
    kiosk = KioskStateStore(config.device_id, config.device_name, config.cloud_url, KioskTimingConfig(owner_missing_grace_seconds=config.owner_missing_grace_seconds,owner_absent_lock_seconds=config.owner_lock_seconds,owner_absent_terminate_seconds=config.owner_terminate_seconds,access_result_hold_seconds=round(config.granted_display_seconds)))
    return AppRuntime(config, repository, detector, recognizer, quality, access, auth, verifier, worker, pipeline, metrics, sync, chatbot, tokens, kiosk)
