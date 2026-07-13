import os
import cv2
import numpy as np
import sys

# Ensure project root is importable so 'edge' module can be found
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from edge.facial_recognition.src.face.detection import HailoSCRFDDetector
from edge.facial_recognition.src.face.alignment import FaceAligner
from edge.facial_recognition.src.face.embedding import HailoArcFaceEmbedder

class ModelInterface:
    def __init__(self, detector_path=None, embedder_path=None, device="cpu"):
        self.detector = None
        self.aligner = None
        self.embedder = None
        
        if detector_path and os.path.exists(detector_path):
            self.detector = HailoSCRFDDetector(detector_path)
        else:
            print(f"Warning: Detector model not found at {detector_path}.")
            
        if embedder_path and os.path.exists(embedder_path):
            self.embedder = HailoArcFaceEmbedder(hef_path=embedder_path)
            self.aligner = FaceAligner()
        else:
            print(f"Warning: Embedder model not found at {embedder_path}.")
            
        self.embedding_cache = {}

    def extract_embedding(self, img_path):
        if img_path in self.embedding_cache:
            return self.embedding_cache[img_path]
            
        if not self.embedder:
            np.random.seed(abs(hash(img_path)) % (2**32))
            emb = np.random.randn(512)
            emb = emb / np.linalg.norm(emb)
            self.embedding_cache[img_path] = emb
            return emb
            
        img = cv2.imread(img_path)
        if img is None:
            raise FileNotFoundError(f"Cannot read image {img_path}")
            
        faces = None
        if self.detector:
            # For Hailo SCRFD, detect expects an image, not just a resized frame.
            faces = self.detector.detect(img)
            
        if faces is not None and len(faces) > 0:
            if isinstance(faces[0], np.ndarray):
                print(f"Debug: faces is ndarray list/tuple. Type: {type(faces)}, len/shape: {len(faces) if isinstance(faces, list) else faces.shape}")
                # Fallback in case detect() returns something unexpected
                # Just skip face detection and use center crop
                h, w = img.shape[:2]
                sz = min(h, w)
                crop = img[(h-sz)//2:(h+sz)//2, (w-sz)//2:(w+sz)//2]
            else:
                face = faces[0]
                landmarks = face.landmarks
                
                if landmarks is not None:
                    aligned_face = self.aligner.align(img, landmarks)
                    crop = aligned_face
                else:
                    h, w = img.shape[:2]
                    sz = min(h, w)
                    crop = img[(h-sz)//2:(h+sz)//2, (w-sz)//2:(w+sz)//2]
        else:
            h, w = img.shape[:2]
            sz = min(h, w)
            crop = img[(h-sz)//2:(h+sz)//2, (w-sz)//2:(w+sz)//2]
            
        emb = self.embedder.embed(crop)
        self.embedding_cache[img_path] = emb
        return emb

    def compute_similarity(self, emb1, emb2):
        return np.dot(emb1, emb2)

