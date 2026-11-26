"""Native Python Pillow Route Visualization Renderer.

Replaces Node.js node-canvas routeVisualizer.js:
- Draws white glow underlay + vibrant teal (#0d9488) walking route
- Draws directional travel arrows matching A* traversal direction
- Draws Start (#0d9488), Destination (#d97706), and Transition (#7c3aed) markers with outlined labels
- Skips intermediate transition-only floorplans
- Saves PNGs under settings.PRIVATE_STORAGE_ROOT / "floorplans" / "visualisations"
- Includes 24-hour retention cleanup
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.models import Floorplan

logger = logging.getLogger("smart-campus.mapping.visualizer")

CANVAS_WIDTH = 800.0
CANVAS_HEIGHT = 600.0

ROUTE_COLOR = (13, 148, 136, 255)       # #0d9488 teal-600
ROUTE_GLOW = (255, 255, 255, 220)       # white glow underlay
START_COLOR = (13, 148, 136, 255)       # #0d9488
END_COLOR = (217, 119, 6, 255)          # #d97706 amber-600
TRANSITION_COLOR = (124, 58, 237, 255)  # #7c3aed violet-600
TEXT_DARK = (51, 65, 85, 255)           # #334155


def get_floorplan_storage_dir() -> Path:
    d = settings.PRIVATE_STORAGE_ROOT / "floorplans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_visualisations_dir() -> Path:
    d = get_floorplan_storage_dir() / "visualisations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_floorplan_image_path(image_path: str) -> Path | None:
    """Resolve a stored floorplan image path safely across private storage and legacy upload dirs."""
    if not image_path:
        return None
    filename = Path(image_path).name
    if not filename or filename in (".", ".."):
        return None

    repo_root = Path(__file__).resolve().parents[5]
    candidates = [
        get_floorplan_storage_dir() / filename,
        repo_root / "mapping_and_notification" / "backend" / "uploads" / filename,
        repo_root / "floorplan" / filename,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, max(10, int(size)))
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_outlined_text(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    outline_width: int = 2,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = x - tw / 2
    ty = y - th
    draw.text(
        (tx, ty),
        text,
        font=font,
        fill=fill,
        stroke_width=max(1, outline_width),
        stroke_fill=(255, 255, 255, 255),
    )


def generate_route_visualisations(
    db: Session,
    route_result: dict,
    notification_id: str,
) -> list[dict]:
    route_path = route_result.get("path") or []
    edges_traversed = route_result.get("edges_traversed") or []
    if len(route_path) < 2:
        return []

    start_node = route_path[0]
    end_node = route_path[-1]
    route_node_map = {n["node_id"]: n for n in route_path}

    target_fp_set = {start_node["floorplan_id"], end_node["floorplan_id"]}
    for edge in edges_traversed:
        if not edge.get("is_cross_floor"):
            from_node = route_node_map.get(edge["from_node_id"])
            if from_node and from_node.get("floorplan_id"):
                target_fp_set.add(from_node["floorplan_id"])

    target_fp_ids: list[int] = []
    for n in route_path:
        fp_id = n["floorplan_id"]
        if fp_id in target_fp_set and fp_id not in target_fp_ids:
            target_fp_ids.append(fp_id)

    fp_rows = (
        db.query(Floorplan)
        .options(joinedload(Floorplan.building))
        .filter(Floorplan.floorplan_id.in_(target_fp_ids))
        .all()
    )
    fp_info_map = {fp.floorplan_id: fp for fp in fp_rows}

    vis_dir = get_visualisations_dir()
    results: list[dict] = []

    for fp_id in target_fp_ids:
        fp_info = fp_info_map.get(fp_id)
        if not fp_info:
            continue

        nodes_on_floor = [n for n in route_path if n["floorplan_id"] == fp_id]
        if not nodes_on_floor:
            continue

        edges_on_floor = []
        for edge_desc in edges_traversed:
            if edge_desc.get("is_cross_floor"):
                continue
            from_n = route_node_map.get(edge_desc["from_node_id"])
            if not from_n or from_n["floorplan_id"] != fp_id:
                continue
            edges_on_floor.append(edge_desc)

        img_disk_path = resolve_floorplan_image_path(fp_info.image_path)
        if img_disk_path:
            try:
                base_img = Image.open(img_disk_path).convert("RGBA")
            except Exception as exc:
                logger.warning("Could not open floorplan image %s: %s", img_disk_path, exc)
                base_img = Image.new("RGBA", (1200, 900), (241, 245, 249, 255))
        else:
            base_img = Image.new("RGBA", (1200, 900), (241, 245, 249, 255))

        w, h = base_img.size
        scale_x = w / CANVAS_WIDTH
        scale_y = h / CANVAS_HEIGHT
        avg_scale = (scale_x + scale_y) / 2.0

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Draw edges & directional arrows
        for edge in edges_on_floor:
            pts = None
            if edge.get("custom_path"):
                try:
                    parsed = json.loads(edge["custom_path"])
                    if isinstance(parsed, list) and len(parsed) >= 2:
                        pts = (
                            parsed
                            if int(edge["source_node_id"]) == int(edge["from_node_id"])
                            else list(reversed(parsed))
                        )
                except Exception:
                    pts = None
            if not pts:
                fn = route_node_map.get(edge["from_node_id"])
                tn = route_node_map.get(edge["to_node_id"])
                if not fn or not tn:
                    continue
                pts = [
                    {"x": fn["coord_x"], "y": fn["coord_y"]},
                    {"x": tn["coord_x"], "y": tn["coord_y"]},
                ]

            mapped = [(p["x"] * scale_x, p["y"] * scale_y) for p in pts]
            if len(mapped) < 2:
                continue

            glow_w = max(4, int(12 * avg_scale))
            line_w = max(2, int(5 * avg_scale))
            draw.line(mapped, fill=ROUTE_GLOW, width=glow_w, joint="curve")
            draw.line(mapped, fill=ROUTE_COLOR, width=line_w, joint="curve")

            # Directional arrows
            for idx in range(1, len(mapped)):
                x1, y1 = mapped[idx - 1]
                x2, y2 = mapped[idx]
                dx, dy = x2 - x1, y2 - y1
                dist = math.hypot(dx, dy)
                if dist > 30 * avg_scale:
                    mx, my = x1 + dx / 2.0, y1 + dy / 2.0
                    angle = math.atan2(dy, dx)
                    arrow_len = 13 * avg_scale
                    arrow_w = 7 * avg_scale
                    ca, sa = math.cos(angle), math.sin(angle)

                    def rot(lx: float, ly: float) -> tuple[float, float]:
                        return (mx + lx * ca - ly * sa, my + lx * sa + ly * ca)

                    tri = [
                        rot(arrow_len / 2, 0),
                        rot(-arrow_len / 2, arrow_w),
                        rot(-arrow_len / 2, -arrow_w),
                    ]
                    draw.polygon(tri, fill=ROUTE_COLOR, outline=(255, 255, 255, 255))

        # Draw Start, Destination, and Transition markers
        main_font = _load_font(int(14 * avg_scale))
        sub_font = _load_font(int(12 * avg_scale))

        for node in nodes_on_floor:
            is_start = node["node_id"] == start_node["node_id"]
            is_end = node["node_id"] == end_node["node_id"]
            is_transition = (
                not is_start
                and not is_end
                and (
                    node.get("node_type") in ("ELEVATOR", "STAIRWELL")
                    or bool(re.search(r"lift|elevator|stair", node.get("room_label") or "", re.I))
                )
            )
            if not (is_start or is_end or is_transition):
                continue

            nx = node["coord_x"] * scale_x
            ny = node["coord_y"] * scale_y

            if is_end:
                color = END_COLOR
                main_label = "DESTINATION"
            elif is_transition:
                color = TRANSITION_COLOR
                main_label = "LIFT / ELEVATOR" if node.get("node_type") == "ELEVATOR" else "STAIRWELL"
            else:
                color = START_COLOR
                main_label = "START"

            glow_r = 18 * avg_scale
            ring_r = 12 * avg_scale
            dot_r = 6 * avg_scale
            glow_color = (color[0], color[1], color[2], 64)

            draw.ellipse((nx - glow_r, ny - glow_r, nx + glow_r, ny + glow_r), fill=glow_color)
            draw.ellipse(
                (nx - ring_r, ny - ring_r, nx + ring_r, ny + ring_r),
                outline=color,
                width=max(2, int(3 * avg_scale)),
            )
            draw.ellipse((nx - dot_r, ny - dot_r, nx + dot_r, ny + dot_r), fill=color)

            node_name = node.get("room_label") or ("Transition" if is_transition else "Location")
            _draw_outlined_text(draw, nx, ny - 24 * avg_scale, main_label, main_font, color, int(2 * avg_scale))
            _draw_outlined_text(draw, nx, ny - 9 * avg_scale, node_name, sub_font, TEXT_DARK, int(2 * avg_scale))

        composed = Image.alpha_composite(base_img, overlay).convert("RGB")
        bldg_name = fp_info.building.building_name if fp_info.building else "building"
        safe_bldg = re.sub(r"[^a-zA-Z0-9_-]", "_", bldg_name)
        filename = f"route_{notification_id}_{safe_bldg}_f{fp_info.floor_level}.png"
        file_path = vis_dir / filename
        composed.save(file_path, format="PNG", optimize=True)

        results.append(
            {
                "cid": f"route-{notification_id}-fp{fp_id}@campusnavigation",
                "filePath": str(file_path),
                "filename": filename,
                "buildingName": bldg_name,
                "floorLevel": fp_info.floor_level,
                "floorplanId": fp_id,
            }
        )

    return results


def cleanup_old_visualizations(retention_hours: int | None = None) -> int:
    hours = retention_hours if retention_hours is not None else int(os.getenv("VISUALISATION_RETENTION_HOURS", "24"))
    cutoff = time.time() - hours * 3600
    removed = 0
    vis_dir = get_visualisations_dir()
    for p in vis_dir.glob("*.png"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    return removed
