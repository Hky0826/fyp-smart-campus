import cv2
import sqlite3
import json
import numpy as np
from deepface import DeepFace

# --- Configuration ---
DB_PATH = "edge_local.db"
MODEL_NAME = "Facenet"

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
        print("Opening camera... Press SPACE to capture, ESC to cancel")
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("Error: Could not open camera.")
            return False
        
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame.")
                cap.release()
                return False
            
            cv2.putText(frame, "Press SPACE to capture, ESC to cancel", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow('Capture Face', frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == 32:  # SPACE
                print("Face captured!")
                break
            elif key == 27:  # ESC
                print("Capture cancelled.")
                cap.release()
                cv2.destroyAllWindows()
                return False
        
        cap.release()
        cv2.destroyAllWindows()
    
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
    # Example 1: Add user from camera
    print("=== Adding User from Camera ===")
    add_user_with_embedding("John Doe", "Admin", image_source="camera")
    
    # Example 2: Add user from image file
    # add_user_with_embedding("Jane Smith", "Staff", image_source="path/to/image.jpg")
