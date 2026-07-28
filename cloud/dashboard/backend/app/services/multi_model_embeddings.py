"""Fail-closed, staged generation of the required enrollment embeddings."""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy.orm import Session

from app.facial_recognition.embedder import EdgeFaceEmbedder
from app.models.models import User, UserFaceEmbedding

SFACE = "openvc_sface"
AURAFACE = "auraface"
ROOT = Path(__file__).resolve().parents[5]


class EnrollmentEmbeddingError(ValueError):
    """A pose/model could not produce a usable enrollment template."""


class MultiModelEmbeddingService:
    def __init__(self):
        self.sface_path = Path(
            os.getenv(
                "SFACE_MODEL_PATH",
                ROOT / "cloud/models/sface/face_recognition_sface_2021dec.onnx",
            )
        )
        self.auraface_path = os.getenv(
            "AURAFACE_MODEL_PATH",
            str(ROOT / "cloud/models/auraface/glintr100.onnx"),
        )
        self._sface = None
        self._auraface = None

    def preflight(self, models=(SFACE, AURAFACE)) -> None:
        """Verify model files and initialize each required backend."""
        for model_name in models:
            if model_name == SFACE:
                if not self.sface_path.is_file():
                    raise EnrollmentEmbeddingError(f"{SFACE}: model not found: {self.sface_path}")
                if self._sface is None:
                    try:
                        self._sface = cv2.FaceRecognizerSF.create(str(self.sface_path), "")
                    except Exception as exc:
                        raise EnrollmentEmbeddingError(f"{SFACE}: model initialization failed: {exc}") from exc
            elif model_name == AURAFACE:
                if not self.auraface_path or not Path(self.auraface_path).is_file():
                    raise EnrollmentEmbeddingError(f"{AURAFACE}: model not found: {self.auraface_path}")
                if self._auraface is None:
                    try:
                        self._auraface = EdgeFaceEmbedder(self.auraface_path)
                    except Exception as exc:
                        raise EnrollmentEmbeddingError(f"{AURAFACE}: model initialization failed: {exc}") from exc
            else:
                raise EnrollmentEmbeddingError(f"{model_name}: unsupported embedding model")

    @staticmethod
    def _validate(vector: object, pose: str, model_name: str) -> np.ndarray:
        array = np.asarray(vector, dtype=np.float32).reshape(-1)
        if array.size == 0 or not np.isfinite(array).all():
            raise EnrollmentEmbeddingError(f"{pose}/{model_name}: embedding is empty or non-finite")
        if float(np.linalg.norm(array)) <= 1e-12:
            raise EnrollmentEmbeddingError(f"{pose}/{model_name}: embedding has zero norm")
        return array

    def _sface_embedding(self, image: np.ndarray) -> np.ndarray:
        face = cv2.resize(image, (112, 112))
        return np.asarray(self._sface.feature(face), dtype=np.float32).reshape(-1)

    def _auraface_embedding(self, image: np.ndarray) -> np.ndarray:
        return np.asarray(self._auraface.embed(image), dtype=np.float32).reshape(-1)

    def generate_images(self, images: dict[str, np.ndarray], models=(SFACE, AURAFACE)) -> dict[tuple[str, str], bytes]:
        """Generate every pose/model result before any database mutation."""
        self.preflight(models)
        generators = {SFACE: self._sface_embedding, AURAFACE: self._auraface_embedding}
        staged: dict[tuple[str, str], bytes] = {}
        for pose, image in images.items():
            if image is None or not isinstance(image, np.ndarray) or image.size == 0:
                raise EnrollmentEmbeddingError(f"{pose}: image is unreadable or empty")
            for model_name in models:
                try:
                    vector = self._validate(generators[model_name](image), pose, model_name)
                except EnrollmentEmbeddingError:
                    raise
                except Exception as exc:
                    raise EnrollmentEmbeddingError(f"{pose}/{model_name}: embedding failed: {exc}") from exc
                staged[(pose, model_name)] = vector.tobytes()
        return staged

    @staticmethod
    def _file_path(web_path: str) -> Path:
        static = Path(__file__).resolve().parents[1] / "static"
        value = web_path.lstrip("/").removeprefix("static/")
        return static / value

    def _stage_user_images(self, user: User, models) -> tuple[dict[str, np.ndarray], list[str]]:
        images: dict[str, np.ndarray] = {}
        errors: list[str] = []
        for record in user.images:
            path = self._file_path(record.image_path)
            image = cv2.imread(str(path))
            if image is None:
                errors.append(f"user {user.user_id}/{record.template_name}: unreadable image {record.image_path}")
            else:
                images[str(record.template_name)] = image
        if errors:
            return {}, errors
        return images, errors

    def reembed_all(self, db: Session, models=(SFACE, AURAFACE)):
        """Stage all users first; preserve every old template on any failure."""
        result = {"written": 0, "skipped": 0, "errors": [], "models": list(models), "committed": False}
        try:
            self.preflight(models)
        except EnrollmentEmbeddingError as exc:
            result["errors"].append(str(exc))
            return result

        staged_by_user: dict[int, dict[tuple[str, str], bytes]] = {}
        for user in db.query(User).all():
            if not user.images:
                continue
            images, errors = self._stage_user_images(user, models)
            if errors:
                result["errors"].extend(errors)
                continue
            try:
                staged_by_user[user.user_id] = self.generate_images(images, models)
            except EnrollmentEmbeddingError as exc:
                result["errors"].append(f"user {user.user_id}: {exc}")

        if result["errors"]:
            result["skipped"] = len(result["errors"])
            return result

        try:
            for user_id, records in staged_by_user.items():
                db.query(UserFaceEmbedding).filter_by(user_id=user_id).delete()
                for (pose, model_name), embedding in records.items():
                    db.add(UserFaceEmbedding(user_id=user_id, template_name=pose, model_name=model_name, embedding=embedding))
                db.query(User).filter_by(user_id=user_id).update(
                    {User.updated_at: __import__("datetime").datetime.utcnow()}, synchronize_session=False
                )
                result["written"] += len(records)
            db.commit()
            result["committed"] = True
        except Exception as exc:
            db.rollback()
            result["errors"].append(f"database: {exc}")
        return result
