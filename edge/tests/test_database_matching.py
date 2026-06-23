import sqlite3
import unittest
from pathlib import Path

import numpy as np

from edge.src.face.database import DeviceUserRepository
from edge.src.face.matching import FaceTemplate, TemplateMatcher


class DatabaseAndMatchingTests(unittest.TestCase):
    def test_database_loader_reads_multiple_embeddings_from_device_users(self):
        db_path = Path.cwd() / "edge" / "tests" / "_device_users_test.db"
        if db_path.exists():
            db_path.unlink()
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE device_users (user_id TEXT, template_name TEXT, face_vector BLOB, is_active INTEGER)"
            )
            conn.execute(
                "INSERT INTO device_users VALUES (?, ?, ?, ?)",
                ("user_001", "front", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 1),
            )
            conn.execute(
                "INSERT INTO device_users VALUES (?, ?, ?, ?)",
                ("user_001", "left_30", np.array([0.0, 1.0], dtype=np.float32).tobytes(), 1),
            )
            conn.commit()
            conn.close()

            templates = DeviceUserRepository(db_path).load_templates()
        finally:
            if db_path.exists():
                db_path.unlink()

        self.assertEqual(len(templates), 2)
        self.assertEqual({template.template_name for template in templates}, {"front", "left_30"})
        self.assertEqual({template.user_id for template in templates}, {"user_001"})

    def test_matcher_best_score_per_user_multi_template(self):
        matcher = TemplateMatcher(threshold=0.8)
        templates = [
            FaceTemplate("user_001", np.array([1.0, 0.0]), "front"),
            FaceTemplate("user_001", np.array([0.0, 1.0]), "low_light"),
            FaceTemplate("user_002", np.array([0.7, 0.7]), "front"),
        ]

        result = matcher.match(np.array([0.0, 1.0]), templates)

        self.assertTrue(result.matched)
        self.assertEqual(result.user_id, "user_001")
        self.assertEqual(result.matched_template, "low_light")


if __name__ == "__main__":
    unittest.main()
