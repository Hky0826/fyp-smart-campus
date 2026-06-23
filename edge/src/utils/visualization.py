"""OpenCV visualization helpers for direct camera pipelines."""

from __future__ import annotations

from typing import Iterable, Sequence

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


GREEN = (0, 255, 0)
RED = (0, 0, 255)
YELLOW = (0, 255, 255)


def show_pipeline_result(window_name: str, frame, result: dict, mirror: bool = True) -> bool:
    """Render a pipeline result and return False when the user presses q."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for display output")

    display = draw_pipeline_result(frame, result, mirror=mirror)
    cv2.imshow(window_name, display)
    key = cv2.waitKey(1) & 0xFF
    return key != ord("q")


def close_display() -> None:
    if cv2 is not None:
        cv2.destroyAllWindows()


def draw_pipeline_result(frame, result: dict, mirror: bool = True):
    if cv2 is None:
        raise RuntimeError("OpenCV is required for display output")

    display = cv2.flip(frame.copy(), 1) if mirror else frame.copy()
    mode = result.get("mode")
    if mode == "surveillance":
        _draw_surveillance(display, result, mirror=mirror)
    else:
        _draw_access_control(display, result, mirror=mirror)
    return display


def _draw_access_control(display, result: dict, mirror: bool) -> None:
    granted = bool(result.get("access_granted"))
    reason = str(result.get("reason") or "")
    identity = str(result.get("identity") or "unknown")
    similarity = float(result.get("similarity") or 0.0)
    face_count = int(result.get("face_count") or 0)

    if granted:
        color = GREEN
        status = f"AUTHORIZED {identity} {similarity:.3f}"
    elif face_count == 0:
        color = YELLOW
        status = reason or "Waiting for face..."
    elif "inconclusive" in reason.lower():
        color = YELLOW
        status = reason
    else:
        color = RED
        status = f"DENIED {identity}" if identity != "unknown" else "DENIED"

    _put_text(display, status, (10, 30), color, scale=0.9, thickness=2)
    if reason and not granted:
        _put_text(display, reason[:70], (10, 60), color)

    label = identity if identity != "unknown" else "FACE"
    for bbox in _access_bboxes(result):
        _draw_box(display, bbox, color, mirror=mirror, label=label)


def _draw_surveillance(display, result: dict, mirror: bool) -> None:
    face_count = int(result.get("face_count") or 0)
    _put_text(display, f"Surveillance: {face_count} face(s)", (10, 30), YELLOW, scale=0.9, thickness=2)
    for item in result.get("results") or []:
        bbox = item.get("bbox")
        if not bbox:
            continue
        status = item.get("status") or "unknown"
        identity = item.get("identity") or "unknown"
        similarity = float(item.get("similarity") or 0.0)
        color = GREEN if status == "recognized" else RED
        label = f"{identity} {similarity:.2f}"
        _draw_box(display, bbox, color, mirror=mirror, label=label)


def _access_bboxes(result: dict) -> Iterable[Sequence[int]]:
    bboxes = result.get("bboxes")
    if bboxes:
        return bboxes
    bbox = result.get("bbox")
    return [bbox] if bbox else []


def _draw_box(display, bbox: Sequence[int], color, mirror: bool, label: str | None = None) -> None:
    x1, y1, x2, y2 = _normalise_bbox(display, bbox, mirror=mirror)
    cv2.rectangle(display, (x1, y1), (x2, y2), color, 3)
    if label:
        _put_text(display, label, (x1, max(20, y1 - 8)), color, scale=0.6, thickness=2)


def _normalise_bbox(display, bbox: Sequence[int], mirror: bool) -> tuple[int, int, int, int]:
    height, width = display.shape[:2]
    x1, y1, x2, y2 = [int(round(float(value))) for value in bbox[:4]]
    if mirror:
        x1, x2 = width - x2, width - x1
    x1 = max(0, min(width - 1, x1))
    x2 = max(0, min(width - 1, x2))
    y1 = max(0, min(height - 1, y1))
    y2 = max(0, min(height - 1, y2))
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def _put_text(display, text: str, origin: tuple[int, int], color, scale: float = 0.7, thickness: int = 2) -> None:
    cv2.putText(display, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)
