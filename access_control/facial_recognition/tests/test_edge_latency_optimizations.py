import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from access_control.facial_recognition.src.camera.camera_reader import CameraReader
from access_control.facial_recognition.src.config import AccessControlConfig
from access_control.facial_recognition.src.face.database import DeviceUserRepository
from access_control.facial_recognition.src.face.detection import YuNetDetector
from access_control.facial_recognition.src.sync import SQLiteEdgeDB


def remove_sqlite_files(db_path: Path):
    for path in (db_path, db_path.with_name(f"{db_path.name}-wal"), db_path.with_name(f"{db_path.name}-shm")):
        if path.exists():
            path.unlink()


class EdgeLatencyOptimizationTests(unittest.TestCase):
    def test_config_latency_optimized_defaults(self):
        config = AccessControlConfig()
        self.assertEqual(config.detector_max_dim, 640)
        self.assertEqual(config.min_embedding_samples, 2)
        self.assertEqual(config.min_stable_frames, 2)
        self.assertEqual(config.min_stable_duration_ms, 100)
        self.assertEqual(config.spoof_history_size, 4)

    def test_camera_reader_defaults_to_720p(self):
        reader = CameraReader()
        self.assertEqual(reader.width, 1280)
        self.assertEqual(reader.height, 720)

    def test_device_user_repository_caches_templates_in_memory(self):
        db_path = Path.cwd() / "edge" / "tests" / "_template_cache_test.db"
        remove_sqlite_files(db_path)
        try:
            SQLiteEdgeDB(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute("INSERT INTO device_users (user_id, is_active) VALUES (?, ?)", (1, 1))
            conn.execute(
                """
                INSERT INTO device_user_face_embeddings (user_id, template_name, model_name, embedding)
                VALUES (?, ?, ?, ?)
                """,
                (1, "front", "openvc_sface", np.array([1.0, 0.0], dtype=np.float32).tobytes()),
            )
            conn.commit()
            conn.close()

            repo = DeviceUserRepository(db_path)
            # First load populates cache
            templates1 = repo.load_templates()
            self.assertEqual(len(templates1), 1)

            # Second load should return from in-memory cache without hitting DB
            with patch.object(repo, "_connect", side_effect=AssertionError("Should not connect to SQLite when cached")):
                templates2 = repo.load_templates()
                self.assertEqual(len(templates2), 1)
                self.assertEqual(templates1[0].user_id, templates2[0].user_id)

            # Invalidation forces DB reconnect
            repo.invalidate_cache()
            templates3 = repo.load_templates()
            self.assertEqual(len(templates3), 1)
        finally:
            remove_sqlite_files(db_path)

    @patch("cv2.FaceDetectorYN.create")
    def test_yunet_detector_downscales_large_frames(self, mock_create):
        mock_cv_detector = MagicMock()
        mock_create.return_value = mock_cv_detector

        # Dummy detection row: [x, y, w, h, 10 landmarks (5 pairs), score]
        # Coordinates relative to 640x360 downscaled frame
        # Box: x=100, y=50, w=120, h=140
        landmarks = [130, 80, 190, 80, 160, 110, 140, 150, 180, 150]
        dummy_row = np.array([100.0, 50.0, 120.0, 140.0] + landmarks + [0.95], dtype=np.float32)
        mock_cv_detector.detect.return_value = (None, np.array([dummy_row]))

        detector = YuNetDetector(
            model_path=Path(__file__).resolve(),  # any existing file
            max_dim=640,
        )

        # 1080p frame (1920x1080)
        large_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        faces = detector.detect(large_frame)

        self.assertEqual(len(faces), 1)
        face = faces[0]

        # Downscale ratio was 1920 / 640 = 3.0, 1080 / 360 = 3.0
        # Check that coordinates were scaled back by 3.0
        expected_x1 = 100.0 * 3.0  # 300
        expected_y1 = 50.0 * 3.0   # 150
        expected_x2 = (100.0 + 120.0) * 3.0  # 660
        expected_y2 = (50.0 + 140.0) * 3.0   # 570

        self.assertAlmostEqual(face.bbox[0], expected_x1, places=1)
        self.assertAlmostEqual(face.bbox[1], expected_y1, places=1)
        self.assertAlmostEqual(face.bbox[2], expected_x2, places=1)
        self.assertAlmostEqual(face.bbox[3], expected_y2, places=1)

        # Verify landmarks were scaled back by 3.0
        self.assertAlmostEqual(face.landmarks[0][0], 130.0 * 3.0, places=1)
        self.assertAlmostEqual(face.landmarks[0][1], 80.0 * 3.0, places=1)


if __name__ == "__main__":
    unittest.main()
