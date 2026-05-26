"""
edge_kiosk_app.py

Zero-Image Architecture facial verification kiosk.

Implements hardware-optimized V4L2 capture, YuNet face detection,
EdgeFace ONNX embedding extraction, SQLite embedding cache,
cosine-based matching, and relational logging.

Placeholders for model assets:
- face detection YuNet ONNX: "face_detection_yunet_2023mar.onnx"
- EdgeFace ONNX: "edgeface.onnx"

This script follows the technical architecture requirements from the
project prompt. Run on Python 3.10+ with required packages installed.
"""

from __future__ import annotations

import gc
import sqlite3
import time
from typing import Dict, Optional, Tuple

import numpy as np
import onnxruntime as ort
import cv2


# ----- Configuration (replace placeholders with actual paths) -----
YU_NET_ONNX_PATH = "face_detection_yunet_2023mar.onnx"  # <-- replace with actual path
EDGEFACE_ONNX_PATH = "edgeface.onnx"  # <-- replace with actual path

CAMERA_INDEX = 4
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
DETECTION_DOWNSAMPLE = (640, 480)
DETECTION_SCORE_THRESHOLD = 0.6
DETECTION_TOP_K = 1

EMBEDDING_SIZE = 512
EMBEDDING_THRESHOLD_DISTANCE = 0.40  # Cosine distance threshold (lower is more similar)

DB_PATH = "edge_local.db"


# ----- Database helpers -----
def ensure_db_schema(db_path: str = DB_PATH) -> None:
    """Create required tables if they do not exist."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            face_vector BLOB,
            active INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_auth_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            auth_status TEXT,
            confidence_score REAL,
            timestamp TEXT DEFAULT (datetime('now')),
            sync_status INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


def load_embeddings_from_db(db_path: str = DB_PATH) -> Dict[int, np.ndarray]:
    """Load active user embeddings from the SQLite DB.

    Returns a dict mapping user_id -> embedding (np.float32 array).
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT user_id, face_vector FROM edge_users WHERE active=1")
    rows = cur.fetchall()
    conn.close()

    embeddings: Dict[int, np.ndarray] = {}
    for user_id, blob in rows:
        if blob is None:
            continue
        arr = np.frombuffer(blob, dtype=np.float32)
        if arr.size == EMBEDDING_SIZE:
            embeddings[int(user_id)] = arr
    return embeddings


def log_event(user_id: Optional[int], auth_status: str, confidence_score: float, db_path: str = DB_PATH) -> None:
    """Write an authentication event to `edge_auth_logs`."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO edge_auth_logs (user_id, auth_status, confidence_score, sync_status) VALUES (?, ?, ?, 0)",
        (user_id, auth_status, float(confidence_score)),
    )
    conn.commit()
    conn.close()


# ----- Model initialization & inference -----
def init_yunet(model_path: str = YU_NET_ONNX_PATH, downsample_size: Tuple[int, int] = DETECTION_DOWNSAMPLE) -> cv2.FaceDetectorYN:
    """Initialize OpenCV YuNet face detector with the specified model.

    The input size is set dynamically later based on frames used for detection.
    """
    # create with placeholder input size; will call setInputSize later
    input_size = (downsample_size[0], downsample_size[1])
    detector = cv2.FaceDetectorYN.create(model_path, '', input_size, DETECTION_SCORE_THRESHOLD, 0.3, DETECTION_TOP_K)
    return detector


def init_edgeface(model_path: str = EDGEFACE_ONNX_PATH) -> ort.InferenceSession:
    """Initialize ONNX runtime session for EdgeFace model."""
    sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    return sess


def preprocess_for_edgeface(face_crop: np.ndarray) -> np.ndarray:
    """Preprocess a face crop for EdgeFace ONNX model.

    - Resize to 112x112
    - Convert to float32
    - Normalize using standard EdgeFace convention: (x - 127.5) / 128.0
    - Convert to NCHW layout
    """
    face = cv2.resize(face_crop, (112, 112), interpolation=cv2.INTER_LINEAR)
    face = face.astype(np.float32)
    face = (face - 127.5) / 128.0
    face = np.transpose(face, (2, 0, 1))  # HWC -> CHW
    face = np.expand_dims(face, axis=0).astype(np.float32)
    return face


def extract_embedding_from_edgeface(sess: ort.InferenceSession, preprocessed: np.ndarray) -> np.ndarray:
    """Run ONNX session to extract embedding and return a 1D float32 numpy array.

    After extracting the embedding, this function does NOT keep any image buffers
    referenced by the caller (caller is responsible for zero-image enforcement).
    """
    input_name = sess.get_inputs()[0].name
    out = sess.run(None, {input_name: preprocessed})
    embedding = np.array(out[0], dtype=np.float32).reshape(-1)
    # L2-normalize embedding for stable cosine comparisons
    norm = np.linalg.norm(embedding) + 1e-10
    embedding = embedding / norm
    return embedding


# ----- Matching utilities -----
def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine distance in [0, 2] where 0 = identical.

    distance = 1 - cosine_similarity
    """
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-10
    cos_sim = float(np.dot(a, b) / denom)
    distance = 1.0 - cos_sim
    return distance


def find_best_match(live_embedding: np.ndarray, db_embeddings: Dict[int, np.ndarray]) -> Tuple[Optional[int], float]:
    """Return best user_id and confidence score (cosine similarity).

    If no candidates, returns (None, 0.0)
    """
    best_id = None
    best_distance = float('inf')
    for user_id, emb in db_embeddings.items():
        d = cosine_distance(live_embedding, emb)
        if d < best_distance:
            best_distance = d
            best_id = user_id
    if best_id is None:
        return None, 0.0
    similarity = 1.0 - best_distance
    return best_id, float(similarity)


# ----- Camera capture & main loop -----
def init_camera(index: int = CAMERA_INDEX) -> cv2.VideoCapture:
    """Initialize V4L2 camera with MJPG protection and target 720p.

    Important: set MJPG before applying higher resolutions to avoid kernel freezes.
    """
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    # Enforce MJPG to avoid USB ring buffer saturation
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    # Request 720p
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    # Give sensor time to negotiate
    time.sleep(2.0)
    return cap


def run_stream(
    camera_index: int = CAMERA_INDEX,
    yunet_model: str = YU_NET_ONNX_PATH,
    edgeface_model: str = EDGEFACE_ONNX_PATH,
):
    """Main loop: read frames, detect faces, extract embeddings, match, and log."""
    ensure_db_schema()
    db_embeddings = load_embeddings_from_db()

    # Initialize models
    detector = init_yunet(yunet_model, DETECTION_DOWNSAMPLE)
    edgeface_sess = init_edgeface(edgeface_model)

    cap = init_camera(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open camera index {camera_index}")

    frame_counter = 0
    last_event_time = 0.0
    cooldown_seconds = 3.0
    detection_interval = 10

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                # Camera returned nothing; short sleep and continue
                time.sleep(0.01)
                continue

            display_frame = frame.copy()
            status_text = "Waiting for face..."
            status_color = (255, 255, 0)  # cyan for waiting

            # Draw a small HUD with current timestamp
            cv2.putText(display_frame, time.strftime('%Y-%m-%d %H:%M:%S'), (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            # Process detection only at specified interval
            if frame_counter % detection_interval == 0 and (time.time() - last_event_time) > cooldown_seconds:
                # Downsample for detection to save CPU
                small = cv2.resize(frame, DETECTION_DOWNSAMPLE, interpolation=cv2.INTER_LINEAR)
                # set detector input size dynamically
                detector.setInputSize((DETECTION_DOWNSAMPLE[0], DETECTION_DOWNSAMPLE[1]))
                try:
                    _, faces = detector.detect(small)
                except Exception:
                    faces = None

                if faces is None or len(faces) == 0:
                    # No detection; render waiting status
                    status_text = "Waiting for face..."
                    status_color = (255, 255, 0)
                else:
                    # faces is an array of shape (N, 15) per YuNet output: [x, y, w, h, score, ...]
                    # We limited top_k=1 so we take the first row
                    f = faces[0]
                    x, y, w, h, score = int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[4])
                    if score < DETECTION_SCORE_THRESHOLD:
                        status_text = "Waiting for face..."
                        status_color = (255, 255, 0)
                    else:
                        # Compute bounding box on the original full-resolution frame
                        # small -> original scale factor
                        sx = frame.shape[1] / DETECTION_DOWNSAMPLE[0]
                        sy = frame.shape[0] / DETECTION_DOWNSAMPLE[1]
                        bx = max(0, int(x * sx))
                        by = max(0, int(y * sy))
                        bw = max(1, int(w * sx))
                        bh = max(1, int(h * sy))

                        # Draw box
                        cv2.rectangle(display_frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)

                        # Extract crop from ORIGINAL frame (high topology accuracy)
                        crop = frame[by:by + bh, bx:bx + bw]
                        if crop.size == 0:
                            status_text = "Face too small"
                            status_color = (0, 165, 255)
                        else:
                            # Preprocess and infer embedding
                            pre = preprocess_for_edgeface(crop)
                            embedding = extract_embedding_from_edgeface(edgeface_sess, pre)

                            # Zero-Image Enforcement: delete raw crop and preprocessed arrays promptly
                            del crop
                            del pre
                            gc.collect()

                            # Refresh embeddings cache occasionally (simple policy: every auth attempt)
                            db_embeddings = load_embeddings_from_db()

                            matched_user, confidence = find_best_match(embedding, db_embeddings)
                            # compute cosine distance for threshold check
                            distance = 1.0 - confidence
                            if matched_user is not None and distance < EMBEDDING_THRESHOLD_DISTANCE:
                                # SUCCESS
                                status_text = f"Authorized: user {matched_user} ({confidence:.3f})"
                                status_color = (0, 255, 0)
                                log_event(matched_user, 'SUCCESS', float(confidence))
                                last_event_time = time.time()
                            else:
                                status_text = f"Unauthorized ({confidence:.3f})"
                                status_color = (0, 0, 255)
                                log_event(None, 'FAILED', float(confidence))
                                last_event_time = time.time()

                            # Ensure embedding memory is released
                            del embedding
                            gc.collect()

            # Overlay status text
            cv2.putText(display_frame, status_text, (10, display_frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)

            cv2.imshow('Edge Kiosk (Zero-Image)', display_frame)

            frame_counter += 1

            # Key handling
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

    finally:
        try:
            cap.release()
        except Exception:
            pass
        cv2.destroyAllWindows()


def main():
    run_stream()


if __name__ == '__main__':
    main()
"""
edge_kiosk_app.py

Zero-Image Architecture facial verification kiosk.

Implements hardware-optimized V4L2 capture, YuNet face detection,
EdgeFace ONNX embedding extraction, SQLite embedding cache,
cosine-based matching, and relational logging.

Placeholders for model assets:
- face detection YuNet ONNX: "face_detection_yunet_2023mar.onnx"
- EdgeFace ONNX: "edgeface.onnx"

This script follows the technical architecture requirements from the
project prompt. Run on Python 3.10+ with required packages installed.
"""

from __future__ import annotations

import gc
import sqlite3
import time
from typing import Dict, Optional, Tuple

import numpy as np
import onnxruntime as ort
import cv2


# ----- Configuration (replace placeholders with actual paths) -----
YU_NET_ONNX_PATH = "face_detection_yunet_2023mar.onnx"  # <-- replace with actual path
EDGEFACE_ONNX_PATH = "edgeface.onnx"  # <-- replace with actual path

CAMERA_INDEX = 4
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
DETECTION_DOWNSAMPLE = (640, 480)
DETECTION_SCORE_THRESHOLD = 0.6
DETECTION_TOP_K = 1

EMBEDDING_SIZE = 512
EMBEDDING_THRESHOLD_DISTANCE = 0.40  # Cosine distance threshold (lower is more similar)

DB_PATH = "edge_local.db"


# ----- Database helpers -----
def ensure_db_schema(db_path: str = DB_PATH) -> None:
    """Create required tables if they do not exist."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            face_vector BLOB,
            active INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_auth_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            auth_status TEXT,
            confidence_score REAL,
            timestamp TEXT DEFAULT (datetime('now')),
            sync_status INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


def load_embeddings_from_db(db_path: str = DB_PATH) -> Dict[int, np.ndarray]:
    """Load active user embeddings from the SQLite DB.

    Returns a dict mapping user_id -> embedding (np.float32 array).
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT user_id, face_vector FROM edge_users WHERE active=1")
    rows = cur.fetchall()
    conn.close()

    embeddings: Dict[int, np.ndarray] = {}
    for user_id, blob in rows:
        if blob is None:
            continue
        arr = np.frombuffer(blob, dtype=np.float32)
        if arr.size == EMBEDDING_SIZE:
            embeddings[int(user_id)] = arr
    return embeddings


def log_event(user_id: Optional[int], auth_status: str, confidence_score: float, db_path: str = DB_PATH) -> None:
    """Write an authentication event to `edge_auth_logs`."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO edge_auth_logs (user_id, auth_status, confidence_score, sync_status) VALUES (?, ?, ?, 0)",
        (user_id, auth_status, float(confidence_score)),
    )
    conn.commit()
    conn.close()


# ----- Model initialization & inference -----
def init_yunet(model_path: str = YU_NET_ONNX_PATH, downsample_size: Tuple[int, int] = DETECTION_DOWNSAMPLE) -> cv2.FaceDetectorYN:
    """Initialize OpenCV YuNet face detector with the specified model.

    The input size is set dynamically later based on frames used for detection.
    """
    # create with placeholder input size; will call setInputSize later
    input_size = (downsample_size[0], downsample_size[1])
    detector = cv2.FaceDetectorYN.create(model_path, '', input_size, DETECTION_SCORE_THRESHOLD, 0.3, DETECTION_TOP_K)
    return detector


def init_edgeface(model_path: str = EDGEFACE_ONNX_PATH) -> ort.InferenceSession:
    """Initialize ONNX runtime session for EdgeFace model."""
    sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    return sess


def preprocess_for_edgeface(face_crop: np.ndarray) -> np.ndarray:
    """Preprocess a face crop for EdgeFace ONNX model.

    - Resize to 112x112
    - Convert to float32
    - Normalize using standard EdgeFace convention: (x - 127.5) / 128.0
    - Convert to NCHW layout
    """
    face = cv2.resize(face_crop, (112, 112), interpolation=cv2.INTER_LINEAR)
    face = face.astype(np.float32)
    face = (face - 127.5) / 128.0
    face = np.transpose(face, (2, 0, 1))  # HWC -> CHW
    face = np.expand_dims(face, axis=0).astype(np.float32)
    return face


def extract_embedding_from_edgeface(sess: ort.InferenceSession, preprocessed: np.ndarray) -> np.ndarray:
    """Run ONNX session to extract embedding and return a 1D float32 numpy array.

    After extracting the embedding, this function does NOT keep any image buffers
    referenced by the caller (caller is responsible for zero-image enforcement).
    """
    input_name = sess.get_inputs()[0].name
    out = sess.run(None, {input_name: preprocessed})
    embedding = np.array(out[0], dtype=np.float32).reshape(-1)
    # L2-normalize embedding for stable cosine comparisons
    norm = np.linalg.norm(embedding) + 1e-10
    embedding = embedding / norm
    return embedding


# ----- Matching utilities -----
def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine distance in [0, 2] where 0 = identical.

    distance = 1 - cosine_similarity
    """
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-10
    cos_sim = float(np.dot(a, b) / denom)
    distance = 1.0 - cos_sim
    return distance


def find_best_match(live_embedding: np.ndarray, db_embeddings: Dict[int, np.ndarray]) -> Tuple[Optional[int], float]:
    """Return best user_id and confidence score (cosine similarity).

    If no candidates, returns (None, 0.0)
    """
    best_id = None
    best_distance = float('inf')
    for user_id, emb in db_embeddings.items():
        d = cosine_distance(live_embedding, emb)
        if d < best_distance:
            best_distance = d
            best_id = user_id
    if best_id is None:
        return None, 0.0
    similarity = 1.0 - best_distance
    return best_id, float(similarity)


# ----- Camera capture & main loop -----
def init_camera(index: int = CAMERA_INDEX) -> cv2.VideoCapture:
    """Initialize V4L2 camera with MJPG protection and target 720p.

    Important: set MJPG before applying higher resolutions to avoid kernel freezes.
    """
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    # Enforce MJPG to avoid USB ring buffer saturation
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    # Request 720p
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    # Give sensor time to negotiate
    time.sleep(2.0)
    return cap


def run_stream(
    camera_index: int = CAMERA_INDEX,
    yunet_model: str = YU_NET_ONNX_PATH,
    edgeface_model: str = EDGEFACE_ONNX_PATH,
):
    """Main loop: read frames, detect faces, extract embeddings, match, and log."""
    ensure_db_schema()
    db_embeddings = load_embeddings_from_db()

    # Initialize models
    detector = init_yunet(yunet_model, DETECTION_DOWNSAMPLE)
    edgeface_sess = init_edgeface(edgeface_model)

    cap = init_camera(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open camera index {camera_index}")

    frame_counter = 0
    last_event_time = 0.0
    cooldown_seconds = 3.0
    detection_interval = 10

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                # Camera returned nothing; short sleep and continue
                time.sleep(0.01)
                continue

            display_frame = frame.copy()
            status_text = "Waiting for face..."
            status_color = (255, 255, 0)  # cyan for waiting

            # Draw a small HUD with current timestamp
            cv2.putText(display_frame, time.strftime('%Y-%m-%d %H:%M:%S'), (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            # Process detection only at specified interval
            if frame_counter % detection_interval == 0 and (time.time() - last_event_time) > cooldown_seconds:
                # Downsample for detection to save CPU
                small = cv2.resize(frame, DETECTION_DOWNSAMPLE, interpolation=cv2.INTER_LINEAR)
                # set detector input size dynamically
                detector.setInputSize((DETECTION_DOWNSAMPLE[0], DETECTION_DOWNSAMPLE[1]))
                try:
                    _, faces = detector.detect(small)
                except Exception:
                    faces = None

                if faces is None or len(faces) == 0:
                    # No detection; render waiting status
                    status_text = "Waiting for face..."
                    status_color = (255, 255, 0)
                else:
                    # faces is an array of shape (N, 15) per YuNet output: [x, y, w, h, score, ...]
                    # We limited top_k=1 so we take the first row
                    f = faces[0]
                    x, y, w, h, score = int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[4])
                    if score < DETECTION_SCORE_THRESHOLD:
                        status_text = "Waiting for face..."
                        status_color = (255, 255, 0)
                    else:
                        # Compute bounding box on the original full-resolution frame
                        # small -> original scale factor
                        sx = frame.shape[1] / DETECTION_DOWNSAMPLE[0]
                        sy = frame.shape[0] / DETECTION_DOWNSAMPLE[1]
                        bx = max(0, int(x * sx))
                        by = max(0, int(y * sy))
                        bw = max(1, int(w * sx))
                        bh = max(1, int(h * sy))

                        # Draw box
                        cv2.rectangle(display_frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)

                        # Extract crop from ORIGINAL frame (high topology accuracy)
                        crop = frame[by:by + bh, bx:bx + bw]
                        if crop.size == 0:
                            status_text = "Face too small"
                            status_color = (0, 165, 255)
                        else:
                            # Preprocess and infer embedding
                            pre = preprocess_for_edgeface(crop)
                            embedding = extract_embedding_from_edgeface(edgeface_sess, pre)

                            # Zero-Image Enforcement: delete raw crop and preprocessed arrays promptly
                            del crop
                            del pre
                            gc.collect()

                            # Refresh embeddings cache occasionally (simple policy: every auth attempt)
                            db_embeddings = load_embeddings_from_db()

                            matched_user, confidence = find_best_match(embedding, db_embeddings)
                            # compute cosine distance for threshold check
                            distance = 1.0 - confidence
                            if matched_user is not None and distance < EMBEDDING_THRESHOLD_DISTANCE:
                                # SUCCESS
                                status_text = f"Authorized: user {matched_user} ({confidence:.3f})"
                                status_color = (0, 255, 0)
                                log_event(matched_user, 'SUCCESS', float(confidence))
                                last_event_time = time.time()
                            else:
                                status_text = f"Unauthorized ({confidence:.3f})"
                                status_color = (0, 0, 255)
                                log_event(None, 'FAILED', float(confidence))
                                last_event_time = time.time()

                            # Ensure embedding memory is released
                            del embedding
                            gc.collect()

            # Overlay status text
            cv2.putText(display_frame, status_text, (10, display_frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)

            cv2.imshow('Edge Kiosk (Zero-Image)', display_frame)

            frame_counter += 1

            # Key handling
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

    finally:
        try:
            cap.release()
        except Exception:
            pass
        cv2.destroyAllWindows()


def main():
    run_stream()


if __name__ == '__main__':
    main()
