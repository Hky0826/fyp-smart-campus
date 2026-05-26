import cv2
import sqlite3
import json
import numpy as np
from deepface import DeepFace
from scipy.spatial.distance import cosine
import time

# --- Configuration ---
DB_PATH = "FacialRecognition/edge_local.db"
MODEL_NAME = "Facenet"
THRESHOLD = 0.40 # Cosine distance threshold for Facenet
COOLDOWN_SECONDS = 3.0 # Cooldown between detections to prevent spam

def load_embeddings_from_db():
    """
    Connect to edge_local.db, fetch embeddings, and deserialize them.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Fetch user_id and the serialized embedding blob
    cur.execute("SELECT user_id, embedding_blob FROM face_embeddings")
    records = cur.fetchall()
    
    stored_embeddings = []
    for user_id, blob in records:
        try:
            # Deserialize JSON string to Python list, then to numpy array
            embedding_list = json.loads(blob)
            embedding = np.array(embedding_list)
            stored_embeddings.append({"user_id": user_id, "embedding": embedding})
        except Exception as e:
            print(f"Error deserializing embedding for user {user_id}: {e}")
            
    conn.close()
    return stored_embeddings

def check_liveness(frame):
    """
    Dummy function for Liveness Check.
    For this prototype phase, it simply returns True to simulate passing a liveness test.
    """
    return True

def log_event(user_id, event_type, similarity=None):
    """
    Log the authentication event to the database buffer.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO auth_events_buffer (user_id, event_type, similarity)
        VALUES (?, ?, ?)
    ''', (user_id, event_type, similarity))
    conn.commit()
    conn.close()

def main():
    print("Initializing Database...")
    stored_embeddings = load_embeddings_from_db()
    print(f"Loaded {len(stored_embeddings)} embeddings from database.")

    # Start webcam capture
    cap = cv2.VideoCapture(0)
    
    # Process every Nth frame to reduce latency and maintain smooth video
    frame_count = 0
    process_interval = 10 
    
    auth_status = "Waiting for face..."
    auth_color = (255, 255, 0) # Cyan in BGR
    current_box = None
    validation_time_ms = 0
    last_detection_time = 0

    print("Starting video capture loop. Press 'q' to quit.")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame. Exiting...")
            break
            
        frame_count += 1
        
        # Add visual feedback on the screen
        display_text = auth_status
        if validation_time_ms > 0 and "Waiting" not in auth_status and "Error" not in auth_status:
            display_text += f" ({validation_time_ms}ms)"
            
        cv2.putText(frame, display_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, auth_color, 2)
        
        if current_box:
            x, y, w, h = current_box
            if all(v is not None for v in (x, y, w, h)):
                cv2.rectangle(frame, (x, y), (x+w, y+h), auth_color, 2)
                
        cv2.imshow("Edge Biometric Authentication", frame)
        
        # Trigger matching engine periodically to save CPU and hit < 2 sec latency goal
        if frame_count % process_interval == 0 and (time.time() - last_detection_time > COOLDOWN_SECONDS):
            # 1. Liveness check
            if check_liveness(frame):
                try:
                    # 2. Zero-Image Feature Extraction
                    # enforce_detection=True will raise ValueError if no face is found
                    # After this block, the raw frame data is strictly discarded.
                    start_time = time.time()
                    result = DeepFace.represent(img_path=frame, model_name=MODEL_NAME, enforce_detection=True)
                    
                    if len(result) > 0:
                        live_embedding = np.array(result[0]["embedding"])
                        
                        # Store bounding box
                        facial_area = result[0].get("facial_area", {})
                        if facial_area:
                            current_box = (facial_area.get('x'), facial_area.get('y'), 
                                           facial_area.get('w'), facial_area.get('h'))
                        
                        # 3. Matching Engine
                        best_match_id = None
                        best_similarity = -1.0 
                        min_distance = float('inf')
                        
                        # Compare the live extracted embedding against stored embeddings
                        for stored in stored_embeddings:
                            # Cosine distance: 0 is identical, 2 is opposite
                            distance = cosine(live_embedding, stored["embedding"])
                            similarity = 1 - distance # 1 is identical
                            
                            if distance < min_distance:
                                min_distance = distance
                                best_similarity = similarity
                                best_match_id = stored["user_id"]
                                
                        # Check against confidence threshold
                        if min_distance < THRESHOLD:
                            auth_status = f"Access Granted (User {best_match_id})"
                            auth_color = (0, 255, 0) # Green
                            log_event(best_match_id, 'SUCCESS', best_similarity)
                        else:
                            auth_status = "Access Denied"
                            auth_color = (0, 0, 255) # Red
                            log_event(None, 'FAILURE', best_similarity)
                            
                        validation_time_ms = int((time.time() - start_time) * 1000)
                        print(f"{auth_status} - Validation Time: {validation_time_ms} ms")
                        last_detection_time = time.time()
                            
                except ValueError:
                    # DeepFace raises ValueError if no face is detected
                    auth_status = "Waiting for face..."
                    auth_color = (255, 255, 0)
                    current_box = None
                except Exception as e:
                    print(f"Error during extraction: {e}")
                    auth_status = "Error processing frame"
                    auth_color = (0, 0, 255)
                    current_box = None

        # Handle key press for quitting
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Cleanup
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
