"""Unit tests for MiniFASNet PAD model adapter and load_pad helper."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from access_control.facial_recognition.src.config import AccessControlConfig
from access_control.facial_recognition.src.face.pad import UnavailablePAD, load_pad
from access_control.facial_recognition.src.face.pad_model_adapter import PADModel
from access_control.facial_recognition.src.face.types import DetectedFace


class TestPADModelAdapter(unittest.TestCase):
    def setUp(self):
        self.frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        self.face = DetectedFace(
            bbox=[200, 150, 300, 270],
            confidence=0.95,
        )

    def test_missing_model_file_behavior(self):
        adapter = PADModel(model_path=Path("non_existent_model.onnx"))
        self.assertIsNone(adapter.net)
        result = adapter.check(self.frame, self.face)
        self.assertEqual(result.state, "unknown")
        self.assertEqual(result.reason, "pad_model_not_loaded")

    def test_extract_crop_dimensions_and_scaling(self):
        adapter = PADModel(model_path="dummy.onnx", scale=2.7)
        crop = adapter.extract_crop(self.frame, self.face)
        self.assertIsNotNone(crop)
        self.assertEqual(crop.shape, (80, 80, 3))

    def test_extract_crop_near_boundary_pads_correctly(self):
        # Face right on the edge of the image
        boundary_face = DetectedFace(bbox=[5, 5, 80, 80], confidence=0.9)
        adapter = PADModel(model_path="dummy.onnx", scale=2.7)
        crop = adapter.extract_crop(self.frame, boundary_face)
        self.assertIsNotNone(crop)
        self.assertEqual(crop.shape, (80, 80, 3))

    def test_extract_crop_invalid_bbox_returns_none(self):
        invalid_face = DetectedFace(bbox=[100, 100, 50, 50], confidence=0.9)
        adapter = PADModel(model_path="dummy.onnx")
        crop = adapter.extract_crop(self.frame, invalid_face)
        self.assertIsNone(crop)

    def test_extract_crop_empty_frame_returns_none(self):
        empty_frame = np.empty((0, 0, 3), dtype=np.uint8)
        adapter = PADModel(model_path="dummy.onnx")
        crop = adapter.extract_crop(empty_frame, self.face)
        self.assertIsNone(crop)

    def test_check_with_mock_net_live_prediction(self):
        adapter = PADModel(model_path="dummy.onnx", threshold=0.75)
        # Mock net output with 3 classes: [print, live, replay] -> live (index 1) is dominant
        mock_net = MagicMock()
        mock_net.forward.return_value = np.array([[0.1, 3.5, 0.2]], dtype=np.float32)
        adapter.net = mock_net

        result = adapter.check(self.frame, self.face)
        self.assertEqual(result.state, "live")
        self.assertGreater(result.score, 0.75)
        self.assertEqual(result.reason, "live_face_verified")

    def test_check_with_mock_net_spoof_prediction(self):
        adapter = PADModel(model_path="dummy.onnx", threshold=0.75)
        # Mock net output with 3 classes: [print, live, replay] -> print spoof (index 0) is dominant
        mock_net = MagicMock()
        mock_net.forward.return_value = np.array([[3.5, 0.1, 0.2]], dtype=np.float32)
        adapter.net = mock_net

        result = adapter.check(self.frame, self.face)
        self.assertEqual(result.state, "spoof")
        self.assertLess(result.score, 0.75)
        self.assertEqual(result.reason, "insufficient_liveness_score")

    def test_check_with_mock_net_binary_output(self):
        adapter = PADModel(model_path="dummy.onnx", threshold=0.70)
        # 2 classes: [spoof, live]
        mock_net = MagicMock()
        mock_net.forward.return_value = np.array([[0.2, 2.0]], dtype=np.float32)
        adapter.net = mock_net

        result = adapter.check(self.frame, self.face)
        self.assertEqual(result.state, "live")
        self.assertGreater(result.score, 0.70)

    def test_check_with_mock_net_single_logit_output(self):
        adapter = PADModel(model_path="dummy.onnx", threshold=0.50)
        # 1 class sigmoid: logit 2.0 -> sigmoid ~0.88
        mock_net = MagicMock()
        mock_net.forward.return_value = np.array([[2.0]], dtype=np.float32)
        adapter.net = mock_net

        result = adapter.check(self.frame, self.face)
        self.assertEqual(result.state, "live")
        self.assertGreater(result.score, 0.80)


class TestLoadPAD(unittest.TestCase):
    def test_load_pad_returns_unavailable_when_not_configured(self):
        cfg = AccessControlConfig(pad_model_path=Path(""))
        pad = load_pad(cfg)
        self.assertIsInstance(pad, UnavailablePAD)
        res = pad.check(None, None)
        self.assertEqual(res.state, "unknown")
        self.assertEqual(res.reason, "pad_model_unavailable")

    def test_load_pad_loads_adapter_when_file_exists(self):
        with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            cfg = AccessControlConfig(
                pad_model_path=tmp_path,
                pad_model_version="test-v1",
                pad_threshold=0.80,
                pad_scale=2.7,
            )
            pad = load_pad(cfg)
            self.assertIsInstance(pad, PADModel)
            self.assertEqual(pad.model_version, "test-v1")
            self.assertEqual(pad.threshold, 0.80)
            self.assertEqual(pad.scale, 2.7)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_load_pad_raises_in_production_when_required_and_missing(self):
        cfg = AccessControlConfig(
            pad_model_path=Path("non_existent.onnx"),
            pad_required=True,
        )
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            with self.assertRaises(RuntimeError):
                load_pad(cfg)


if __name__ == "__main__":
    unittest.main()
