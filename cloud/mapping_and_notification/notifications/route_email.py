from __future__ import annotations

import html
import io
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

LOGICAL_CANVAS_WIDTH = 800
LOGICAL_CANVAS_HEIGHT = 600


def _text(value: Any) -> str:
    return html.escape(str(value or ""))


def _as_points(value: Any) -> list[tuple[float, float]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []
    points = []
    for point in value:
        if isinstance(point, dict) and "x" in point and "y" in point:
            try:
                points.append((float(point["x"]), float(point["y"])))
            except (TypeError, ValueError):
                continue
    return points if len(points) >= 2 else []


def _route_points(start: dict, end: dict, edge: dict | None) -> list[tuple[float, float]]:
    start_point = (float(start["coord_x"]), float(start["coord_y"]))
    end_point = (float(end["coord_x"]), float(end["coord_y"]))
    points = _as_points((edge or {}).get("custom_path"))
    if len(points) < 2:
        return [start_point, end_point]
    direct = math.dist(points[0], start_point) + math.dist(points[-1], end_point)
    reverse = math.dist(points[-1], start_point) + math.dist(points[0], end_point)
    return list(reversed(points)) if reverse < direct else points


def _scale_points(points: list[tuple[float, float]], image_size: tuple[int, int]) -> list[tuple[float, float]]:
    scale_x = image_size[0] / LOGICAL_CANVAS_WIDTH
    scale_y = image_size[1] / LOGICAL_CANVAS_HEIGHT
    return [(x * scale_x, y * scale_y) for x, y in points]


def _floorplan_metadata(db, floorplan_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not floorplan_ids:
        return {}
    from app.models.models import Building, Floorplan
    from app.core.private_storage import safe_existing_path

    rows = (
        db.query(Floorplan, Building.building_name)
        .join(Building, Floorplan.building_id == Building.building_id)
        .filter(Floorplan.floorplan_id.in_(floorplan_ids))
        .all()
    )
    result = {}
    for floorplan, building_name in rows:
        image_path = None
        if floorplan.image_path:
            try:
                image_path = safe_existing_path("floorplans", floorplan.image_path)
            except Exception:
                image_path = None
        result[int(floorplan.floorplan_id)] = {
            "building_name": building_name,
            "floor_level": floorplan.floor_level,
            "image_path": image_path,
        }
    return result


def _render_route_images(route_context: dict[str, Any], floorplans: dict[int, dict[str, Any]]):
    path = route_context.get("path") or route_context.get("route") or []
    edges = route_context.get("edges_traversed") or []
    if not isinstance(path, list):
        return [], {}
    nodes = {int(node["node_id"]): node for node in path if isinstance(node, dict) and node.get("node_id") is not None}
    edge_by_pair = {(int(edge["from_node_id"]), int(edge["to_node_id"])): edge for edge in edges if isinstance(edge, dict) and edge.get("from_node_id") is not None and edge.get("to_node_id") is not None}
    floor_ids = []
    # Match the original preview: render the start and destination floors only.
    for node in (path[0], path[-1]) if path else ():
        try:
            floor_id = int(node["floorplan_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if floor_id not in floor_ids:
            floor_ids.append(floor_id)

    attachments = []
    cids = {}
    for floor_id in floor_ids:
        metadata = floorplans.get(floor_id) or {}
        image_path = metadata.get("image_path")
        if not isinstance(image_path, Path) or not image_path.is_file():
            continue
        try:
            with Image.open(image_path) as source:
                image = source.convert("RGBA")
        except (OSError, ValueError):
            continue

        draw = ImageDraw.Draw(image, "RGBA")
        avg_scale = ((image.width / LOGICAL_CANVAS_WIDTH) + (image.height / LOGICAL_CANVAS_HEIGHT)) / 2
        floor_nodes = [node for node in path if int(node.get("floorplan_id", -1)) == floor_id]
        for start, end in zip(path, path[1:]):
            if int(start.get("floorplan_id", -1)) != floor_id or int(end.get("floorplan_id", -1)) != floor_id:
                continue
            edge = edge_by_pair.get((int(start["node_id"]), int(end["node_id"])))
            points = _scale_points(_route_points(start, end, edge), image.size)
            draw.line(points, fill=(20, 184, 166, 65), width=max(5, round(12 * avg_scale)), joint="curve")
            draw.line(points, fill=(20, 184, 166, 230), width=max(3, round(5 * avg_scale)), joint="curve")

        if floor_nodes:
            glow_radius = max(8, round(17 * avg_scale))
            radius = max(6, round(12 * avg_scale))
            dot_radius = max(3, round(6 * avg_scale))
            for index, node in enumerate(floor_nodes):
                point = _scale_points([(float(node["coord_x"]), float(node["coord_y"]))], image.size)[0]
                is_start = node is path[0]
                is_destination = node is path[-1]
                draw.ellipse((point[0] - glow_radius, point[1] - glow_radius, point[0] + glow_radius, point[1] + glow_radius), fill=(20, 184, 166, 45))
                draw.ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), outline=(20, 184, 166, 230), width=max(2, round(2.5 * avg_scale)))
                if is_start or is_destination:
                    colour = (20, 184, 166, 255) if is_start else (245, 158, 11, 255)
                    draw.ellipse((point[0] - dot_radius, point[1] - dot_radius, point[0] + dot_radius, point[1] + dot_radius), fill=colour)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        cid = f"route-floorplan-{floor_id}"
        cids[floor_id] = cid
        attachments.append({"data": buffer.getvalue(), "filename": f"route-floorplan-{floor_id}.png", "cid": cid, "maintype": "image", "subtype": "png"})
    return attachments, cids


def render_route_email(*, route_context: dict[str, Any], db, recipient_name: str | None = None, body: str = "") -> tuple[str, list[dict[str, Any]]]:
    summary = route_context.get("route_summary") or route_context.get("summary") or {}
    instructions = route_context.get("instructions") or []
    path = route_context.get("path") or route_context.get("route") or []
    floorplan_ids = {int(node["floorplan_id"]) for node in path if isinstance(node, dict) and node.get("floorplan_id") is not None}
    floorplans = _floorplan_metadata(db, floorplan_ids)
    attachments, cids = _render_route_images(route_context, floorplans)

    start_label = summary.get("start_label") or "your current location"
    destination_label = summary.get("destination_label") or "your destination"
    distance = summary.get("total_distance_m")
    duration = summary.get("estimated_time_seconds")
    duration_text = f"{round(float(duration) / 60)} min" if duration is not None else ""
    summary_items = [f"<strong>From:</strong> {_text(start_label)}", f"<strong>To:</strong> {_text(destination_label)}"]
    if distance is not None:
        summary_items.append(f"<strong>Distance:</strong> {_text(distance)} m")
    if duration_text:
        summary_items.append(f"<strong>Estimated time:</strong> {_text(duration_text)}")

    instruction_items = []
    for item in instructions:
        if not isinstance(item, dict):
            continue
        instruction = item.get("instruction") or item.get("description")
        if instruction:
            distance_suffix = f" <span style='color:#64748b'>({item['distance_m']} m)</span>" if item.get("distance_m") is not None else ""
            instruction_items.append(f"<li>{_text(instruction)}{distance_suffix}</li>")
    if not instruction_items:
        instruction_items.append("<li>Follow the route shown below to reach your destination.</li>")

    image_items = []
    for floor_id, cid in cids.items():
        metadata = floorplans.get(floor_id) or {}
        label = f"{metadata.get('building_name') or 'Building'} - Floor {metadata.get('floor_level', floor_id)}"
        image_items.append(f"<figure><figcaption><strong>{_text(label)}</strong></figcaption><img src='cid:{_text(cid)}' alt='Route on {_text(label)}' style='max-width:100%;height:auto;border:1px solid #cbd5e1;border-radius:8px'></figure>")

    body_html = f"<p>{_text(body).replace(chr(10), '<br>')}</p>" if body else ""
    greeting = f"Hello {_text(recipient_name)}," if recipient_name else "Hello,"
    images_html = "".join(image_items) or "<p>Route image unavailable; use the directions above.</p>"
    html_body = f"""<!doctype html>
<html><body style="font-family:Arial,sans-serif;color:#172033;line-height:1.5;max-width:760px;margin:auto;padding:24px">
<h1 style="color:#0f766e">Campus route notification</h1>
<p>{greeting}</p>{body_html}
<h2>Journey details</h2><p>{"<br>".join(summary_items)}</p>
<h2>Turn-by-turn directions</h2><ol>{"".join(instruction_items)}</ol>
<h2>Route map</h2>{images_html}
<p style="color:#64748b;font-size:12px">This route was generated by Smart Campus.</p>
</body></html>"""
    return html_body, attachments
