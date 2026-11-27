"""In-process Python bridge to the Floorplan AI Computer Vision services.

Calls WallDetector and FloorplanAnalyzerService directly in Python via run_in_threadpool
(eliminating the Node.js -> HTTP -> FastAPI hop) with bounded LRU caching.
"""

from __future__ import annotations

from collections import OrderedDict
import logging
from typing import Any

from fastapi.concurrency import run_in_threadpool

from app.services.mapping.route_visualizer import resolve_floorplan_image_path

logger = logging.getLogger("smart-campus.mapping.ai_bridge")

MAX_AI_CACHE_ENTRIES = 50
_wall_cache: OrderedDict[str, dict] = OrderedDict()
_analysis_cache: OrderedDict[str, dict] = OrderedDict()

_wall_detector = None
_floorplan_analyzer = None


def _ensure_ai_services_path() -> None:
    import sys
    from pathlib import Path

    ai_services_dir = str(Path(__file__).resolve().parents[6] / "mapping_and_notification" / "ai-services")
    if ai_services_dir not in sys.path:
        sys.path.insert(0, ai_services_dir)


def _get_wall_detector():
    global _wall_detector
    if _wall_detector is None:
        _ensure_ai_services_path()
        from src.modules.wall_detection.detector import WallDetector
        _wall_detector = WallDetector()
    return _wall_detector


def _get_floorplan_analyzer():
    global _floorplan_analyzer
    if _floorplan_analyzer is None:
        _ensure_ai_services_path()
        from src.services.floorplan_analyzer import FloorplanAnalyzerService
        _floorplan_analyzer = FloorplanAnalyzerService()
    return _floorplan_analyzer


def _set_bounded_cache(cache: OrderedDict, key: str, value: dict) -> None:
    if key in cache:
        cache.move_to_end(key)
    else:
        if len(cache) >= MAX_AI_CACHE_ENTRIES:
            cache.popitem(last=False)
    cache[key] = value


def invalidate_floorplan_caches(floorplan_id: int | str) -> None:
    prefix = f"{floorplan_id}_"
    for cache in (_wall_cache, _analysis_cache):
        for k in [key for key in cache.keys() if key.startswith(prefix)]:
            cache.pop(k, None)


def is_ai_available() -> bool:
    try:
        _get_wall_detector()
        return True
    except Exception:
        return False


async def detect_walls_for_floorplan(
    *,
    floorplan_id: int | str,
    image_path: str,
    sensitivity: int = 120,
    canvas_width: int = 800,
    canvas_height: int = 600,
    grid_scale: int = 8,
) -> dict[str, Any]:
    cache_key = f"{floorplan_id}_{image_path}_{sensitivity}_{canvas_width}_{canvas_height}_{grid_scale}"
    if cache_key in _wall_cache:
        _wall_cache.move_to_end(cache_key)
        return _wall_cache[cache_key]

    disk_path = resolve_floorplan_image_path(image_path)
    if not disk_path:
        raise FileNotFoundError(f"Floorplan image not found on disk: {image_path}")

    image_bytes = disk_path.read_bytes()
    detector = _get_wall_detector()
    detection = await run_in_threadpool(
        detector.detect,
        image_bytes=image_bytes,
        sensitivity=sensitivity,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        grid_scale=grid_scale,
    )

    result = {
        "wallGrid": {
            "grid": detection.wall_grid.grid,
            "grid_width": detection.wall_grid.grid_width,
            "grid_height": detection.wall_grid.grid_height,
            "canvas_width": detection.wall_grid.canvas_width,
            "canvas_height": detection.wall_grid.canvas_height,
            "grid_scale": detection.wall_grid.grid_scale,
        },
        "timing": detection.processing_time_ms,
    }
    _set_bounded_cache(_wall_cache, cache_key, result)
    return result


async def analyze_floorplan_image(
    *,
    floorplan_id: int | str,
    image_path: str,
    sensitivity: int = 120,
    room_gap_close_px: int = 25,
    min_room_area_px: int = 2000,
    max_room_area_ratio: float = 0.30,
    min_ocr_confidence: float = 0.60,
    wall_clearance_px: int = 8,
    canvas_width: int = 800,
    canvas_height: int = 600,
    grid_scale: int = 8,
) -> dict[str, Any]:
    cache_key = "_".join(
        str(v)
        for v in (
            floorplan_id,
            image_path,
            sensitivity,
            room_gap_close_px,
            min_room_area_px,
            max_room_area_ratio,
            min_ocr_confidence,
            wall_clearance_px,
            canvas_width,
            canvas_height,
            grid_scale,
        )
    )
    if cache_key in _analysis_cache:
        _analysis_cache.move_to_end(cache_key)
        return _analysis_cache[cache_key]

    disk_path = resolve_floorplan_image_path(image_path)
    if not disk_path:
        raise FileNotFoundError(f"Floorplan image not found on disk: {image_path}")

    image_bytes = disk_path.read_bytes()
    analyzer = _get_floorplan_analyzer()
    analysis = await run_in_threadpool(
        analyzer.analyze,
        image_bytes=image_bytes,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        sensitivity=sensitivity,
        grid_scale=grid_scale,
        room_gap_close_px=room_gap_close_px,
        min_room_area_px=min_room_area_px,
        max_room_area_ratio=max_room_area_ratio,
        min_ocr_confidence=min_ocr_confidence,
        wall_clearance_px=wall_clearance_px,
    )
    result = analysis.model_dump() if hasattr(analysis, "model_dump") else dict(analysis)
    _set_bounded_cache(_analysis_cache, cache_key, result)
    return result
