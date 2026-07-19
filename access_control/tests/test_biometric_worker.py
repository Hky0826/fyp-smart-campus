import sys
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import BoundingBox, FaceDetection, FramePacket
from app.services import BiometricWorker


def frame(frame_id):
    return FramePacket(frame_id, time.monotonic(), np.zeros((32, 32, 3), np.uint8))


class Detector:
    def __init__(self):
        self.calls = []

    def detect(self, packet):
        self.calls.append(packet.frame_id)
        return [FaceDetection(BoundingBox(2, 2, 16, 16), np.zeros((5, 2), np.float32), .9, packet.frame_id, time.monotonic())]


class Authentication:
    def process_detector_frame(self, packet, detections):
        return ('access', packet.frame_id)


class Verifier:
    def verify(self, packet, detections):
        return ('identity', packet.frame_id)

    def presence(self, packet, detections, reference):
        return ('presence', packet.frame_id, reference)


class BiometricWorkerTests(unittest.TestCase):
    def test_worker_serializes_all_device_biometric_modes_through_one_detector(self):
        detector = Detector()
        worker = BiometricWorker(detector, Authentication(), Verifier())
        worker.start()
        try:
            self.assertEqual(worker.request('identity', frame(1)).outcome, ('identity', 1))
            self.assertEqual(worker.request('presence', frame(2), 'owner').outcome, ('presence', 2, 'owner'))
            worker.submit(frame(3))
            deadline = time.monotonic() + 1
            result = None
            while result is None and time.monotonic() < deadline:
                result = worker.poll()
                time.sleep(.01)
            self.assertIsNotNone(result)
            self.assertEqual(result.outcome, ('access', 3))
            self.assertEqual(detector.calls, [1, 2, 3])
        finally:
            worker.stop()


if __name__ == '__main__':
    unittest.main()
