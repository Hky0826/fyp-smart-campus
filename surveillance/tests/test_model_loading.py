"""Unit tests for Hailo model loading, path configuration, and mock fallbacks."""

import unittest
from pathlib import Path
from surveillance.config import SurveillanceConfig
from surveillance.models.loader import HailoModelRunner, HailoModelManager, MockHailoModelRunner
from surveillance.models.yolox import YOLOXPersonDetector
from surveillance.models.yunet import YuNetFaceDetector
from surveillance.models.auraface import AuraFaceEmbedder


class TestModelLoading(unittest.TestCase):

    def test_configurable_model_paths_in_config(self):
        config = SurveillanceConfig(
            person_detector_model_path=Path("custom/yolox.hef"),
            face_detector_model_path=Path("custom/yunet.hef"),
            face_embedder_model_path=Path("custom/auraface.hef"),
        )
        self.assertEqual(config.person_detector_model_path, Path("custom/yolox.hef"))
        self.assertEqual(config.face_detector_model_path, Path("custom/yunet.hef"))
        self.assertEqual(config.face_embedder_model_path, Path("custom/auraface.hef"))

    def test_default_model_path_resolution(self):
        config = SurveillanceConfig()
        self.assertTrue(config.person_detector_model_path.name.endswith("yolox_m_hailo8.hef"))
        self.assertTrue(config.face_detector_model_path.name.endswith("yunet_hailo8.hef"))
        self.assertTrue(config.face_embedder_model_path.name.endswith("auraface_hailo8.hef"))

    def test_mock_hailo_runner_fallback_when_path_missing(self):
        runner = HailoModelRunner("non_existent_model.hef", allow_mock=True)
        self.assertTrue(runner.is_mock)
        output = runner.infer(np.zeros((1, 3, 640, 640), dtype=np.float32))
        self.assertIn("output_0", output)

    def test_runner_error_handling_when_mock_disallowed(self):
        with self.assertRaises((FileNotFoundError, RuntimeError)):
            HailoModelRunner("non_existent_model.hef", allow_mock=False)

    def test_hailo_model_manager(self):
        manager = HailoModelManager(allow_mock=True)
        yolox_runner = manager.load_model("yolox", "models/yolox_m.hef")
        self.assertIsNotNone(yolox_runner)
        self.assertEqual(manager.get_runner("yolox"), yolox_runner)

    def test_model_adapters_with_mock_runners(self):
        yolox = YOLOXPersonDetector("models/yolox_m.hef")
        yunet = YuNetFaceDetector("models/yunet.hef")
        auraface = AuraFaceEmbedder("models/auraface.hef")

        self.assertIsNotNone(yolox.runner)
        self.assertIsNotNone(yunet.runner)
        self.assertIsNotNone(auraface.runner)


import numpy as np

if __name__ == "__main__":
    unittest.main()
