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
import cv2
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..camera.camera_reader import CameraReader
from ..config import AccessControlConfig
from ..hardware.door_controller import get_door_controller
from ..face.aggregation import EmbeddingAggregationConfig, TrackEmbeddingAggregator
from ..face.alignment import FaceAligner
from ..face.database import DeviceUserRepository
from ..face.matching import TemplateMatcher
from ..face.quality import FaceQualityChecker, FaceQualityConfig
from ..face.spoofing import MotionSpoofDetector, SpoofResult
from ..face.pad import load_pad, PADResult
from ..face.association import IdentityManager, TrackIdentity
from ..face.presence import PresenceConfig, PresenceDetector, PresenceStatus
from ..face.tracking import FaceTracker, FaceTrackerConfig
from ..face.types import AuthenticationResult, DetectedFace
from ..utils.logging import configure_logging
from ..utils.timing import StageTimer
from ..utils.visualization import close_display, show_pipeline_result
from .access_audio import AccessControlAudioCoordinator


logger = logging.getLogger(__name__)
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
        pad_detector: Any | None = None,
        identity_manager: IdentityManager | None = None,
        presence_detector: PresenceDetector | None = None,
    ) -> None:
        self.config = config or AccessControlConfig()
        self.detector = detector
        self.embedder = embedder
        self.repository = repository
        self.aligner = aligner or FaceAligner()
        self.matcher = matcher or TemplateMatcher(self.config.recognition_threshold)
        self.identity_manager = identity_manager or IdentityManager()
        self.spoof_detector = spoof_detector or MotionSpoofDetector(
            history_size=getattr(self.config, "spoof_history_size", 4)
        )
        self.pad_detector = pad_detector or load_pad(self.config)
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
        self._last_full_recognition_time = 0.0
        self._cached_recognition_result: dict | None = None
        self._recognition_interval = 0.25

        presence_cfg = PresenceConfig(
            enabled=getattr(self.config, "presence_activation_enabled", True),
            dwell_seconds=getattr(self.config, "presence_dwell_seconds", 3.0),
            grace_period_seconds=getattr(self.config, "presence_detection_grace_ms", 400) / 1000.0,
            cooldown_seconds=getattr(self.config, "presence_activation_cooldown_seconds", 5.0),
            interaction_zone=(
                getattr(self.config, "interaction_zone_x", 0.15),
                getattr(self.config, "interaction_zone_y", 0.10),
                getattr(self.config, "interaction_zone_x", 0.15) + getattr(self.config, "interaction_zone_width", 0.70),
                getattr(self.config, "interaction_zone_y", 0.10) + getattr(self.config, "interaction_zone_height", 0.80),
            ),
            min_face_size_ratio=getattr(self.config, "minimum_face_size_ratio", 0.15),
            max_yaw_degrees=getattr(self.config, "frontal_face_threshold", 25.0),
            max_pitch_degrees=getattr(self.config, "frontal_pitch_threshold", 20.0),
        )
        self.presence_detector = presence_detector or PresenceDetector(
            config=presence_cfg,
            clock=self._clock,
        )

    def process_frame(self, frame: np.ndarray, target_user_id: Optional[str] = None) -> dict:
        timer = StageTimer()
        timestamp = self._clock()
        try:
            all_faces = self._detect(frame, return_all=True)
            faces = [max(all_faces, key=lambda face: face.width() * face.height())] if all_faces else []
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

        # Update presence detector on every frame
        presence_status = self.presence_detector.update(
            faces=all_faces,
            tracks=visible_tracks,
            frame_shape=frame.shape[:2],
            timestamp=timestamp,
        )

        def with_presence(res: dict) -> dict:
            res["presence"] = presence_status.as_dict()
            return res

        if face_count == 0:
            if self._active_track_id is not None and not any(
                track.track_id == self._active_track_id for track in tracks
            ):
                self._reset_active_track()
            timer.total()
            return with_presence(self._deny(
                "No face detected", 0, AuthenticationResult.RETRY_NO_FACE,
                metrics=timer.metrics, bboxes=bboxes,
            ))

        track = visible_tracks[0]
        if self._active_track_id != track.track_id:
            self._reset_active_track()
            self._active_track_id = track.track_id
        face = track.as_detection(faces[0].confidence if faces else 1.0)
        bbox = face.xyxy_int()
        if not track.stable:
            timer.total()
            return with_presence(self._deny(
                "Face track is not stable yet", face_count, AuthenticationResult.RETRY_UNSTABLE_TRACK,
                metrics=timer.metrics, bbox=bbox, bboxes=bboxes,
            ))

        active_track_ids = {t.track_id for t in tracks}
        self.identity_manager.update_active_tracks(active_track_ids, timestamp=timestamp)

        # Fast-Path: Persistent Track Identity Check (Track-then-Recognize)
        # Avoid repeatedly running face recognition once identity is assigned to this active track
        if not self.identity_manager.should_recognize(track.track_id):
            identity_rec = self.identity_manager.get_identity(track.track_id)
            if identity_rec.cached_payload is not None:
                result = dict(identity_rec.cached_payload)
                result["bbox"] = bbox
                result["bboxes"] = bboxes
                result["track_id"] = track.track_id
                timer.total()
                result["metrics"] = timer.metrics
                return with_presence(result)

        if self._cached_recognition_result is not None and (timestamp - self._last_full_recognition_time) < self._recognition_interval:
            result = dict(self._cached_recognition_result)
            result["bbox"] = bbox
            result["bboxes"] = bboxes
            timer.total()
            result["metrics"] = timer.metrics
            return with_presence(result)

        def cache_and_return(res: dict) -> dict:
            self._cached_recognition_result = res
            self._last_full_recognition_time = timestamp
            auth_res = res.get("authentication_result")
            if auth_res == AuthenticationResult.GRANT.value and res.get("user_id"):
                self.presence_detector.update([], is_auth_transition=True, timestamp=timestamp)
                self.identity_manager.associate_identity(
                    track_id=track.track_id,
                    user_id=str(res["user_id"]),
                    identity=str(res.get("identity", "unknown")),
                    similarity=float(res.get("similarity") or 0.0),
                    matched_template=res.get("matched_template"),
                    access_decision="GRANTED",
                    reason=res.get("decision_reason"),
                    cached_payload=res,
                    timestamp=timestamp,
                )
            elif auth_res in (AuthenticationResult.DENY_NO_MATCH.value, AuthenticationResult.DENY_SPOOF.value):
                self.identity_manager.associate_denial(
                    track_id=track.track_id,
                    reason=str(res.get("reason") or "Access denied"),
                    similarity=float(res.get("similarity") or 0.0),
                    cached_payload=res,
                    timestamp=timestamp,
                )
            return with_presence(res)

        try:
            quality = self.quality_checker.check(frame, face)
            if not quality.passed:
                timer.total()
                return cache_and_return(self._deny(
                    f"Face quality check failed: {quality.reason}",
                    face_count,
                    AuthenticationResult.RETRY_LOW_QUALITY,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                    quality=self._quality_payload(quality),
                ))

            if self.config.require_liveness:
                spoof_result = self.spoof_detector.check(frame, face)
                logger.info("Access-control spoofing result: %s score=%.4f reason=%s", spoof_result.state, spoof_result.score, spoof_result.reason)
                pad_result = self.pad_detector.check(frame, face)
                logger.info("Access-control PAD result: %s score=%.4f model=%s threshold=%.4f", pad_result.state, pad_result.score, pad_result.model_version, pad_result.threshold)
                liveness_failed = pad_result.state != "live" if self.config.pad_required else spoof_result.state != "live"
                if liveness_failed:
                    is_spoof = pad_result.state == "spoof" or (not self.config.pad_required and spoof_result.state == "spoof")
                    reason = "Spoofing/liveness check failed." if is_spoof else "Liveness check inconclusive."
                    if is_spoof:
                        self._log_event(None, "SPOOFING", spoof_result.score)
                    timer.total()
                    return cache_and_return(self._deny(
                        reason,
                        face_count,
                        AuthenticationResult.DENY_SPOOF if is_spoof else AuthenticationResult.RETRY_UNSTABLE_TRACK,
                        spoofing_passed=False,
                        similarity=pad_result.score if self.config.pad_required else spoof_result.score,
                        metrics=timer.metrics,
                        bbox=bbox,
                        bboxes=bboxes,
                    ))

            alignment = self.aligner.align(frame, face)
            if not alignment.success or alignment.aligned_face is None:
                timer.total()
                return cache_and_return(self._deny(
                    f"Face alignment failed: {alignment.failure_reason}",
                    face_count,
                    AuthenticationResult.RETRY_ALIGNMENT,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                ))
            embedding = self.embedder.embed(alignment.aligned_face)
            timer.mark("recognition")

            templates = self.repository.load_templates()
            # Only use 'front' and 'low_light' templates for access control
            templates = [t for t in templates if t.template_name in (None, "front", "low_light")]
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

            logger.info(
                "Face frame recognition evaluation: identity=%s recognition_score=%.4f (similarity=%.4f) template=%s matched=%s sample_count=%d/%d threshold=%.3f",
                match.identity,
                match.similarity,
                match.similarity,
                match.matched_template,
                match.matched,
                self.embedding_aggregator.sample_count,
                self.config.min_embedding_samples,
                self.config.recognition_threshold,
            )

            if not self.embedding_aggregator.has_enough_samples():
                timer.mark("database_matching")
                timer.total()
                return with_presence(self._deny(
                    "Collecting valid face samples",
                    face_count,
                    AuthenticationResult.RETRY_INSUFFICIENT_SAMPLES,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                    sample_count=self.embedding_aggregator.sample_count,
                    quality=self._quality_payload(quality),
                ))

            consistent_candidate = self.embedding_aggregator.consistent_candidate()
            if consistent_candidate is None:
                timer.mark("database_matching")
                timer.total()
                terminal = self.embedding_aggregator.sample_count >= self.config.max_embedding_samples
                if terminal:
                    image_path = self._save_face_snapshot(frame, face)
                    self._log_event(None, "FAILED", match.similarity, image_path=image_path)
                    self.embedding_aggregator.reset()
                result = self._deny(
                    "Candidate identity is not consistent across frames",
                    face_count,
                    AuthenticationResult.DENY_NO_MATCH if terminal else AuthenticationResult.RETRY_INSUFFICIENT_SAMPLES,
                    similarity=match.similarity,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                    sample_count=self.embedding_aggregator.sample_count,
                )
                return cache_and_return(result) if terminal else with_presence(result)

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
                "Access-control recognition result: identity=%s recognition_score=%.4f (similarity=%.4f) template=%s matched=%s threshold=%.3f",
                match.identity,
                match.similarity,
                match.similarity,
                match.matched_template,
                match.matched,
                self.config.recognition_threshold,
            )

            if not match.matched or str(match.user_id) != consistent_candidate:
                logger.info(
                    "ACCESS DENIED (low confidence / candidate mismatch): identity=%s recognition_score=%.4f threshold=%.3f",
                    match.identity,
                    match.similarity,
                    self.config.recognition_threshold,
                )
                image_path = self._save_face_snapshot(frame, face)
                self._log_event(None, "FAILED", match.similarity, image_path=image_path)
                self.embedding_aggregator.reset()
                timer.total()
                return cache_and_return(self._deny(
                    "Unknown face or low-confidence match",
                    face_count,
                    AuthenticationResult.DENY_NO_MATCH,
                    similarity=match.similarity,
                    matched_template=match.matched_template,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                ))

            if not match.is_active:
                logger.info(
                    "ACCESS DENIED (user inactive): identity=%s recognition_score=%.4f threshold=%.3f",
                    match.identity,
                    match.similarity,
                    self.config.recognition_threshold,
                )
                image_path = self._save_face_snapshot(frame, face)
                self._log_event(match.user_id, "FAILED", match.similarity, image_path=image_path)
                timer.total()
                return cache_and_return(self._deny(
                    "Matched user is inactive",
                    face_count,
                    AuthenticationResult.DENY_NO_MATCH,
                    identity=match.identity,
                    similarity=match.similarity,
                    matched_template=match.matched_template,
                    metrics=timer.metrics,
                    bbox=bbox,
                    bboxes=bboxes,
                ))

            policy_check = getattr(self.repository, "evaluate_access", None)
            if callable(policy_check):
                decision = policy_check(match.user_id, getattr(self.config, "node_id", None))
                if not decision.allowed:
                    self._log_event(match.user_id, "FAILED", match.similarity, node_id=decision.node_id, policy_version=decision.policy_version, decision_reason=decision.reason)
                    timer.total()
                    denied = self._deny("Access policy denied", face_count, AuthenticationResult.DENY_NO_MATCH, identity=match.identity, similarity=match.similarity, matched_template=match.matched_template, metrics=timer.metrics, bbox=bbox, bboxes=bboxes)
                    denied.update({"node_id": decision.node_id, "policy_version": decision.policy_version, "decision_reason": decision.reason})
                    return cache_and_return(denied)

            logger.info(
                "ACCESS GRANTED: user_id=%s identity=%s recognition_score=%.4f threshold=%.3f",
                match.user_id,
                match.identity,
                match.similarity,
                self.config.recognition_threshold,
            )

            image_path = self._save_face_snapshot(frame, face)
            decision = policy_check(match.user_id, getattr(self.config, "node_id", None)) if callable(policy_check) else None
            self._log_event(match.user_id, "SUCCESS", match.similarity, image_path=image_path, node_id=getattr(decision, "node_id", getattr(self.config, "node_id", None)), policy_version=getattr(decision, "policy_version", None), decision_reason=getattr(decision, "reason", "explicit_node_permission"))
            timer.total()
            return cache_and_return({
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
                "node_id": getattr(decision, "node_id", getattr(self.config, "node_id", None)),
                "policy_version": getattr(decision, "policy_version", None),
                "decision_reason": getattr(decision, "reason", "explicit_node_permission"),
            })
        except Exception:
            logger.exception("Access-control frame processing failed")
            timer.total()
            denial = self._deny(
                "Access-control processing error", face_count, AuthenticationResult.SYSTEM_ERROR,
                metrics=timer.metrics, bbox=bbox, bboxes=bboxes,
            )
            return with_presence(denial) if "with_presence" in locals() else denial
        finally:
            self._mark_recognition_finished()

    def describe_faces(self, frame: np.ndarray, include_embeddings: bool = False) -> dict:
        """Return detected face boxes, optionally with embeddings, without access gating."""
        timer = StageTimer()
        try:
            faces = self._detect(frame)
        except Exception:
            logger.exception("Face detection failed during face description")
            timer.total()
            return {
                "face_count": 0,
                "bboxes": [],
                "faces": [],
                "error": "face_detection_failed",
                "metrics": timer.metrics,
            }
        timer.mark("detection")
        timestamp = self._clock()
        tracks = self.tracker.update(faces, timestamp)
        descriptions: list[dict[str, Any]] = []

        for idx, face in enumerate(sorted(faces, key=lambda item: item.width() * item.height(), reverse=True)):
            track_id = tracks[idx].track_id if idx < len(tracks) else None
            item: dict[str, Any] = {
                "bbox": face.xyxy_int(),
                "confidence": float(face.confidence),
                "track_id": track_id,
            }
            if include_embeddings:
                try:
                    quality = self.quality_checker.check(frame, face)
                    item["quality_passed"] = quality.passed
                    item["quality_reason"] = quality.reason
                except Exception:
                    logger.exception("Face quality check failed during face description")
                    item["quality_passed"] = False
                    item["quality_reason"] = "quality_check_error"
                    descriptions.append(item)
                    continue
                if quality.passed:
                    alignment = self.aligner.align(frame, face)
                    item["alignment_passed"] = alignment.success
                    item["alignment_reason"] = alignment.failure_reason
                    if alignment.success and alignment.aligned_face is not None:
                        try:
                            item["embedding"] = self.embedder.embed(alignment.aligned_face)
                        except Exception:
                            logger.exception("Face embedding failed during face description")
                            item["embedding_error"] = "embedding_error"
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

    def verify_owner_presence(
        self,
        frame: np.ndarray,
        owner_track_id: Optional[str | int] = None,
        owner_embedding: Optional[np.ndarray] = None,
    ) -> tuple[bool, Optional[int], list[list[int]]]:
        """Verify the owner identity; a recycled spatial track alone is not identity evidence."""
        try:
            faces = self._detect(frame, return_all=True)
        except Exception:
            logger.exception("Face detection failed during presence check")
            return False, None, []

        if not faces:
            self.tracker.update([], self._clock())
            return False, None, []

        bboxes = [f.xyxy_int() for f in faces]
        timestamp = self._clock()
        tracks = self.tracker.update(faces, timestamp)
        visible_tracks = [t for t in tracks if t.visible]
        self.identity_manager.update_active_tracks({t.track_id for t in tracks}, timestamp=timestamp)

        target_tid: Optional[int] = None
        if owner_track_id is not None:
            try:
                target_tid = int(owner_track_id)
            except (TypeError, ValueError):
                target_tid = None

        # Tier 1 (Fast-Path): If owner_track_id is active and tracked, return immediately without embedding
        if target_tid is not None and owner_embedding is None:
            for tr in visible_tracks:
                if tr.track_id == target_tid:
                    logger.debug("Owner presence FAST-PATH: track %s is active", target_tid)
                    return True, target_tid, bboxes

        # Tier 2 (Fallback / Re-identification): If track lost or changed, check embedding
        if owner_embedding is not None and visible_tracks:
            threshold = float(getattr(self.config, "recognition_threshold", 0.55))
            for tr in visible_tracks:
                det = tr.as_detection()
                alignment = self.aligner.align(frame, det)
                if alignment.success and alignment.aligned_face is not None:
                    try:
                        emb = self.embedder.embed(alignment.aligned_face)
                        sim = self.matcher.cosine_similarity(owner_embedding, emb)
                        logger.info(
                            "Owner presence fallback: track=%s score=%.4f threshold=%.3f matched=%s",
                            tr.track_id, sim, threshold, sim >= threshold
                        )
                        if sim >= threshold:
                            return True, tr.track_id, bboxes
                    except Exception:
                        logger.exception("Embedding extraction failed during presence check")

        return False, None, bboxes

    def _wait_for_recognition_delay(self) -> None:
        delay_seconds = self.config.recognition_delay_seconds
        if delay_seconds <= 0 or self._last_recognition_finished_at is None:
            return

        remaining_seconds = delay_seconds - (self._clock() - self._last_recognition_finished_at)
        if remaining_seconds > 0:
            self._sleep(remaining_seconds)

    def _mark_recognition_finished(self) -> None:
        self._last_recognition_finished_at = self._clock()

    def _detect(self, frame: np.ndarray, return_all: bool = False) -> List[DetectedFace]:
        if hasattr(self.detector, "detect_all") and return_all:
            raw_faces = self.detector.detect_all(frame)
        elif hasattr(self.detector, "detect"):
            try:
                raw_faces = self.detector.detect(frame, return_all=return_all)
            except TypeError:
                raw_faces = self.detector.detect(frame)
        else:
            raw_faces = []
        faces = [self._coerce_face(face) for face in raw_faces]
        if not faces:
            return []
        if return_all:
            return faces
        # Keep only the face closest to the camera (largest bounding box area)
        closest_face = max(faces, key=lambda face: face.width() * face.height())
        return [closest_face]

    def notify_chat_started(self) -> None:
        """Notify the presence detector that a chatbot session is active."""
        self.presence_detector.notify_chat_started()

    def notify_chat_ended(self) -> None:
        """Notify the presence detector that a chatbot session has closed."""
        self.presence_detector.notify_chat_ended()

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
        self._cached_recognition_result = None
        self._last_full_recognition_time = 0.0

    @staticmethod
    def _quality_payload(quality: Any) -> dict:
        return {
            "overall_score": float(getattr(quality, "overall_score", getattr(quality, "score", 0.0))),
            "failure_reasons": list(getattr(quality, "failure_reasons", [])),
        }

    def _save_face_snapshot(self, frame: np.ndarray, face: DetectedFace) -> Optional[str]:
        if not hasattr(self.config, 'snapshot_enabled') or not self.config.snapshot_enabled or cv2 is None:
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

        try:
            snapshot_dir = Path(getattr(self.config, 'snapshot_dir', 'data/snapshots')) / datetime.now(timezone.utc).strftime("%Y%m%d")
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{datetime.now(timezone.utc).strftime('%H%M%S_%f')}_access.jpg"
            path = snapshot_dir / filename

            if not cv2.imwrite(str(path), crop):
                logger.warning("Failed to save face snapshot to %s", path)
                return None
            retention_days = max(1, int(getattr(self.config, "snapshot_retention_days", 7)))
            cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
            root = Path(getattr(self.config, "snapshot_dir", snapshot_dir))
            for old_file in root.rglob("*"):
                if old_file.is_file() and old_file.stat().st_mtime < cutoff:
                    old_file.unlink(missing_ok=True)
        except Exception:
            logger.exception("Failed to save access face snapshot")
            return None
        return str(path)

    def _log_event(self, user_id: Optional[str], status: str, confidence: Optional[float], image_path: Optional[str] = None, **audit_fields: Any) -> None:
        log_method = getattr(self.repository, "log_auth_event", None)
        if callable(log_method):
            try:
                log_method(user_id, status, confidence, image_path=image_path, **audit_fields)
            except TypeError:
                try:
                    log_method(user_id, status, confidence)
                except Exception:
                    logger.exception("Failed to log access-control event")
            except Exception:
                logger.exception("Failed to log access-control event")


def build_pipeline(config: AccessControlConfig) -> AccessControlPipeline:
    from ..face.detection import YuNetDetector
    from ..face.embedding import SFaceEmbedder

    detector = YuNetDetector(
        config.detector_model_path,
        confidence_threshold=config.detection_threshold,
        nms_iou_threshold=config.detector_nms_iou_threshold,
        min_face_size=float(config.min_face_size),
        max_dim=getattr(config, "detector_max_dim", 640),
    )
    embedder = SFaceEmbedder(
        config.embedding_model_path,
        model_name=config.recognition_model_name,
    )
    repository = DeviceUserRepository(config.database_path)
    return AccessControlPipeline(detector, embedder, repository, config=config)


def main() -> None:
    from ..sync import SyncEngine

    parser = argparse.ArgumentParser(description="Run YuNet/SFace access-control face recognition")
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
    parser.add_argument("--window-name", default="Access Control", help="OpenCV display window name")
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

    door = get_door_controller(
        pin=config.door_relay_pin,
        unlock_duration=config.door_unlock_duration_seconds,
        active_high=config.door_relay_active_high,
        enabled=config.door_relay_enabled,
    )
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
            if result.get("access_granted"):
                door.unlock()
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
        door.cleanup()
        camera.release()
        audio_coordinator.stop()
        sync_engine.stop()
        if args.display:
            close_display()


if __name__ == "__main__":
    main()
