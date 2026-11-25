"""Unit tests for CameraReader source parsing, RGB/BGR swap, and ADB Camera2 integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from surveillance.utils.camera import AdbCameraSession, CameraReader


def test_parse_adb_camera_id():
    assert CameraReader._parse_adb_camera_id("adb") == "0"
    assert CameraReader._parse_adb_camera_id("adb:back") == "0"
    assert CameraReader._parse_adb_camera_id("adb:front") == "1"
    assert CameraReader._parse_adb_camera_id("adb:1") == "1"
    assert CameraReader._parse_adb_camera_id("/dev/video4") is None


def test_parse_source_variants():
    assert CameraReader._parse_source("/dev/video4") == 4
    assert CameraReader._parse_source("0") == 0
    assert CameraReader._parse_source("rtsp://example/stream") == "rtsp://example/stream"


def test_swap_rb_defaults_and_channel_swap():
    adb_reader = CameraReader("adb")
    usb_reader = CameraReader("/dev/video4")
    assert adb_reader.swap_rb is True
    assert usb_reader.swap_rb is False

    # Pure red pixel in RGB [R=255, G=0, B=0] -> BGR [B=0, G=0, R=255]
    rgb_red = np.array([[[255, 0, 0]]], dtype=np.uint8)
    fixed = adb_reader._normalize_color(rgb_red)
    assert fixed[0, 0].tolist() == [0, 0, 255]


def test_open_adb_starts_session_and_opens_ffmpeg():
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (False, None)

    with patch.object(AdbCameraSession, "start", return_value=True) as mock_start, \
         patch.object(AdbCameraSession, "stop") as mock_stop, \
         patch("surveillance.utils.camera.cv2") as mock_cv2:
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.CAP_FFMPEG = 1900
        mock_cv2.CAP_PROP_BUFFERSIZE = 38

        reader = CameraReader("adb:front")
        assert reader.open() is True
        mock_start.assert_called_once()
        mock_cv2.VideoCapture.assert_called_once_with("tcp://127.0.0.1:27183", 1900)
        mock_cap.set.assert_called_once_with(38, 1)
        reader.release()
        mock_stop.assert_called_once()
