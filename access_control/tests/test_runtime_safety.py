import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.camera import CameraUnavailableError, OpenCVCameraSource
from app.config import AppConfig
from app.config.settings import ROOT
from app.detection import YuNetDetector
from app.domain import BoundingBox, FaceDetection, FramePacket
from app.quality import FaceQualityConfig, FaceQualityEvaluator
from app.recognition import SFaceRecognizer
from app.tracking.kcf import KCFTracker
from app.utilities import RuntimeMetrics


class ClosedCapture:
    def isOpened(self):
        return False

    def release(self):
        pass


class RuntimeSafetyTests(unittest.TestCase):
    def test_missing_camera_fails_safely(self):
        with patch('app.camera.sources.cv2.VideoCapture', return_value=ClosedCapture()):
            with self.assertRaisesRegex(CameraUnavailableError, 'camera unavailable'):
                OpenCVCameraSource(99).start()

    def test_kcf_dependency_fails_fast_when_contrib_backend_is_missing(self):
        if not KCFTracker.available():
            with self.assertRaisesRegex(RuntimeError,'opencv-contrib'):
                KCFTracker()

    def test_missing_model_files_fail_before_runtime_processing(self):
        missing = Path(tempfile.gettempdir()) / 'definitely-missing-access-model.onnx'
        with self.assertRaises(FileNotFoundError):
            YuNetDetector(missing)
        with self.assertRaises(FileNotFoundError):
            SFaceRecognizer(missing)

    def test_quality_gate_rejects_dark_blurry_detector_face(self):
        image = np.zeros((100, 100, 3), np.uint8)
        packet = FramePacket(1, time.monotonic(), image)
        detection = FaceDetection(BoundingBox(20, 20, 60, 60), np.array([[30, 35], [65, 35], [48, 50], [34, 68], [62, 68]], np.float32), .95, 1, time.monotonic())
        result = FaceQualityEvaluator(FaceQualityConfig(min_width=20, min_height=20, min_area_ratio=.01)).evaluate(packet, detection)
        self.assertFalse(result.passed)
        self.assertIn('hold_still', result.reasons)
        self.assertIn('lighting_too_dark', result.reasons)

    def test_yunet_interval_is_derived_from_configured_display_and_detector_rates(self):
        with patch.dict('os.environ',{'ACCESS_DISPLAY_FPS':'30','ACCESS_YUNET_FPS':'5'},clear=True):
            self.assertEqual(AppConfig().detector_interval,6)

    def test_relative_runtime_paths_are_anchored_to_the_standalone_module(self):
        with patch.dict('os.environ', {'ACCESS_DB_PATH':'data/test.db','ACCESS_YUNET_MODEL':'models/yunet/model.onnx'}, clear=False):
            config=AppConfig()
        self.assertEqual(config.database_path,ROOT/'data'/'test.db')
        self.assertEqual(config.yunet_model,ROOT/'models'/'yunet'/'model.onnx')

    def test_metrics_report_measured_rates_latencies_and_drops(self):
        metrics = RuntimeMetrics(enabled=True, window_seconds=2)
        metrics.tick('display', 2)
        metrics.observe_ms('yunet_inference', 7.5)
        metrics.gauge('dropped_biometric_frames', 3)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot['rates']['display_fps'], 1.0)
        self.assertEqual(snapshot['latency']['yunet_inference_ms']['last'], 7.5)
        self.assertEqual(snapshot['gauges']['dropped_biometric_frames'], 3)


if __name__ == '__main__':
    unittest.main()
