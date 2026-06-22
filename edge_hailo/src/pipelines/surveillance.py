"""Surveillance pipeline using SCRFD 10G and ArcFace R50."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, List, Sequence

import numpy as np

from ..camera.camera_reader import CameraReader
from ..config import SurveillanceConfig
from ..face.alignment import FaceAligner
from ..face.database import DeviceUserRepository
from ..face.matching import TemplateMatcher
from ..face.types import DetectedFace
from ..utils.logging import configure_logging
from ..utils.timing import StageTimer
from ..utils.visualization import close_display, show_pipeline_result


logger = logging.getLogger(__name__)


class SurveillancePipeline:
    """Multi-face monitoring pipeline.

    Surveillance intentionally does not run spoofing/liveness checks. It reports
    recognition scores only and must not trigger access decisions.
    """

    def __init__(
        self,
        detector: Any,
        embedder: Any,
        repository: Any,
        config: SurveillanceConfig | None = None,
        aligner: FaceAligner | None = None,
        matcher: TemplateMatcher | None = None,
    ) -> None:
        self.config = config or SurveillanceConfig()
        self.detector = detector
        self.embedder = embedder
        self.repository = repository
        self.aligner = aligner or FaceAligner()
        self.matcher = matcher or TemplateMatcher(self.config.recognition_threshold)

    def process_frame(self, frame: np.ndarray) -> dict:
        timer = StageTimer()
        faces = self._detect(frame)
        timer.mark("detection")
        logger.info("Surveillance detected %s faces", len(faces))

        templates = self.repository.load_templates()
        results = []
        recognition_latency_ms = 0.0
        database_matching_latency_ms = 0.0
        for face in faces:
            recognition_started = time.perf_counter()
            face_image = self.aligner.extract(frame, face)
            embedding = self.embedder.embed(face_image)
            recognition_latency_ms += (time.perf_counter() - recognition_started) * 1000.0

            matching_started = time.perf_counter()
            match = self.matcher.match(
                embedding,
                templates,
                threshold=self.config.recognition_threshold,
                include_inactive=False,
            )
            database_matching_latency_ms += (time.perf_counter() - matching_started) * 1000.0
            status = "recognized" if match.matched else "unknown"
            identity = match.identity if match.matched else "unknown"
            logger.info(
                "Surveillance recognition result: identity=%s similarity=%.4f template=%s status=%s",
                identity,
                match.similarity,
                match.matched_template,
                status,
            )
            results.append(
                {
                    "bbox": face.xyxy_int(),
                    "detection_confidence": float(face.confidence),
                    "identity": identity,
                    "user_id": match.user_id if match.matched else None,
                    "similarity": float(match.similarity),
                    "matched_template": match.matched_template if match.matched else None,
                    "status": status,
                    "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                }
            )

        timer.metrics["recognition_latency_ms"] = recognition_latency_ms
        timer.metrics["database_matching_latency_ms"] = database_matching_latency_ms
        timer.total()
        return {
            "success": True,
            "mode": "surveillance",
            "face_count": len(faces),
            "results": results,
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


def build_pipeline(config: SurveillanceConfig) -> SurveillancePipeline:
    from ..face.detection import HailoSCRFDDetector
    from ..face.embedding import HailoArcFaceEmbedder

    detector = HailoSCRFDDetector(config.detector_model_path, confidence_threshold=config.detection_threshold)
    embedder = HailoArcFaceEmbedder(config.embedding_model_path)
    repository = DeviceUserRepository(config.database_path)
    return SurveillancePipeline(detector, embedder, repository, config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Hailo surveillance face recognition")
    parser.add_argument("--camera", default=None, help="Camera index, /dev/videoN, RTSP URL, or video file")
    parser.add_argument("--database", default=None, help="SQLite database path")
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument("--display", dest="display", action="store_true", default=True, help="Show an OpenCV camera window with overlays (default)")
    display_group.add_argument("--no-display", dest="display", action="store_false", help="Run without the OpenCV display window")
    parser.add_argument("--window-name", default="Hailo Surveillance", help="OpenCV display window name")
    parser.add_argument("--mirror", dest="mirror", action="store_true", default=True, help="Mirror the displayed frame")
    parser.add_argument("--no-mirror", dest="mirror", action="store_false", help="Do not mirror the displayed frame")
    args = parser.parse_args()

    config = SurveillanceConfig(
        camera=args.camera or SurveillanceConfig().camera,
        database_path=args.database or SurveillanceConfig().database_path,
    )
    configure_logging(config.log_level)
    pipeline = build_pipeline(config)
    camera = CameraReader(config.camera)
    camera.open()
    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                logger.warning("Camera read failed")
                time.sleep(0.05)
                continue
            result = pipeline.process_frame(frame)
            print(json.dumps(result, default=str))
            if args.display and not show_pipeline_result(args.window_name, frame, result, mirror=args.mirror):
                break
    finally:
        camera.release()
        if args.display:
            close_display()


if __name__ == "__main__":
    main()
