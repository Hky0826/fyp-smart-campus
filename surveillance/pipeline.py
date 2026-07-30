"""Surveillance pipeline orchestrator coordinating YOLOX-M, YuNet, AuraFace, and ByteTrack."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from .config import SurveillanceConfig
from .database import SurveillanceUserRepository
from .sync import SurveillanceSyncEngine
from .models.auraface import AuraFaceEmbedder
from .models.yolox import YOLOXPersonDetector
from .models.yunet import YuNetFaceDetector
from .tracking.association import IdentityManager, TrackIdentity
from .tracking.bytetrack import ByteTracker, STrack
from .utils.alignment import FaceAligner
from .utils.matching import TemplateMatcher, FaceTemplate
from .utils.timing import StageTimer

logger = logging.getLogger(__name__)


class SurveillancePipeline:
    """Coordinated surveillance monitoring pipeline.

    Coordinates:
    1. YOLOX-M: Person Detection
    2. ByteTrack: Multi-Object Tracking with persistent track IDs
    3. YuNet: Face Detection within person tracks
    4. AuraFace: 512-d Face Embedding & Template Matching
    5. Identity Persistence: Preserves recognized identity over active track lifetime without redundant re-recognition.
    """

    def __init__(
        self,
        person_detector: YOLOXPersonDetector,
        face_detector: YuNetFaceDetector,
        embedder: AuraFaceEmbedder,
        repository: SurveillanceUserRepository,
        config: Optional[SurveillanceConfig] = None,
        aligner: Optional[FaceAligner] = None,
        matcher: Optional[TemplateMatcher] = None,
        tracker: Optional[ByteTracker] = None,
        identity_manager: Optional[IdentityManager] = None,
    ) -> None:
        self.config = config or SurveillanceConfig()
        self.person_detector = person_detector
        self.face_detector = face_detector
        self.embedder = embedder
        self.repository = repository
        self.aligner = aligner or FaceAligner()
        self.matcher = matcher or TemplateMatcher(self.config.recognition_threshold)
        self.tracker = tracker or ByteTracker(
            track_high_thresh=self.config.track_high_thresh,
            track_low_thresh=self.config.track_low_thresh,
            new_track_thresh=self.config.new_track_thresh,
            track_buffer=self.config.track_buffer,
            match_thresh=self.config.match_thresh,
        )
        self.identity_manager = identity_manager or IdentityManager()
        self.frame_count = 0
        self._cached_templates: Optional[List[FaceTemplate]] = None

    def load_templates(self, force_reload: bool = False) -> List[FaceTemplate]:
        """Loads user templates from SQLite DB."""
        if self._cached_templates is None or force_reload:
            try:
                self._cached_templates = self.repository.load_templates()
            except Exception:
                logger.exception("Failed to load user face templates from database")
                self._cached_templates = []
        return self._cached_templates

    def process_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """Processes a single video frame through the full surveillance pipeline."""
        timer = StageTimer()
        self.frame_count += 1

        if frame is None or frame.size == 0:
            timer.total()
            return {
                "success": False,
                "mode": "surveillance",
                "person_count": 0,
                "results": [],
                "active_tracks": [],
                "error": "empty_frame",
                "metrics": timer.metrics,
            }

        h, w = frame.shape[:2]

        # Stage 1: Person Detection (YOLOX-M)
        try:
            person_dets = self.person_detector.detect(frame)
        except Exception:
            logger.exception("Person detection (YOLOX-M) failed")
            timer.total()
            return {
                "success": False,
                "mode": "surveillance",
                "person_count": 0,
                "results": [],
                "active_tracks": [],
                "error": "person_detection_failed",
                "metrics": timer.metrics,
            }
        timer.mark("person_detection")

        # Stage 2: Multi-Object Tracking (ByteTrack)
        try:
            active_stracks = self.tracker.update(person_dets)
        except Exception:
            logger.exception("Multi-object tracking (ByteTrack) failed")
            timer.total()
            return {
                "success": False,
                "mode": "surveillance",
                "person_count": len(person_dets),
                "results": [],
                "active_tracks": [],
                "error": "tracking_failed",
                "metrics": timer.metrics,
            }
        timer.mark("bytetrack")

        # Stage 3: Sync & Manage Active Track Identities
        active_track_ids: Set[int] = {t.track_id for t in active_stracks}
        self.identity_manager.update_active_tracks(active_track_ids, frame_id=self.frame_count)

        templates = self.load_templates()
        results: List[Dict[str, Any]] = []
        recognition_latency_ms = 0.0

        for strack in active_stracks:
            track_id = strack.track_id
            person_bbox = [int(round(v)) for v in strack.tlbr]
            # Clip bbox to image bounds
            x1, y1, x2, y2 = person_bbox
            x1, y1 = max(0, min(w, x1)), max(0, min(h, y1))
            x2, y2 = max(0, min(w, x2)), max(0, min(h, y2))
            person_bbox = [x1, y1, x2, y2]

            identity_rec = self.identity_manager.get_identity(track_id)
            identity_source = "track" if identity_rec.is_recognized else "recognition"
            rec_error: Optional[str] = None

            face_bbox_out: Optional[List[int]] = None
            # Requirement 8: Avoid repeatedly running face recognition once identity is assigned
            if self.identity_manager.should_recognize(track_id):
                rec_start = time.perf_counter()
                if x2 > x1 and y2 > y1:
                    person_crop = frame[y1:y2, x1:x2]
                else:
                    person_crop = frame

                # Run Face Detection (YuNet) on crop/frame
                try:
                    faces = self.face_detector.detect(person_crop if person_crop.size > 0 else frame)
                except Exception:
                    logger.exception("Face detection (YuNet) failed for track %s", track_id)
                    faces = []
                    rec_error = "face_detection_failed"

                if faces:
                    # Select best face candidate by score
                    best_face = max(faces, key=lambda f: f.score)
                    if best_face.score >= self.config.face_detection_threshold:
                        # Translate face bbox relative to full frame if crop was used
                        if person_crop.size > 0 and (x1, y1) != (0, 0):
                            fx1, fy1, fx2, fy2 = best_face.bbox
                            face_bbox = (fx1 + x1, fy1 + y1, fx2 + x1, fy2 + y1)
                            face_lms = best_face.landmarks.copy() if best_face.landmarks is not None else None
                            if face_lms is not None:
                                face_lms[:, 0] += x1
                                face_lms[:, 1] += y1
                        else:
                            face_bbox = best_face.bbox
                            face_lms = best_face.landmarks

                        face_bbox_out = [int(round(v)) for v in face_bbox]
                        align_res = self.aligner.align(frame, face_bbox, face_lms)
                        if align_res.success and align_res.aligned_face is not None:
                            try:
                                embedding = self.embedder.embed(align_res.aligned_face)
                                match_res = self.matcher.match(
                                    embedding,
                                    templates,
                                    threshold=self.config.recognition_threshold,
                                )
                                if match_res.matched and match_res.user_id:
                                    # Requirement 6: Bind identity persistently to track ID
                                    identity_rec = self.identity_manager.associate_identity(
                                        track_id=track_id,
                                        user_id=match_res.user_id,
                                        identity=match_res.identity,
                                        similarity=match_res.similarity,
                                        matched_template=match_res.matched_template,
                                        frame_id=self.frame_count,
                                    )
                                    identity_source = "recognition"
                                    timestamp = datetime.now(timezone.utc).isoformat()
                                    self._maybe_log_event(frame, person_bbox, identity_rec, timestamp)
                                    logger.info(
                                        "Track %s RECOGNIZED: user=%s (%s) confidence=%.4f (threshold=%.2f)",
                                        track_id,
                                        match_res.identity,
                                        match_res.user_id,
                                        match_res.similarity,
                                        self.config.recognition_threshold,
                                    )
                                else:
                                    logger.info(
                                        "Track %s UNKNOWN: face confidence=%.4f below threshold=%.2f",
                                        track_id,
                                        match_res.similarity,
                                        self.config.recognition_threshold,
                                    )
                            except Exception:
                                logger.exception("Face embedding / matching failed for track %s", track_id)
                                rec_error = "embedding_failed"
                        else:
                            rec_error = f"alignment_failed:{align_res.failure_reason}"

                recognition_latency_ms += (time.perf_counter() - rec_start) * 1000.0

            # Build result dictionary for track
            status = identity_rec.status
            display_identity = identity_rec.identity if status == "recognized" else "unknown"

            track_item = {
                "track_id": track_id,
                "bbox": person_bbox,
                "face_bbox": face_bbox_out,
                "detection_confidence": float(strack.score),
                "identity": display_identity,
                "user_id": identity_rec.user_id if status == "recognized" else None,
                "similarity": float(identity_rec.similarity),
                "matched_template": identity_rec.matched_template if status == "recognized" else None,
                "status": status,
                "identity_source": identity_source,
                "frame_id": self.frame_count,
            }
            if rec_error:
                track_item["recognition_error"] = rec_error

            results.append(track_item)

        # Fallback: If 0 person tracks were found by YOLOX, run YuNet face detection directly on full frame
        if not results:
            try:
                fallback_faces = self.face_detector.detect(frame)
                for face in fallback_faces:
                    if face.score >= self.config.face_detection_threshold:
                        fb_bbox = [int(round(v)) for v in face.bbox]
                        results.append({
                            "track_id": 0,
                            "bbox": fb_bbox,
                            "face_bbox": fb_bbox,
                            "detection_confidence": float(face.score),
                            "identity": "face_detected",
                            "user_id": None,
                            "similarity": float(face.score),
                            "status": "face_only",
                            "identity_source": "fallback_detection",
                            "frame_id": self.frame_count,
                        })
            except Exception:
                logger.debug("Fallback full-frame face detection failed")

        timer.metrics["recognition_latency_ms"] = round(recognition_latency_ms, 2)
        timer.total()

        return {
            "success": True,
            "mode": "surveillance",
            "person_count": len(person_dets),
            "track_count": len(active_stracks),
            "results": results,
            "active_tracks": [
                {
                    "track_id": t["track_id"],
                    "bbox": t["bbox"],
                    "identity": t["identity"],
                    "user_id": t["user_id"],
                    "status": t["status"],
                }
                for t in results
            ],
            "metrics": timer.metrics,
        }

    def _maybe_log_event(
        self,
        frame: np.ndarray,
        bbox: List[int],
        identity_rec: TrackIdentity,
        timestamp: str,
    ) -> None:
        """Logs surveillance recognition event and saves snapshot if configured."""
        if identity_rec.event_logged:
            return

        image_path: Optional[str] = None
        if self.config.snapshot_enabled and cv2 is not None:
            image_path = self._save_snapshot(frame, bbox, identity_rec, timestamp)

        try:
            self.repository.log_surveillance_event(
                user_id=identity_rec.user_id,
                recognition_status="RECOGNIZED",
                confidence_score=identity_rec.similarity,
                matched_template=identity_rec.matched_template,
                face_count=1,
                bbox=bbox,
                image_path=image_path,
                timestamp=timestamp,
            )
            identity_rec.event_logged = True
        except Exception:
            logger.exception("Failed to log surveillance recognition event")

    def _save_snapshot(
        self,
        frame: np.ndarray,
        bbox: List[int],
        identity_rec: TrackIdentity,
        timestamp: str,
    ) -> Optional[str]:
        if cv2 is None or frame is None or frame.size == 0:
            return None

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        x1, y1 = max(0, min(w, x1)), max(0, min(h, y1))
        x2, y2 = max(0, min(w, x2)), max(0, min(h, y2))
        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        try:
            snap_dir = Path(self.config.snapshot_dir) / datetime.now(timezone.utc).strftime("%Y%m%d")
            snap_dir.mkdir(parents=True, exist_ok=True)
            safe_ts = timestamp.replace("-", "").replace(":", "").replace(".", "").replace("+", "")
            filename = f"{safe_ts}_track_{identity_rec.track_id}_user_{identity_rec.user_id}.jpg"
            file_path = snap_dir / filename
            if cv2.imwrite(str(file_path), crop):
                return str(file_path)
        except Exception:
            logger.exception("Failed to save snapshot file")

        return None


def build_surveillance_pipeline(config: Optional[SurveillanceConfig] = None) -> SurveillancePipeline:
    """Builds SurveillancePipeline with config and models."""
    cfg = config or SurveillanceConfig()
    repository = SurveillanceUserRepository(cfg.database_path)

    person_detector = YOLOXPersonDetector(
        hef_path=cfg.person_detector_model_path,
        confidence_threshold=cfg.person_detection_threshold,
    )
    face_detector = YuNetFaceDetector(
        hef_path=cfg.face_detector_model_path,
        confidence_threshold=cfg.face_detection_threshold,
    )
    embedder = AuraFaceEmbedder(
        hef_path=cfg.face_embedder_model_path,
    )

    return SurveillancePipeline(
        person_detector=person_detector,
        face_detector=face_detector,
        embedder=embedder,
        repository=repository,
        config=cfg,
    )


def main() -> None:
    """CLI runner to execute surveillance camera pipeline with optional OpenCV display."""
    import argparse
    from .utils.camera import CameraReader
    from .utils.visualization import show_pipeline_result, close_display
    from .utils.logging import configure_logging

    parser = argparse.ArgumentParser(description="Run surveillance monitoring pipeline")
    parser.add_argument("--camera", default=None, help="Camera index, RTSP URL, or video file")
    parser.add_argument("--database", default=None, help="SQLite database path")
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument(
        "--display",
        dest="display",
        action="store_true",
        default=True,
        help="Show OpenCV camera window with overlays (default)",
    )
    display_group.add_argument(
        "--no-display",
        dest="display",
        action="store_false",
        help="Run headless without OpenCV display window",
    )
    parser.add_argument("--window-name", default="Smart Campus Surveillance", help="OpenCV display window title")
    parser.add_argument("--mirror", dest="mirror", action="store_true", default=True, help="Mirror displayed frame")
    parser.add_argument("--no-mirror", dest="mirror", action="store_false", help="Do not mirror displayed frame")
    args = parser.parse_args()

    defaults = SurveillanceConfig()
    config = SurveillanceConfig(
        camera=args.camera or defaults.camera,
        database_path=Path(args.database).expanduser() if args.database else defaults.database_path,
    )
    configure_logging(config.log_level)

    pipeline = build_surveillance_pipeline(config)
    camera = CameraReader(config.camera)

    if not camera.open():
        logger.error("Could not open camera source: %s", config.camera)
        return

    sync_engine = SurveillanceSyncEngine.from_config(config, pipeline.repository)
    sync_engine.start()

    logger.info("Starting surveillance pipeline loop. Press 'q' or 'ESC' on display window to stop.")
    try:
        while True:
            ok, frame = camera.read_latest()
            if not ok or frame is None:
                ok, frame = camera.read()
                if not ok or frame is None:
                    time.sleep(0.005)
                    continue

            result = pipeline.process_frame(frame)

            if args.display:
                if not show_pipeline_result(args.window_name, frame, result, mirror=args.mirror):
                    break
    finally:
        sync_engine.stop()
        camera.release()
        if args.display:
            close_display()


if __name__ == "__main__":
    main()
