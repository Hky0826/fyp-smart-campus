"""Run access-control and surveillance pipelines from one camera stream."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from ..camera.camera_reader import CameraReader
from ..config import AccessControlConfig, SurveillanceConfig
from ..sync import SyncEngine
from ..utils.logging import configure_logging
from ..utils.visualization import close_display, show_pipeline_result
from .access_control import build_pipeline as build_access_pipeline
from .surveillance import build_pipeline as build_surveillance_pipeline


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Hailo access-control and surveillance together")
    parser.add_argument("--camera", default=None, help="Camera index, /dev/videoN, RTSP URL, or video file")
    parser.add_argument("--database", default=None, help="SQLite database path")
    parser.add_argument("--target-user-id", default=None, help="Optional access-control 1:1 verification user ID")
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument("--display", dest="display", action="store_true", default=True, help="Show OpenCV camera windows with overlays (default)")
    display_group.add_argument("--no-display", dest="display", action="store_false", help="Run without OpenCV display windows")
    parser.add_argument("--access-window-name", default="Hailo Access Control", help="Access-control display window name")
    parser.add_argument("--surveillance-window-name", default="Hailo Surveillance", help="Surveillance display window name")
    parser.add_argument("--mirror", dest="mirror", action="store_true", default=True, help="Mirror the displayed frame")
    parser.add_argument("--no-mirror", dest="mirror", action="store_false", help="Do not mirror the displayed frame")
    args = parser.parse_args()

    access_defaults = AccessControlConfig()
    camera_source = args.camera or access_defaults.camera
    database_path = Path(args.database).expanduser() if args.database else access_defaults.database_path

    access_config = AccessControlConfig(camera=camera_source, database_path=database_path)
    surveillance_config = SurveillanceConfig(camera=camera_source, database_path=database_path)
    configure_logging(access_config.log_level)

    logger.info("Running access-control and surveillance on camera %s", camera_source)
    sync_engine = SyncEngine.from_config(access_config)
    sync_engine.start()
    camera = CameraReader(camera_source)
    try:
        access_pipeline = build_access_pipeline(access_config)
        surveillance_pipeline = build_surveillance_pipeline(surveillance_config)
        camera.open()
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                logger.warning("Camera read failed")
                time.sleep(0.05)
                continue

            access_result = access_pipeline.process_frame(frame, target_user_id=args.target_user_id)
            surveillance_result = surveillance_pipeline.process_frame(frame)
            result = {
                "success": True,
                "camera": camera_source,
                "access_control": access_result,
                "surveillance": surveillance_result,
            }
            logger.debug(json.dumps(result, default=str))

            if args.display:
                if not show_pipeline_result(args.access_window_name, frame, access_result, mirror=args.mirror):
                    break
                if not show_pipeline_result(args.surveillance_window_name, frame, surveillance_result, mirror=args.mirror):
                    break
    finally:
        camera.release()
        sync_engine.stop()
        if args.display:
            close_display()


if __name__ == "__main__":
    main()
