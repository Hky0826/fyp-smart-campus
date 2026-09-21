"""Unit tests for Raspberry Pi 5 GPIO relay door controller and API endpoints."""

from __future__ import annotations

import sys
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from access_control.facial_recognition.src.api.main import app
from access_control.facial_recognition.src.hardware.door_controller import (
    DoorController,
    DoorState,
    get_door_controller,
    reset_door_controller,
)


class TestDoorController(unittest.TestCase):
    def setUp(self):
        reset_door_controller()

    def tearDown(self):
        reset_door_controller()

    def test_door_controller_simulation_fallback(self):
        # Force OutputDevice to be None to test simulation mode
        with patch("access_control.facial_recognition.src.hardware.door_controller.OutputDevice", None):
            door = DoorController(pin=17, unlock_duration=0.5, active_high=False, enabled=True)
            self.assertTrue(door._is_simulated)
            self.assertFalse(door.is_unlocked)
            self.assertEqual(door.get_state()["state"], DoorState.LOCKED.value)

            # Unlock
            res = door.unlock(duration=0.2)
            self.assertTrue(res)
            self.assertTrue(door.is_unlocked)
            self.assertEqual(door.get_state()["state"], DoorState.UNLOCKED.value)
            self.assertEqual(door.get_state()["unlock_count"], 1)

            # Auto-relock wait
            time.sleep(0.3)
            self.assertFalse(door.is_unlocked)
            self.assertEqual(door.get_state()["state"], DoorState.LOCKED.value)

            door.cleanup()

    def test_door_controller_hardware_lifecycle(self):
        mock_device = MagicMock()
        mock_output_device_cls = MagicMock(return_value=mock_device)

        with patch("access_control.facial_recognition.src.hardware.door_controller.OutputDevice", mock_output_device_cls):
            door = DoorController(pin=17, unlock_duration=0.2, active_high=False, enabled=True)
            self.assertFalse(door._is_simulated)
            mock_output_device_cls.assert_called_once_with(17, active_high=False, initial_value=False)

            # Test unlock activates relay
            door.unlock(duration=0.2)
            mock_device.on.assert_called_once()
            self.assertTrue(door.is_unlocked)

            # Test auto-relock
            time.sleep(0.3)
            self.assertFalse(door.is_unlocked)
            mock_device.off.assert_called_once()

            # Test cleanup
            door.cleanup()
            mock_device.close.assert_called_once()

    def test_door_controller_debouncing_and_extension(self):
        mock_device = MagicMock()
        with patch("access_control.facial_recognition.src.hardware.door_controller.OutputDevice", return_value=mock_device):
            door = DoorController(pin=17, unlock_duration=1.0)
            door.unlock(duration=0.3)
            self.assertTrue(door.is_unlocked)
            self.assertEqual(mock_device.on.call_count, 1)

            # Second trigger while unlocked extends duration without bouncing relay
            door.unlock(duration=0.5)
            self.assertEqual(mock_device.on.call_count, 1)
            self.assertEqual(door.get_state()["unlock_count"], 1)

            # Explicit lock immediately turns off
            door.lock()
            self.assertFalse(door.is_unlocked)
            mock_device.off.assert_called_once()

    def test_door_controller_disabled(self):
        door = DoorController(pin=17, enabled=False)
        self.assertFalse(door.enabled)
        res = door.unlock()
        self.assertFalse(res)
        self.assertFalse(door.is_unlocked)

    def test_get_door_controller_singleton(self):
        d1 = get_door_controller(pin=17, unlock_duration=3.0)
        d2 = get_door_controller(pin=17, unlock_duration=3.0)
        self.assertIs(d1, d2)
        self.assertEqual(d1.pin, 17)


class TestDoorApiEndpoints(unittest.TestCase):
    def setUp(self):
        reset_door_controller()
        self.client = TestClient(app, client=("127.0.0.1", 50001))

    def tearDown(self):
        reset_door_controller()

    def test_get_door_status_endpoint(self):
        resp = self.client.get("/kiosk/door/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("state", data)
        self.assertEqual(data["state"], "LOCKED")
        self.assertFalse(data["is_unlocked"])
        self.assertEqual(data["pin"], 17)

    def test_post_door_unlock_endpoint(self):
        resp = self.client.post("/kiosk/door/unlock", json={"duration_seconds": 1.0})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["state"], "UNLOCKED")
        self.assertTrue(data["is_unlocked"])
        self.assertGreater(data["remaining_seconds"], 0)

        # Check status endpoint reflects unlocked state
        status_resp = self.client.get("/kiosk/door/status")
        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(status_resp.json()["state"], "UNLOCKED")


if __name__ == "__main__":
    unittest.main()
