# edge/edge_kiosk_app.py
"""Orchestrator for the Zero-Image Edge Kiosk.

This module wires the modular classes (camera, detector, embedder, storage, matcher)
and runs the main capture/inference loop.
"""

from __future__ import annotations

import time
from typing import Tuple

import cv2
import numpy as np

# Flexible imports: support running as a script (no package) or as a package
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# Resolve package or direct module imports
if __package__:
    from .camera import CameraCapture
    from .detector import YuNetDetector
    from .embedder import EdgeFaceEmbedder
    from .storage import StorageManager
    from .matcher import Matcher
    from .spoof_detector import SpoofDetector
else:
    from camera import CameraCapture
    from detector import YuNetDetector
    from embedder import EdgeFaceEmbedder
    from storage import StorageManager
    from matcher import Matcher
    from spoof_detector import SpoofDetector

SCRIPT_DIR = CURRENT_DIR

# Local model paths inside edge/models
FACE_DETECTION_MODEL = os.path.abspath(os.path.join(SCRIPT_DIR, "models", "face_detection_yunet_2023mar_int8bq.onnx"))
EDGEFACE_MODEL = os.path.abspath(os.path.join(SCRIPT_DIR, "models", "edgeface_s_gamma_05.pt"))


def main_loop(db_path: str = "device_local.db", cam_index: int = 0, target_resolution: Tuple[int, int] = (640, 480)):
    """
    Core camera frame processing loop. Checks liveness and matches face vectors
    against the local SQLite cache.
    """
    storage = StorageManager(db_path)
    storage.ensure_schema()
    last_db_refresh_time = 0.0
    db_embeddings = []
    db_user_ids = []
    db_user_active_map = {}
    db_embedding_matrix = np.empty((0, 0), dtype=np.float32)

    def refresh_db_cache() -> None:
        nonlocal db_embeddings, db_user_ids, db_embedding_matrix, db_user_active_map, last_db_refresh_time
        db_embeddings = storage.load_embeddings()
        db_user_ids = [user_id for user_id, _, _ in db_embeddings]
        db_user_active_map = {user_id: is_active for user_id, _, is_active in db_embeddings}
        if db_embeddings:
            db_embedding_matrix = np.vstack([vec for _, vec, _ in db_embeddings]).astype(np.float32, copy=False)
            norms = np.linalg.norm(db_embedding_matrix, axis=1, keepdims=True) + 1e-10
            db_embedding_matrix = db_embedding_matrix / norms
        else:
            db_embedding_matrix = np.empty((0, 0), dtype=np.float32)
        last_db_refresh_time = time.time()

    refresh_db_cache()

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
    spoof_detector = SpoofDetector()

    frame_idx = 0
    last_event_time = 0.0
    cooldown_seconds = 3.0
    db_refresh_seconds = 2.0
    heavy_interval = 10

    status_text = "Waiting for face..."
    status_color = (255, 255, 0)
    last_spoof_log_time = 0.0

    try:
        while True:
            ret, frame = camera.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            display = cv2.flip(frame.copy(), 1)
            small = cv2.resize(frame, det_size)
            faces = detector.detect(small)

            if faces is None or len(faces) == 0:
                status_text = "Waiting for face..."
                status_color = (255, 255, 0)
                spoof_detector.reset()
            else:
                f = faces[0]
                x, y, w, h = int(f[0]), int(f[1]), int(f[2]), int(f[3])
                scale_x = orig_w / det_w
                scale_y = orig_h / det_h
                bx = int(x * scale_x)
                by = int(y * scale_y)
                bw = int(w * scale_x)
                bh = int(h * scale_y)
                spoof_result = spoof_detector.update(frame, f, (bx, by, bw, bh))

                # draw box
                mirrored_x = max(0, orig_w - (bx + bw))
                box_color = (0, 255, 255)
                if spoof_result.state == "live":
                    box_color = (0, 255, 0)
                elif spoof_result.state == "spoof":
                    box_color = (0, 0, 255)
                cv2.rectangle(display, (mirrored_x, by), (mirrored_x + bw, by + bh), box_color, 2)

                if spoof_result.state == "spoof":
                    status_text = f"SPOOFING {spoof_result.score:.3f}"
                    status_color = (0, 0, 255)
                    if (time.time() - last_spoof_log_time) > cooldown_seconds:
                        storage.log_event(None, 'SPOOFING', spoof_result.score)
                        last_spoof_log_time = time.time()
                    cv2.putText(display, "Liveness failed", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    cv2.putText(display, "Move your head slightly", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    cv2.putText(display, "or blink to pass the check", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    cv2.putText(display, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, status_color, 2)
                    cv2.imshow('Edge Kiosk', display)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        break
                    frame_idx += 1
                    continue
                elif spoof_result.state == "unknown":
                    status_text = f"Checking liveness {spoof_result.score:.3f}"
                    status_color = (255, 255, 0)
                    cv2.putText(display, "Move your head slightly", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                    cv2.putText(display, "or blink to pass the check", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                    cv2.putText(display, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, status_color, 2)
                    cv2.imshow('Edge Kiosk', display)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        break
                    frame_idx += 1
                    continue

                status_text = f"Liveness passed {spoof_result.score:.3f}"
                status_color = (0, 255, 0)

                now = time.time()
                if frame_idx % heavy_interval == 0 and (now - last_event_time) > cooldown_seconds:
                    crop = frame[max(0, by):min(orig_h, by + bh), max(0, bx):min(orig_w, bx + bw)]
                    if crop.size > 0:
                        emb = embedder.embed(crop)
                        try:
                            del crop
                        except Exception:
                            pass

                        if (now - last_db_refresh_time) > db_refresh_seconds:
                            refresh_db_cache()

                        matched_id, confidence = matcher.find_best_matrix(emb, db_user_ids, db_embedding_matrix)
                        duration_ms = (time.time() - now) * 1000.0
                        if matched_id is not None:
                            is_active = db_user_active_map.get(matched_id, 1)
                            if is_active == 0:
                                status_text = f"DENIED {matched_id} (DEACTIVATED)"
                                status_color = (0, 0, 255)
                                storage.log_event(matched_id, 'FAILED', confidence)
                                print(f"Auth DENIED id={matched_id} (DEACTIVATED) score={confidence:.4f} time_ms={duration_ms:.1f}")
                                print("deny entry since the account has been deactivated")
                            else:
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
    try:
        main_loop()
    except Exception as e:
        print('Fatal error in edge_kiosk_app:', e)
