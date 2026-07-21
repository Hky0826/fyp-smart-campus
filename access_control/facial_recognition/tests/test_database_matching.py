import base64
import json
import sqlite3
import unittest
from pathlib import Path

import numpy as np

from access_control.facial_recognition.src.face.database import DeviceUserRepository
from access_control.facial_recognition.src.face.matching import FaceTemplate, TemplateMatcher
from access_control.facial_recognition.src.sync import SQLiteEdgeDB


def remove_sqlite_files(db_path: Path):
    for path in (db_path, db_path.with_name(f"{db_path.name}-wal"), db_path.with_name(f"{db_path.name}-shm")):
        if path.exists():
            path.unlink()


class DatabaseAndMatchingTests(unittest.TestCase):
    def test_database_loader_reads_multiple_embeddings_from_device_users(self):
        db_path = Path.cwd() / "edge" / "tests" / "_device_users_test.db"
        remove_sqlite_files(db_path)
        try:
            SQLiteEdgeDB(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("INSERT INTO device_users (user_id, is_active) VALUES (?, ?)", (1, 1))
            conn.execute(
                """
                INSERT INTO device_user_face_embeddings (user_id, template_name, model_name, embedding)
                VALUES (?, ?, ?, ?)
                """,
                (1, "front", "arcface_mobilefacenet", np.array([1.0, 0.0], dtype=np.float32).tobytes()),
            )
            conn.execute(
                """
                INSERT INTO device_user_face_embeddings (user_id, template_name, model_name, embedding)
                VALUES (?, ?, ?, ?)
                """,
                (1, "left_30", "arcface_mobilefacenet", np.array([0.0, 1.0], dtype=np.float32).tobytes()),
            )
            conn.commit()
            conn.close()

            templates = DeviceUserRepository(db_path).load_templates()
        finally:
            remove_sqlite_files(db_path)

        self.assertEqual(len(templates), 2)
        self.assertEqual({template.template_name for template in templates}, {"front", "left_30"})
        self.assertEqual({template.user_id for template in templates}, {"1"})

    def test_sync_delta_writes_embeddings_to_updated_sqlite_schema(self):
        db_path = Path.cwd() / "edge" / "tests" / "_device_sync_test.db"
        remove_sqlite_files(db_path)
        try:
            db = SQLiteEdgeDB(db_path)
            vector = np.array([0.0, 1.0], dtype=np.float32).tobytes()

            db.save_users_delta(
                [
                    {
                        "user_id": 7,
                        "is_active": 1,
                        "face_embeddings": [
                            {
                                "template_name": "right_60",
                                "model_name": "arcface_r50",
                                "embedding_b64": base64.b64encode(vector).decode("ascii"),
                            }
                        ],
                    }
                ]
            )

            templates = DeviceUserRepository(db_path).load_templates()
        finally:
            remove_sqlite_files(db_path)

        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0].user_id, "7")
        self.assertEqual(templates[0].template_name, "right_60")

    def test_sync_init_migrates_legacy_face_vector_to_embedding_table(self):
        db_path = Path.cwd() / "edge" / "tests" / "_device_legacy_test.db"
        remove_sqlite_files(db_path)
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE device_users (
                    user_id INTEGER PRIMARY KEY NOT NULL,
                    template_name TEXT,
                    face_vector BLOB NOT NULL,
                    is_active INTEGER DEFAULT 1 NOT NULL,
                    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "INSERT INTO device_users (user_id, template_name, face_vector, is_active) VALUES (?, ?, ?, ?)",
                (9, "low_light", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 1),
            )
            conn.commit()
            conn.close()

            SQLiteEdgeDB(db_path)
            templates = DeviceUserRepository(db_path).load_templates()
        finally:
            remove_sqlite_files(db_path)

        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0].user_id, "9")
        self.assertEqual(templates[0].template_name, "low_light")

    def test_repository_logs_auth_event_with_sync_key(self):
        db_path = Path.cwd() / "edge" / "tests" / "_device_auth_log_test.db"
        remove_sqlite_files(db_path)
        try:
            SQLiteEdgeDB(db_path)
            DeviceUserRepository(db_path).log_auth_event("7", "SUCCESS", 0.91)

            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT sync_key, auth_status, sync_status FROM device_auth_logs").fetchone()
            conn.close()
        finally:
            remove_sqlite_files(db_path)

        self.assertIsNotNone(row)
        self.assertEqual(len(row[0]), 26)
        self.assertEqual(row[1], "SUCCESS")
        self.assertEqual(row[2], 0)

    def test_repository_logs_surveillance_event_with_sync_key(self):
        db_path = Path.cwd() / "edge" / "tests" / "_device_surveillance_log_test.db"
        remove_sqlite_files(db_path)
        try:
            SQLiteEdgeDB(db_path)
            DeviceUserRepository(db_path).log_surveillance_event(
                "7",
                "RECOGNIZED",
                0.91,
                matched_template="front",
                face_count=2,
                bbox=[10, 20, 80, 100],
                image_path="surveillance/test.jpg",
                timestamp="2026-06-23T00:00:00+00:00",
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT sync_key, user_id, recognition_status, matched_template, face_count, bbox, image_path, sync_status
                FROM device_surveillance_logs
                """
            ).fetchone()
            conn.close()
        finally:
            remove_sqlite_files(db_path)

        self.assertIsNotNone(row)
        self.assertEqual(len(row[0]), 26)
        self.assertEqual(row[1], 7)
        self.assertEqual(row[2], "RECOGNIZED")
        self.assertEqual(row[3], "front")
        self.assertEqual(row[4], 2)
        self.assertEqual(json.loads(row[5]), [10, 20, 80, 100])
        self.assertEqual(row[6], "surveillance/test.jpg")
        self.assertEqual(row[7], 0)

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
