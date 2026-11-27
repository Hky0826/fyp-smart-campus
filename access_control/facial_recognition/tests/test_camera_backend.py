"""Unit tests for unified camera capture backend, CSI IMX219 support, and auto-detection."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from access_control.facial_recognition.src.camera.capture_backend import (
    AdaptiveExposureController,
    DEFAULT_AUTO_EXPOSURE,
    DEFAULT_BRIGHTNESS,
    DEFAULT_CONTRAST,
    DEFAULT_EXPOSURE_VALUE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_PIXEL_FORMAT,
    DEFAULT_SWAP_RB,
    DEFAULT_WIDTH,
    Picamera2Capture,
    detect_available_cameras,
    detect_csi_cameras,
    detect_v4l2_devices,
    get_camera_candidates,
    open_camera_capture,
    open_single_capture,
    parse_camera_source,
)
from access_control.facial_recognition.src.camera.camera_reader import CameraReader
from access_control.ui.access_control_gui.controllers.camera_controller import (
    _camera_candidates,
    _open_capture,
)


class TestCameraBackend(unittest.TestCase):
    def test_parse_camera_source(self):
        self.assertEqual(parse_camera_source("/dev/video0"), 0)
        self.assertEqual(parse_camera_source("/dev/video4"), 4)
        self.assertEqual(parse_camera_source("0"), 0)
        self.assertEqual(parse_camera_source("4"), 4)
        self.assertEqual(parse_camera_source(0), 0)
        self.assertEqual(parse_camera_source("csi"), "csi")
        self.assertEqual(parse_camera_source("csi:0"), "csi:0")
        self.assertEqual(parse_camera_source("rtsp://10.0.0.1/live"), "rtsp://10.0.0.1/live")

    def test_detect_csi_cameras_when_picamera2_missing(self):
        with patch("access_control.facial_recognition.src.camera.capture_backend.is_picamera2_available", return_value=False):
            result = detect_csi_cameras()
            self.assertEqual(result, [])

    def test_detect_csi_cameras_when_picamera2_present(self):
        mock_picam_cls = MagicMock()
        mock_picam_cls.global_camera_info.return_value = [{"Id": "cam0", "Model": "imx219"}]
        with patch("access_control.facial_recognition.src.camera.capture_backend.is_picamera2_available", return_value=True):
            with patch.dict(sys.modules, {"picamera2": MagicMock(Picamera2=mock_picam_cls)}):
                result = detect_csi_cameras()
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["Model"], "imx219")

    def test_get_camera_candidates_auto_with_csi_detected(self):
        with patch(
            "access_control.facial_recognition.src.camera.capture_backend.detect_csi_cameras",
            return_value=[{"Model": "imx219"}],
        ):
            candidates = get_camera_candidates("auto")
            self.assertEqual(candidates[0], "csi:0")
            # Should also include fallbacks
            self.assertIn(4, candidates)
            self.assertIn(0, candidates)

    def test_get_camera_candidates_explicit_source_first(self):
        with patch(
            "access_control.facial_recognition.src.camera.capture_backend.detect_csi_cameras",
            return_value=[{"Model": "imx219"}],
        ):
            candidates = get_camera_candidates("/dev/video4")
            self.assertEqual(candidates[0], 4)
            # CSI and 0 should still be in fallbacks
            self.assertIn("csi:0", candidates)
            self.assertIn(0, candidates)

    def test_get_camera_candidates_no_fallbacks(self):
        candidates = get_camera_candidates("/dev/video4", allow_fallbacks=False)
        self.assertEqual(candidates, [4])

    def test_picamera2_capture_success_lifecycle(self):
        mock_picam_inst = MagicMock()
        mock_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        mock_picam_inst.capture_array.return_value = mock_frame
        mock_picam_cls = MagicMock(return_value=mock_picam_inst)
        mock_picam_cls.global_camera_info.return_value = [{"Model": "imx219"}]

        with patch.dict(sys.modules, {"picamera2": MagicMock(Picamera2=mock_picam_cls)}):
            with patch("time.sleep", return_value=None):
                cap = Picamera2Capture(camera_idx=0, width=1280, height=720, fps=30)
                self.assertTrue(cap.isOpened())
                self.assertEqual(cap.camera_model, "imx219")
                self.assertEqual(cap.get(cv2.CAP_PROP_FRAME_WIDTH) if cv2 else 1280, 1280)
                self.assertEqual(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) if cv2 else 720, 720)

                # Verify configuration was requested in RGB888 format (DRM format mapping to BGR memory)
                mock_picam_inst.create_video_configuration.assert_called_once()
                config_arg = mock_picam_inst.create_video_configuration.call_args[1]["main"]
                self.assertEqual(config_arg["format"], "RGB888")
                self.assertEqual(config_arg["size"], (1280, 720))

                # Test frame reading
                ok, frame = cap.read()
                self.assertTrue(ok)
                self.assertIsNotNone(frame)
                self.assertEqual(frame.shape, (720, 1280, 3))

                # Test release
                cap.release()
                self.assertFalse(cap.isOpened())
                mock_picam_inst.stop.assert_called_once()
                mock_picam_inst.close.assert_called_once()

    def test_picamera2_capture_swap_rb(self):
        mock_picam_inst = MagicMock()
        # Mock frame with distinct B, G, R values
        mock_frame = np.zeros((10, 10, 3), dtype=np.uint8)
        mock_frame[:, :, 0] = 10  # B
        mock_frame[:, :, 1] = 20  # G
        mock_frame[:, :, 2] = 30  # R
        mock_picam_inst.capture_array.return_value = mock_frame
        mock_picam_cls = MagicMock(return_value=mock_picam_inst)
        mock_picam_cls.global_camera_info.return_value = [{"Model": "imx219"}]

        with patch.dict(sys.modules, {"picamera2": MagicMock(Picamera2=mock_picam_cls)}):
            with patch("time.sleep", return_value=None):
                cap = Picamera2Capture(camera_idx=0, swap_rb=True)
                ok, frame = cap.read()
                self.assertTrue(ok)
                self.assertEqual(frame[0, 0, 0], 30)  # Was R, now in index 0
                self.assertEqual(frame[0, 0, 1], 20)  # G remains
                self.assertEqual(frame[0, 0, 2], 10)  # Was B, now in index 2
                cap.release()

    def test_picamera2_capture_init_failure(self):
        mock_picam_cls = MagicMock(side_effect=RuntimeError("No CSI camera found"))
        with patch.dict(sys.modules, {"picamera2": MagicMock(Picamera2=mock_picam_cls)}):
            cap = Picamera2Capture(camera_idx=0)
            self.assertFalse(cap.isOpened())
            ok, frame = cap.read()
            self.assertFalse(ok)
            self.assertIsNone(frame)
            cap.release()

    def test_open_single_capture_routes_to_csi(self):
        with patch("access_control.facial_recognition.src.camera.capture_backend.Picamera2Capture") as mock_cap_cls:
            mock_inst = MagicMock()
            mock_inst.isOpened.return_value = True
            mock_cap_cls.return_value = mock_inst

            cap = open_single_capture("csi:1", width=640, height=480)
            self.assertEqual(cap, mock_inst)
            mock_cap_cls.assert_called_once_with(
                camera_idx=1,
                width=640,
                height=480,
                fps=DEFAULT_FPS,
                pixel_format=DEFAULT_PIXEL_FORMAT,
                swap_rb=DEFAULT_SWAP_RB,
                exposure_value=DEFAULT_EXPOSURE_VALUE,
                brightness=DEFAULT_BRIGHTNESS,
                contrast=DEFAULT_CONTRAST,
                auto_exposure=DEFAULT_AUTO_EXPOSURE,
            )

    def test_open_camera_capture_auto_fallback(self):
        # First candidate fails frame read, second candidate succeeds
        first_mock = MagicMock()
        first_mock.read.return_value = (False, None)

        second_mock = MagicMock()
        second_mock.read.return_value = (True, np.ones((720, 1280, 3), dtype=np.uint8))

        def side_effect(source, **kwargs):
            if str(source).startswith("csi"):
                return first_mock
            return second_mock

        with patch("access_control.facial_recognition.src.camera.capture_backend.get_camera_candidates", return_value=["csi:0", 4]):
            with patch("access_control.facial_recognition.src.camera.capture_backend.open_single_capture", side_effect=side_effect):
                with patch("time.sleep", return_value=None):
                    cap, active_src = open_camera_capture("auto", test_frames=1)
                    self.assertEqual(cap, second_mock)
                    self.assertEqual(active_src, 4)
                    first_mock.release.assert_called_once()

    def test_camera_reader_auto_lifecycle(self):
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, np.ones((720, 1280, 3), dtype=np.uint8))

        with patch(
            "access_control.facial_recognition.src.camera.camera_reader.open_camera_capture",
            return_value=(mock_cap, "csi:0"),
        ):
            reader = CameraReader(source="auto", width=1280, height=720)
            self.assertEqual(reader.width, 1280)
            self.assertEqual(reader.height, 720)
            self.assertIsNone(reader.cap)

            reader.open()
            self.assertEqual(reader.cap, mock_cap)
            self.assertEqual(reader.active_source, "csi:0")

            ok, frame = reader.read()
            self.assertTrue(ok)
            self.assertIsNotNone(frame)

            reader.release()
            self.assertIsNone(reader.cap)
            mock_cap.release.assert_called_once()

    def test_camera_reader_open_failure_raises(self):
        with patch(
            "access_control.facial_recognition.src.camera.camera_reader.open_camera_capture",
            return_value=(None, None),
        ):
            reader = CameraReader(source="invalid_source")
            with self.assertRaises(RuntimeError):
                reader.open()

    def test_gui_camera_candidates_auto(self):
        with patch(
            "access_control.facial_recognition.src.camera.capture_backend.detect_csi_cameras",
            return_value=[{"Model": "imx219"}],
        ):
            candidates = _camera_candidates("auto")
            self.assertIn("csi:0", candidates)
            self.assertIn(4, candidates)
            self.assertIn(0, candidates)

    def test_gui_open_capture_routes_to_csi(self):
        with patch("access_control.ui.access_control_gui.controllers.camera_controller.open_single_capture") as mock_open:
            mock_inst = MagicMock()
            mock_open.return_value = mock_inst

            cap = _open_capture("csi")
            self.assertEqual(cap, mock_inst)
            mock_open.assert_called_once()

    def test_adaptive_exposure_reduces_ev_when_overexposed(self):
        ae = AdaptiveExposureController(initial_ev=0.0, interval_seconds=0.0)
        bright_frame = np.full((120, 160, 3), 235, dtype=np.uint8)
        next_ev = ae.compute_next_ev(bright_frame, now=1.0)
        self.assertIsNotNone(next_ev)
        self.assertLess(next_ev, 0.0)
        self.assertEqual(ae.current_ev, next_ev)

    def test_adaptive_exposure_reduces_ev_on_highlight_clipping(self):
        ae = AdaptiveExposureController(initial_ev=0.0, interval_seconds=0.0, max_clip_ratio=0.08)
        # Mostly mid-dark background (100) with 25% clipped white highlights (255)
        frame = np.full((120, 160, 3), 100, dtype=np.uint8)
        frame[:30, :, :] = 255
        next_ev = ae.compute_next_ev(frame, now=1.0)
        self.assertIsNotNone(next_ev)
        self.assertLess(next_ev, 0.0)

    def test_adaptive_exposure_increases_ev_when_underexposed(self):
        ae = AdaptiveExposureController(initial_ev=0.0, interval_seconds=0.0)
        dark_frame = np.full((120, 160, 3), 30, dtype=np.uint8)
        next_ev = ae.compute_next_ev(dark_frame, now=1.0)
        self.assertIsNotNone(next_ev)
        self.assertGreater(next_ev, 0.0)

    def test_adaptive_exposure_stays_stable_within_deadband(self):
        ae = AdaptiveExposureController(initial_ev=0.0, target_luma=128.0, tolerance=18.0, interval_seconds=0.0)
        balanced_frame = np.full((120, 160, 3), 128, dtype=np.uint8)
        self.assertIsNone(ae.compute_next_ev(balanced_frame, now=1.0))
        self.assertEqual(ae.current_ev, 0.0)

    def test_adaptive_exposure_respects_interval_and_clamps_bounds(self):
        ae = AdaptiveExposureController(initial_ev=-2.4, min_ev=-2.5, max_ev=1.5, interval_seconds=0.5)
        bright_frame = np.full((120, 160, 3), 255, dtype=np.uint8)
        ev1 = ae.compute_next_ev(bright_frame, now=1.0)
        self.assertEqual(ev1, -2.5)
        # Within interval -> no adjustment
        self.assertIsNone(ae.compute_next_ev(bright_frame, now=1.2))
        # At min bound -> stays clamped
        self.assertIsNone(ae.compute_next_ev(bright_frame, now=2.0))

    def test_picamera2_capture_adaptive_ae_adjusts_controls_on_bright_frame(self):
        mock_picam_inst = MagicMock()
        bright_frame = np.full((120, 160, 3), 250, dtype=np.uint8)
        mock_picam_inst.capture_array.return_value = bright_frame
        mock_picam_cls = MagicMock(return_value=mock_picam_inst)
        mock_picam_cls.global_camera_info.return_value = [{"Model": "imx219"}]

        with patch.dict(sys.modules, {"picamera2": MagicMock(Picamera2=mock_picam_cls)}):
            with patch("time.sleep", return_value=None):
                cap = Picamera2Capture(camera_idx=0, exposure_value=0.0, auto_exposure=True)
                mock_picam_inst.set_controls.reset_mock()

                ok, frame = cap.read()
                self.assertTrue(ok)
                self.assertIsNotNone(frame)
                mock_picam_inst.set_controls.assert_called_once()
                sent_controls = mock_picam_inst.set_controls.call_args[0][0]
                self.assertIn("ExposureValue", sent_controls)
                self.assertLess(sent_controls["ExposureValue"], 0.0)
                self.assertEqual(cap.exposure_value, sent_controls["ExposureValue"])
                cap.release()

    def test_picamera2_capture_auto_exposure_disabled_skips_adaptive_updates(self):
        mock_picam_inst = MagicMock()
        bright_frame = np.full((120, 160, 3), 250, dtype=np.uint8)
        mock_picam_inst.capture_array.return_value = bright_frame
        mock_picam_cls = MagicMock(return_value=mock_picam_inst)
        mock_picam_cls.global_camera_info.return_value = [{"Model": "imx219"}]

        with patch.dict(sys.modules, {"picamera2": MagicMock(Picamera2=mock_picam_cls)}):
            with patch("time.sleep", return_value=None):
                cap = Picamera2Capture(camera_idx=0, exposure_value=0.0, auto_exposure=False)
                config_controls = mock_picam_inst.create_video_configuration.call_args[1]["controls"]
                self.assertFalse(config_controls["AeEnable"])
                mock_picam_inst.set_controls.reset_mock()

                ok, _ = cap.read()
                self.assertTrue(ok)
                mock_picam_inst.set_controls.assert_not_called()
                cap.release()

    def test_open_single_capture_enables_opencv_auto_exposure(self):
        if cv2 is None:
            self.skipTest("cv2 not installed")
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        with patch("access_control.facial_recognition.src.camera.capture_backend.cv2.VideoCapture", return_value=mock_cap):
            with patch("access_control.facial_recognition.src.camera.capture_backend.sys_platform_is_linux", return_value=True):
                with patch("time.sleep", return_value=None):
                    cap = open_single_capture(0, auto_exposure=True)
                    self.assertEqual(cap, mock_cap)
                    mock_cap.set.assert_any_call(cv2.CAP_PROP_AUTO_EXPOSURE, 3)


if __name__ == "__main__":
    unittest.main()
