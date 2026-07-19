"""Single-owner biometric worker with bounded access frames and serialized commands."""
from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from time import perf_counter
import logging
import threading

from ..domain import FramePacket

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BiometricResult:
    frame: FramePacket
    detections: list
    outcome: object
    error: str | None = None
    elapsed_ms: float = 0.0
    yunet_ms: float = 0.0
    sface_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class _Command:
    mode: str
    frame: FramePacket
    payload: object
    response: Queue


class BiometricWorker:
    def __init__(self, detector, authentication, identity_verifier=None):
        self.detector = detector
        self.authentication = authentication
        self.identity_verifier = identity_verifier
        self._frames = Queue(maxsize=1)
        self._commands = Queue(maxsize=8)
        self._results = Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = None
        self.dropped_frames = 0

    @staticmethod
    def _snapshot(frame):
        return FramePacket(frame.frame_id, frame.captured_at, frame.image.copy(), dict(frame.metadata))

    @staticmethod
    def _latest_put(queue, item):
        try:
            queue.put_nowait(item)
            return False
        except Full:
            try:
                queue.get_nowait()
            except Empty:
                pass
            queue.put_nowait(item)
            return True

    def submit(self, frame):
        if self._latest_put(self._frames, self._snapshot(frame)):
            self.dropped_frames += 1

    def request(self, mode, frame, payload=None, timeout=10):
        if self.identity_verifier is None:
            raise RuntimeError('identity verifier is unavailable')
        response = Queue(maxsize=1)
        self._commands.put(_Command(mode, self._snapshot(frame), payload, response), timeout=min(timeout, 1))
        result = response.get(timeout=timeout)
        if result.error:
            raise RuntimeError(result.error)
        return result

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='access-biometric-worker', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def poll(self):
        latest = None
        while True:
            try:
                latest = self._results.get_nowait()
            except Empty:
                return latest

    def _run(self):
        while not self._stop.is_set():
            try:
                command = self._commands.get_nowait()
            except Empty:
                command = None
            if command is not None:
                command.response.put(self._execute(command.frame, command.mode, command.payload))
                continue
            try:
                frame = self._frames.get(timeout=.05)
            except Empty:
                continue
            self._latest_put(self._results, self._execute(frame, 'access', None))

    def _execute(self, frame, mode, payload):
        started = perf_counter()
        try:
            detections = self.detector.detect(frame)
            if mode == 'access':
                service = self.authentication
                outcome = service.process_detector_frame(frame, detections)
            elif mode == 'identity':
                service = self.identity_verifier
                outcome = service.verify(frame, detections)
            elif mode == 'presence':
                service = self.identity_verifier
                outcome = service.presence(frame, detections, payload)
            else:
                raise ValueError(f'unknown biometric mode: {mode}')
            return BiometricResult(
                frame,
                detections,
                outcome,
                elapsed_ms=(perf_counter() - started) * 1000,
                yunet_ms=getattr(self.detector, 'last_inference_ms', 0.0),
                sface_ms=getattr(getattr(service, 'recognizer', None), 'last_inference_ms', 0.0),
            )
        except Exception as exc:
            logger.exception('biometric worker failure in %s mode', mode)
            return BiometricResult(frame, [], None, str(exc), (perf_counter() - started) * 1000)
