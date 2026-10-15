"""MiniFASNet presentation attack detection (PAD) adapter for edge access control."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np

from .pad import PADResult

logger = logging.getLogger(__name__)

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


class PADModel:
    """Production ONNX adapter for Presentation Attack Detection (e.g. MiniFASNet).

    Adheres to the PresentationAttackDetector protocol expected by the access control
    pipeline. Supports multi-scale bounding-box expansion, padding, 80x80 preprocessing,
    and OpenCV DNN inference with CPU/NEON acceleration on Raspberry Pi 5.
    """

    def __init__(
        self,
        model_path: Path | str,
        model_version: str = "minifasnet-v2",
        threshold: float = 0.75,
        scale: float = 2.7,
    ) -> None:
        self.model_path = Path(model_path)
        self.model_version = str(model_version)
        self.threshold = float(threshold)
        self.scale = float(scale)
        self.net: Optional[Any] = None

        self._load_model()

    def _load_model(self) -> None:
        if cv2 is None:
            logger.warning("OpenCV is unavailable; PADModel cannot perform DNN inference")
            return

        if not self.model_path.is_file():
            logger.warning("PAD model file not found at: %s", self.model_path)
            return

        try:
            self.net = cv2.dnn.readNetFromONNX(str(self.model_path))
            # Configure backend for CPU / ARM NEON
            if hasattr(cv2.dnn, "DNN_BACKEND_OPENCV"):
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            if hasattr(cv2.dnn, "DNN_TARGET_CPU"):
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            logger.info(
                "Successfully loaded PAD model (%s) from %s with threshold=%.2f, scale=%.2f",
                self.model_version,
                self.model_path,
                self.threshold,
                self.scale,
            )
        except Exception as exc:
            logger.error("Failed to load ONNX model %s: %s", self.model_path, exc)
            self.net = None

    @staticmethod
    def _get_new_box(
        src_w: int,
        src_h: int,
        bbox: list[int | float] | tuple[int | float, ...],
        scale: float,
    ) -> Tuple[int, int, int, int]:
        """Calculate scaled bounding box with boundary shifting matching MiniFASNet."""
        x = float(bbox[0])
        y = float(bbox[1])
        box_w = float(bbox[2])
        box_h = float(bbox[3])

        scale = min((src_h - 1) / max(1.0, box_h), min((src_w - 1) / max(1.0, box_w), scale))

        new_width = box_w * scale
        new_height = box_h * scale
        center_x, center_y = box_w / 2.0 + x, box_h / 2.0 + y

        left_top_x = center_x - new_width / 2.0
        left_top_y = center_y - new_height / 2.0
        right_bottom_x = center_x + new_width / 2.0
        right_bottom_y = center_y + new_height / 2.0

        if left_top_x < 0:
            right_bottom_x -= left_top_x
            left_top_x = 0.0

        if left_top_y < 0:
            right_bottom_y -= left_top_y
            left_top_y = 0.0

        if right_bottom_x > src_w - 1:
            left_top_x -= right_bottom_x - src_w + 1
            right_bottom_x = float(src_w - 1)

        if right_bottom_y > src_h - 1:
            left_top_y -= right_bottom_y - src_h + 1
            right_bottom_y = float(src_h - 1)

        l_x = max(0, min(int(round(left_top_x)), src_w - 1))
        l_y = max(0, min(int(round(left_top_y)), src_h - 1))
        r_x = max(0, min(int(round(right_bottom_x)), src_w - 1))
        r_y = max(0, min(int(round(right_bottom_y)), src_h - 1))
        return l_x, l_y, r_x, r_y

    def extract_crop(self, frame: np.ndarray, face: Any) -> Optional[np.ndarray]:
        """Extract a scaled face crop for MiniFASNet (80x80) using bounding box shifting."""
        if cv2 is None or frame is None or frame.size == 0:
            return None

        if hasattr(face, "xyxy_int"):
            x1, y1, x2, y2 = face.xyxy_int()
        elif hasattr(face, "bbox"):
            x1, y1, x2, y2 = [int(round(v)) for v in face.bbox]
        else:
            return None

        if x2 <= x1 or y2 <= y1:
            return None

        frame_h, frame_w = frame.shape[:2]
        box_w = x2 - x1
        box_h = y2 - y1

        left_top_x, left_top_y, right_bottom_x, right_bottom_y = self._get_new_box(
            frame_w, frame_h, [x1, y1, box_w, box_h], self.scale
        )

        if right_bottom_x <= left_top_x or right_bottom_y <= left_top_y:
            return None

        crop = frame[left_top_y : right_bottom_y + 1, left_top_x : right_bottom_x + 1]
        if crop.size == 0:
            return None

        resized = cv2.resize(
            crop,
            (80, 80),
            interpolation=cv2.INTER_AREA if crop.shape[0] >= 80 else cv2.INTER_LINEAR,
        )
        return resized

    def check(self, frame: np.ndarray, face: Any) -> PADResult:
        """Run PAD inference and return a standardized PADResult."""
        if cv2 is None:
            return PADResult("unknown", 0.0, self.model_version, self.threshold, "opencv_unavailable")

        if self.net is None:
            return PADResult("unknown", 0.0, self.model_version, self.threshold, "pad_model_not_loaded")

        crop = self.extract_crop(frame, face)
        if crop is None:
            return PADResult("unknown", 0.0, self.model_version, self.threshold, "invalid_face_crop")

        try:
            # MiniFASNet expects (1, 3, 80, 80) BGR input with raw [0, 255] values
            blob = cv2.dnn.blobFromImage(
                crop,
                scalefactor=1.0,
                size=(80, 80),
                mean=(0, 0, 0),
                swapRB=False,
            )
            self.net.setInput(blob)
            raw_output = self.net.forward()

            output = np.asarray(raw_output).flatten()
            if output.size >= 3:
                # Softmax across logits
                exp_logits = np.exp(output - np.max(output))
                probs = exp_logits / np.sum(exp_logits)
                # In MiniFASNet-V2:
                # Class 0: Print-Attack (Fake)
                # Class 1: Real / Live
                # Class 2: Replay-Attack (Fake)
                live_score = float(probs[1])
                logger.info(
                    "MiniFASNet probabilities: live=%.4f (class 1) print_fake=%.4f (class 0) replay_fake=%.4f (class 2)",
                    live_score, float(probs[0]), float(probs[2]),
                )
            elif output.size == 2:
                exp_logits = np.exp(output - np.max(output))
                probs = exp_logits / np.sum(exp_logits)
                # Standard binary: Class 0: Spoof, Class 1: Live
                live_score = float(probs[1])
            elif output.size == 1:
                # Sigmoid for single-logit binary model
                live_score = float(1.0 / (1.0 + np.exp(-output[0])))
            else:
                return PADResult("unknown", 0.0, self.model_version, self.threshold, "malformed_output")

            state = "live" if live_score >= self.threshold else "spoof"
            reason = "live_face_verified" if state == "live" else "insufficient_liveness_score"
            return PADResult(state, live_score, self.model_version, self.threshold, reason)

        except Exception as exc:
            logger.error("PAD inference error: %s", exc)
            return PADResult("unknown", 0.0, self.model_version, self.threshold, f"inference_error: {exc}")
