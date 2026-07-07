import datetime
import importlib.util
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "cloud" / "dashboard" / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SERVICE_PATH = PROJECT_ROOT / "cloud" / "sync" / "edge_to_cloud" / "cloud_sync_service.py"
spec = importlib.util.spec_from_file_location("edge_to_cloud_sync_service", SERVICE_PATH)
cloud_sync_service = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(cloud_sync_service)

from app.core.database import Base
from app.models.models import Building, Device, Floorplan, Node, User


class LocationTrackingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.handler = cloud_sync_service.SQLAlchemyUpstreamHandler()
        self._seed_location_data()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _seed_location_data(self):
        building = Building(building_name="Main Block")
        self.db.add(building)
        self.db.flush()

        floorplan = Floorplan(
            building_id=building.building_id,
            floor_level=1,
            image_path="/static/floorplans/main-1.png",
        )
        self.db.add(floorplan)
        self.db.flush()

        self.node_a = Node(
            floorplan_id=floorplan.floorplan_id,
            cord_x=10.0,
            cord_y=20.0,
            room_label="Entrance",
            node_type="ENTRANCE",
        )
        self.node_b = Node(
            floorplan_id=floorplan.floorplan_id,
            cord_x=30.0,
            cord_y=40.0,
            room_label="Library",
            node_type="ROOM",
        )
        self.db.add_all([self.node_a, self.node_b])
        self.db.flush()

        self.db.add_all(
            [
                Device(
                    device_id="access-gate-1",
                    device_name="Access Gate 1",
                    node_id=self.node_a.node_id,
                    device_type="ENTRY_GATE",
                ),
                Device(
                    device_id="camera-library",
                    device_name="Library Camera",
                    node_id=self.node_b.node_id,
                    device_type="CLASSROOM",
                ),
                User(
                    user_id=10,
                    given_name="Test",
                    family_name="User",
                    email="test.user@example.com",
                    username="testuser",
                ),
            ]
        )
        self.db.commit()

    def test_successful_access_control_log_updates_last_known_location(self):
        payload = cloud_sync_service.EdgeLogPayload(
            sync_key="auth-success-1",
            user_id=10,
            device_id="access-gate-1",
            auth_status="SUCCESS",
            confidence_score=0.93,
            timestamp="2026-07-07T02:00:00Z",
        )

        processed = self.handler.ingest_authentication_logs(self.db, [payload])

        user = self.db.query(User).filter_by(user_id=10).one()
        self.assertEqual(processed, [0])
        self.assertEqual(user.last_known_location, self.node_a.node_id)
        self.assertEqual(user.last_seen, datetime.datetime(2026, 7, 7, 2, 0, 0))

    def test_recognized_surveillance_log_updates_last_known_location(self):
        payload = cloud_sync_service.EdgeSurveillanceLogPayload(
            sync_key="surveillance-recognized-1",
            user_id=10,
            device_id="camera-library",
            recognition_status="RECOGNIZED",
            confidence_score=0.88,
            matched_template="front",
            face_count=1,
            bbox=[10, 20, 80, 100],
            timestamp="2026-07-07T02:05:00Z",
        )

        processed = self.handler.ingest_surveillance_logs(self.db, [payload])

        user = self.db.query(User).filter_by(user_id=10).one()
        self.assertEqual(processed, [0])
        self.assertEqual(user.last_known_location, self.node_b.node_id)
        self.assertEqual(user.last_seen, datetime.datetime(2026, 7, 7, 2, 5, 0))

    def test_unknown_surveillance_log_does_not_update_location(self):
        payload = cloud_sync_service.EdgeSurveillanceLogPayload(
            sync_key="surveillance-unknown-1",
            user_id=None,
            device_id="camera-library",
            recognition_status="UNKNOWN",
            confidence_score=0.21,
            timestamp="2026-07-07T02:10:00Z",
        )

        processed = self.handler.ingest_surveillance_logs(self.db, [payload])

        user = self.db.query(User).filter_by(user_id=10).one()
        self.assertEqual(processed, [0])
        self.assertIsNone(user.last_known_location)
        self.assertIsNone(user.last_seen)

    def test_older_events_do_not_overwrite_newer_location(self):
        newer = cloud_sync_service.EdgeSurveillanceLogPayload(
            sync_key="surveillance-newer-1",
            user_id=10,
            device_id="camera-library",
            recognition_status="RECOGNIZED",
            confidence_score=0.88,
            timestamp="2026-07-07T02:15:00Z",
        )
        older = cloud_sync_service.EdgeLogPayload(
            sync_key="auth-older-1",
            user_id=10,
            device_id="access-gate-1",
            auth_status="SUCCESS",
            confidence_score=0.93,
            timestamp="2026-07-07T02:00:00Z",
        )

        self.handler.ingest_surveillance_logs(self.db, [newer])
        self.handler.ingest_authentication_logs(self.db, [older])

        user = self.db.query(User).filter_by(user_id=10).one()
        self.assertEqual(user.last_known_location, self.node_b.node_id)
        self.assertEqual(user.last_seen, datetime.datetime(2026, 7, 7, 2, 15, 0))


if __name__ == "__main__":
    unittest.main()
