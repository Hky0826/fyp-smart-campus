"""Regression tests for Workstream 3 edge access-control, hardware, audio, and UI fixes."""

from __future__ import annotations

import datetime as dt
import io
import math
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from access_control.audio_io.audio_player import AudioPlayer
from access_control.audio_io.config import AudioIOConfig
from access_control.audio_io.main import AudioInteractionPipeline
from access_control.audio_io.recorder import AudioRecorder
from access_control.facial_recognition.src.api.kiosk import (
    KioskStateStore,
    KioskTimingConfig,
    RuntimeConfig,
)
from access_control.facial_recognition.src.access_policy import configured_max_policy_age_seconds
from access_control.facial_recognition.src.config import AccessControlConfig, _int_env
from access_control.facial_recognition.src.face.bytetrack import ByteTracker, STrack
from access_control.facial_recognition.src.face.database import DeviceUserRepository
from access_control.facial_recognition.src.face.quality import FaceQualityChecker
from access_control.facial_recognition.src.hardware.door_controller import DoorController, DoorState
from access_control.facial_recognition.src.sync import SQLiteEdgeDB
from access_control.ui.access_control_gui.controllers.api_client import (
    KioskApiClient,
    get_default_api_base_url,
)
from access_control.ui.access_control_gui.controllers.camera_controller import (
    DEFAULT_CAMERA_FALLBACKS,
)


class Workstream3RegressionTests(unittest.TestCase):
    def test_sync_snapshot_preserves_device_rbac_and_wal_cache_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "edge_wal.db"
            edge_db = SQLiteEdgeDB(db_path)
            now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
            vec1 = np.array([1.0, 0.0], dtype=np.float32).tobytes()
            vec2 = np.array([0.0, 1.0], dtype=np.float32).tobytes()

            edge_db.save_users_delta([{"user_id": 10, "is_active": 1, "face_vector_b64": ""}])
            edge_db.save_authorization_snapshot(
                roles=[{"role_id": 2, "role_name": "STAFF"}],
                user_roles=[{"user_id": 10, "role_id": 2}],
                rbac=[{"node_id": 100, "role_id": 2}],
                device_rbac=[{"device_id": "gate-1", "role_id": 2}],
            )
            edge_db.save_policy_metadata(node_id=100, policy_version="v1", synced_at=now_iso)

            # Re-syncing roles snapshot without device_rbac must NOT cascade-wipe existing device_rbac
            edge_db.save_authorization_snapshot(
                roles=[{"role_id": 2, "role_name": "STAFF"}],
                user_roles=[{"user_id": 10, "role_id": 2}],
            )
            repo = DeviceUserRepository(db_path)
            self.assertTrue(repo.evaluate_access(user_id=10, node_id=100, device_id="gate-1").allowed)

            # Fail closed if multiple devices exist and effective_device is None
            edge_db.save_device_rbac_delta([
                {"device_id": "gate-1", "role_id": 2},
                {"device_id": "gate-2", "role_id": 2},
            ])
            with patch.dict(os.environ, {}, clear=True):
                self.assertFalse(repo.evaluate_access(user_id=10, node_id=100, device_id=None).allowed)

            # WAL update must invalidate DeviceUserRepository cache on next load
            edge_db.save_users_delta([
                {
                    "user_id": 11,
                    "is_active": 1,
                    "face_embeddings": [{"template_name": "front", "model_name": "openvc_sface", "embedding": vec1}],
                }
            ])
            loaded1 = repo.load_templates()
            self.assertEqual([t.user_id for t in loaded1], ["11"])

            edge_db.save_users_delta([
                {
                    "user_id": 12,
                    "is_active": 1,
                    "face_embeddings": [{"template_name": "front", "model_name": "openvc_sface", "embedding": vec2}],
                }
            ])
            loaded2 = repo.load_templates()
            self.assertEqual({t.user_id for t in loaded2}, {"11", "12"})

    def test_sharpness_score_handles_1px_crops_and_bytetrack_guards(self):
        tiny = np.zeros((10, 1), dtype=np.uint8)
        score = FaceQualityChecker._sharpness_score(tiny)
        self.assertFalse(math.isnan(score))
        self.assertEqual(score, 0.0)

        xyah = STrack.tlwh_to_xyah(np.array([10.0, 20.0, 30.0, 0.0], dtype=np.float32))
        self.assertEqual(float(xyah[2]), 0.0)

        tracker = ByteTracker()
        tracker.removed_stracks = [STrack([0, 0, 10, 10], 0.9) for _ in range(1100)]
        tracker.update([])
        self.assertLessEqual(len(tracker.removed_stracks), 1000)

    def test_door_controller_apply_lock_failure_preserves_state_and_generation(self):
        door = DoorController(pin=17, unlock_duration=1.0, enabled=True)
        failing_dev = MagicMock()
        failing_dev.off.side_effect = RuntimeError("GPIO busy")
        door._device = failing_dev
        door._state = DoorState.UNLOCKED
        self.assertFalse(door._apply_lock())
        self.assertEqual(door._state, DoorState.UNLOCKED)

        door.unlock(duration=1.0)
        stale_gen = door._timer_generation - 1
        door._on_timer_expire(generation=stale_gen)
        self.assertEqual(door._state, DoorState.UNLOCKED)
        door._device = None
        door.cleanup()

    def test_kiosk_timings_lock_before_terminate_and_cached_skips_unlock(self):
        timings = KioskTimingConfig()
        lock_after = timings.owner_missing_grace_seconds + timings.owner_absent_lock_seconds
        self.assertLess(lock_after, timings.owner_absent_terminate_seconds)

        store = KioskStateStore(RuntimeConfig())
        store.start_access_attempt()
        mock_door = MagicMock()
        with patch(
            "access_control.facial_recognition.src.api.kiosk.get_door_controller",
            return_value=mock_door,
        ):
            store.complete_access_attempt({"access_granted": True, "cached": True, "face_count": 1})
            mock_door.unlock.assert_not_called()
            store.complete_access_attempt({"access_granted": True, "cached": False, "face_count": 1})
            mock_door.unlock.assert_called_once()

    def test_audio_io_and_gui_api_client_fixes(self):
        # stop() interrupting playback should not raise AudioPlaybackError
        player = AudioPlayer(AudioIOConfig(playback_backend="sounddevice", speaker_device="usb_spk"))
        with patch("sounddevice.play", side_effect=RuntimeError("interrupted")), patch("sounddevice.wait"):
            player._stop_requested.set()
            player._play_pcm_sounddevice(b"\x00\x01\x02\x03")

        # auth_required_handler should be invoked during retry
        mock_handler = MagicMock(return_value=False)
        pipeline = AudioInteractionPipeline(auth_required_handler=mock_handler)
        pipeline.cloud = MagicMock()
        pipeline._retry_after_authentication(Path("nonexistent.wav"))
        mock_handler.assert_called_once_with("auth_required")

        # ALSA recorder handles odd-length read chunks without raising ValueError
        recorder = AudioRecorder(AudioIOConfig(recording_backend="alsa", max_record_seconds=0.1, min_record_seconds=0.05))
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 0
        fake_proc.returncode = 0
        fake_proc.communicate.return_value = (b"", b"")
        fake_proc.stdout = MagicMock()
        fake_proc.stdout.read.side_effect = [b"\x01\x02\x03", b"\x04\x05\x06", b""]
        fake_proc.stderr = io.BytesIO(b"")
        with tempfile.TemporaryDirectory() as tmp_dir:
            recorder.config = AudioIOConfig(
                recording_backend="alsa",
                max_record_seconds=0.05,
                min_record_seconds=0.02,
                temp_dir=Path(tmp_dir),
            )
            with patch("access_control.audio_io.recorder.subprocess.Popen", return_value=fake_proc):
                result = recorder._record_alsa()
                self.assertTrue(result.path.exists())

        # API client defaults to 8080 even if EDGE_SYNC_LOCAL_PORT is set
        with patch.dict(os.environ, {"EDGE_SYNC_LOCAL_PORT": "8001"}, clear=True):
            self.assertEqual(get_default_api_base_url(), "http://127.0.0.1:8080")
        client = KioskApiClient("http://127.0.0.1:8080")
        self.assertIsNotNone(client._session)
        self.assertTrue(isinstance(DEFAULT_CAMERA_FALLBACKS, str) and len(DEFAULT_CAMERA_FALLBACKS) > 0)

        # Ensure policy age helpers accept both env var names
        with patch.dict(os.environ, {"EDGE_ACCESS_POLICY_MAX_AGE_SECONDS": "900"}, clear=True):
            self.assertEqual(configured_max_policy_age_seconds(), 900)
            self.assertEqual(_int_env("EDGE_ACCESS_MAX_POLICY_AGE_SECONDS", 300, "EDGE_ACCESS_POLICY_MAX_AGE_SECONDS"), 900)
