import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api import create_app
from app.api.state import KioskStateStore


class Repository:
    def status(self):
        return {'database': 'ok'}


class Sync:
    last_error = None

    def __init__(self):
        self.deactivated = []

    def status(self):
        return 'online'

    def deactivate_user(self, user_id):
        self.deactivated.append(user_id)
        return True

    def trigger_immediate_sync(self):
        return True


class Runtime:
    def __init__(self):
        self.config = SimpleNamespace(
            device_id='gate-1',
            device_name='Gate',
            cloud_url='http://cloud',
            yunet_model=Path('models/yunet.onnx'),
            sface_model=Path('models/sface.onnx'),
        )
        self.repository = Repository()
        self.sync = Sync()
        self.kiosk = KioskStateStore('gate-1', 'Gate', 'http://cloud')
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


class ApiContractTests(unittest.TestCase):
    def test_health_state_database_and_json_deactivation_contracts(self):
        runtime = Runtime()
        with TestClient(create_app(runtime)) as client:
            self.assertEqual(client.get('/health').json()['pipeline'], 'yunet-kcf-sface')
            self.assertEqual(client.get('/database/status').json(), {'database': 'ok'})
            state = client.get('/kiosk/state').json()
            self.assertEqual(state['device']['device_id'], 'gate-1')
            response = client.post('/api/edge/deactivate', json={'user_id': 42})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'deactivated')
            self.assertEqual(runtime.sync.deactivated, [42])
            attempt = client.post('/kiosk/access/request').json()['attempt']
            self.assertEqual(attempt['access_decision'], 'VERIFYING')
        self.assertEqual((runtime.starts, runtime.stops), (1, 1))

    def test_chatbot_requires_verified_unlocked_session(self):
        runtime = Runtime()
        with TestClient(create_app(runtime)) as client:
            response = client.post('/kiosk/chat/message', json={'query': 'hello'})
            self.assertEqual(response.status_code, 409)


if __name__ == '__main__':
    unittest.main()
