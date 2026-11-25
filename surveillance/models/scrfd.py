"""SCRFD face detector adapter for official Hailo Model Zoo HEF models."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from .loader import BaseHailoRunner, HailoModelRunner
from .yunet import YuNetDetectedFace, _nms, _parse_input_size, _sigmoid

logger = logging.getLogger(__name__)


def _decode_scrfd_outputs(
    outputs: Dict[str, np.ndarray],
    input_size: Tuple[int, int],
    confidence_threshold: float,
    pad: Tuple[int, int],
    scale: float,
    orig_shape: Tuple[int, int],
    nms_threshold: float = 0.4,
) -> List[YuNetDetectedFace]:
    """Decodes 3-stride Hailo Model Zoo SCRFD outputs (strides 8, 16, 32; 2 anchors/cell)."""
    target_w, target_h = input_size
    pad_w, pad_h = pad
    orig_h, orig_w = orig_shape

    # Group heads by spatial grid height -> stride
    stride_map = {
        max(1, target_h // 8): 8,
        max(1, target_h // 16): 16,
        max(1, target_h // 32): 32,
    }

    score_maps: Dict[int, np.ndarray] = {}
    bbox_maps: Dict[int, np.ndarray] = {}
    kps_maps: Dict[int, np.ndarray] = {}

    for raw_arr in outputs.values():
        if raw_arr is None or raw_arr.size == 0:
            continue
        arr = np.squeeze(raw_arr)
        if arr.ndim != 3:
            continue
        h_grid, w_grid, channels = arr.shape
        if h_grid not in stride_map:
            continue

        if channels == 2:
            score_maps[h_grid] = arr
        elif channels == 8:
            bbox_maps[h_grid] = arr
        elif channels == 20:
            kps_maps[h_grid] = arr

    faces: List[YuNetDetectedFace] = []

    for h_grid, stride in stride_map.items():
        if h_grid not in score_maps or h_grid not in bbox_maps:
            continue

        scores_raw = score_maps[h_grid]
        bboxes_raw = bbox_maps[h_grid]
        kps_raw = kps_maps.get(h_grid)

        w_grid = scores_raw.shape[1]
        num_anchors = scores_raw.shape[2]  # 2 for scrfd_10g / scrfd_2.5g / scrfd_500m

        scores = scores_raw.reshape(-1)
        if scores.size == 0:
            continue
        if scores.max() > 1.0 or scores.min() < 0.0:
            scores = _sigmoid(scores)

        keep_idx = np.where(scores >= confidence_threshold)[0]
        if keep_idx.size == 0:
            continue

        bboxes = bboxes_raw.reshape(-1, 4)
        kps = kps_raw.reshape(-1, 10) if kps_raw is not None else None

        # Anchor centers match Hailo Model Zoo SCRFDPostProc: (x * stride, y * stride)
        # Flattened order of (H, W, num_anchors): cell_idx = idx // num_anchors
        cell_idx = keep_idx // num_anchors
        grid_y = (cell_idx // w_grid).astype(np.float32)
        grid_x = (cell_idx % w_grid).astype(np.float32)
        cx = grid_x * stride
        cy = grid_y * stride

        sel_scores = scores[keep_idx]
        sel_bboxes = bboxes[keep_idx] * stride

        x1s = (cx - sel_bboxes[:, 0] - pad_w) / scale
        y1s = (cy - sel_bboxes[:, 1] - pad_h) / scale
        x2s = (cx + sel_bboxes[:, 2] - pad_w) / scale
        y2s = (cy + sel_bboxes[:, 3] - pad_h) / scale

        x1s = np.clip(x1s, 0.0, float(orig_w))
        y1s = np.clip(y1s, 0.0, float(orig_h))
        x2s = np.clip(x2s, 0.0, float(orig_w))
        y2s = np.clip(y2s, 0.0, float(orig_h))

        sel_kps = kps[keep_idx] * stride if kps is not None else None

        for i in range(keep_idx.size):
            x1, y1, x2, y2 = float(x1s[i]), float(y1s[i]), float(x2s[i]), float(y2s[i])
            if (x2 - x1) < 8.0 or (y2 - y1) < 8.0:
                continue

            landmarks: Optional[np.ndarray] = None
            if sel_kps is not None:
                lm = sel_kps[i].reshape(5, 2)
                landmarks = np.zeros((5, 2), dtype=np.float32)
                landmarks[:, 0] = (cx[i] + lm[:, 0] - pad_w) / scale
                landmarks[:, 1] = (cy[i] + lm[:, 1] - pad_h) / scale

            faces.append(
                YuNetDetectedFace(
                    bbox=(x1, y1, x2, y2),
                    score=float(sel_scores[i]),
                    landmarks=landmarks,
                )
            )

    return _nms(faces, iou_threshold=nms_threshold)


class SCRFDFaceDetector:
    """Official Hailo Model Zoo SCRFD face detector (scrfd_10g / scrfd_2.5g / scrfd_500m)."""

    def __init__(
        self,
        hef_path: str | Path,
        input_size: Tuple[int, int] = (640, 640),
        confidence_threshold: float = 0.60,
        nms_threshold: float = 0.40,
        runner: Optional[BaseHailoRunner] = None,
    ) -> None:
        self.hef_path = Path(hef_path)
        self.runner = runner or HailoModelRunner(self.hef_path, allow_mock=True)
        self.confidence_threshold = float(confidence_threshold)
        self.nms_threshold = float(nms_threshold)
        self.input_size = _parse_input_size(getattr(self.runner, "input_shape", None), default=input_size)

    def preprocess(self, image: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """Letterbox-resize BGR image to RGB float32 tensor. Returns (tensor, scale, (pad_w, pad_h))."""
        h, w = image.shape[:2]
        target_w, target_h = self.input_size

        r = min(target_w / max(w, 1), target_h / max(h, 1))
        new_w, new_h = max(1, int(round(w * r))), max(1, int(round(h * r)))
        pad_w, pad_h = target_w - new_w, target_h - new_h
        dw, dh = pad_w / 2.0, pad_h / 2.0

        if cv2 is not None and (w, h) != (new_w, new_h):
            resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        else:
            resized = image

        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))

        if cv2 is not None:
            padded = cv2.copyMakeBorder(
                resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(0, 0, 0)
            )
            rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        else:
            padded = np.zeros((target_h, target_w, 3), dtype=image.dtype)
            padded[top : top + new_h, left : left + new_w] = resized
            rgb = padded

        tensor = rgb.astype(np.float32)
        if len(getattr(self.runner, "input_shape", ())) == 4 and self.runner.input_shape[1] == 3:
            tensor = tensor.transpose(2, 0, 1)
        tensor = np.expand_dims(tensor, axis=0)
        return tensor, r, (left, top)

    def postprocess(
        self,
        outputs: Dict[str, np.ndarray],
        scale: float,
        pad: Tuple[int, int],
        orig_shape: Tuple[int, int],
    ) -> List[YuNetDetectedFace]:
        if not outputs:
            return []
        return _decode_scrfd_outputs(
            outputs=outputs,
            input_size=self.input_size,
            confidence_threshold=self.confidence_threshold,
            pad=pad,
            scale=scale,
            orig_shape=orig_shape,
            nms_threshold=self.nms_threshold,
        )

    def detect(self, image: np.ndarray) -> List[YuNetDetectedFace]:
        """Detect faces in BGR image or person crop."""
        if image is None or image.size == 0:
            return []
        tensor, scale, pad = self.preprocess(image)
        outputs = self.runner.infer(tensor)
        return self.postprocess(outputs, scale=scale, pad=pad, orig_shape=image.shape[:2])
