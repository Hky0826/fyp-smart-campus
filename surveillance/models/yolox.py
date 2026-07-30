"""YOLOX-M person detector adapter for Hailo HEF models."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from .loader import HailoModelRunner, BaseHailoRunner

logger = logging.getLogger(__name__)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0)))


def _decode_yolox_raw_heads(
    outputs: Dict[str, np.ndarray],
    input_size: Tuple[int, int],
    confidence_threshold: float,
    pad: Tuple[int, int],
    scale: float,
    orig_shape: Tuple[int, int],
    ignore_class_id: bool = True,
    person_class_id: int = 0,
) -> List[np.ndarray]:
    """Decodes 3-scale raw YOLOX feature maps from Hailo-8 NPU (strides 8, 16, 32)."""
    # Group output heads by spatial resolution (80x80 -> s8, 40x40 -> s16, 20x20 -> s32)
    stride_map = {80: 8, 40: 16, 20: 32}
    pad_w, pad_h = pad
    orig_h, orig_w = orig_shape
    boxes: List[np.ndarray] = []

    # Map output tensors by spatial shape
    obj_maps: Dict[int, np.ndarray] = {}
    bbox_maps: Dict[int, np.ndarray] = {}
    cls_maps: Dict[int, np.ndarray] = {}

    for name, raw_arr in outputs.items():
        if raw_arr is None or raw_arr.size == 0:
            continue
        arr = np.squeeze(raw_arr)
        
        # obj_map (H, W, 1) squeezes to (H, W). Restore the channel dimension.
        if arr.ndim == 2:
            arr = np.expand_dims(arr, axis=-1)
            
        if arr.ndim != 3:
            continue
        h_grid, w_grid, channels = arr.shape
        if h_grid not in stride_map:
            continue

        if channels == 1:
            obj_maps[h_grid] = arr[:, :, 0]
        elif channels == 4:
            bbox_maps[h_grid] = arr
        elif channels in (80, 85, 1):
            cls_maps[h_grid] = arr

    for h_grid, stride in stride_map.items():
        if h_grid not in obj_maps or h_grid not in bbox_maps:
            continue

        obj_raw = obj_maps[h_grid]
        obj_prob = _sigmoid(obj_raw) if (obj_raw.max() > 1.0 or obj_raw.min() < 0.0) else obj_raw
        bbox_reg = bbox_maps[h_grid]
        cls_reg = cls_maps.get(h_grid)

        ys, xs = np.where(obj_prob >= confidence_threshold)
        for y, x in zip(ys, xs):
            obj_score = float(obj_prob[y, x])
            cls_score = 1.0
            class_id = person_class_id

            if cls_reg is not None and cls_reg.ndim == 3:
                cls_row = cls_reg[y, x]
                if cls_row.size > 1:
                    class_id = int(np.argmax(cls_row))
                    cls_score_raw = float(cls_row[class_id])
                    cls_score = float(_sigmoid(np.array(cls_score_raw))[0]) if (cls_score_raw > 1.0 or cls_score_raw < 0.0) else cls_score_raw
                elif cls_row.size == 1:
                    cls_score = float(cls_row[0])

            if not ignore_class_id and class_id != person_class_id:
                continue

            score = obj_score * cls_score
            if score < confidence_threshold:
                continue

            reg = bbox_reg[y, x]
            dx, dy, dw, dh = float(reg[0]), float(reg[1]), float(reg[2]), float(reg[3])

            cx = (x + dx) * stride
            cy = (y + dy) * stride
            w = np.exp(dw) * stride
            h = np.exp(dh) * stride

            x1 = (cx - w / 2.0 - pad_w) / scale
            y1 = (cy - h / 2.0 - pad_h) / scale
            x2 = (cx + w / 2.0 - pad_w) / scale
            y2 = (cy + h / 2.0 - pad_h) / scale

            x1 = max(0.0, min(float(orig_w), x1))
            y1 = max(0.0, min(float(orig_h), y1))
            x2 = max(0.0, min(float(orig_w), x2))
            y2 = max(0.0, min(float(orig_h), y2))

            if x2 > x1 and y2 > y1:
                boxes.append(np.array([x1, y1, x2, y2, score], dtype=np.float32))

    return boxes


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


class YOLOXPersonDetector:
    """YOLOX-M detector tuned for person class detection."""

    def __init__(
        self,
        hef_path: str | Path,
        input_size: Tuple[int, int] = (640, 640),
        confidence_threshold: float = 0.5,
        person_class_id: int = 0,
        ignore_class_id: bool = True,
        runner: Optional[BaseHailoRunner] = None,
    ) -> None:
        self.hef_path = Path(hef_path)
        self.runner = runner or HailoModelRunner(self.hef_path, allow_mock=True)
        self.confidence_threshold = float(confidence_threshold)
        self.person_class_id = int(person_class_id)
        self.ignore_class_id = bool(ignore_class_id)
        self.input_size = _parse_input_size(getattr(self.runner, "input_shape", None), default=input_size)

    def preprocess(self, frame: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """Resize and pad image frame to input_size. Returns (tensor, scale, (pad_w, pad_h))."""
        h, w = frame.shape[:2]
        target_w, target_h = self.input_size

        r = min(target_w / w, target_h / h)
        new_unpad_w, new_unpad_h = int(round(w * r)), int(round(h * r))
        pad_w, pad_h = target_w - new_unpad_w, target_h - new_unpad_h

        dw, dh = pad_w / 2, pad_h / 2
        if cv2 is not None and (w, h) != (new_unpad_w, new_unpad_h):
            resized = cv2.resize(frame, (new_unpad_w, new_unpad_h), interpolation=cv2.INTER_LINEAR)
        else:
            resized = frame

        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))

        if cv2 is not None:
            padded = cv2.copyMakeBorder(
                resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
            )
        else:
            padded = np.full((target_h, target_w, 3), 114, dtype=frame.dtype)
            padded[top : top + new_unpad_h, left : left + new_unpad_w] = resized

        # Format as NCHW or NHWC tensor depending on runner input shape
        tensor = padded.astype(np.float32)
        if len(getattr(self.runner, "input_shape", ())) == 4 and self.runner.input_shape[1] == 3:
            tensor = tensor.transpose(2, 0, 1)  # NHWC -> NCHW
        tensor = np.expand_dims(tensor, axis=0)

        return tensor, r, (left, top)

    def postprocess(
        self,
        outputs: Dict[str, np.ndarray],
        scale: float,
        pad: Tuple[int, int],
        orig_shape: Tuple[int, int],
    ) -> List[np.ndarray]:
        """Decode YOLOX detections into [x1, y1, x2, y2, score] arrays."""
    def postprocess(
        self,
        outputs: Dict[str, np.ndarray],
        scale: float,
        pad: Tuple[int, int],
        orig_shape: Tuple[int, int],
    ) -> List[np.ndarray]:
        """Decode YOLOX detections into [x1, y1, x2, y2, score] arrays."""
        if not outputs:
            return []

        has_raw_heads = any("conv" in k for k in outputs)
        if has_raw_heads:
            raw_boxes = _decode_yolox_raw_heads(
                outputs=outputs,
                input_size=self.input_size,
                confidence_threshold=self.confidence_threshold,
                pad=pad,
                scale=scale,
                orig_shape=orig_shape,
                ignore_class_id=self.ignore_class_id,
                person_class_id=self.person_class_id,
            )
            logger.debug("YOLOX raw heads decoded %d candidate boxes", len(raw_boxes))
            return self._nms(raw_boxes, iou_threshold=0.45) if raw_boxes else []

        # Collect and flatten rows from all output heads
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

        boxes: List[np.ndarray] = []
        pad_w, pad_h = pad
        orig_h, orig_w = orig_shape
        max_score_seen = 0.0

        for output in all_rows:
            if output.shape[-1] < 5:
                continue

            for row in output:
                if len(row) >= 85:
                    # YOLOX standard raw layout: [cx, cy, w, h, obj_conf, class_scores...]
                    obj_conf = float(row[4])
                    class_scores = row[5:]
                    class_id = int(np.argmax(class_scores))
                    score = float(obj_conf * class_scores[class_id])
                    max_score_seen = max(max_score_seen, score)

                    if score < self.confidence_threshold:
                        continue

                    if not self.ignore_class_id:
                        valid_class = (class_id == self.person_class_id) or (self.person_class_id == 0 and class_id in (0, 1))
                        if not valid_class:
                            continue

                    cx, cy, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                    if max(abs(cx), abs(cy), abs(w), abs(h)) <= 1.0:
                        target_w, target_h = self.input_size
                        cx *= target_w
                        cy *= target_h
                        w *= target_w
                        h *= target_h

                    x1 = (cx - w / 2 - pad_w) / scale
                    y1 = (cy - h / 2 - pad_h) / scale
                    x2 = (cx + w / 2 - pad_w) / scale
                    y2 = (cy + h / 2 - pad_h) / scale
                else:
                    # Pre-decoded / Hailo NMS format: [x1, y1, x2, y2, score/class, class/score]
                    c1, c2, c3, c4 = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                    v4 = float(row[4])
                    v5 = float(np.asarray(row[5]).flat[0]) if len(row) > 5 else float(self.person_class_id)

                    # Auto-detect if index 4 is class_id and index 5 is score (or vice versa)
                    if v4.is_integer() and 0.0 <= v4 <= 80.0 and 0.0 <= v5 <= 1.0 and not (v5.is_integer() and v5 > 0):
                        class_id = int(v4)
                        score = v5
                    else:
                        score = v4
                        class_id = int(v5)

                    max_score_seen = max(max_score_seen, score)

                    if score < self.confidence_threshold:
                        continue

                    if not self.ignore_class_id:
                        valid_class = (class_id == self.person_class_id) or (self.person_class_id == 0 and class_id in (0, 1))
                        if not valid_class:
                            continue

                    # Auto-detect if coordinates are in normalized [0, 1] vs pixel space, and [ymin, xmin, ymax, xmax]
                    target_w, target_h = self.input_size
                    if max(abs(c1), abs(c2), abs(c3), abs(c4)) <= 1.0:
                        # Hailo NMS standard format: [ymin, xmin, ymax, xmax]
                        if c1 <= c3 and c2 <= c4 and (c3 - c1) <= 1.0 and (c4 - c2) <= 1.0:
                            y1_raw = c1 * target_h
                            x1_raw = c2 * target_w
                            y2_raw = c3 * target_h
                            x2_raw = c4 * target_w
                        else:
                            x1_raw = min(c1, c3) * target_w
                            y1_raw = min(c2, c4) * target_h
                            x2_raw = max(c1, c3) * target_w
                            y2_raw = max(c2, c4) * target_h
                    else:
                        x1_raw = min(c1, c3)
                        y1_raw = min(c2, c4)
                        x2_raw = max(c1, c3)
                        y2_raw = max(c2, c4)

                    x1 = (x1_raw - pad_w) / scale
                    y1 = (y1_raw - pad_h) / scale
                    x2 = (x2_raw - pad_w) / scale
                    y2 = (y2_raw - pad_h) / scale

                # Ensure x1 < x2 and y1 < y2
                if x1 > x2:
                    x1, x2 = x2, x1
                if y1 > y2:
                    y1, y2 = y2, y1

                # Clip to image boundary
                x1 = max(0.0, min(float(orig_w), float(x1)))
                y1 = max(0.0, min(float(orig_h), float(y1)))
                x2 = max(0.0, min(float(orig_w), float(x2)))
                y2 = max(0.0, min(float(orig_h), float(y2)))

                if x2 > x1 and y2 > y1:
                    boxes.append(np.array([x1, y1, x2, y2, score], dtype=np.float32))

        logger.debug("YOLOX postprocess max_score=%.3f boxes=%d", max_score_seen, len(boxes))
        return self._nms(boxes, iou_threshold=0.45)

    @staticmethod
    def _nms(boxes: List[np.ndarray], iou_threshold: float = 0.45) -> List[np.ndarray]:
        if not boxes:
            return []
        arr = np.array(boxes, dtype=np.float32)
        x1, y1, x2, y2, scores = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
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
            ovr = inter / (areas[i] + areas[order[1:]] - inter)

            inds = np.where(ovr <= iou_threshold)[0]
            order = order[inds + 1]

        return [arr[k] for k in keep]

    def detect(self, frame: np.ndarray) -> List[np.ndarray]:
        """Runs person detection on frame, returning list of [x1, y1, x2, y2, score] arrays."""
        if frame is None or frame.size == 0:
            return []
        tensor, scale, pad = self.preprocess(frame)
        outputs = self.runner.infer(tensor)
        return self.postprocess(outputs, scale, pad, orig_shape=frame.shape[:2])
