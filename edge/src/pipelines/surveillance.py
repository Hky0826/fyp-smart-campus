"""Surveillance pipeline using SCRFD 10G and ArcFace R50."""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from ..camera.camera_reader import CameraReader
from ..config import SurveillanceConfig
from ..face.alignment import FaceAligner
from ..face.database import DeviceUserRepository
from ..face.matching import TemplateMatcher
from ..face.types import DetectedFace
from ..utils.logging import configure_logging
from ..sync import SyncEngine
from ..utils.timing import StageTimer
from ..utils.visualization import close_display, show_pipeline_result


logger = logging.getLogger(__name__)

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


@dataclass
class TrackedFace:
    track_id: int
    bbox: List[int]
    missing_frames: int = 0
    identity: str = "unknown"
    user_id: Optional[str] = None
    similarity: float = 0.0
    matched_template: Optional[str] = None
    status: str = "unknown"
    entry_logged: bool = False
    recognized_logged: bool = False

    @property
    def is_recognized(self) -> bool:
        return self.status == "recognized" and self.user_id is not None

    def remember_match(self, match: Any) -> None:
        self.identity = match.identity
        self.user_id = match.user_id
        self.similarity = float(match.similarity)
        self.matched_template = match.matched_template
        self.status = "recognized"


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
        self._next_track_id = 1
        self._tracks: Dict[int, TrackedFace] = {}

    def process_frame(self, frame: np.ndarray) -> dict:
        timer = StageTimer()
        faces = self._detect(frame)
        timer.mark("detection")
        logger.info("Surveillance detected %s faces", len(faces))

        tracks_by_face = self._assign_tracks(faces)
        templates = None
        results = []
        recognition_latency_ms = 0.0
        database_matching_latency_ms = 0.0
        for index, face in enumerate(faces):
            track = tracks_by_face[index]
            identity_source = "track" if track.is_recognized else "recognition"

            if not track.is_recognized:
                recognition_started = time.perf_counter()
                face_image = self.aligner.extract(frame, face)
                embedding = self.embedder.embed(face_image)
                recognition_latency_ms += (time.perf_counter() - recognition_started) * 1000.0

                if templates is None:
                    templates = self.repository.load_templates()
                matching_started = time.perf_counter()
                match = self.matcher.match(
                    embedding,
                    templates,
                    threshold=self.config.recognition_threshold,
                    include_inactive=False,
                )
                database_matching_latency_ms += (time.perf_counter() - matching_started) * 1000.0

                if match.matched:
                    track.remember_match(match)
                else:
                    track.identity = "unknown"
                    track.user_id = None
                    track.similarity = float(match.similarity)
                    track.matched_template = match.matched_template
                    track.status = "unknown"

            status = track.status
            identity = track.identity if status == "recognized" else "unknown"
            timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            bbox = face.xyxy_int()
            track.bbox = bbox
            logger.info(
                "Surveillance recognition result: track=%s identity=%s similarity=%.4f template=%s status=%s source=%s",
                track.track_id,
                identity,
                track.similarity,
                track.matched_template,
                status,
                identity_source,
            )
            self._maybe_log_track_event(frame, face, track, face_count=len(faces), timestamp=timestamp)
            results.append(
                {
                    "track_id": track.track_id,
                    "bbox": bbox,
                    "detection_confidence": float(face.confidence),
                    "identity": identity,
                    "user_id": track.user_id if status == "recognized" else None,
                    "similarity": float(track.similarity),
                    "matched_template": track.matched_template if status == "recognized" else None,
                    "status": status,
                    "identity_source": identity_source,
                    "timestamp": timestamp,
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
            "active_tracks": self._active_track_results(),
            "metrics": timer.metrics,
        }

    def _assign_tracks(self, faces: Sequence[DetectedFace]) -> Dict[int, TrackedFace]:
        assignments: Dict[int, TrackedFace] = {}
        unmatched_track_ids = set(self._tracks.keys())

        for index, face in enumerate(faces):
            bbox = face.xyxy_int()
            best_track_id: Optional[int] = None
            best_iou = max(0.0, float(self.config.track_iou_threshold))
            for track_id in unmatched_track_ids:
                iou = self._bbox_iou(bbox, self._tracks[track_id].bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_track_id = track_id

            if best_track_id is None:
                track = TrackedFace(track_id=self._next_track_id, bbox=bbox)
                self._tracks[track.track_id] = track
                self._next_track_id += 1
            else:
                track = self._tracks[best_track_id]
                track.bbox = bbox
                track.missing_frames = 0
                unmatched_track_ids.remove(best_track_id)
            assignments[index] = track

        for track_id in list(unmatched_track_ids):
            track = self._tracks[track_id]
            track.missing_frames += 1
            if track.missing_frames > max(0, int(self.config.track_max_missing_frames)):
                del self._tracks[track_id]

        return assignments

    @staticmethod
    def _bbox_iou(a: Sequence[int], b: Sequence[int]) -> float:
        ax1, ay1, ax2, ay2 = [float(value) for value in a[:4]]
        bx1, by1, bx2, by2 = [float(value) for value in b[:4]]
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - inter_area
        if union <= 0.0:
            return 0.0
        return inter_area / union

    def _maybe_log_track_event(
        self,
        frame: np.ndarray,
        face: DetectedFace,
        track: TrackedFace,
        face_count: int,
        timestamp: str,
    ) -> None:
        if track.status == "recognized":
            if track.recognized_logged:
                return
            recognition_status = "RECOGNIZED"
        elif track.entry_logged:
            return
        else:
            recognition_status = "UNKNOWN"

        image_path = self._save_face_snapshot(frame, face, track, recognition_status, timestamp)
        log_method = getattr(self.repository, "log_surveillance_event", None)
        if callable(log_method):
            log_method(
                track.user_id if recognition_status == "RECOGNIZED" else None,
                recognition_status,
                track.similarity,
                matched_template=track.matched_template if recognition_status == "RECOGNIZED" else None,
                face_count=face_count,
                bbox=track.bbox,
                image_path=image_path,
                timestamp=timestamp,
            )

        track.entry_logged = True
        if recognition_status == "RECOGNIZED":
            track.recognized_logged = True

    def _save_face_snapshot(
        self,
        frame: np.ndarray,
        face: DetectedFace,
        track: TrackedFace,
        recognition_status: str,
        timestamp: str,
    ) -> Optional[str]:
        if not self.config.snapshot_enabled or cv2 is None:
            return None

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = face.xyxy_int()
        x1 = max(0, min(w, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h, y1))
        y2 = max(0, min(h, y2))
        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        snapshot_dir = Path(self.config.snapshot_dir) / datetime.now(timezone.utc).strftime("%Y%m%d")
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        safe_timestamp = (
            timestamp.replace("-", "")
            .replace(":", "")
            .replace(".", "")
            .replace("+", "")
        )
        filename = f"{safe_timestamp}_track_{track.track_id}_{recognition_status.lower()}.jpg"
        path = snapshot_dir / filename
        if not cv2.imwrite(str(path), crop):
            return None
        return str(path)

    def _active_track_results(self) -> List[dict]:
        return [
            {
                "track_id": track.track_id,
                "bbox": track.bbox,
                "identity": track.identity,
                "user_id": track.user_id,
                "similarity": float(track.similarity),
                "matched_template": track.matched_template,
                "status": track.status,
                "visible": track.missing_frames == 0,
                "missing_frames": track.missing_frames,
            }
            for track in sorted(self._tracks.values(), key=lambda item: item.track_id)
        ]

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

    defaults = SurveillanceConfig()
    config = SurveillanceConfig(
        camera=args.camera or defaults.camera,
        database_path=args.database or defaults.database_path,
    )
    configure_logging(config.log_level)
    sync_engine = SyncEngine.from_config(config)
    sync_engine.start()
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
            result = pipeline.process_frame(frame)
            print(json.dumps(result, default=str))
            if args.display and not show_pipeline_result(args.window_name, frame, result, mirror=args.mirror):
                break
    finally:
        camera.release()
        sync_engine.stop()
        if args.display:
            close_display()


if __name__ == "__main__":
    main()
