"""Regression tests for Workstream 4 surveillance pipeline, model, database, and tracking fixes."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from surveillance.config import SurveillanceConfig
from surveillance.database import SurveillanceUserRepository
from surveillance.models.yolox import YOLOXPersonDetector
from surveillance.models.yunet import YuNetDetectedFace, _decode_yunet_raw_heads
from surveillance.pipeline import SurveillancePipeline
from surveillance.tracking.bytetrack import ByteTracker, STrack
from surveillance.utils.alignment import FaceAligner
from surveillance.utils.camera import CameraReader
from surveillance.utils.matching import FaceTemplate, TemplateMatcher


class _CropRejectingFaceDetector:
    """Returns empty for smaller person crops, returns a face only if given the full frame."""

    def detect(self, image: np.ndarray):
        if image.shape[:2] == (640, 640):
            return [
                YuNetDetectedFace(
                    bbox=(420, 420, 500, 500),
                    score=0.95,
                    landmarks=np.array([[435, 440], [475, 440], [455, 460], [440, 480], [470, 480]], dtype=np.float32),
                )
            ]
        return []


class Workstream4RegressionTests(unittest.TestCase):
    def test_no_cross_person_full_frame_fallback_and_template_reload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "surv.db"
            repo = SurveillanceUserRepository(db_path)
            vec = np.ones((512,), dtype=np.float32)
            vec /= np.linalg.norm(vec)

            person_det = MagicMock()
            person_det.detect.return_value = [np.array([10, 10, 110, 210, 0.9], dtype=np.float32)]
            embedder = MagicMock()
            embedder.embed.return_value = vec

            pipeline = SurveillancePipeline(
                person_detector=person_det,
                face_detector=_CropRejectingFaceDetector(),
                embedder=embedder,
                repository=repo,
                config=SurveillanceConfig(database_path=db_path, snapshot_enabled=False, person_detection_threshold=0.3),
            )

            # Initial template load is empty
            self.assertEqual(pipeline.load_templates(), [])

            # Delta update writes new auraface template; load_templates must auto-reload without force_reload=True
            repo.apply_delta([
                {
                    "user_id": 5,
                    "is_active": 1,
                    "embeddings": [{"model_name": "auraface", "template_name": "front", "embedding": vec.tobytes()}],
                }
            ])
            reloaded = pipeline.load_templates()
            self.assertEqual(len(reloaded), 1)
            self.assertEqual(reloaded[0].user_id, "5")

            # Verify stored model_name preserved as 'auraface'
            conn = sqlite3.connect(db_path)
            model_name = conn.execute("SELECT model_name FROM device_user_face_embeddings WHERE user_id = 5").fetchone()[0]
            conn.close()
            self.assertEqual(model_name, "auraface")

            # Faceless person crop must NOT fall back to full frame to hijack user 5's identity
            frame = np.zeros((640, 640, 3), dtype=np.uint8)
            res = pipeline.process_frame(frame)
            self.assertEqual(len(res["results"]), 1)
            self.assertEqual(res["results"][0]["status"], "unknown")
            embedder.embed.assert_not_called()

    def test_yolox_filters_non_person_classes_and_yunet_dynamic_grids(self):
        yolox = YOLOXPersonDetector("mock_yolox.hef")
        self.assertFalse(yolox.ignore_class_id)

        # Two boxes: [class_id=2 (car), score=0.95] and [class_id=0 (person), score=0.90]
        raw = np.array([
            [0.1, 0.1, 0.5, 0.5, 2.0, 0.95],
            [0.2, 0.2, 0.6, 0.6, 0.0, 0.90],
        ], dtype=np.float32)
        boxes = yolox.postprocess({"nms": raw}, scale=1.0, pad=(0, 0), orig_shape=(640, 640))
        self.assertEqual(len(boxes), 1)
        self.assertAlmostEqual(float(boxes[0][4]), 0.90, places=3)

        # Zero-area boxes in _nms should not produce NaN warnings/failures
        kept = yolox._nms([
            np.array([10.0, 10.0, 10.0, 10.0, 0.9], dtype=np.float32),
            np.array([20.0, 20.0, 50.0, 50.0, 0.8], dtype=np.float32),
        ])
        self.assertEqual(len(kept), 2)

        # YuNet 320x320 grid dimensions -> stride 32 is 10x10 (100 cells)
        conf_32 = np.zeros((10, 10, 1), dtype=np.float32)
        conf_32[5, 4, 0] = 0.95
        bbox_32 = np.zeros((10, 10, 4), dtype=np.float32)
        bbox_32[5, 4] = [0.0, 0.0, 1.5, 1.5]
        faces = _decode_yunet_raw_heads(
            {"activation2": conf_32, "format_conversion1": bbox_32},
            input_size=(320, 320),
            confidence_threshold=0.8,
            orig_shape=(640, 640),
        )
        self.assertEqual(len(faces), 1)
        cx = (faces[0].x1 + faces[0].x2) * 0.5
        cy = (faces[0].y1 + faces[0].y2) * 0.5
        self.assertAlmostEqual(cx, 4 * 32 * 2.0, delta=5.0)
        self.assertAlmostEqual(cy, 5 * 32 * 2.0, delta=5.0)

    def test_camera_matching_alignment_and_bytetrack_guards(self):
        cam = CameraReader()
        cam.cap = MagicMock()
        cam.cap.grab.return_value = True
        dummy_frame = np.zeros((10, 10, 3), dtype=np.uint8)
        cam.cap.retrieve.return_value = (True, dummy_frame)
        ok, frame = cam.read_latest()
        self.assertTrue(ok)
        self.assertIsNotNone(frame)
        cam.cap.grab.assert_called_once()

        # Mismatched dimensions skipped safely
        matcher = TemplateMatcher(threshold=0.5)
        bad_tpl = FaceTemplate("1", "u1", "front", np.ones((128,), dtype=np.float32))
        good_tpl = FaceTemplate("2", "u2", "front", np.ones((512,), dtype=np.float32))
        res = matcher.match(np.ones((512,), dtype=np.float32), [bad_tpl, good_tpl])
        self.assertTrue(res.matched)
        self.assertEqual(res.user_id, "2")

        # Scaled alignment landmarks for 224x224 target_size
        aligner = FaceAligner(target_size=(224, 224))
        img = np.zeros((300, 300, 3), dtype=np.uint8)
        lms = np.array([[76, 103], [147, 103], [112, 143], [83, 184], [141, 184]], dtype=np.float32)
        aligned = aligner.align(img, (20, 20, 220, 220), landmarks=lms)
        self.assertTrue(aligned.success)
        self.assertEqual(aligned.aligned_face.shape[:2], (224, 224))

        # ByteTrack zero-height & removed_stracks cap
        xyah = STrack.tlwh_to_xyah(np.array([10.0, 20.0, 30.0, 0.0], dtype=np.float32))
        self.assertEqual(float(xyah[2]), 0.0)
        tracker = ByteTracker()
        tracker.removed_stracks = [STrack([0, 0, 10, 10], 0.9) for _ in range(1100)]
        tracker.update([])
        self.assertLessEqual(len(tracker.removed_stracks), 1000)
