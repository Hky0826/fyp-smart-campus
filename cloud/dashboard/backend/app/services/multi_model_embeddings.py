"""Model-specific embedding generation from enrolled image paths."""
from __future__ import annotations
import os
from pathlib import Path
import cv2
import numpy as np
from sqlalchemy.orm import Session
from app.models.models import User, UserFaceEmbedding
from app.facial_recognition.embedder import EdgeFaceEmbedder

SFACE = 'openvc_sface'
AURAFACE = 'auraface'
ROOT = Path(__file__).resolve().parents[5]

class MultiModelEmbeddingService:
    def __init__(self):
        self.sface_path = Path(os.getenv('SFACE_MODEL_PATH', ROOT / 'access_control/models/sface/face_recognition_sface_2021dec.onnx'))
        self.auraface_path = os.getenv('AURAFACE_MODEL_PATH', str(ROOT / 'surveillance/models/glintr100.onnx'))
        self._sface = None
        self._auraface = None
    def _sface_embedding(self, image):
        if not self.sface_path.is_file():
            raise FileNotFoundError(f'SFace model not found: {self.sface_path}')
        if self._sface is None:
            self._sface = cv2.FaceRecognizerSF.create(str(self.sface_path), '')
        face = cv2.resize(image, (112, 112))
        vector = np.asarray(self._sface.feature(face), dtype=np.float32).reshape(-1)
        return vector / max(float(np.linalg.norm(vector)), 1e-12)
    def _auraface_embedding(self, image):
        if not self.auraface_path or not Path(self.auraface_path).is_file():
            raise FileNotFoundError('AuraFace model is required; set AURAFACE_MODEL_PATH to its ONNX model file')
        if self._auraface is None:
            self._auraface = EdgeFaceEmbedder(self.auraface_path)
        return self._auraface.embed(image)
    @staticmethod
    def _file_path(web_path: str):
        static = Path(__file__).resolve().parents[1] / 'static'
        value = web_path.lstrip('/').removeprefix('static/')
        return static / value
    def reembed_all(self, db: Session, models=(SFACE, AURAFACE)):
        result = {'written': 0, 'skipped': 0, 'errors': [], 'models': list(models)}
        generators = {SFACE: self._sface_embedding, AURAFACE: self._auraface_embedding}
        for user in db.query(User).all():
            for record in user.images:
                image = cv2.imread(str(self._file_path(record.image_path)))
                if image is None:
                    result['skipped'] += 1; result['errors'].append(f'user {user.user_id}: unreadable {record.image_path}'); continue
                for model_name in models:
                    try:
                        vector = generators[model_name](image).astype(np.float32).tobytes()
                        row = db.query(UserFaceEmbedding).filter_by(user_id=user.user_id, template_name=record.template_name, model_name=model_name).first()
                        if row: row.embedding = vector
                        else: db.add(UserFaceEmbedding(user_id=user.user_id, template_name=record.template_name, model_name=model_name, embedding=vector))
                        result['written'] += 1
                    except Exception as exc:
                        result['errors'].append(f'user {user.user_id}/{record.template_name}/{model_name}: {exc}')
        db.commit()
        return result
