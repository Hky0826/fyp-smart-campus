import tempfile
import unittest
import sys
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
            raise OSError('offline')
        if url.endswith('user-ids'):
            return Response(200, [1])
        return Response(200, {'users': [], 'roles': [], 'user_roles': [], 'node_rbac': [], 'timestamp': '2026-01-01T00:00:00Z'})

    def post(self, url, **kwargs):
        if self.fail:
            raise OSError('offline')
        self.posts.append((url, kwargs))
        count = len(kwargs.get('json', {}).get('logs', []))
        return Response(200, {'successful_indices': list(range(count))})


class DatabaseSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'edge.db'

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def emb(frame=1):
        return Embedding(np.array([1, 0, 0, 0], np.float32), 'opencv_sface', '2021dec', 4, frame, 1.0)

    def test_cloud_delivered_sface_embedding_is_stored_and_matched(self):
        repo = SQLiteIdentityRepository(self.path)
        repo.save_users_delta([{
            'user_id': 1,
            'display_name': 'Ada',
            'is_active': True,
            'embeddings': [{
                'template_name': 'cloud-template',
                'model_name': 'opencv_sface',
                'model_version': '2021dec',
                'embedding_dimension': 4,
                'embedding': [1, 0, 0, 0],
                'quality_metadata': {'source': 'cloud'},
            }],
        }])
        match = repo.find_match(self.emb(), .9)
        self.assertIsNotNone(match)
        self.assertEqual(match.identity_id, '1')
        self.assertEqual(repo.status()['sface_templates'], 1)

    def test_explicit_empty_cloud_template_list_clears_local_templates(self):
        repo = SQLiteIdentityRepository(self.path)
        repo.save_users_delta([{'user_id': 1, 'display_name': 'Ada', 'embeddings': [{'model_name': 'opencv_sface', 'model_version': '2021dec', 'embedding_dimension': 4, 'embedding': [1, 0, 0, 0]}]}])
        self.assertEqual(repo.status()['sface_templates'], 1)
        repo.save_users_delta([{'user_id': 1, 'display_name': 'Ada', 'embeddings': []}])
        self.assertEqual(repo.status()['sface_templates'], 0)
        self.assertIsNone(repo.find_match(self.emb()))
    def test_cloud_embedding_from_another_model_is_not_cross_compared(self):
        repo = SQLiteIdentityRepository(self.path)
        repo.save_users_delta([{
            'user_id': 1,
            'display_name': 'Ada',
            'is_active': True,
            'embeddings': [{
                'model_name': 'another_model',
                'model_version': 'v1',
                'embedding_dimension': 4,
                'embedding': [1, 0, 0, 0],
            }],
        }])
        self.assertIsNone(repo.find_match(self.emb()))

    def test_offline_logs_remain_chronological_and_replay(self):
        repo = SQLiteIdentityRepository(self.path)
        repo.log_authentication_event(None, 'FAILED', .1, timestamp='2026-01-01T00:00:02Z')
        repo.log_authentication_event(None, 'FAILED', .2, timestamp='2026-01-01T00:00:01Z')
        self.assertEqual([x['confidence_score'] for x in repo.get_unsynced_logs()], [.2, .1])
        http = FakeHTTP()
        service = BackgroundDatabaseSyncService(repo, SyncConfig('http://cloud', 'gate', 'Gate'), http)
        self.assertTrue(service.replay_pending_authentication_logs())
        self.assertEqual(repo.get_unsynced_logs(), [])

    def test_network_failure_is_contained(self):
        repo = SQLiteIdentityRepository(self.path)
        http = FakeHTTP()
        http.fail = True
        service = BackgroundDatabaseSyncService(repo, SyncConfig('http://cloud', 'gate', 'Gate'), http)
        self.assertFalse(service.perform_downstream_sync())
        self.assertEqual(service.status(), 'offline')
        self.assertIn('offline', service.last_error)


if __name__ == '__main__':
    unittest.main()
