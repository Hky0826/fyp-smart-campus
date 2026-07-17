# sync/test_sync.py

import os
import sys
import unittest
import sqlite3
import base64
import numpy as np
import datetime
import shutil

# Configure paths
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from edge.facial_recognition.src.sync import SQLiteEdgeDB, DownstreamSyncWorker

class TestDatabaseSynchronization(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_device_local.db"
        # Ensure clean database environment
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
            
        cls.db_dir = os.path.dirname(os.path.abspath(cls.db_path))
        # WAL mode files
        for ext in ["-wal", "-shm"]:
            fpath = cls.db_path + ext
            if os.path.exists(fpath):
                os.remove(fpath)

    def setUp(self):
        # We instantiate the DB which triggers table initializations
        self.db = SQLiteEdgeDB(self.db_path)

    def tearDown(self):
        # Clean up database tables between tests
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS device_auth_logs")
        cursor.execute("DROP TABLE IF EXISTS device_surveillance_logs")
        cursor.execute("DROP TABLE IF EXISTS device_user_face_embeddings")
        cursor.execute("DROP TABLE IF EXISTS device_user_roles")
        cursor.execute("DROP TABLE IF EXISTS device_node_rbac")
        cursor.execute("DROP TABLE IF EXISTS device_roles")
        cursor.execute("DROP TABLE IF EXISTS device_users")
        cursor.execute("DROP TABLE IF EXISTS device_info")
        cursor.execute("DROP TABLE IF EXISTS sync_metadata")
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        # Remove the file completely
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except PermissionError:
                pass
        for ext in ["-wal", "-shm"]:
            fpath = cls.db_path + ext
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except PermissionError:
                    pass

    def test_schema_initialization(self):
        """
        Verify that all 6 specifying tables and metadata table are correctly initialized with required schemas.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cursor.fetchall()]
        conn.close()
        
        required_tables = [
            "device_users", "device_roles", "device_user_roles", 
            "device_user_face_embeddings", "device_auth_logs", "device_surveillance_logs",
            "device_info", "device_node_rbac", "sync_metadata"
        ]
        
        for table in required_tables:
            self.assertIn(table, tables, f"Table {table} was not created by the SQLite db manager.")

    def test_numpy_vector_serialization_and_deserialization(self):
        """
        Verify high-dimensional float32 vector NumPy transformations to bytes (BLOB) and transit.
        """
        # Create a mock 512-dim Float32 vector
        np.random.seed(42)
        original_vector = np.random.rand(512).astype(np.float32)
        
        # Serialize to bytes (representing BLOB storage)
        vector_bytes = original_vector.tobytes()
        self.assertEqual(len(vector_bytes), 512 * 4) # 512 floats * 4 bytes/float = 2048 bytes
        
        # Encode to Base64 (representing transit payload)
        b64_encoded = base64.b64encode(vector_bytes).decode('utf-8')
        
        # Decode and reconstruct
        decoded_bytes = base64.b64decode(b64_encoded)
        reconstructed_vector = np.frombuffer(decoded_bytes, dtype=np.float32)
        
        self.assertTrue(np.allclose(original_vector, reconstructed_vector))

    def test_downstream_user_profile_and_role_deltas(self):
        """
        Verify that downstream delta sync payload processes correctly into the local SQLite database.
        """
        # Seed mock face vector
        mock_vec = np.ones(512, dtype=np.float32) * 0.5
        mock_b64 = base64.b64encode(mock_vec.tobytes()).decode('utf-8')
        
        users_payload = [
            {"user_id": 10, "face_vector_b64": mock_b64, "is_active": 1},
            {"user_id": 11, "face_vector_b64": mock_b64, "is_active": 1}
        ]
        roles_payload = [
            {"role_id": 1, "role_name": "STUDENT"},
            {"role_id": 2, "role_name": "LECTURER"}
        ]
        
        # Execute updates
        self.db.save_roles_delta(roles_payload)
        self.db.save_users_delta(users_payload)
        
        # Check database directly
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id, is_active FROM device_users")
        users = cursor.fetchall()
        self.assertEqual(len(users), 2)
        self.assertEqual(users[0][0], 10)
        self.assertEqual(users[0][1], 1)
        
        # Check reconstructed vector from device_user_face_embeddings
        cursor.execute("SELECT embedding FROM device_user_face_embeddings WHERE user_id = 10")
        db_face_bytes = cursor.fetchone()[0]
        db_vector = np.frombuffer(db_face_bytes, dtype=np.float32)
        self.assertTrue(np.allclose(db_vector, mock_vec))
        
        cursor.execute("SELECT role_id, role_name FROM device_roles")
        roles = cursor.fetchall()
        self.assertEqual(len(roles), 2)
        self.assertEqual(roles[0][1], "STUDENT")
        
        conn.close()

    def test_instantaneous_deactivation_gate(self):
        """
        Verify that immediate access deactivation update commits instantly to the database.
        """
        # Save a user initially active
        users_payload = [{"user_id": 42, "face_vector_b64": "AAAA", "is_active": 1}]
        self.db.save_users_delta(users_payload)
        
        # Deactivate
        deactivated = self.db.deactivate_user_instantly(42)
        self.assertTrue(deactivated)
        
        # Verify status
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM device_users WHERE user_id = 42")
        row = cursor.fetchone()
        conn.close()
        
        self.assertEqual(row[0], 0, "Instantaneous deactivation did not toggle user state to 0.")

    def test_offline_buffering_and_chronological_replay(self):
        """
        Verify that offline authentications log locally with sync_status=0 and replay in order.
        """
        # Seed user 10 to satisfy SQLite FK constraint
        users_payload = [{"user_id": 10, "face_vector_b64": "AAAA", "is_active": 1}]
        self.db.save_users_delta(users_payload)

        # 1. Log two authentications offline
        time_1 = datetime.datetime.utcnow() - datetime.timedelta(seconds=10)
        time_2 = datetime.datetime.utcnow()
        
        log_id_1 = self.db.log_authentication_event(user_id=10, auth_status="SUCCESS", confidence_score=0.92, timestamp=time_1)
        log_id_2 = self.db.log_authentication_event(user_id=None, auth_status="FAILED", confidence_score=0.34, timestamp=time_2)
        
        # 2. Verify both logs are in pending state
        pending = self.db.get_unsynced_logs()
        self.assertEqual(len(pending), 2)
        
        # Verify chronological order (log_id_1 before log_id_2)
        self.assertEqual(pending[0]["log_id"], log_id_1)
        self.assertEqual(pending[1]["log_id"], log_id_2)
        self.assertEqual(pending[0]["auth_status"], "SUCCESS")
        self.assertEqual(pending[1]["auth_status"], "FAILED")
        
        # 3. Simulate confirmation upload for log_id_1 only
        self.db.mark_logs_as_synced([log_id_1])
        
        # Check pending queue again
        remaining = self.db.get_unsynced_logs()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["log_id"], log_id_2)
        
        # 4. Clear the queue
        self.db.mark_logs_as_synced([log_id_2])
        self.assertEqual(len(self.db.get_unsynced_logs()), 0)

    def test_surveillance_buffering_and_replay_status(self):
        users_payload = [{"user_id": 10, "face_vector_b64": "AAAA", "is_active": 1}]
        self.db.save_users_delta(users_payload)

        timestamp = datetime.datetime.utcnow()
        log_id = self.db.log_surveillance_event(
            user_id=10,
            recognition_status="RECOGNIZED",
            confidence_score=0.91,
            matched_template="front",
            face_count=2,
            bbox=[10, 20, 80, 100],
            image_path="surveillance/test.jpg",
            timestamp=timestamp,
        )

        pending = self.db.get_unsynced_surveillance_logs()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["log_id"], log_id)
        self.assertEqual(pending[0]["recognition_status"], "RECOGNIZED")
        self.assertEqual(pending[0]["matched_template"], "front")
        self.assertEqual(pending[0]["face_count"], 2)
        self.assertEqual(pending[0]["bbox"], [10, 20, 80, 100])

        self.db.mark_surveillance_logs_as_synced([log_id])
        self.assertEqual(len(self.db.get_unsynced_surveillance_logs()), 0)

    def test_deleted_users_locally(self):
        """
        Verify that calling delete_users_locally deletes specified users from both device_users and device_user_roles.
        """
        # 1. Insert a user and roles
        users_payload = [{"user_id": 99, "face_vector_b64": "AAAA", "is_active": 1}]
        self.db.save_users_delta(users_payload)
        
        # Insert a user-role mapping
        roles_payload = [{"role_id": 3, "role_name": "LECTURER"}]
        self.db.save_roles_delta(roles_payload)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO device_user_roles (user_id, role_id) VALUES (99, 3)")
        conn.commit()
        
        # Verify inserted
        cursor.execute("SELECT COUNT(*) FROM device_users WHERE user_id = 99")
        self.assertEqual(cursor.fetchone()[0], 1)
        cursor.execute("SELECT COUNT(*) FROM device_user_roles WHERE user_id = 99")
        self.assertEqual(cursor.fetchone()[0], 1)
        
        # 2. Delete the user
        self.db.delete_users_locally([99])
        
        # Verify deleted
        cursor.execute("SELECT COUNT(*) FROM device_users WHERE user_id = 99")
        self.assertEqual(cursor.fetchone()[0], 0)
        cursor.execute("SELECT COUNT(*) FROM device_user_roles WHERE user_id = 99")
        self.assertEqual(cursor.fetchone()[0], 0)
        conn.close()

    def test_user_roles_update_clears_old_ones(self):
        """
        Verify that save_user_roles_delta deletes old user-role mappings for updated users.
        """
        # Insert user and roles
        users_payload = [{"user_id": 99, "face_vector_b64": "AAAA", "is_active": 1}]
        self.db.save_users_delta(users_payload)
        roles_payload = [{"role_id": 3, "role_name": "LECTURER"}, {"role_id": 4, "role_name": "STUDENT"}]
        self.db.save_roles_delta(roles_payload)

        # 1. Map to role 3
        self.db.save_user_roles_delta([{"user_id": 99, "role_id": 3}])
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT role_id FROM device_user_roles WHERE user_id = 99")
        roles = [row[0] for row in cursor.fetchall()]
        self.assertEqual(roles, [3])

        # 2. Update mapping to role 4
        self.db.save_user_roles_delta([{"user_id": 99, "role_id": 4}])

        cursor.execute("SELECT role_id FROM device_user_roles WHERE user_id = 99")
        roles = [row[0] for row in cursor.fetchall()]
        self.assertEqual(roles, [4])
        conn.close()

    def test_load_embeddings_with_active_flag(self):
        """
        Verify that load_templates returns user_id, embedding, and is_active status.
        """
        from edge.facial_recognition.src.face.database import DeviceUserRepository
        repository = DeviceUserRepository(self.db_path)
        
        # Seed an active and an inactive user
        mock_vec = np.ones(512, dtype=np.float32) * 0.5
        mock_b64 = base64.b64encode(mock_vec.tobytes()).decode('utf-8')
        
        users_payload = [
            {"user_id": 20, "face_vector_b64": mock_b64, "is_active": 1},
            {"user_id": 21, "face_vector_b64": mock_b64, "is_active": 0}
        ]
        self.db.save_users_delta(users_payload)
        
        templates = repository.load_templates()
        self.assertEqual(len(templates), 2)
        
        # Check active status
        emb_map = {int(t.user_id): t.is_active for t in templates}
        self.assertTrue(emb_map[20])
        self.assertFalse(emb_map[21])

    def test_perform_startup_cleanup(self):
        """
        Verify perform_startup_cleanup successfully deletes orphaned user IDs.
        """
        # 1. Insert two users in SQLite
        users_payload = [
            {"user_id": 101, "face_vector_b64": "AAAA", "is_active": 1},
            {"user_id": 102, "face_vector_b64": "AAAA", "is_active": 1}
        ]
        self.db.save_users_delta(users_payload)
        
        # 2. Setup mock cloud response where only user 101 exists (102 has been deleted)
        from unittest.mock import patch, MagicMock
        worker = DownstreamSyncWorker(self.db, "http://localhost:8000")
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [101]
        
        with patch('requests.get', return_value=mock_response) as mock_get:
            worker.perform_startup_cleanup()
            
            # Check requests get details
            mock_get.assert_called_once_with("http://localhost:8000/api/sync/downstream/user-ids", timeout=10.0)
            
        # Verify user 102 was deleted from local SQLite, but 101 remains
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM device_users")
        uids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        self.assertIn(101, uids)
        self.assertNotIn(102, uids)


if __name__ == "__main__":
    unittest.main()
