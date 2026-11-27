"""Full-Map AI Auto-Generator (Doorway-Threshold Vision + Orthogonal Corridor Spine Synthesis).

Produces clean, architectural, human-grade campus maps matching manual mapping conventions:
1. Gemini Multimodal Vision identifies every room, lab, office, washroom, elevator, stairwell,
   and exit — placing each node right at its DOORWAY THRESHOLD (the gap in the black wall
   opening into the corridor), rather than the room center.
2. OpenCV extracts the walkable grey corridor mask + medial-axis centerline.
3. For each doorway node, projects a crisp perpendicular stub onto the nearest corridor
   centerline, creating clean T-junction CORRIDOR nodes (merging nearby projections).
4. Connects corridor nodes into straight horizontal/vertical hallway segments with clean 90°
   intersections (using wall-avoiding A* only when a straight segment is blocked by a wall).
5. Pre-fills smart default RBAC roles and auto-links Elevators/Stairwells to adjacent floors.
"""

from __future__ import annotations

import heapq
import io
import json
import logging
import math
import os
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.models.models import Floorplan, Node, NodeRBAC
from app.services.mapping.route_visualizer import resolve_floorplan_image_path

logger = logging.getLogger("smart-campus.mapping.auto_mapper")

VALID_NODE_TYPES = {
    "CLASSROOM",
    "CORRIDOR",
    "ENTRANCE",
    "STAIRWELL",
    "ELEVATOR",
    "FOOD",
    "OFFICE",
    "FACILITIES",
    "HALL",
    "WASHROOM",
    "OUTDOOR",
    "SOCIAL SPACES",
    "OTHER",
}

ALL_ROLES = [1, 2, 3, 4, 5]     # ADMIN, STAFF, LECTURER, STUDENT, VISITOR
ACADEMIC_ROLES = [1, 2, 3, 4]   # ADMIN, STAFF, LECTURER, STUDENT
STAFF_ONLY_ROLES = [1, 2, 3]    # ADMIN, STAFF, LECTURER
ADMIN_STAFF_ROLES = [1, 2]      # ADMIN, STAFF


def _default_roles_for_node(node_type: str, room_label: str) -> list[int]:
    lbl = (room_label or "").lower()
    if any(k in lbl for k in ("storeroom", "storage", "server", "electrical", "switchboard", "plant", "prepare room", "preparation room")):
        return list(ADMIN_STAFF_ROLES)
    if node_type == "OFFICE" or any(k in lbl for k in ("staff", "examination", "admin", "dean", "counselling")):
        return list(STAFF_ONLY_ROLES)
    if node_type == "CLASSROOM" or any(k in lbl for k in ("lab", "lecture", "classroom", "tutorial", "studio", "growth room", "transfer room")):
        return list(ACADEMIC_ROLES)
    return list(ALL_ROLES)


def _annotate_reference_grid(image_bytes: bytes) -> bytes:
    """Add subtle 0..1000 coordinate ticks around the image border to improve Gemini coordinate accuracy."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)
    for frac in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        x = int(w * frac)
        y = int(h * frac)
        draw.line([(x, 0), (x, 12)], fill=(220, 38, 38), width=2)
        draw.line([(x, h - 12), (x, h)], fill=(220, 38, 38), width=2)
        draw.line([(0, y), (12, y)], fill=(220, 38, 38), width=2)
        draw.line([(w - 12, y), (w, y)], fill=(220, 38, 38), width=2)
    buf = io.BytesIO()
    overlay.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _call_gemini_vision(
    image_bytes: bytes,
    *,
    building_name: str = "",
    floor_level: int | None = None,
    canvas_width: int = 800,
    canvas_height: int = 600,
) -> list[dict[str, Any]]:
    api_key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY / GEMINI_API_KEY is not configured")

    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=45_000),
    )
    annotated = _annotate_reference_grid(image_bytes)

    floor_hint = f"Building: {building_name}, Floor Level: {floor_level}" if building_name else "Campus building floorplan"
    prompt = f"""You are a precision architectural floorplan digitization engine for a Smart Campus indoor navigation system.
Context: {floor_hint}.

Analyze this floorplan image and output ONLY a valid JSON object (no markdown fences) with a single key "nodes": a list of ALL destination rooms, labs, offices, washrooms, elevators, stairwells, and exits on this floor.

CRITICAL PLACEMENT RULE (RIGHT OUTSIDE DOORWAYS — DO NOT PUT NODES IN ROOM CENTERS):
- Look at the black walls separating each colored room from the light-grey hallway/corridor. Notice the small DOORWAY GAPS in the black walls.
- Place every room's (x, y) RIGHT OUTSIDE ITS DOORWAY OPENING (just on the corridor-facing threshold of the doorway gap in the black wall), NOT inside the middle of the room!
- For RED emergency exit boxes: place the ENTRANCE node right outside the red box where it opens onto the grey corridor.
- For BLACK circular Elevator / Stairwell icons: place the ELEVATOR / STAIRWELL node right outside the opening facing the grey corridor.
- For BLUE Washroom areas (male/female/wheelchair icons): place the WASHROOM node right outside the doorway opening facing the grey corridor.
- Do NOT output CORRIDOR nodes — our corridor geometry engine will automatically build a clean, ruler-straight corridor spine with explicit 90° turning-point nodes and connect every doorway perpendicularly.
- Preserve exact room labels and abbreviations printed on the map (e.g. "Lecture Room 6 (LR6)", "Molecular Biology Lab").
- For icon-only areas with no text, give clear names: "Men's Washroom", "Women's Washroom", "Accessible Washroom (OKU)", "Elevator 1", "Stairwell 1", "Emergency Exit 1", "Emergency Exit 2".

Coordinate system:
- x is horizontal from 0 (left edge) to 1000 (right edge).
- y is vertical from 0 (top edge) to 1000 (bottom edge).
- Red tick marks on the image borders mark every 100 units (100, 200, ..., 900).

Allowed node_type values (use EXACTLY one):
CLASSROOM, ENTRANCE, STAIRWELL, ELEVATOR, FOOD, OFFICE, FACILITIES, HALL, WASHROOM, OUTDOOR, SOCIAL SPACES, OTHER

Output JSON schema:
{{
  "nodes": [
    {{
      "room_label": "string",
      "node_type": "CLASSROOM",
      "x": 250,
      "y": 445,
      "confidence": 0.95
    }}
  ]
}}"""

    model_candidates = [
        os.getenv("MAPPING_VISION_MODEL", "").strip(),
        "gemini-3.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.8-flash",
        os.getenv("RAG_LLM_MODEL", "").strip(),
    ]
    seen_models: set[str] = set()
    model_candidates = [m for m in model_candidates if m and not (m in seen_models or seen_models.add(m))]

    last_err: Exception | None = None
    raw_text = ""
    for model_name in model_candidates:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=annotated, mime_type="image/jpeg"),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            raw_text = (response.text or "").strip()
            if raw_text:
                logger.info("Gemini Vision doorway analysis succeeded with model=%s", model_name)
                break
        except Exception as exc:
            logger.warning("Gemini Vision model=%s failed: %s", model_name, exc)
            last_err = exc

    if not raw_text:
        raise RuntimeError(f"All Gemini Vision models failed: {last_err}")

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].strip()

    parsed = json.loads(raw_text)
    raw_nodes = parsed.get("nodes") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_nodes, list):
        return []

    nodes_out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_nodes):
        if not isinstance(item, dict):
            continue
        label = str(item.get("room_label") or "").strip()
        if not label:
            continue
        ntype = str(item.get("node_type") or "OTHER").strip().upper()
        if ntype not in VALID_NODE_TYPES or ntype == "CORRIDOR":
            if ntype == "CORRIDOR":
                continue
            ntype = "OTHER"
        nx_norm = max(0.0, min(1000.0, float(item.get("x", 500))))
        ny_norm = max(0.0, min(1000.0, float(item.get("y", 500))))
        cx = round((nx_norm / 1000.0) * canvas_width, 2)
        cy = round((ny_norm / 1000.0) * canvas_height, 2)
        conf = round(max(0.1, min(1.0, float(item.get("confidence", 0.92)))), 3)

        nodes_out.append(
            {
                "temp_id": f"ai_gemini_{idx}",
                "room_label": label,
                "node_type": ntype,
                "x": cx,
                "y": cy,
                "is_accessible": "ALLOW",
                "allowed_roles": _default_roles_for_node(ntype, label),
                "ai_generated": True,
                "ai_confidence": conf,
                "ai_source": "gemini_vision",
                "review_status": "PENDING",
            }
        )

    return nodes_out


# ─────────────────────────────────────────────────────────────────────────────
# CORRIDOR EXTRACTION & ORTHOGONAL SPINE SYNTHESIS
# ─────────────────────────────────────────────────────────────────────────────


def _extract_corridor_mask(
    image_bytes: bytes,
    canvas_width: int = 800,
    canvas_height: int = 600,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract the light-grey walkable corridor mask and its distance transform at 800x600."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        empty = np.zeros((canvas_height, canvas_width), dtype=np.uint8)
        return empty, np.zeros((canvas_height, canvas_width), dtype=np.float32)

    resized = cv2.resize(bgr, (canvas_width, canvas_height), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    # Light-grey corridor pixels: low saturation (S < 35) and medium-high brightness (165 <= V <= 245)
    # Excludes black walls (low V), colored rooms (high S), and pure-white text (V > 245)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    corridor = ((sat < 35) & (val >= 165) & (val <= 245)).astype(np.uint8) * 255

    # Remove tiny noise specs & fill minor icon/doorway notches
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    corridor = cv2.morphologyEx(corridor, cv2.MORPH_OPEN, kernel_open)

    # Keep only significant connected components (largest walkable hallway network)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(corridor, connectivity=8)
    cleaned = np.zeros_like(corridor)
    for lbl_id in range(1, num_labels):
        if stats[lbl_id, cv2.CC_STAT_AREA] >= 1200:
            cleaned[labels == lbl_id] = 255

    dist_tf = cv2.distanceTransform(cleaned, cv2.DIST_L2, 5)
    return cleaned, dist_tf


def _find_corridor_centerline_point(
    x: float,
    y: float,
    corridor_mask: np.ndarray,
    dist_tf: np.ndarray,
    canvas_width: int,
    canvas_height: int,
) -> tuple[float, float] | None:
    """Given a room doorway (x, y), cast perpendicular rays (up/down/left/right) into the grey
    corridor and return the exact centerline point (maximum distance-transform ridge along the ray)."""
    ix = max(0, min(canvas_width - 1, int(round(x))))
    iy = max(0, min(canvas_height - 1, int(round(y))))

    # 1. Try 4 cardinal rays (up, down, left, right) to find the closest corridor channel
    best_candidate: tuple[float, float, float] | None = None  # (dist_from_door, cx, cy)
    for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        in_corridor = False
        seg_pts: list[tuple[int, int, float]] = []
        entry_step = None
        for step in range(1, 95):
            nx = ix + dx * step
            ny = iy + dy * step
            if not (0 <= nx < canvas_width and 0 <= ny < canvas_height):
                break
            if corridor_mask[ny, nx] > 0:
                if not in_corridor:
                    in_corridor = True
                    entry_step = step
                seg_pts.append((nx, ny, float(dist_tf[ny, nx])))
                # Stop after traversing ~55px of corridor width
                if len(seg_pts) >= 55:
                    break
            elif in_corridor:
                # Reached the far wall of the corridor!
                break

        if seg_pts and entry_step is not None:
            # Pick the midpoint / max-clearance ridge of this corridor cross-section
            max_dt = max(p[2] for p in seg_pts)
            ridge_pts = [p for p in seg_pts if p[2] >= max_dt * 0.92]
            mid = ridge_pts[len(ridge_pts) // 2]
            score = entry_step
            if best_candidate is None or score < best_candidate[0]:
                best_candidate = (score, float(mid[0]), float(mid[1]))

    if best_candidate is not None:
        return round(best_candidate[1], 2), round(best_candidate[2], 2)

    # 2. Fallback: nearest corridor pixel within 120px radius
    ys, xs = np.where(corridor_mask > 0)
    if len(xs) == 0:
        return None
    dists_sq = (xs - x) ** 2 + (ys - y) ** 2
    idx = int(np.argmin(dists_sq))
    if dists_sq[idx] <= 140 ** 2:
        # Nudge slightly toward local ridge
        px, py = int(xs[idx]), int(ys[idx])
        win_x0, win_x1 = max(0, px - 18), min(canvas_width, px + 19)
        win_y0, win_y1 = max(0, py - 18), min(canvas_height, py + 19)
        sub = dist_tf[win_y0:win_y1, win_x0:win_x1]
        if sub.size > 0 and sub.max() > 0:
            _, _, _, max_loc = cv2.minMaxLoc(sub)
            return round(float(win_x0 + max_loc[0]), 2), round(float(win_y0 + max_loc[1]), 2)
        return float(px), float(py)
    return None


def _snap_point_off_walls(
    x: float,
    y: float,
    grid: list[list[int]],
    grid_scale: int,
    canvas_width: int,
    canvas_height: int,
) -> tuple[float, float]:
    if not grid or not grid[0]:
        return x, y
    gh, gw = len(grid), len(grid[0])
    gx = max(0, min(gw - 1, int(x // grid_scale)))
    gy = max(0, min(gh - 1, int(y // grid_scale)))
    if grid[gy][gx] == 0:
        return x, y
    for radius in range(1, 8):
        best = None
        best_d = float("inf")
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < gw and 0 <= ny < gh and grid[ny][nx] == 0:
                    d = math.hypot(dx, dy)
                    if d < best_d:
                        best_d = d
                        best = (nx, ny)
        if best is not None:
            return (
                round(max(4.0, min(canvas_width - 4.0, (best[0] + 0.5) * grid_scale)), 2),
                round(max(4.0, min(canvas_height - 4.0, (best[1] + 0.5) * grid_scale)), 2),
            )
    return x, y


def _line_is_clear(
    p1: tuple[float, float],
    p2: tuple[float, float],
    wall_grid: list[list[int]],
    grid_scale: int,
) -> bool:
    """Check if the straight segment between p1 and p2 avoids walls (ignoring 1-cell doorway tips)."""
    if not wall_grid or not wall_grid[0]:
        return True
    gh, gw = len(wall_grid), len(wall_grid[0])
    dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    steps = max(2, int(dist / (grid_scale * 0.5)))
    # Skip first/last 15% near doorway threshold
    for s in range(1, steps):
        t = s / steps
        if t < 0.12 or t > 0.88:
            continue
        x = p1[0] + (p2[0] - p1[0]) * t
        y = p1[1] + (p2[1] - p1[1]) * t
        gx = max(0, min(gw - 1, int(x // grid_scale)))
        gy = max(0, min(gh - 1, int(y // grid_scale)))
        if wall_grid[gy][gx] == 1:
            return False
    return True


def _astar_grid_cells(
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    grid: list[list[int]],
    grid_scale: int,
) -> list[tuple[int, int]] | None:
    """4-directional orthogonal A* returning raw grid cells from start to end."""
    if not grid or not grid[0]:
        return None
    gh, gw = len(grid), len(grid[0])
    sx = max(0, min(gw - 1, int(start_xy[0] // grid_scale)))
    sy = max(0, min(gh - 1, int(start_xy[1] // grid_scale)))
    ex = max(0, min(gw - 1, int(end_xy[0] // grid_scale)))
    ey = max(0, min(gh - 1, int(end_xy[1] // grid_scale)))
    if (sx, sy) == (ex, ey):
        return [(sx, sy)]

    neighbors = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    g_score: dict[tuple[int, int], float] = {(sx, sy): 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    heap: list[tuple[float, tuple[int, int]]] = [(abs(ex - sx) + abs(ey - sy), (sx, sy))]
    visited: set[tuple[int, int]] = set()

    while heap:
        _, curr = heapq.heappop(heap)
        if curr in visited:
            continue
        visited.add(curr)
        if curr == (ex, ey):
            cells = [curr]
            while curr in came_from:
                curr = came_from[curr]
                cells.append(curr)
            cells.reverse()
            return cells

        cx, cy = curr
        for dx, dy in neighbors:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < gw and 0 <= ny < gh):
                continue
            if (nx, ny) != (ex, ey) and grid[ny][nx] == 1:
                continue
            prev = came_from.get(curr)
            turn_pen = 0.0
            if prev is not None:
                pdx, pdy = cx - prev[0], cy - prev[1]
                if (pdx, pdy) != (dx, dy):
                    turn_pen = 0.4
            ng = g_score[curr] + 1.0 + turn_pen
            if ng < g_score.get((nx, ny), float("inf")):
                g_score[(nx, ny)] = ng
                came_from[(nx, ny)] = curr
                heapq.heappush(heap, (ng + abs(ex - nx) + abs(ey - ny), (nx, ny)))
    return None


def _astar_grid_path(
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    grid: list[list[int]],
    grid_scale: int,
) -> list[dict[str, float]] | None:
    """4-directional orthogonal A* on the wall grid for clean 90° turns when a straight line is blocked."""
    if not grid or not grid[0]:
        return [{"x": start_xy[0], "y": start_xy[1]}, {"x": end_xy[0], "y": end_xy[1]}]
    cells = _astar_grid_cells(start_xy, end_xy, grid, grid_scale)
    if cells is None:
        return None
    if len(cells) <= 1:
        return [{"x": start_xy[0], "y": start_xy[1]}, {"x": end_xy[0], "y": end_xy[1]}]

    pts = [{"x": start_xy[0], "y": start_xy[1]}]
    for i in range(1, len(cells) - 1):
        dx1 = cells[i][0] - cells[i - 1][0]
        dy1 = cells[i][1] - cells[i - 1][1]
        dx2 = cells[i + 1][0] - cells[i][0]
        dy2 = cells[i + 1][1] - cells[i][1]
        if (dx1, dy1) != (dx2, dy2):
            pts.append(
                {
                    "x": round((cells[i][0] + 0.5) * grid_scale, 2),
                    "y": round((cells[i][1] + 0.5) * grid_scale, 2),
                }
            )
    pts.append({"x": end_xy[0], "y": end_xy[1]})
    return pts


def _snap_room_to_doorway_threshold(
    rn: dict[str, Any],
    corridor_mask: np.ndarray,
    dist_tf: np.ndarray,
    wall_grid: list[list[int]],
    *,
    canvas_width: int,
    canvas_height: int,
    grid_scale: int,
) -> None:
    """If Gemini placed a room/exit node slightly behind a black wall instead of inside the doorway
    gap, trace the wall-avoiding path into the corridor and snap the node right onto the exact
    doorway threshold (where the room exits into the grey corridor)."""
    rx, ry = float(rn["x"]), float(rn["y"])
    ix = max(0, min(canvas_width - 1, int(round(rx))))
    iy = max(0, min(canvas_height - 1, int(round(ry))))
    if corridor_mask[iy, ix] > 0:
        return  # Already on corridor threshold

    proj = _find_corridor_centerline_point(rx, ry, corridor_mask, dist_tf, canvas_width, canvas_height)
    if proj is None:
        return

    # Case A: Unobstructed line to corridor — slide right up to the outside edge of the doorway
    if _line_is_clear((rx, ry), proj, wall_grid, grid_scale):
        dist_to_proj = math.hypot(proj[0] - rx, proj[1] - ry)
        if dist_to_proj <= 70.0:
            steps = max(2, int(dist_to_proj))
            for s in range(1, steps + 1):
                t = s / steps
                sx = rx + (proj[0] - rx) * t
                sy = ry + (proj[1] - ry) * t
                px = min(canvas_width - 1, max(0, int(round(sx))))
                py = min(canvas_height - 1, max(0, int(round(sy))))
                if corridor_mask[py, px] > 0:
                    # Place right outside the doorway opening (just on the corridor edge)
                    rn["x"] = round(sx, 2)
                    rn["y"] = round(sy, 2)
                    return
        return

    # Case B: Blocked by a black wall — trace A* to find the actual doorway gap into the corridor
    cells = _astar_grid_cells((rx, ry), proj, wall_grid, grid_scale)
    if not cells or len(cells) < 2:
        return

    max_snap_dist = 130.0 if rn.get("node_type") == "ENTRANCE" else 90.0
    for idx, (gx, gy) in enumerate(cells):
        px = min(canvas_width - 1, max(0, int((gx + 0.5) * grid_scale)))
        py = min(canvas_height - 1, max(0, int((gy + 0.5) * grid_scale)))
        if corridor_mask[py, px] > 0:
            # Place right outside the doorway opening on the corridor-entry threshold
            tx = round((gx + 0.5) * grid_scale, 2)
            ty = round((gy + 0.5) * grid_scale, 2)
            if math.hypot(tx - rx, ty - ry) <= max_snap_dist:
                rn["x"] = tx
                rn["y"] = ty
            return


def _path_length_meters(pts: list[dict[str, float]], scale_ratio: float) -> float:
    px = 0.0
    for i in range(1, len(pts)):
        px += math.hypot(pts[i]["x"] - pts[i - 1]["x"], pts[i]["y"] - pts[i - 1]["y"])
    return round(px * (scale_ratio or 1.0), 2)


def _align_corridor_axes(corridor_nodes: list[dict[str, Any]], tolerance_px: float = 16.0) -> None:
    """Snap corridor nodes that lie along the same hallway band onto an exact shared Y or X centerline
    so horizontal & vertical corridors are ruler-straight (just like manual CAD mapping)."""
    if len(corridor_nodes) < 2:
        return

    # 1. Snap horizontal hallway clusters (nodes within tolerance_px in Y)
    visited_y: set[int] = set()
    for i in range(len(corridor_nodes)):
        if i in visited_y:
            continue
        cluster = [i]
        for j in range(i + 1, len(corridor_nodes)):
            if j not in visited_y and abs(corridor_nodes[j]["y"] - corridor_nodes[i]["y"]) <= tolerance_px:
                cluster.append(j)
        if len(cluster) >= 3:
            median_y = round(float(np.median([corridor_nodes[k]["y"] for k in cluster])), 2)
            for k in cluster:
                corridor_nodes[k]["y"] = median_y
                visited_y.add(k)

    # 2. Snap vertical hallway clusters (nodes within tolerance_px in X)
    visited_x: set[int] = set()
    for i in range(len(corridor_nodes)):
        if i in visited_x:
            continue
        cluster = [i]
        for j in range(i + 1, len(corridor_nodes)):
            if j not in visited_x and abs(corridor_nodes[j]["x"] - corridor_nodes[i]["x"]) <= tolerance_px:
                cluster.append(j)
        if len(cluster) >= 2:
            median_x = round(float(np.median([corridor_nodes[k]["x"] for k in cluster])), 2)
            for k in cluster:
                corridor_nodes[k]["x"] = median_x
                visited_x.add(k)


def _build_orthogonal_graph(
    room_nodes: list[dict[str, Any]],
    corridor_mask: np.ndarray,
    dist_tf: np.ndarray,
    wall_grid: list[list[int]],
    *,
    canvas_width: int = 800,
    canvas_height: int = 600,
    grid_scale: int = 8,
    scale_ratio: float = 1.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Synthesize perpendicular corridor T-junctions for every doorway + straight hallway spine."""
    corridor_nodes: list[dict[str, Any]] = []
    room_to_corridor: dict[int, int] = {}

    # 0. Snap any room/exit node placed slightly behind a black wall right onto its doorway threshold
    for rn in room_nodes:
        _snap_room_to_doorway_threshold(
            rn,
            corridor_mask,
            dist_tf,
            wall_grid,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            grid_scale=grid_scale,
        )

    # 1. Project every doorway perpendicularly into the grey corridor centerline
    for r_idx, rn in enumerate(room_nodes):
        proj = _find_corridor_centerline_point(
            rn["x"], rn["y"], corridor_mask, dist_tf, canvas_width, canvas_height
        )
        if proj is None:
            continue
        cx, cy = _snap_point_off_walls(proj[0], proj[1], wall_grid, grid_scale, canvas_width, canvas_height)

        # Merge with an existing corridor node if very close (< 22px)
        merged_c_idx = None
        for c_idx, cn in enumerate(corridor_nodes):
            if math.hypot(cn["x"] - cx, cn["y"] - cy) < 22.0:
                merged_c_idx = c_idx
                break

        if merged_c_idx is not None:
            room_to_corridor[r_idx] = merged_c_idx
        else:
            c_idx = len(corridor_nodes)
            corridor_nodes.append(
                {
                    "temp_id": f"ai_corridor_{c_idx}",
                    "room_label": "Corridor",
                    "node_type": "CORRIDOR",
                    "x": cx,
                    "y": cy,
                    "is_accessible": "ALLOW",
                    "allowed_roles": list(ALL_ROLES),
                    "ai_generated": True,
                    "ai_confidence": 0.95,
                    "ai_source": "corridor_spine",
                    "review_status": "PENDING",
                }
            )
            room_to_corridor[r_idx] = c_idx

    # 2. Snap corridor nodes onto exact horizontal/vertical hallway axes for ruler-straight lines
    _align_corridor_axes(corridor_nodes, tolerance_px=22.0)

    # Combine: rooms first, then corridors
    all_nodes = list(room_nodes) + corridor_nodes
    corridor_offset = len(room_nodes)
    edges_out: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int]] = set()

    def _try_orthogonal_l_path(p1: tuple[float, float], p2: tuple[float, float]) -> list[dict[str, float]] | None:
        """Try clean 90° L-shaped bend (horizontal-then-vertical or vertical-then-horizontal)."""
        candidates = [(p2[0], p1[1]), (p1[0], p2[1])]
        # Prefer the corner that sits inside the walkable grey corridor
        def corner_score(c: tuple[float, float]) -> int:
            ix = max(0, min(canvas_width - 1, int(round(c[0]))))
            iy = max(0, min(canvas_height - 1, int(round(c[1]))))
            return 0 if corridor_mask[iy, ix] > 0 else 1

        candidates.sort(key=corner_score)
        for corner in candidates:
            if _line_is_clear(p1, corner, wall_grid, grid_scale) and _line_is_clear(corner, p2, wall_grid, grid_scale):
                return [
                    {"x": p1[0], "y": p1[1]},
                    {"x": round(corner[0], 2), "y": round(corner[1], 2)},
                    {"x": p2[0], "y": p2[1]},
                ]
        return None

    turn_node_counter = len(corridor_nodes)

    def _find_or_create_turn_node(x: float, y: float) -> int:
        """Promote every 90° turning corner into an explicit CORRIDOR node (reusing nearby nodes)
        so turn-by-turn navigation accurately emits 'Turn left' / 'Turn right' instructions."""
        nonlocal turn_node_counter
        sx, sy = _snap_point_off_walls(x, y, wall_grid, grid_scale, canvas_width, canvas_height)
        for idx, n in enumerate(all_nodes):
            if n.get("node_type") == "CORRIDOR" and math.hypot(n["x"] - sx, n["y"] - sy) < 14.0:
                return idx
        new_idx = len(all_nodes)
        all_nodes.append(
            {
                "temp_id": f"ai_corridor_turn_{turn_node_counter}",
                "room_label": "Corridor",
                "node_type": "CORRIDOR",
                "x": round(sx, 2),
                "y": round(sy, 2),
                "is_accessible": "ALLOW",
                "allowed_roles": list(ALL_ROLES),
                "ai_generated": True,
                "ai_confidence": 0.95,
                "ai_source": "corridor_turn",
                "review_status": "PENDING",
            }
        )
        turn_node_counter += 1
        return new_idx

    def _emit_straight_segment(u: int, v: int, *, is_custom: bool = False) -> None:
        a, b = (u, v) if u < v else (v, u)
        if a == b or (a, b) in seen_pairs:
            return
        seen_pairs.add((a, b))
        na, nb = all_nodes[a], all_nodes[b]
        seg_pts = [{"x": na["x"], "y": na["y"]}, {"x": nb["x"], "y": nb["y"]}]
        roles_a = set(na.get("allowed_roles") or ALL_ROLES)
        roles_b = set(nb.get("allowed_roles") or ALL_ROLES)
        shared = sorted(roles_a & roles_b)
        edges_out.append(
            {
                "edge_id": None,
                "start": a,
                "end": b,
                "weight": _path_length_meters(seg_pts, scale_ratio),
                "is_bidirectional": True,
                "is_accessible": "ALLOW" if shared else "DENY",
                "allowed_roles": shared,
                "isCustom": is_custom,
                "customPathPoints": seg_pts if is_custom else None,
                "pathPoints": seg_pts,
                "ai_generated": True,
            }
        )

    def add_clean_edge(i: int, j: int, *, prefer_straight: bool = True) -> None:
        a, b = (i, j) if i < j else (j, i)
        if a == b or (a, b) in seen_pairs:
            return
        na, nb = all_nodes[a], all_nodes[b]
        p1, p2 = (na["x"], na["y"]), (nb["x"], nb["y"])
        is_axis_aligned = (abs(p1[0] - p2[0]) <= 14.0) or (abs(p1[1] - p2[1]) <= 14.0)

        pts: list[dict[str, float]] | None = None
        is_custom = False
        if prefer_straight and is_axis_aligned and _line_is_clear(p1, p2, wall_grid, grid_scale):
            _emit_straight_segment(a, b, is_custom=False)
            return
        elif prefer_straight and not is_axis_aligned:
            pts = _try_orthogonal_l_path(p1, p2)

        if pts is None:
            pts = _astar_grid_path(p1, p2, wall_grid, grid_scale)
            if pts is None:
                _emit_straight_segment(a, b, is_custom=True)
                return

        # Promote every interior 90° turning point into a real CORRIDOR node
        chain = [a]
        for corner in pts[1:-1]:
            cx, cy = float(corner["x"]), float(corner["y"])
            prev_node = all_nodes[chain[-1]]
            if math.hypot(cx - prev_node["x"], cy - prev_node["y"]) < 10.0:
                continue
            if math.hypot(cx - nb["x"], cy - nb["y"]) < 10.0:
                continue
            c_idx = _find_or_create_turn_node(cx, cy)
            if c_idx != chain[-1]:
                chain.append(c_idx)
        if chain[-1] != b:
            chain.append(b)

        for k in range(len(chain) - 1):
            _emit_straight_segment(chain[k], chain[k + 1], is_custom=is_custom)

    # 3. Connect every room doorway to its perpendicular corridor node with a short straight stub
    for r_idx, c_local_idx in room_to_corridor.items():
        add_clean_edge(r_idx, corridor_offset + c_local_idx, prefer_straight=True)

    # 4. Connect corridor nodes via Prim's MST favoring straight unobstructed hallway links
    c_indices = [corridor_offset + k for k in range(len(corridor_nodes))]
    if len(c_indices) >= 2:
        in_tree = {c_indices[0]}
        remaining = set(c_indices[1:])
        while remaining:
            best_pair = None
            best_cost = float("inf")
            for u in in_tree:
                for v in remaining:
                    nu, nv = all_nodes[u], all_nodes[v]
                    d = math.hypot(nu["x"] - nv["x"], nu["y"] - nv["y"])
                    # Strongly prefer axis-aligned, unobstructed hallway segments
                    is_aligned = (abs(nu["x"] - nv["x"]) <= 14.0) or (abs(nu["y"] - nv["y"]) <= 14.0)
                    clear = _line_is_clear((nu["x"], nu["y"]), (nv["x"], nv["y"]), wall_grid, grid_scale)
                    cost = d * (0.75 if is_aligned else 1.25) * (1.0 if clear else 2.5)
                    if cost < best_cost:
                        best_cost = cost
                        best_pair = (u, v)
            if best_pair is None:
                break
            u, v = best_pair
            add_clean_edge(u, v, prefer_straight=True)
            in_tree.add(v)
            remaining.remove(v)

    # 5. Connect any unprojected room (fallback) to its closest node
    for r_idx in range(len(room_nodes)):
        if r_idx not in room_to_corridor and len(all_nodes) > 1:
            targets = c_indices if c_indices else [k for k in range(len(all_nodes)) if k != r_idx]
            nearest = min(
                targets,
                key=lambda k: math.hypot(all_nodes[k]["x"] - all_nodes[r_idx]["x"], all_nodes[k]["y"] - all_nodes[r_idx]["y"]),
            )
            add_clean_edge(r_idx, nearest, prefer_straight=False)

    return all_nodes, edges_out


def _suggest_cross_floor_transitions(
    db: Session,
    *,
    floorplan: Floorplan,
    nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not floorplan or not floorplan.building_id:
        return []

    adj_floorplans = (
        db.query(Floorplan)
        .filter(
            Floorplan.building_id == floorplan.building_id,
            Floorplan.floorplan_id != floorplan.floorplan_id,
            Floorplan.floor_level.in_([floorplan.floor_level - 1, floorplan.floor_level + 1]),
        )
        .all()
    )
    if not adj_floorplans:
        return []

    adj_fp_ids = [fp.floorplan_id for fp in adj_floorplans]
    adj_nodes = (
        db.query(Node)
        .filter(
            Node.floorplan_id.in_(adj_fp_ids),
            Node.node_type.in_(["ELEVATOR", "STAIRWELL"]),
        )
        .all()
    )
    if not adj_nodes:
        return []

    adj_node_ids = [n.node_id for n in adj_nodes]
    adj_roles_map: dict[int, list[int]] = {}
    for nr in db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(adj_node_ids)).all():
        adj_roles_map.setdefault(nr.node_id, []).append(nr.role_id)

    transitions: list[dict[str, Any]] = []
    for idx, node in enumerate(nodes):
        if node["node_type"] not in ("ELEVATOR", "STAIRWELL"):
            continue
        for adj_fp in adj_floorplans:
            same_floor_targets = [
                an for an in adj_nodes
                if an.floorplan_id == adj_fp.floorplan_id and an.node_type == node["node_type"]
            ]
            if not same_floor_targets:
                continue
            closest = min(
                same_floor_targets,
                key=lambda an: math.hypot(float(an.coord_x) - node["x"], float(an.coord_y) - node["y"]),
            )
            dist_px = math.hypot(float(closest.coord_x) - node["x"], float(closest.coord_y) - node["y"])
            if dist_px <= 140.0:
                target_roles = set(adj_roles_map.get(closest.node_id) or ALL_ROLES)
                my_roles = set(node.get("allowed_roles") or ALL_ROLES)
                shared = sorted(my_roles & target_roles) or list(ALL_ROLES)
                transitions.append(
                    {
                        "edge_id": None,
                        "start": idx,
                        "is_cross_floor": True,
                        "target_node_id": closest.node_id,
                        "weight": 10.0,
                        "is_bidirectional": True,
                        "is_accessible": "ALLOW",
                        "allowed_roles": shared,
                        "isCustom": False,
                        "customPathPoints": None,
                        "pathPoints": None,
                        "ai_generated": True,
                    }
                )
    return transitions


def auto_map_floorplan_sync(
    db: Session,
    *,
    floorplan: Floorplan,
    sensitivity: int = 120,
    canvas_width: int = 800,
    canvas_height: int = 600,
    grid_scale: int = 8,
    room_gap_close_px: int = 25,
    min_room_area_px: int = 2000,
    max_room_area_ratio: float = 0.30,
    min_ocr_confidence: float = 0.60,
    wall_clearance_px: int = 8,
) -> dict[str, Any]:
    """Run full-map auto-generation with doorway-threshold placement & orthogonal corridor spine."""
    disk_path = resolve_floorplan_image_path(floorplan.image_path)
    if not disk_path:
        raise FileNotFoundError(f"Floorplan image not found on disk: {floorplan.image_path}")

    image_bytes = disk_path.read_bytes()
    bldg_name = floorplan.building.building_name if floorplan.building else ""
    scale_ratio = float(floorplan.scale_ratio) if floorplan.scale_ratio else 1.0

    # 1. Wall grid + grey corridor mask
    import sys
    from pathlib import Path

    ai_services_dir = str(Path(__file__).resolve().parents[6] / "mapping_and_notification" / "ai-services")
    if ai_services_dir not in sys.path:
        sys.path.insert(0, ai_services_dir)

    from src.modules.wall_detection.detector import WallDetector
    detector = WallDetector()
    wall_det = detector.detect(
        image_bytes=image_bytes,
        sensitivity=sensitivity,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        grid_scale=grid_scale,
    )
    wall_grid = wall_det.wall_grid.grid
    corridor_mask, dist_tf = _extract_corridor_mask(image_bytes, canvas_width, canvas_height)

    # 2. Extract doorway-threshold room/icon nodes via Gemini Vision (with OpenCV fallback)
    engine_used = "gemini_vision"
    room_nodes: list[dict[str, Any]] = []
    try:
        room_nodes = _call_gemini_vision(
            image_bytes,
            building_name=bldg_name,
            floor_level=floorplan.floor_level,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )
    except Exception as exc:
        logger.warning("Gemini Vision auto-map unavailable (%s); falling back to OpenCV analyzer.", exc)
        engine_used = "opencv_fallback"

    if not room_nodes:
        from src.services.floorplan_analyzer import FloorplanAnalyzerService
        analyzer = FloorplanAnalyzerService()
        fallback = analyzer.analyze(
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
        for n in fallback.nodes:
            ntype = n.node_type if n.node_type in VALID_NODE_TYPES else "CLASSROOM"
            room_nodes.append(
                {
                    "temp_id": n.temp_id,
                    "room_label": n.room_label,
                    "node_type": ntype,
                    "x": n.x,
                    "y": n.y,
                    "is_accessible": "ALLOW",
                    "allowed_roles": _default_roles_for_node(ntype, n.room_label),
                    "ai_generated": True,
                    "ai_confidence": n.ai_confidence,
                    "ai_source": n.ai_source.value if hasattr(n.ai_source, "value") else str(n.ai_source),
                    "review_status": "PENDING",
                }
            )

    # 3. Snap doorway nodes gently off wall cells
    for n in room_nodes:
        n["x"], n["y"] = _snap_point_off_walls(n["x"], n["y"], wall_grid, grid_scale, canvas_width, canvas_height)

    # 4. Synthesize perpendicular corridor spine + straight hallway edges + cross-floor links
    all_nodes, same_floor_edges = _build_orthogonal_graph(
        room_nodes,
        corridor_mask,
        dist_tf,
        wall_grid,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        grid_scale=grid_scale,
        scale_ratio=scale_ratio,
    )
    cross_floor_edges = _suggest_cross_floor_transitions(db, floorplan=floorplan, nodes=all_nodes)
    all_edges = same_floor_edges + cross_floor_edges

    room_count = sum(1 for n in all_nodes if n["node_type"] != "CORRIDOR")
    corridor_count = sum(1 for n in all_nodes if n["node_type"] == "CORRIDOR")

    return {
        "status": "success",
        "engine": engine_used,
        "nodes": all_nodes,
        "edges": all_edges,
        "wall_grid": {
            "grid": wall_grid,
            "grid_width": wall_det.wall_grid.grid_width,
            "grid_height": wall_det.wall_grid.grid_height,
            "canvas_width": canvas_width,
            "canvas_height": canvas_height,
            "grid_scale": grid_scale,
        },
        "summary": {
            "nodes_generated": len(all_nodes),
            "rooms_detected": room_count,
            "corridors_generated": corridor_count,
            "edges_generated": len(same_floor_edges),
            "transitions_suggested": len(cross_floor_edges),
        },
    }
