"""Responsive 24 FPS display coordinator for YuNet/KCF/SFace processing."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from time import perf_counter

from ..domain import BoundingBox, FramePacket
from ..tracking.validation import TrackerValidationConfig, validate_tracker_box
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineView:
    frame: FramePacket
    box: BoundingBox | None
    box_source: str
    status: str
    outcome: object | None
    detector_submitted: bool
    forced_detection: bool
    forced_reason: str | None
    dropped_biometric_frames: int


class RealTimeAccessPipeline:
    def __init__(self, worker, tracker, scheduler, tracker_validation=TrackerValidationConfig(), metrics=None):
        self.worker = worker
        self.tracker = tracker
        self.scheduler = scheduler
        self.validation = tracker_validation
        self.metrics = metrics
        self._box = None
        self._box_source = 'none'
        self._detector_frame = -1
        self._last_result_frame = -1
        self._last_outcome = None
        self._status = 'No face detected'
        self._started = False

    def start(self):
        if not self._started:
            self.worker.start()
            self._started = True

    def stop(self):
        self.worker.stop()
        self.tracker.reset()
        self._started = False

    def process(self, frame):
        self.start()
        applied_detector = False
        if self.metrics:
            self.metrics.tick('display')
        result = self.worker.poll()
        if result is not None and result.frame.frame_id > self._last_result_frame:
            self._last_result_frame = result.frame.frame_id
            applied_detector = True
            if self.metrics:
                self.metrics.tick('detector')
                self.metrics.observe_ms('biometric_total', getattr(result, 'elapsed_ms', 0.0))
                self.metrics.gauge('dropped_biometric_frames', self.worker.dropped_frames)
                if result.detections:
                    self.metrics.observe_ms('yunet_inference', getattr(result.detections[0], 'inference_ms', 0.0))
            if result.error:
                self._status = 'Biometric processing error'
                self._box = None
                self._box_source = 'none'
                self.tracker.reset()
                self.scheduler.force('biometric_worker_error');logger.error('pipeline_forced_detection reason=biometric_worker_error')
            else:
                self.scheduler.confirmed(result.frame.frame_id)
                self._last_outcome = result.outcome
                self._status = getattr(result.outcome, 'status', 'Verifying identity')
                if len(result.detections) == 1:
                    self._box = result.detections[0].box
                    self._box_source = 'detector'
                    self._detector_frame = result.frame.frame_id
                    try:
                        if not self.tracker.initialize(result.frame, self._box):
                            self.scheduler.force('tracker_initialization_failed')
                    except Exception:
                        self.scheduler.force('tracker_unavailable')
                else:
                    self._box = None
                    self._box_source = 'none'
                    self.tracker.reset()
                    if len(result.detections) > 1:
                        self.scheduler.force('multiple_faces_detected')
        tracker_valid = self._box is not None
        if self._box is not None and not applied_detector and frame.frame_id > self._detector_frame:
            previous = self._box
            try:
                tracker_started = perf_counter()
                success, current = self.tracker.update(frame)
                if self.metrics:
                    self.metrics.tick('tracker')
                    self.metrics.observe_ms('kcf_update', (perf_counter() - tracker_started) * 1000)
            except Exception:
                success, current = False, None
            check = validate_tracker_box(success, current, previous, frame.image.shape[1], frame.image.shape[0], frame.frame_id - self._detector_frame, self.validation)
            if check.valid:
                self._box = current
                self._box_source = 'tracker'
            else:
                self._box = None
                self._box_source = 'none'
                self.tracker.reset()
                force_reason=check.reasons[0] if check.reasons else 'tracker_invalid'
                self.scheduler.force(force_reason);logger.warning('tracker_reset forced_detection=true reason=%s',force_reason)
                tracker_valid = False
        pending = bool(getattr(self._last_outcome, 'force_detection', False))
        decision = self.scheduler.decide(frame.frame_id, tracker_valid=tracker_valid, authentication_pending=pending)
        if decision.run_detector:
            if decision.forced:logger.info('detector_submitted forced=true reason=%s frame_id=%s',decision.reason,frame.frame_id)
            if self.metrics and decision.forced:
                self.metrics.tick('forced_detection')
            self.worker.submit(frame)
        return PipelineView(frame, self._box, self._box_source, self._status, self._last_outcome, decision.run_detector, decision.forced, decision.reason if decision.forced else None, self.worker.dropped_frames)
