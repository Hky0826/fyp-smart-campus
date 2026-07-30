"""YuNet face detector adapter for Hailo HEF models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from .loader import HailoModelRunner, BaseHailoRunner

logger = logging.getLogger(__name__)


@dataclass
class YuNetDetectedFace:
    """Detected face structure with bounding box, score, and 5 facial landmarks."""

    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    score: float
    landmarks: Optional[np.ndarray] = None  # Shape (5, 2) array of (x, y) coordinates

    @property
    def x1(self) -> float:
        return self.bbox[0]

    @property
    def y1(self) -> float:
        return self.bbox[1]

    @property
    def x2(self) -> float:
        return self.bbox[2]

    @property
    def y2(self) -> float:
        return self.bbox[3]

    def xyxy_int(self) -> List[int]:
        return [int(round(self.x1)), int(round(self.y1)), int(round(self.x2)), int(round(self.y2))]


def _parse_input_size(runner_shape: Optional[Tuple[int, ...]], default: Tuple[int, int]) -> Tuple[int, int]:
    if not runner_shape:
        return default
    shape = list(runner_shape)
    if len(shape) == 4:
        if shape[1] == 3:
            return (int(shape[3]), int(shape[2]))
        if shape[3] == 3:
            return (int(shape[2]), int(shape[1]))
        return (int(shape[2]), int(shape[1]))
    if len(shape) == 3:
        if shape[0] == 3:
            return (int(shape[2]), int(shape[1]))
        if shape[2] == 3:
            return (int(shape[1]), int(shape[0]))
        return (int(shape[1]), int(shape[0]))
    return default


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0)))


def _nms(faces: List[YuNetDetectedFace], iou_threshold: float = 0.3) -> List[YuNetDetectedFace]:
    if not faces:
        return []
    boxes = np.array([f.bbox for f in faces], dtype=np.float32)
    scores = np.array([f.score for f in faces], dtype=np.float32)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(ovr <= iou_threshold)[0]
        order = order[inds + 1]
    return [faces[k] for k in keep]


def _decode_yunet_raw_heads(
    outputs: Dict[str, np.ndarray],
    input_size: Tuple[int, int],
    confidence_threshold: float,
    orig_shape: Tuple[int, int],
    nms_threshold: float = 0.3,
) -> List[YuNetDetectedFace]:
    """Decodes 3-scale YuNet feature maps (activation1..6, format_conversion1..12) from Hailo-8 NPU."""
    stride_configs = [
        ("activation6", "format_conversion10", "format_conversion12", 8, 80, 80),
        ("activation4", "format_conversion6", "format_conversion8", 16, 40, 40),
        ("activation2", "format_conversion1", "format_conversion3", 32, 20, 20),
    ]

    target_w, target_h = input_size
    orig_h, orig_w = orig_shape
    scale_x = orig_w / target_w
    scale_y = orig_h / target_h
    faces: List[YuNetDetectedFace] = []

    for conf_key, bbox_key, lms_key, stride, grid_h, grid_w in stride_configs:
        conf_arr = outputs.get(conf_key)
        bbox_arr = outputs.get(bbox_key)
        lms_arr = outputs.get(lms_key)
        if conf_arr is None or bbox_arr is None:
            continue

        conf_map = np.squeeze(conf_arr).reshape(-1)
        if conf_map.max() > 1.0 or conf_map.min() < 0.0:
            conf_map = _sigmoid(conf_map)

        bbox_reg = np.squeeze(bbox_arr).reshape(-1, 4)
        lms_reg = np.squeeze(lms_arr).reshape(-1, 10) if lms_arr is not None else None

        indices = np.where(conf_map >= confidence_threshold)[0]
        for idx in indices:
            score = float(conf_map[idx])
            reg = bbox_reg[idx]
            dx, dy, dw, dh = float(reg[0]), float(reg[1]), float(reg[2]), float(reg[3])

            grid_x = idx % grid_w
            grid_y = idx // grid_w

            cx = (grid_x + dx) * stride
            cy = (grid_y + dy) * stride
            w = np.exp(np.clip(dw, -5.0, 5.0)) * stride
            h = np.exp(np.clip(dh, -5.0, 5.0)) * stride

            if w < 5.0 or h < 5.0:
                continue

            x1 = max(0.0, min(float(orig_w), (cx - w / 2.0) * scale_x))
            y1 = max(0.0, min(float(orig_h), (cy - h / 2.0) * scale_y))
            x2 = max(0.0, min(float(orig_w), (cx + w / 2.0) * scale_x))
            y2 = max(0.0, min(float(orig_h), (cy + h / 2.0) * scale_y))

            if (x2 - x1) < 40.0 or (y2 - y1) < 40.0:
                continue

            landmarks = np.zeros((5, 2), dtype=np.float32)
            if lms_reg is not None and idx < lms_reg.shape[0]:
                lm_raw = lms_reg[idx].reshape(5, 2)
                landmarks[:, 0] = (grid_x * stride + lm_raw[:, 0] * stride) * scale_x
                landmarks[:, 1] = (grid_y * stride + lm_raw[:, 1] * stride) * scale_y

            faces.append(
                YuNetDetectedFace(
                    bbox=(x1, y1, x2, y2),
                    score=score,
                    landmarks=landmarks,
                )
            )

    return _nms(faces, nms_threshold)


class YuNetFaceDetector:
    """YuNet face detector adapter."""

    def __init__(
        self,
        hef_path: str | Path,
        input_size: Tuple[int, int] = (320, 320),
        confidence_threshold: float = 0.85,
        nms_threshold: float = 0.3,
        runner: Optional[BaseHailoRunner] = None,
    ) -> None:
        self.hef_path = Path(hef_path)
        self.runner = runner or HailoModelRunner(self.hef_path, allow_mock=True)
        self.confidence_threshold = float(confidence_threshold)
        self.nms_threshold = float(nms_threshold)
        self.input_size = _parse_input_size(getattr(self.runner, "input_shape", None), default=input_size)

    def preprocess(self, image: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """Resize image to input_size. Returns (tensor, scale, (pad_w, pad_h))."""
        h, w = image.shape[:2]
        target_w, target_h = self.input_size

        scale_w = target_w / w
        scale_h = target_h / h

        if cv2 is not None:
            resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        else:
            resized = image

        tensor = resized.astype(np.float32)
        if len(getattr(self.runner, "input_shape", ())) == 4 and self.runner.input_shape[1] == 3:
            tensor = tensor.transpose(2, 0, 1)
        tensor = np.expand_dims(tensor, axis=0)

        return tensor, scale_w, (0, 0)

    def postprocess(
        self,
        outputs: Dict[str, np.ndarray],
        orig_shape: Tuple[int, int],
        input_size: Tuple[int, int],
    ) -> List[YuNetDetectedFace]:
        """Postprocess YuNet model raw outputs."""
        if not outputs:
            return []

        # Strip model name prefix (e.g. "yunet/activation6" -> "activation6")
        stripped = {}
        for k, v in outputs.items():
            base_key = k.rsplit("/", 1)[-1] if "/" in k else k
            stripped[base_key] = v
        outputs = stripped

        has_raw_heads = any(k in outputs for k in ("activation6", "activation4", "activation2", "format_conversion10"))
        if has_raw_heads:
            raw_faces = _decode_yunet_raw_heads(
                outputs=outputs,
                input_size=input_size,
                confidence_threshold=self.confidence_threshold,
                orig_shape=orig_shape,
                nms_threshold=self.nms_threshold,
            )
            logger.debug("YuNet raw heads decoded %d faces after NMS", len(raw_faces))
            return raw_faces

        orig_h, orig_w = orig_shape
        target_w, target_h = input_size
        scale_x = orig_w / target_w
        scale_y = orig_h / target_h

        all_rows: List[np.ndarray] = []
        for name, raw_output in outputs.items():
            if raw_output is None or raw_output.size == 0:
                continue
            arr = np.squeeze(raw_output)
            if arr.size == 0 or np.all(arr == 0):
                continue
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            elif arr.ndim > 2:
                arr = arr.reshape(-1, arr.shape[-1])
            all_rows.append(arr)

        if not all_rows:
            return []

        faces: List[YuNetDetectedFace] = []
        max_score_seen = 0.0

        for output in all_rows:
            for row in output:
                if len(row) >= 15:
                    # YuNet format: [x, y, w, h, lm1_x, lm1_y, ... lm5_x, lm5_y, score]
                    x, y, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                    landmarks_raw = row[4:14].reshape(5, 2)
                    score = float(row[14])
                    max_score_seen = max(max_score_seen, score)

                    if score < self.confidence_threshold:
                        continue

                    if max(abs(x), abs(y), abs(w), abs(h)) <= 1.0:
                        x *= target_w
                        y *= target_h
                        w *= target_w
                        h *= target_h
                        landmarks_raw[:, 0] *= target_w
                        landmarks_raw[:, 1] *= target_h

                    x1 = max(0.0, min(float(orig_w), float(x * scale_x)))
                    y1 = max(0.0, min(float(orig_h), float(y * scale_y)))
                    x2 = max(0.0, min(float(orig_w), float((x + w) * scale_x)))
                    y2 = max(0.0, min(float(orig_h), float((y + h) * scale_y)))

                    landmarks = np.zeros((5, 2), dtype=np.float32)
                    landmarks[:, 0] = landmarks_raw[:, 0] * scale_x
                    landmarks[:, 1] = landmarks_raw[:, 1] * scale_y

                    faces.append(
                        YuNetDetectedFace(
                            bbox=(x1, y1, x2, y2),
                            score=score,
                            landmarks=landmarks,
                        )
                    )
                elif len(row) >= 5:
                    x1_raw, y1_raw, x2_raw, y2_raw = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                    score = float(row[4])
                    max_score_seen = max(max_score_seen, score)

                    if score < self.confidence_threshold:
                        continue

                    if max(abs(x1_raw), abs(y1_raw), abs(x2_raw), abs(y2_raw)) <= 1.0:
                        x1_raw *= target_w
                        y1_raw *= target_h
                        x2_raw *= target_w
                        y2_raw *= target_h

                    x1 = max(0.0, min(float(orig_w), float(x1_raw * scale_x)))
                    y1 = max(0.0, min(float(orig_h), float(y1_raw * scale_y)))
                    x2 = max(0.0, min(float(orig_w), float(x2_raw * scale_x)))
                    y2 = max(0.0, min(float(orig_h), float(y2_raw * scale_y)))

                    faces.append(
                        YuNetDetectedFace(
                            bbox=(x1, y1, x2, y2),
                            score=score,
                            landmarks=None,
                        )
                    )

        logger.debug("YuNet postprocess max_score=%.3f faces=%d", max_score_seen, len(faces))
        return faces

    def detect(self, image: np.ndarray) -> List[YuNetDetectedFace]:
        """Detect faces in image or crop."""
        if image is None or image.size == 0:
            return []
        tensor, _, _ = self.preprocess(image)
        outputs = self.runner.infer(tensor)
        return self.postprocess(outputs, orig_shape=image.shape[:2], input_size=self.input_size)
