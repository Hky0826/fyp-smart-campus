"""Access-control pipeline using SCRFD 2.5G and ArcFace MobileFaceNet."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, List, Optional, Sequence

import numpy as np

from ..camera.camera_reader import CameraReader
from ..config import AccessControlConfig
from ..face.aggregation import EmbeddingAggregationConfig, TrackEmbeddingAggregator
from ..face.alignment import FaceAligner
from ..face.database import DeviceUserRepository
from ..face.matching import TemplateMatcher
from ..face.quality import FaceQualityChecker, FaceQualityConfig
from ..face.spoofing import MotionSpoofDetector, SpoofResult
from ..face.tracking import FaceTracker, FaceTrackerConfig
from ..face.types import AuthenticationResult, DetectedFace
from ..utils.logging import configure_logging
from ..utils.timing import StageTimer
from ..utils.visualization import close_display, show_pipeline_result
from .access_audio import AccessControlAudioCoordinator


logger = logging.getLogger(__name__)
MULTIPLE_FACE_REASON = "Only one user is allowed within the frame."
SPACE_KEY = ord(" ")
QUIT_KEY = ord("q")


class KeyboardControlListener:
    """Listen for terminal space/q controls while the camera loop is running."""

    def __init__(self, on_space: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self.on_space = on_space
        self.on_quit = on_quit
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="access-control-keyboard")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        try:
            if os.name == "nt":
                self._run_windows()
            else:
                self._run_posix()
        except Exception as exc:
            logger.info("Terminal keyboard controls are unavailable: %s", exc)

    def _handle_key(self, key: str) -> None:
        if key == " ":
            self.on_space()
        elif key.lower() == "q":
            self.on_quit()

    def _run_windows(self) -> None:
        import msvcrt

        while not self._stop_event.is_set():
            if msvcrt.kbhit():
                self._handle_key(msvcrt.getwch())
            time.sleep(0.05)

    def _run_posix(self) -> None:
        if not sys.stdin or not sys.stdin.isatty():
            raise RuntimeError("interactive terminal is not attached")

        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        original_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self._stop_event.is_set():
                readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                if readable:
                    self._handle_key(sys.stdin.read(1))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)


class AccessControlPipeline:
    def __init__(
        self,
        detector: Any,
        embedder: Any,
        repository: Any,
        config: AccessControlConfig | None = None,
        aligner: FaceAligner | None = None,
        matcher: TemplateMatcher | None = None,
        spoof_detector: Any | None = None,
        quality_checker: Any | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        tracker: FaceTracker | None = None,
        embedding_aggregator: TrackEmbeddingAggregator | None = None,
    ) -> None:
        self.config = config or AccessControlConfig()
        self.detector = detector
        self.embedder = embedder
        self.repository = repository
        self.aligner = aligner or FaceAligner()
        self.matcher = matcher or TemplateMatcher(self.config.recognition_threshold)
        self.spoof_detector = spoof_detector or MotionSpoofDetector()
        self.quality_checker = quality_checker or FaceQualityChecker(
            config=FaceQualityConfig(
                min_face_size=self.config.min_face_size,
                min_inter_eye_distance=self.config.min_inter_eye_distance,
            )
        )
        self.tracker = tracker or FaceTracker(FaceTrackerConfig(
            min_stable_frames=self.config.min_stable_frames,
            min_stable_duration_ms=self.config.min_stable_duration_ms,
            max_missed_frames=self.config.max_missed_frames,
            track_timeout_ms=self.config.track_timeout_ms,
            min_iou_for_match=self.config.min_iou_for_match,
            max_landmark_jump_ratio=self.config.max_landmark_jump_ratio,
        ))
        self.embedding_aggregator = embedding_aggregator or TrackEmbeddingAggregator(
            EmbeddingAggregationConfig(
                min_embedding_samples=self.config.min_embedding_samples,
                max_embedding_samples=self.config.max_embedding_samples,
                embedding_outlier_threshold=self.config.embedding_outlier_threshold,
                candidate_consistency_ratio=self.config.candidate_consistency_ratio,
            )
        )
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._last_recognition_finished_at: float | None = None
        self._active_track_id: int | None = None

    def process_frame(self, frame: np.ndarray, target_user_id: Optional[str] = None) -> dict:
        timer = StageTimer()
        timestamp = self._clock()
        try:
            faces = self._detect(frame)
        except Exception:
            logger.exception("Face detection failed")
            timer.total()
            return self._deny(
                "Face detection failed", 0, AuthenticationResult.SYSTEM_ERROR,
                metrics=timer.metrics, bboxes=[],
            )
        timer.mark("detection")
        tracks = self.tracker.update(faces, timestamp)
        visible_tracks = [track for track in tracks if track.visible]
        face_count = len(visible_tracks)
        bboxes = [face.xyxy_int() for face in faces]

        if face_count == 0:
            if self._active_track_id is not None and not any(
                track.track_id == self._active_track_id for track in tracks
            ):
                self._reset_active_track()
            timer.total()
            return self._deny(
                "No face detected", 0, AuthenticationResult.RETRY_NO_FACE,
                metrics=timer.metrics, bboxes=bboxes,
            )

        if face_count > 1:
            self._reset_active_track()
            timer.total()
            return self._deny(
                MULTIPLE_FACE_REASON, face_count, AuthenticationResult.DENY_MULTIPLE_FACES,
                metrics=timer.metrics, bboxes=bboxes,
            )

        track = visible_tracks[0]
        if self._active_track_id != track.track_id:
            self._reset_active_track()
            self._active_track_id = track.track_id
        face = track.as_detection(faces[0].confidence if faces else 1.0)
        bbox = face.xyxy_int()
        if not track.stable:
            timer.total()
            return self._deny(
                "Face track is not stable yet", face_count, AuthenticationResult.RETRY_UNSTABLE_TRACK,
                metrics=timer.metrics, bbox=bbox, bboxes=bboxes,
            )

        try:
            quality = self.quality_checker.check(frame, face)
            if not quality.passed:
                timer.total()
                return self._deny(
                    f"Face quality check failed: {quality.reason}",
                    face_count,
                    AuthenticationResult.RETRY_LOW_QUALITY,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                    quality=self._quality_payload(quality),
                )

            if self.config.require_liveness:
                spoof_result = self.spoof_detector.check(frame, face)
                logger.info("Access-control spoofing result: %s score=%.4f reason=%s", spoof_result.state, spoof_result.score, spoof_result.reason)
                if spoof_result.state != "live":
                    is_spoof = spoof_result.state == "spoof"
                    reason = "Spoofing/liveness check failed." if is_spoof else "Liveness check inconclusive."
                    if is_spoof:
                        self._log_event(None, "SPOOFING", spoof_result.score)
                    timer.total()
                    return self._deny(
                        reason,
                        face_count,
                        AuthenticationResult.DENY_SPOOF if is_spoof else AuthenticationResult.RETRY_UNSTABLE_TRACK,
                        spoofing_passed=False,
                        similarity=spoof_result.score,
                        metrics=timer.metrics,
                        bbox=bbox,
                        bboxes=bboxes,
                    )

            alignment = self.aligner.align(frame, face)
            if not alignment.success or alignment.aligned_face is None:
                timer.total()
                return self._deny(
                    f"Face alignment failed: {alignment.failure_reason}",
                    face_count,
                    AuthenticationResult.RETRY_ALIGNMENT,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                )
            embedding = self.embedder.embed(alignment.aligned_face)
            timer.mark("recognition")

            templates = self.repository.load_templates()
            if target_user_id is not None:
                match = self.matcher.verify(
                    embedding,
                    templates,
                    target_user_id=str(target_user_id),
                    threshold=self.config.recognition_threshold,
                    include_inactive=True,
                )
            else:
                match = self.matcher.match(
                    embedding,
                    templates,
                    threshold=self.config.recognition_threshold,
                    include_inactive=True,
                )
            candidate_id = str(match.user_id) if match.matched and match.user_id is not None else None
            self.embedding_aggregator.add_sample(
                embedding, float(quality.score), timestamp, candidate_id=candidate_id
            )
            if not self.embedding_aggregator.has_enough_samples():
                timer.mark("database_matching")
                timer.total()
                return self._deny(
                    "Collecting valid face samples",
                    face_count,
                    AuthenticationResult.RETRY_INSUFFICIENT_SAMPLES,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                    sample_count=self.embedding_aggregator.sample_count,
                    quality=self._quality_payload(quality),
                )

            consistent_candidate = self.embedding_aggregator.consistent_candidate()
            if consistent_candidate is None:
                timer.mark("database_matching")
                timer.total()
                terminal = self.embedding_aggregator.sample_count >= self.config.max_embedding_samples
                if terminal:
                    self._log_event(None, "FAILED", match.similarity)
                return self._deny(
                    "Candidate identity is not consistent across frames",
                    face_count,
                    AuthenticationResult.DENY_NO_MATCH if terminal else AuthenticationResult.RETRY_INSUFFICIENT_SAMPLES,
                    similarity=match.similarity,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                    sample_count=self.embedding_aggregator.sample_count,
                )

            aggregated_embedding = self.embedding_aggregator.get_aggregated_embedding()
            if target_user_id is not None:
                match = self.matcher.verify(
                    aggregated_embedding, templates, str(target_user_id),
                    threshold=self.config.recognition_threshold, include_inactive=True,
                )
            else:
                match = self.matcher.match(
                    aggregated_embedding, templates,
                    threshold=self.config.recognition_threshold, include_inactive=True,
                )
            timer.mark("database_matching")

            logger.info(
                "Access-control recognition result: identity=%s similarity=%.4f template=%s matched=%s",
                match.identity,
                match.similarity,
                match.matched_template,
                match.matched,
            )

            if not match.matched or str(match.user_id) != consistent_candidate:
                self._log_event(None, "FAILED", match.similarity)
                timer.total()
                return self._deny(
                    "Unknown face or low-confidence match",
                    face_count,
                    AuthenticationResult.DENY_NO_MATCH,
                    similarity=match.similarity,
                    matched_template=match.matched_template,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                )

            if not match.is_active:
                self._log_event(match.user_id, "FAILED", match.similarity)
                timer.total()
                return self._deny(
                    "Matched user is inactive",
                    face_count,
                    AuthenticationResult.DENY_NO_MATCH,
                    identity=match.identity,
                    similarity=match.similarity,
                    matched_template=match.matched_template,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                )

            self._log_event(match.user_id, "SUCCESS", match.similarity)
            timer.total()
            return {
                "success": True,
                "authentication_result": AuthenticationResult.GRANT.value,
                "mode": "access_control",
                "access_granted": True,
                "identity": match.identity,
                "user_id": match.user_id,
                "similarity": match.similarity,
                "matched_template": match.matched_template,
                "spoofing_passed": True,
                "face_count": face_count,
                "bbox": bbox,
                "bboxes": bboxes,
                "metrics": timer.metrics,
                "track_id": track.track_id,
                "sample_count": self.embedding_aggregator.sample_count,
            }
        except Exception:
            logger.exception("Access-control frame processing failed")
            timer.total()
            return self._deny(
                "Access-control processing error", face_count, AuthenticationResult.SYSTEM_ERROR,
                metrics=timer.metrics, bbox=bbox, bboxes=bboxes,
            )
        finally:
            self._mark_recognition_finished()

    def describe_faces(self, frame: np.ndarray, include_embeddings: bool = False) -> dict:
        """Return detected face boxes, optionally with embeddings, without access gating."""
        timer = StageTimer()
        faces = self._detect(frame)
        timer.mark("detection")
        descriptions: list[dict[str, Any]] = []

        for face in sorted(faces, key=lambda item: item.width() * item.height(), reverse=True):
            item: dict[str, Any] = {
                "bbox": face.xyxy_int(),
                "confidence": float(face.confidence),
            }
            if include_embeddings:
                quality = self.quality_checker.check(frame, face)
                item["quality_passed"] = quality.passed
                item["quality_reason"] = quality.reason
                if quality.passed:
                    face_image = self.aligner.extract(frame, face)
                    item["embedding"] = self.embedder.embed(face_image)
            descriptions.append(item)

        if include_embeddings:
            timer.mark("embedding")
        timer.total()
        return {
            "face_count": len(faces),
            "bboxes": [item["bbox"] for item in descriptions],
            "faces": descriptions,
            "metrics": timer.metrics,
        }

    def _wait_for_recognition_delay(self) -> None:
        delay_seconds = self.config.recognition_delay_seconds
        if delay_seconds <= 0 or self._last_recognition_finished_at is None:
            return

        remaining_seconds = delay_seconds - (self._clock() - self._last_recognition_finished_at)
        if remaining_seconds > 0:
            self._sleep(remaining_seconds)

    def _mark_recognition_finished(self) -> None:
        self._last_recognition_finished_at = self._clock()

    def _detect(self, frame: np.ndarray) -> List[DetectedFace]:
        raw_faces = self.detector.detect(frame)
        return [self._coerce_face(face) for face in raw_faces]

    @staticmethod
    def _coerce_face(face: Any) -> DetectedFace:
        if isinstance(face, DetectedFace):
            return face
        if isinstance(face, dict):
            return DetectedFace(
                bbox=face["bbox"],
                confidence=float(face.get("confidence", face.get("detection_confidence", 1.0))),
                landmarks=face.get("landmarks"),
            )
        if isinstance(face, Sequence) and len(face) >= 5:
            return DetectedFace(bbox=face[:4], confidence=float(face[4]))
        raise TypeError(f"Unsupported face detection object: {type(face)!r}")

    def _deny(
        self,
        reason: str,
        face_count: int,
        authentication_result: AuthenticationResult = AuthenticationResult.DENY_NO_MATCH,
        identity: str = "unknown",
        similarity: float = 0.0,
        matched_template: Optional[str] = None,
        spoofing_passed: bool = True,
        metrics: Optional[dict] = None,
        bbox: Optional[List[int]] = None,
        bboxes: Optional[List[List[int]]] = None,
        sample_count: int | None = None,
        quality: dict | None = None,
    ) -> dict:
        result = {
            "success": False,
            "authentication_result": authentication_result.value,
            "mode": "access_control",
            "access_granted": False,
            "reason": reason,
            "identity": identity,
            "similarity": similarity,
            "matched_template": matched_template,
            "spoofing_passed": spoofing_passed,
            "face_count": face_count,
            "metrics": metrics or {},
        }
        if bbox is not None:
            result["bbox"] = bbox
        if bboxes is not None:
            result["bboxes"] = bboxes
        if sample_count is not None:
            result["sample_count"] = sample_count
        if quality is not None:
            result["quality"] = quality
        if self._active_track_id is not None:
            result["track_id"] = self._active_track_id
        return result

    def _reset_active_track(self) -> None:
        self._active_track_id = None
        self.embedding_aggregator.reset()
        reset = getattr(self.spoof_detector, "reset", None)
        if callable(reset):
            reset()

    @staticmethod
    def _quality_payload(quality: Any) -> dict:
        return {
            "overall_score": float(getattr(quality, "overall_score", getattr(quality, "score", 0.0))),
            "failure_reasons": list(getattr(quality, "failure_reasons", [])),
        }

    def _log_event(self, user_id: Optional[str], status: str, confidence: Optional[float]) -> None:
        log_method = getattr(self.repository, "log_auth_event", None)
        if callable(log_method):
            log_method(user_id, status, confidence)


def build_pipeline(config: AccessControlConfig) -> AccessControlPipeline:
    from ..face.detection import HailoSCRFDDetector
    from ..face.embedding import HailoArcFaceEmbedder

    detector = HailoSCRFDDetector(
        config.detector_model_path,
        confidence_threshold=config.detection_threshold,
        log_empty_detections=False,
        nms_iou_threshold=config.detector_nms_iou_threshold,
        min_box_size=config.detector_min_box_size,
        max_box_size_ratio=config.detector_max_box_size_ratio,
        box_expansion_ratio=config.detector_box_expansion_ratio,
    )
    embedder = HailoArcFaceEmbedder(config.embedding_model_path)
    repository = DeviceUserRepository(config.database_path)
    return AccessControlPipeline(detector, embedder, repository, config=config)


def main() -> None:
    from ..sync import SyncEngine

    parser = argparse.ArgumentParser(description="Run Hailo access-control face recognition")
    parser.add_argument("--camera", default=None, help="Camera index, /dev/videoN, RTSP URL, or video file")
    parser.add_argument("--database", default=None, help="SQLite database path")
    parser.add_argument("--target-user-id", default=None, help="Optional 1:1 verification user ID")
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument("--audio", dest="audio", action="store_true", default=None, help="Start audio I/O with access control")
    audio_group.add_argument("--no-audio", dest="audio", action="store_false", help="Run access control without audio I/O")
    parser.add_argument("--audio-skip-model-setup", action="store_true", help="Do not download or prepare audio models at startup")
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument("--display", dest="display", action="store_true", default=True, help="Show an OpenCV camera window with overlays (default)")
    display_group.add_argument("--no-display", dest="display", action="store_false", help="Run without the OpenCV display window")
    parser.add_argument("--window-name", default="Hailo Access Control", help="OpenCV display window name")
    parser.add_argument("--mirror", dest="mirror", action="store_true", default=True, help="Mirror the displayed frame")
    parser.add_argument("--no-mirror", dest="mirror", action="store_false", help="Do not mirror the displayed frame")
    args = parser.parse_args()

    defaults = AccessControlConfig()
    config_kwargs = {
        "camera": args.camera or defaults.camera,
        "database_path": args.database or defaults.database_path,
    }
    if args.audio is not None:
        config_kwargs["audio_enabled"] = args.audio
    if args.audio_skip_model_setup:
        config_kwargs["audio_skip_model_setup"] = True
    config = AccessControlConfig(**config_kwargs)
    configure_logging(config.log_level)
    sync_engine = SyncEngine.from_config(config)
    sync_engine.start()
    audio_coordinator = AccessControlAudioCoordinator(config)
    audio_coordinator.start()
    stop_requested = threading.Event()

    def activate_chatbot() -> None:
        audio_coordinator.activate_chatbot()

    def request_stop() -> None:
        stop_requested.set()

    keyboard_listener = KeyboardControlListener(activate_chatbot, request_stop)
    keyboard_listener.start()

    def handle_display_key(key: int) -> None:
        if key == SPACE_KEY:
            activate_chatbot()
        elif key == QUIT_KEY:
            request_stop()

    camera = CameraReader(config.camera)
    try:
        pipeline = build_pipeline(config)
        camera.open()
        while not stop_requested.is_set():
            ok, frame = camera.read()
            if not ok or frame is None:
                logger.warning("Camera read failed")
                time.sleep(0.05)
                continue
            result = pipeline.process_frame(frame, target_user_id=args.target_user_id)
            audio_coordinator.handle_access_result(result)
            logger.debug(json.dumps(result, default=str))
            if args.display and not show_pipeline_result(
                args.window_name,
                frame,
                result,
                mirror=args.mirror,
                key_handler=handle_display_key,
            ):
                break
    finally:
        keyboard_listener.stop()
        camera.release()
        audio_coordinator.stop()
        sync_engine.stop()
        if args.display:
            close_display()


if __name__ == "__main__":
    main()
