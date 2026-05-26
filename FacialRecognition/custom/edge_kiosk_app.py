"""Orchestrator for the Zero-Image Edge Kiosk.

This module wires the modular classes (camera, detector, embedder, storage, matcher)
and runs the main capture/inference loop.
"""

from __future__ import annotations

import time
import gc
from typing import Tuple, Optional

import cv2

# Flexible imports: support running as a script (no package) or as a package
import os
import sys

if __package__:
    from .camera import CameraCapture
    from .detector import YuNetDetector
    from .embedder import EdgeFaceEmbedder
    from .storage import StorageManager
    from .matcher import Matcher
else:
    # When executed directly, ensure the local directory is on sys.path
    script_dir = os.path.dirname(__file__)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from camera import CameraCapture
    from detector import YuNetDetector
    from embedder import EdgeFaceEmbedder
    from storage import StorageManager
    from matcher import Matcher


# Model path placeholders - replace with real paths before running
FACE_DETECTION_MODEL = "face_detection_yunet_2023mar_int8bq.onnx"
EDGEFACE_MODEL = "edgeface_xxs.pt"


def main_loop(db_path: str = "edge_local.db", cam_index: int = 0, target_resolution: Tuple[int, int] = (640, 480)):
    storage = StorageManager(db_path)
    storage.ensure_schema()
    db_embeddings = storage.load_embeddings()

    camera = CameraCapture(index=cam_index, width=target_resolution[0], height=target_resolution[1])
    camera.open()

    # warm frame
    ret, frame = camera.read()
    if not ret or frame is None:
        camera.release()
        raise RuntimeError("Failed to read initial camera frame")

    orig_h, orig_w = frame.shape[:2]
    det_w = min(target_resolution[0], orig_w)
    det_h = min(target_resolution[1], orig_h)
    det_size = (det_w, det_h)

    detector = YuNetDetector(FACE_DETECTION_MODEL, det_size)
    embedder = EdgeFaceEmbedder(EDGEFACE_MODEL)
    matcher = Matcher(threshold_distance=0.40)

    frame_idx = 0
    last_event_time = 0.0
    cooldown_seconds = 3.0
    heavy_interval = 10

    status_text = "Waiting for face..."
    status_color = (255, 255, 0)

    try:
        while True:
            ret, frame = camera.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            display = frame.copy()
            small = cv2.resize(frame, det_size)
            faces = detector.detect(small)

            if faces is None or len(faces) == 0:
                status_text = "Waiting for face..."
                status_color = (255, 255, 0)
            else:
                f = faces[0]
                x, y, w, h = int(f[0]), int(f[1]), int(f[2]), int(f[3])
                scale_x = orig_w / det_w
                scale_y = orig_h / det_h
                bx = int(x * scale_x)
                by = int(y * scale_y)
                bw = int(w * scale_x)
                bh = int(h * scale_y)

                # draw provisional box
                cv2.rectangle(display, (bx, by), (bx + bw, by + bh), (0, 255, 255), 2)

                now = time.time()
                if frame_idx % heavy_interval == 0 and (now - last_event_time) > cooldown_seconds:
                    crop = frame[max(0, by):min(orig_h, by + bh), max(0, bx):min(orig_w, bx + bw)]
                    if crop.size > 0:
                        emb = embedder.embed(crop)
                        # zero-image enforcement
                        try:
                            del crop
                        except Exception:
                            pass
                        gc.collect()

                        # refresh DB cache and match
                        db_embeddings = storage.load_embeddings()
                        matched_id, confidence = matcher.find_best(emb, db_embeddings)
                        duration_ms = (time.time() - now) * 1000.0
                        if matched_id is not None:
                            status_text = f"AUTHORIZED {matched_id} {confidence:.3f}"
                            status_color = (0, 255, 0)
                            storage.log_event(matched_id, 'SUCCESS', confidence)
                            print(f"Auth SUCCESS id={matched_id} score={confidence:.4f} time_ms={duration_ms:.1f}")
                        else:
                            status_text = f"UNAUTHORIZED {confidence:.3f}"
                            status_color = (0, 0, 255)
                            storage.log_event(None, 'FAILED', confidence)
                            print(f"Auth FAILED best_score={confidence:.4f} time_ms={duration_ms:.1f}")

                        last_event_time = time.time()

            cv2.putText(display, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, status_color, 2)
            cv2.imshow('Edge Kiosk', display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

            frame_idx += 1

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    # Entrypoint: run main loop with defaults. Adjust model constants above as needed.
    try:
        main_loop()
    except Exception as e:
        print('Fatal error in edge_kiosk_app:', e)
