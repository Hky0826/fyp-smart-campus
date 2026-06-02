import json
import os
import sqlite3
import sys

import cv2
import numpy as np
from deepface import DeepFace

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOM_DIR = os.path.join(CURRENT_DIR, "custom")
for path in (CUSTOM_DIR, CURRENT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from camera import CameraCapture

# --- Configuration ---
DB_PATH = "edge_local.db"
MODEL_NAME = "Facenet"


def capture_frame_from_camera(camera_index=0, width=640, height=480):
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

def add_user_with_embedding(full_name, role_name, image_source="camera"):
    """
    Add a new user with their facial embedding to the database.
    
    Args:
        full_name: User's full name
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
    
    # Step 2: Extract embedding
    print("Extracting facial embedding...")
    try:
        result = DeepFace.represent(img_path=frame, model_name=MODEL_NAME, enforce_detection=True)
        if len(result) == 0:
            print("No face detected in image.")
            return False
        
        embedding = np.array(result[0]['embedding'])
        print(f"Embedding extracted: {len(embedding)} dimensions")
    
    except Exception as e:
        print(f"Error extracting embedding: {e}")
        return False
    
    # Step 3: Insert into database
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # Insert user
        cur.execute('''
            INSERT INTO users (full_name, role_name)
            VALUES (?, ?)
        ''', (full_name, role_name))
        
        user_id = cur.lastrowid
        print(f"User '{full_name}' created with ID: {user_id}")
        
        # Convert embedding to JSON and insert
        embedding_json = json.dumps(embedding.tolist())
        cur.execute('''
            INSERT INTO face_embeddings (user_id, embedding_blob)
            VALUES (?, ?)
        ''', (user_id, embedding_json))
        
        conn.commit()
        conn.close()
        
        print(f"✓ Successfully added {full_name} with valid embedding!")
        return True
    
    except Exception as e:
        print(f"Error inserting into database: {e}")
        return False

if __name__ == "__main__":
    # Interactive prompt: ask for full name and role, then capture from camera
    print("=== Add User (interactive) ===")
    try:
        full_name = input("Full name: ").strip()
        role_name = input("Role name (e.g. Admin, Staff): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("Input cancelled.")
        sys.exit(1)

    if not full_name:
        print("Full name is required. Exiting.")
        sys.exit(1)

    success = add_user_with_embedding(full_name, role_name or "User", image_source="camera")
    if not success:
        print("Failed to add user.")
