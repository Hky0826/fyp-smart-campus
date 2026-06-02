import json
import os
import sqlite3
import sys

import cv2
import numpy as np

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOM_DIR = os.path.join(CURRENT_DIR, "custom")
for path in (CUSTOM_DIR, CURRENT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from camera import CameraCapture
from detector import YuNetDetector
from embedder import EdgeFaceEmbedder

# --- Configuration ---
DB_PATH = "edge_local.db"
MODEL_NAME = "Facenet"

# Model paths (match kiosk defaults)
FACE_DETECTION_MODEL = os.path.abspath(os.path.join(CURRENT_DIR, "..", "models", "face_detection_yunet_2023mar_int8bq.onnx"))
EDGEFACE_MODEL = os.path.abspath(os.path.join(CURRENT_DIR, "..", "models", "edgeface_xxs.pt"))


def capture_frame_from_camera(camera_index=4, width=640, height=480):
    """Capture a single frame using the same camera setup as the kiosk app."""

    print("Opening camera... Press SPACE to capture, ESC to cancel")
    camera = CameraCapture(index=camera_index, width=width, height=height)

    try:
        camera.open()
    except Exception as exc:
        print(f"Error: Could not open camera. {exc}")
        return None

    try:
        while True:
            ret, frame = camera.read()
            if not ret or frame is None:
                print("Failed to grab frame.")
                return None

            preview = cv2.flip(frame.copy(), 1)
            cv2.putText(
                preview,
                "Press SPACE to capture, ESC to cancel",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            cv2.imshow("Capture Face", preview)

            key = cv2.waitKey(1) & 0xFF
            if key == 32:
                print("Face captured!")
                return frame
            if key == 27:
                print("Capture cancelled.")
                return None
    finally:
        camera.release()
        cv2.destroyAllWindows()

def add_user_with_embedding(role_name, image_source="camera"):
    """
    Add a new user with their facial embedding to the database.
    
    Args:
        role_name: User's role (e.g., "Admin", "User", "Staff")
        image_source: "camera" to capture from webcam, or path to image file
    """
    
    # Step 1: Get image (either from camera or file)
    frame = None
    
    if image_source == "camera":
        frame = capture_frame_from_camera()
        if frame is None:
            return False
    
    else:
        # Load from file
        frame = cv2.imread(image_source)
        if frame is None:
            print(f"Error: Could not load image from {image_source}")
            return False
        print(f"Image loaded from {image_source}")
    
    # Step 2: Detect face and extract embedding using EdgeFace
    print("Detecting face and extracting embedding with EdgeFace...")
    try:
        # Prepare detector and embedder
        orig_h, orig_w = frame.shape[:2]
        det_w = min(640, orig_w)
        det_h = min(480, orig_h)
        det_size = (det_w, det_h)

        detector = YuNetDetector(FACE_DETECTION_MODEL, det_size)
        small = cv2.resize(frame, det_size)
        faces = detector.detect(small)

        if faces is None or len(faces) == 0:
            print("No face detected in image.")
            return False

        f = faces[0]
        x, y, w, h = int(f[0]), int(f[1]), int(f[2]), int(f[3])
        scale_x = orig_w / det_w
        scale_y = orig_h / det_h
        bx = int(x * scale_x)
        by = int(y * scale_y)
        bw = int(w * scale_x)
        bh = int(h * scale_y)

        crop = frame[max(0, by):min(orig_h, by + bh), max(0, bx):min(orig_w, bx + bw)]
        if crop.size == 0:
            print("Failed to extract face crop.")
            return False

        embedder = EdgeFaceEmbedder(EDGEFACE_MODEL)
        embedding = embedder.embed(crop).astype(np.float32)
        print(f"Embedding extracted: {embedding.shape[0]} dimensions")

    except Exception as e:
        print(f"Error extracting embedding: {e}")
        return False
    
    # Step 3: Insert into database using Python-side auto-incremented user_id
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Compute next user_id in Python (prototype behavior)
        cur.execute("SELECT MAX(user_id) FROM edge_users")
        row = cur.fetchone()
        max_id = row[0] if row is not None and row[0] is not None else 0
        next_id = int(max_id) + 1

        # Store embedding as float32 blob so StorageManager can read it back
        emb_blob = embedding.astype(np.float32).tobytes()

        # Insert the user record. Leave name NULL (prototype without full name)
        cur.execute(
            "INSERT INTO edge_users (user_id, role_name, face_vector, active) VALUES (?, ?, 1)",
            (next_id, role_name, emb_blob),
        )

        conn.commit()
        conn.close()

        print(f"User created with ID: {next_id}")
        print(f"✓ Successfully added user {next_id} with valid embedding!")
        return True

    except Exception as e:
        print(f"Error inserting into database: {e}")
        return False

if __name__ == "__main__":
    # Example 1: Add user from camera
    print("=== Adding User from Camera ===")
    role_name = input("Enter role name for new user (e.g., Student, Staff): ").strip()
    add_user_with_embedding(role_name, image_source="camera")
    
    # Example 2: Add user from image file
    # add_user_with_embedding("Jane Smith", "Staff", image_source="path/to/image.jpg")
