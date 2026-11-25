"""Unit tests for Hailo model loading, path configuration, and mock fallbacks."""

import unittest
from pathlib import Path
from surveillance.config import SurveillanceConfig
from surveillance.models.loader import HailoModelRunner, HailoModelManager, MockHailoModelRunner
from surveillance.models.yolox import YOLOXPersonDetector
from surveillance.models.yunet import YuNetFaceDetector
from surveillance.models.scrfd import SCRFDFaceDetector
from surveillance.models.auraface import AuraFaceEmbedder


class TestModelLoading(unittest.TestCase):

    def test_configurable_model_paths_in_config(self):
        config = SurveillanceConfig(
            person_detector_model_path=Path("custom/yolov8s.hef"),
            face_detector_model_path=Path("custom/scrfd_10g.hef"),
            face_embedder_model_path=Path("custom/arcface_r50.hef"),
        )
        self.assertEqual(config.person_detector_model_path, Path("custom/yolov8s.hef"))
        self.assertEqual(config.face_detector_model_path, Path("custom/scrfd_10g.hef"))
        self.assertEqual(config.face_embedder_model_path, Path("custom/arcface_r50.hef"))

    def test_default_model_path_resolution(self):
        config = SurveillanceConfig()
        self.assertEqual(config.camera, "adb")
        self.assertEqual(config.person_detector_model_path.name, "yolov8s.hef")
        self.assertEqual(config.face_detector_model_path.name, "scrfd_10g.hef")
        self.assertEqual(config.face_embedder_model_path.name, "arcface_r50.hef")

    def test_yolov8_hailo_nms_by_class_postprocess(self):
        detector = YOLOXPersonDetector("mock_yolov8s.hef", confidence_threshold=0.5)
        # Packed HAILO_NMS_BY_CLASS: class 0 (person) has 1 box, class 2 (car) has 1 box
        buf = np.zeros((1, 40080), dtype=np.float32)
        flat = buf[0]
        # class 0: 1 detection [ymin, xmin, ymax, xmax, score]
        flat[0] = 1.0
        flat[1:6] = [0.1, 0.2, 0.9, 0.8, 0.88]
        # class 1: 0 detections -> flat[6] = 0.0
        # class 2: 1 detection (should be filtered out because person_class_id=0)
        flat[7] = 1.0
        flat[8:13] = [0.0, 0.0, 0.5, 0.5, 0.95]

        boxes = detector.postprocess(
            {"yolov8s/yolov8_nms_postprocess": buf},
            scale=1.0,
            pad=(0, 0),
            orig_shape=(640, 640),
        )
        self.assertEqual(len(boxes), 1)
        np.testing.assert_allclose(boxes[0][:4], [128.0, 64.0, 512.0, 576.0], atol=1.0)
        self.assertAlmostEqual(float(boxes[0][4]), 0.88, places=3)

    def test_scrfd_postprocess_decodes_box_and_landmarks(self):
        detector = SCRFDFaceDetector("mock_scrfd_10g.hef", confidence_threshold=0.6)
        scores_32 = np.zeros((1, 20, 20, 2), dtype=np.float32)
        bboxes_32 = np.zeros((1, 20, 20, 8), dtype=np.float32)
        kps_32 = np.zeros((1, 20, 20, 20), dtype=np.float32)

        # Anchor 0 at cell (y=10, x=10) -> center (320, 320), stride=32
        scores_32[0, 10, 10, 0] = 0.92
        bboxes_32[0, 10, 10, 0:4] = [2.0, 2.0, 2.0, 2.0]  # 64px in each direction -> [256, 256, 384, 384]
        kps_32[0, 10, 10, 0:10] = [-1.0, -0.5, 1.0, -0.5, 0.0, 0.0, -0.5, 1.0, 0.5, 1.0]

        faces = detector.postprocess(
            {"scrfd_10g/conv56": scores_32, "scrfd_10g/conv57": bboxes_32, "scrfd_10g/conv58": kps_32},
            scale=1.0,
            pad=(0, 0),
            orig_shape=(640, 640),
        )
        self.assertEqual(len(faces), 1)
        self.assertAlmostEqual(faces[0].score, 0.92, places=3)
        np.testing.assert_allclose(faces[0].bbox, (256.0, 256.0, 384.0, 384.0), atol=1.0)
        self.assertIsNotNone(faces[0].landmarks)
        self.assertEqual(faces[0].landmarks.shape, (5, 2))
        np.testing.assert_allclose(faces[0].landmarks[2], [320.0, 320.0], atol=1.0)

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
