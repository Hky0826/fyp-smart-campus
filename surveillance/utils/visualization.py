"""Visualization tools for rendering detection, track IDs, and recognized identities."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

logger = logging.getLogger(__name__)


def draw_pipeline_result(
    frame: np.ndarray,
    results: List[Dict[str, Any]],
    mirror: bool = False,
) -> np.ndarray:
    """Draw bounding boxes, track IDs, and recognized user names on frame."""
    if cv2 is None or frame is None or frame.size == 0:
        return frame

    canvas = frame.copy()
    if mirror:
        canvas = cv2.flip(canvas, 1)

    h, w = canvas.shape[:2]

    for item in results:
        bbox = item.get("bbox", [0, 0, 0, 0])
        x1, y1, x2, y2 = [int(round(v)) for v in bbox]
        if mirror:
            # Adjust coordinates for mirrored frame
            x1, x2 = w - x2, w - x1

        track_id = item.get("track_id", 0)
        identity = item.get("identity", "unknown")
        user_id = item.get("user_id")
        status = item.get("status", "unknown")
        similarity = item.get("similarity", 0.0)

        is_recognized = status == "recognized" and identity != "unknown"

        # Color: Green for recognized person, Cyan for tracking person
        color = (0, 255, 0) if is_recognized else (255, 191, 0)

        # Draw Person Bounding Box
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)

        # Draw Face Bounding Box if available
        face_bbox = item.get("face_bbox")
        if face_bbox and len(face_bbox) == 4 and any(face_bbox):
            fx1, fy1, fx2, fy2 = [int(round(v)) for v in face_bbox]
            if mirror:
                fx1, fx2 = w - fx2, w - fx1
            cv2.rectangle(canvas, (fx1, fy1), (fx2, fy2), (255, 0, 255), 2)

        # Label text
        if is_recognized:
            label = f"ID:{track_id} | {identity} ({user_id}) [{similarity:.2f}]"
        else:
            label = f"ID:{track_id} | Searching face..."

        # Draw text background
        (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        text_y1 = max(y1 - text_h - 6, 0)
        cv2.rectangle(canvas, (x1, text_y1), (x1 + text_w + 4, text_y1 + text_h + 6), color, -1)
        cv2.putText(
            canvas,
            label,
            (x1 + 2, text_y1 + text_h + 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    return canvas


def show_pipeline_result(
    window_name: str,
    frame: np.ndarray,
    result: Dict[str, Any],
    mirror: bool = True,
) -> bool:
    """Show pipeline output window. Returns False if user pressed ESC or 'q'."""
    if cv2 is None:
        return True

    rendered = draw_pipeline_result(frame, result.get("results", []), mirror=mirror)
    cv2.imshow(window_name, rendered)
    key = cv2.waitKey(1) & 0xFF
    return key not in (27, ord("q"))


def close_display() -> None:
    if cv2 is not None:
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
