import os
import cv2
import numpy as np
import sys

# Ensure project root is importable
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from access_control.facial_recognition.src.face.detection import YuNetDetector
from access_control.facial_recognition.src.face.alignment import FaceAligner
from access_control.facial_recognition.src.face.embedding import SFaceEmbedder

ENABLE_CAMERA_SIMULATION = False
CAMERA_SCALE_PERCENT = 20
CAMERA_BLUR_KERNEL = (5, 5)
CAMERA_NOISE_VARIANCE = 10.0
CAMERA_JPEG_QUALITY = 30


class CameraSimulator:
    def __init__(
        self,
        enabled=ENABLE_CAMERA_SIMULATION,
        scale_percent=CAMERA_SCALE_PERCENT,
        blur_kernel=CAMERA_BLUR_KERNEL,
        noise_variance=CAMERA_NOISE_VARIANCE,
        jpeg_quality=CAMERA_JPEG_QUALITY,
    ):
        self.enabled = enabled
        self.scale_percent = scale_percent
        self.blur_kernel = blur_kernel
        self.noise_variance = noise_variance
        self.jpeg_quality = jpeg_quality

    def apply(self, img):
        if not self.enabled or img is None:
            return img

        h, w = img.shape[:2]
        new_w = max(1, int(w * self.scale_percent / 100))
        new_h = max(1, int(h * self.scale_percent / 100))
        img_down = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        img_degraded = cv2.resize(img_down, (w, h), interpolation=cv2.INTER_NEAREST)

        img_degraded = cv2.GaussianBlur(img_degraded, self.blur_kernel, 0)

        sigma = self.noise_variance ** 0.5
        noise = np.random.normal(0, sigma, img_degraded.shape)
        img_degraded = np.clip(img_degraded.astype(np.float32) + noise, 0, 255).astype(np.uint8)

        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        success, enc_img = cv2.imencode(".jpg", img_degraded, encode_param)
        if success:
            img_degraded = cv2.imdecode(enc_img, 1)

        return img_degraded


class ModelInterface:
    def __init__(self, detector_path=None, embedder_path=None, device="cpu", camera_simulator=None):
        self.detector = None
        self.aligner = None
        self.embedder = None
        self.camera_simulator = camera_simulator or CameraSimulator()

        if detector_path and os.path.exists(detector_path):
            self.detector = YuNetDetector(detector_path)
        else:
            print(f"Warning: Detector model not found at {detector_path}.")

        if embedder_path and os.path.exists(embedder_path):
            self.embedder = SFaceEmbedder(model_path=embedder_path)
            self.aligner = FaceAligner()
        else:
            print(f"Warning: Embedder model not found at {embedder_path}.")

        self.embedding_cache = {}

    def extract_embedding(self, img_path):
        if img_path in self.embedding_cache:
            return self.embedding_cache[img_path]

        if not self.embedder:
            np.random.seed(abs(hash(img_path)) % (2**32))
            emb = np.random.randn(128)
            emb = emb / np.linalg.norm(emb)
            self.embedding_cache[img_path] = emb
            return emb

        img = cv2.imread(img_path)
        if img is None:
            raise FileNotFoundError(f"Cannot read image {img_path}")

        img = self.camera_simulator.apply(img)

        faces = None
        if self.detector:
            faces = self.detector.detect(img)

        if faces is not None and len(faces) > 0:
            face = faces[0]
            align_result = self.aligner.align(img, face)

            if align_result.success and align_result.aligned_face is not None:
                crop = align_result.aligned_face
            else:
                x1, y1, x2, y2 = face.xyxy_int()
                crop = img[max(0, y1) : min(img.shape[0], y2), max(0, x1) : min(img.shape[1], x2)]
                if crop.size == 0:
                    crop = img
                crop = cv2.resize(crop, (112, 112))
            emb = self.embedder.embed(crop)
        else:
            crop = cv2.resize(img, (112, 112))
            emb = self.embedder.embed(crop)

        self.embedding_cache[img_path] = emb
        return emb
