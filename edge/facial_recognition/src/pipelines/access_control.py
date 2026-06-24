"""Access-control pipeline using SCRFD 2.5G and ArcFace MobileFaceNet."""

from __future__ import annotations

import argparse
import json
import logging
import time
from typing import Any, List, Optional, Sequence

import numpy as np

from ..camera.camera_reader import CameraReader
from ..config import AccessControlConfig
from ..face.alignment import FaceAligner
from ..face.database import DeviceUserRepository
from ..face.matching import TemplateMatcher
from ..face.quality import FaceQualityChecker
from ..face.spoofing import MotionSpoofDetector, SpoofResult
from ..face.types import DetectedFace
from ..utils.logging import configure_logging
from ..utils.timing import StageTimer
from ..utils.visualization import close_display, show_pipeline_result
from .access_audio import AccessControlAudioCoordinator


logger = logging.getLogger(__name__)
MULTIPLE_FACE_REASON = "Only one user is allowed within the frame."


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
    ) -> None:
        self.config = config or AccessControlConfig()
        self.detector = detector
        self.embedder = embedder
        self.repository = repository
        self.aligner = aligner or FaceAligner()
        self.matcher = matcher or TemplateMatcher(self.config.recognition_threshold)
        self.spoof_detector = spoof_detector or MotionSpoofDetector()
        self.quality_checker = quality_checker or FaceQualityChecker(self.config.min_face_size)

    def process_frame(self, frame: np.ndarray, target_user_id: Optional[str] = None) -> dict:
        timer = StageTimer()
        faces = self._detect(frame)
        timer.mark("detection")
        face_count = len(faces)
        bboxes = [face.xyxy_int() for face in faces]
        logger.info("Access-control detected %s faces", face_count)

        if face_count == 0:
            timer.total()
            return self._deny("No face detected", 0, metrics=timer.metrics, bboxes=bboxes)

        if face_count > 1:
            timer.total()
            logger.info(MULTIPLE_FACE_REASON)
            return self._deny(MULTIPLE_FACE_REASON, face_count, metrics=timer.metrics, bboxes=bboxes)

        face = faces[0]
        bbox = face.xyxy_int()
        quality = self.quality_checker.check(frame, face)
        if not quality.passed:
            timer.total()
            return self._deny(
                f"Face quality check failed: {quality.reason}",
                face_count,
                metrics=timer.metrics,
                bbox=bbox,
                bboxes=bboxes,
            )

        if self.config.require_liveness:
            spoof_result = self.spoof_detector.check(frame, face)
            logger.info("Access-control spoofing result: %s score=%.4f reason=%s", spoof_result.state, spoof_result.score, spoof_result.reason)
            if spoof_result.state != "live":
                reason = "Spoofing/liveness check failed." if spoof_result.state == "spoof" else "Liveness check inconclusive."
                self._log_event(None, "SPOOFING", spoof_result.score)
                timer.total()
                return self._deny(
                    reason,
                    face_count,
                    spoofing_passed=False,
                    similarity=spoof_result.score,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                )

        face_image = self.aligner.extract(frame, face)
        embedding = self.embedder.embed(face_image)
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
        timer.mark("database_matching")

        logger.info(
            "Access-control recognition result: identity=%s similarity=%.4f template=%s matched=%s",
            match.identity,
            match.similarity,
            match.matched_template,
            match.matched,
        )

        if not match.matched:
            self._log_event(None, "FAILED", match.similarity)
            timer.total()
            return self._deny(
                "Unknown face or low-confidence match",
                face_count,
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
        }

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
        identity: str = "unknown",
        similarity: float = 0.0,
        matched_template: Optional[str] = None,
        spoofing_passed: bool = True,
        metrics: Optional[dict] = None,
        bbox: Optional[List[int]] = None,
        bboxes: Optional[List[List[int]]] = None,
    ) -> dict:
        result = {
            "success": False,
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
        return result

    def _log_event(self, user_id: Optional[str], status: str, confidence: Optional[float]) -> None:
        log_method = getattr(self.repository, "log_auth_event", None)
        if callable(log_method):
            log_method(user_id, status, confidence)


def build_pipeline(config: AccessControlConfig) -> AccessControlPipeline:
    from ..face.detection import HailoSCRFDDetector
    from ..face.embedding import HailoArcFaceEmbedder

    detector = HailoSCRFDDetector(config.detector_model_path, confidence_threshold=config.detection_threshold)
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
    camera = CameraReader(config.camera)
    try:
        pipeline = build_pipeline(config)
        camera.open()
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                logger.warning("Camera read failed")
                time.sleep(0.05)
                continue
            result = pipeline.process_frame(frame, target_user_id=args.target_user_id)
            audio_coordinator.handle_access_result(result)
            logger.debug(json.dumps(result, default=str))
            if args.display and not show_pipeline_result(args.window_name, frame, result, mirror=args.mirror):
                break
    finally:
        camera.release()
        audio_coordinator.stop()
        sync_engine.stop()
        if args.display:
            close_display()


if __name__ == "__main__":
    main()
