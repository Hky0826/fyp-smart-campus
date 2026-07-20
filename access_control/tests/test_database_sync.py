import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SQLiteIdentityRepository
from app.domain import Embedding
from app.synchronization import BackgroundDatabaseSyncService, SyncConfig


class Response:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


class FakeHTTP:
    def __init__(self):
        self.fail = False
        self.posts = []

    def get(self, url, **kwargs):
        if self.fail:
            raise OSError("offline")
        if url.endswith("user-ids"):
            return Response(200, [1])
        return Response(
            200,
            {
                "users": [],
                "roles": [],
                "user_roles": [],
                "node_rbac": [],
                "timestamp": "2026-01-01T00:00:00Z",
            },
        )

    def post(self, url, **kwargs):
        if self.fail:
            raise OSError("offline")
        self.posts.append((url, kwargs))
        count = len(kwargs.get("json", {}).get("logs", []))
        return Response(200, {"successful_indices": list(range(count))})


class DatabaseSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "device_local.db"

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def emb(frame=1):
        return Embedding(np.array([1, 0, 0, 0], np.float32), "opencv_sface", "2021dec", 4, frame, 1.0)

    @staticmethod
    def schema_signature(script_path):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(Path(script_path).read_text(encoding="utf-8"))
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            columns = {
                table: [tuple(row[1:6]) for row in conn.execute(f"PRAGMA table_info({table})")]
                for table in tables
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
                )
            }
            return tables, columns, indexes
        finally:
            conn.close()

    def test_access_schema_matches_edge_shape(self):
        repo_root = Path(__file__).resolve().parents[2]
        access_schema = repo_root / "access_control" / "app" / "database" / "schema.sql"
        edge_schema = repo_root / "edge" / "facial_recognition" / "setup_sqlite.sql"
        self.assertEqual(self.schema_signature(access_schema), self.schema_signature(edge_schema))

    def test_cloud_delivered_sface_embedding_is_stored_and_matched(self):
        repo = SQLiteIdentityRepository(self.path)
        repo.save_users_delta(
            [
                {
                    "user_id": 1,
                    "is_active": True,
                    "embeddings": [
                        {
                            "template_name": "cloud-template",
                            "model_name": "opencv_sface",
                            "model_version": "2021dec",
                            "embedding_dimension": 4,
                            "embedding": [1, 0, 0, 0],
                        }
                    ],
                }
            ]
        )
        match = repo.find_match(self.emb(), 0.9)
        self.assertIsNotNone(match)
        self.assertEqual(match.identity_id, "1")
        self.assertEqual(repo.status()["sface_templates"], 1)

    def test_embedding_table_uses_sface_model_constraint(self):
        repo = SQLiteIdentityRepository(self.path)
        with self.assertRaises(sqlite3.IntegrityError):
            repo.save_users_delta(
                [
                    {
                        "user_id": 1,
                        "embeddings": [
                            {"model_name": "arcface_r50", "embedding": [1, 0, 0, 0]}
                        ],
                    }
                ]
            )

    def test_explicit_empty_cloud_template_list_clears_local_templates(self):
        repo = SQLiteIdentityRepository(self.path)
        repo.save_users_delta(
            [
                {
                    "user_id": 1,
                    "embeddings": [{"model_name": "opencv_sface", "embedding": [1, 0, 0, 0]}],
                }
            ]
        )
        repo.save_users_delta([{"user_id": 1, "embeddings": []}])
        self.assertEqual(repo.status()["sface_templates"], 0)
        self.assertIsNone(repo.find_match(self.emb()))

    def test_offline_authentication_logs_remain_chronological_and_replay(self):
        repo = SQLiteIdentityRepository(self.path)
        repo.log_authentication_event(None, "FAILED", 0.1, timestamp="2026-01-01T00:00:02Z")
        repo.log_authentication_event(None, "FAILED", 0.2, timestamp="2026-01-01T00:00:01Z")
        self.assertEqual([item["confidence_score"] for item in repo.get_unsynced_logs()], [0.2, 0.1])
        http = FakeHTTP()
        service = BackgroundDatabaseSyncService(repo, SyncConfig("http://cloud", "gate", "Gate"), http)
        self.assertTrue(service.replay_pending_authentication_logs())
        self.assertEqual(repo.get_unsynced_logs(), [])

    def test_surveillance_logs_are_retained_ordered_and_replayed(self):
        repo = SQLiteIdentityRepository(self.path)
        repo.log_surveillance_event(
            None,
            "UNKNOWN",
            0.2,
            face_count=2,
            bbox={"x": 2, "y": 3, "width": 4, "height": 5},
            timestamp="2026-01-01T00:00:02Z",
        )
        repo.log_surveillance_event(
            None,
            "UNKNOWN",
            0.1,
            timestamp="2026-01-01T00:00:01Z",
        )
        pending = repo.get_unsynced_surveillance_logs()
        self.assertEqual([item["confidence_score"] for item in pending], [0.1, 0.2])
        self.assertEqual(pending[1]["bbox"]["width"], 4)
        self.assertEqual(repo.status()["pending_surveillance_logs"], 2)

        http = FakeHTTP()
        service = BackgroundDatabaseSyncService(repo, SyncConfig("http://cloud", "gate", "Gate"), http)
        self.assertTrue(service.replay_pending_surveillance_logs())
        self.assertEqual(repo.get_unsynced_surveillance_logs(), [])
        self.assertTrue(http.posts[-1][0].endswith("/api/sync/upstream/surveillance-logs"))

    def test_network_failure_is_contained(self):
        repo = SQLiteIdentityRepository(self.path)
        http = FakeHTTP()
        http.fail = True
        service = BackgroundDatabaseSyncService(repo, SyncConfig("http://cloud", "gate", "Gate"), http)
        self.assertFalse(service.perform_downstream_sync())
        self.assertEqual(service.status(), "offline")
        self.assertIn("offline", service.last_error)


if __name__ == "__main__":
    unittest.main()