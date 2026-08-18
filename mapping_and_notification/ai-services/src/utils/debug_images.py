"""
utils/debug_images.py
---------------------
DebugImageWriter — saves intermediate pipeline images to disk when debug_mode=True.

When enabled, saves all intermediate representations to:
  ai-services/debug_output/{prefix}/

  01_original.png              Stage 1A: raw floorplan
  02_grayscale.png             Stage 1A: grayscale conversion
  03_denoised.png              Stage 1A: noise reduction
  04_contrast_enhanced.png     Stage 1A: CLAHE contrast
  05_wall_view.png             Stage 1A: wall detection view
  05b_wall_mask_dilated.png    Stage 1B: wall mask (dilated)
  06_room_view.png             Stage 1A: room detection view
  07_ocr_view.png              Stage 1A: OCR view (sharpened)
  08_room_candidates.png       Stage 1F: CCA candidates (green=accepted, red=rejected)
  09_room_accepted.png         Stage 1F: accepted room polygons annotated
  10_ocr_raw_detections.png    Stage 1C: raw PaddleOCR bounding boxes
  10b_ocr_merged.png           Stage 1D: merged OCR fragments (green=multi, blue=single)
  11_room_label_associations.png Stage 1F: room↔label associations
  12_nodes_final.png           Stage 1F: all final nodes
                               (cyan=OCR_PRIMARY, blue=ROOM_DETECTION_OCR, grey=ROOM_DETECTION)

These images allow visual inspection of every pipeline stage, making it possible
to identify exactly where analysis fails on any given floorplan.

───────────────────────────────────────────────────────────────────────────────
CLI Developer Tool Usage
───────────────────────────────────────────────────────────────────────────────
Can also be run as a standalone developer tool to annotate any image with an
existing AI analysis JSON result:

    python -m src.utils.debug_images \\
        --image path/to/floorplan.jpg \\
        --analysis path/to/analysis_result.json \\
        --output debug_output/manual_run/

    python -m src.utils.debug_images \\
        --image path/to/floorplan.jpg \\
        --analysis path/to/analysis_result.json \\
        --output debug_output/manual_run/ \\
        --overlays nodes rooms

Arguments:
    --image       Path to the floorplan image (JPEG, PNG, WEBP, BMP).
    --analysis    Path to a FloorplanAnalysisResult JSON file.
    --output      Output directory for annotated images (default: debug_output/manual_cli/).
    --overlays    Space-separated list of overlays to render:
                  nodes, rooms, all (default: all).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# Default output directory is ai-services/debug_output/ relative to this file's package root
_DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(  # src/utils
        os.path.dirname(  # src
            os.path.dirname(__file__)  # ai-services/src
        )
    ),
    "debug_output",
)


class DebugImageWriter:
    """
    Conditionally saves intermediate analysis images to disk.

    When enabled=False (default), every method is a no-op so no code paths
    need to guard against None returns — callers can always call write().

    Usage:
        writer = DebugImageWriter(prefix="fp_1234", enabled=True)
        writer.write("01_original", original_bgr)
        writer.write_labeled_rooms("09_room_accepted", bgr_image, accepted_rooms)
        paths = writer.paths  # Dict of written files
    """

    def __init__(
        self,
        prefix:     str,
        enabled:    bool = False,
        output_dir: Optional[str] = None,
    ) -> None:
        self.enabled    = enabled
        self.prefix     = prefix
        self._paths: Dict[str, str] = {}

        if enabled:
            self.output_dir = Path(output_dir or _DEFAULT_OUTPUT_DIR) / prefix
            self.output_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Debug image output enabled", path=str(self.output_dir))

    @property
    def paths(self) -> Dict[str, str]:
        """Return a copy of the written-file path map."""
        return dict(self._paths)

    # ── Core Writer ───────────────────────────────────────────────────────────

    def write(self, name: str, image: np.ndarray) -> Optional[str]:
        """
        Save image to the debug output directory as {name}.png.

        Args:
            name:  Filename without extension (e.g. "01_original").
            image: NumPy array, BGR or grayscale.

        Returns:
            Absolute path to the saved file, or None if disabled/failed.
        """
        if not self.enabled or image is None:
            return None
        path = str(self.output_dir / f"{name}.png")
        try:
            cv2.imwrite(path, image)
            self._paths[name] = path
            logger.debug("Debug image saved", name=name)
            return path
        except Exception as exc:
            logger.warning("Failed to save debug image", name=name, error=str(exc))
            return None

    # ── Annotated Writers ─────────────────────────────────────────────────────

    def write_colored_components(
        self,
        name:         str,
        labels:       np.ndarray,
        num_labels:   int,
        accepted_ids: Optional[List[int]] = None,
    ) -> Optional[str]:
        """
        Draw CCA components: accepted=green, rejected=dark red.
        """
        if not self.enabled:
            return None

        h, w = labels.shape[:2]
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        accepted_set = set(accepted_ids or [])

        for label_id in range(1, num_labels):
            mask = labels == label_id
            if label_id in accepted_set:
                canvas[mask] = (0, 200, 80)
            else:
                canvas[mask] = (50, 50, 180)

        return self.write(name, canvas)

    def write_labeled_rooms(
        self,
        name:        str,
        base_image:  np.ndarray,
        rooms,                    # List[RoomPolygon]
        color:       tuple = (0, 200, 100),
        label_color: tuple = (255, 255, 0),
    ) -> Optional[str]:
        """
        Draw room polygon outlines, centroids, and labels on a copy of base_image.
        """
        if not self.enabled or base_image is None:
            return None

        canvas = (
            cv2.cvtColor(base_image, cv2.COLOR_GRAY2BGR)
            if len(base_image.shape) == 2
            else base_image.copy()
        )

        for room in rooms:
            pts = np.array(
                [[int(p.x), int(p.y)] for p in room.polygon], dtype=np.int32
            )
            cv2.polylines(canvas, [pts], isClosed=True, color=color, thickness=2)
            cx, cy = int(room.centroid.x), int(room.centroid.y)
            cv2.circle(canvas, (cx, cy), 4, (0, 100, 255), -1)
            label = room.label or room.id
            cv2.putText(
                canvas, label, (cx + 6, cy - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, label_color, 1, cv2.LINE_AA,
            )

        return self.write(name, canvas)

    def write_ocr_detections(
        self,
        name:       str,
        base_image: np.ndarray,
        texts,                 # List[TextDetection]
    ) -> Optional[str]:
        """Draw OCR bounding boxes and text strings on base_image."""
        if not self.enabled or base_image is None:
            return None

        canvas = (
            cv2.cvtColor(base_image, cv2.COLOR_GRAY2BGR)
            if len(base_image.shape) == 2
            else base_image.copy()
        )

        for td in texts:
            pts = np.array(
                [[int(p.x), int(p.y)] for p in td.bbox], dtype=np.int32
            )
            # Orange if assigned to a room, red if unassigned
            color = (0, 165, 255) if td.associated_room_id else (80, 80, 220)
            cv2.polylines(canvas, [pts], isClosed=True, color=color, thickness=1)
            cx, cy = int(td.center.x), int(td.center.y)
            cv2.putText(
                canvas, td.text, (cx, cy - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA,
            )

        return self.write(name, canvas)

    def write_merged_fragments(
        self,
        name:          str,
        base_image:    np.ndarray,
        raw_texts,                  # List[TextDetection] — before merging
        merged_texts,               # List[TextDetection] — after merging
    ) -> Optional[str]:
        """
        Visualise the result of OCR fragment merging.

        - Raw bounding boxes drawn in faint grey (show what OCR originally found).
        - Merged bounding boxes drawn in:
            GREEN  — merged from 2+ fragments
            BLUE   — single unmerged fragment (passed through)
        - Merged text label drawn above the merged bbox.
        """
        if not self.enabled or base_image is None:
            return None

        canvas = (
            cv2.cvtColor(base_image, cv2.COLOR_GRAY2BGR)
            if len(base_image.shape) == 2
            else base_image.copy()
        )

        # Draw raw detections in faint grey
        for td in raw_texts:
            pts = np.array([[int(p.x), int(p.y)] for p in td.bbox], dtype=np.int32)
            cv2.polylines(canvas, [pts], isClosed=True, color=(120, 120, 120), thickness=1)

        # Draw merged groups
        for td in merged_texts:
            pts = np.array([[int(p.x), int(p.y)] for p in td.bbox], dtype=np.int32)
            is_merged = getattr(td, "fragment_count", 1) > 1
            color = (0, 210, 90) if is_merged else (200, 120, 40)  # green / blue-orange
            thickness = 2 if is_merged else 1
            cv2.polylines(canvas, [pts], isClosed=True, color=color, thickness=thickness)
            cx, cy = int(td.center.x), int(td.center.y)
            label = f"[{td.fragment_count}] {td.text}" if is_merged else td.text
            cv2.putText(
                canvas, label, (cx, cy - 7),
                cv2.FONT_HERSHEY_SIMPLEX, 0.36, color, 1, cv2.LINE_AA,
            )

        return self.write(name, canvas)

    def write_labeled_nodes(
        self,
        name:       str,
        base_image: np.ndarray,
        nodes,                   # List[AiNode]
    ) -> Optional[str]:
        """
        Draw node positions and labels on base_image.

        Colour coding by AiNodeSource:
          Cyan   (255, 255,   0) — OCR_PRIMARY          (primary OCR-first node)
          Blue   (255,  80,  80) — ROOM_DETECTION_OCR   (room polygon + OCR label)
          Grey   (160, 160, 160) — ROOM_DETECTION       (gap-fill, Unknown Room)
        """
        if not self.enabled or base_image is None:
            return None

        canvas = (
            cv2.cvtColor(base_image, cv2.COLOR_GRAY2BGR)
            if len(base_image.shape) == 2
            else base_image.copy()
        )

        # BGR colours keyed by ai_source value string
        _SOURCE_COLORS = {
            "ocr_primary":        (255, 255,   0),   # Cyan
            "room_detection+ocr": (255,  80,  80),   # Blue
            "room_detection":     (160, 160, 160),   # Grey
        }
        _DEFAULT_COLOR = (0, 0, 220)

        for node in nodes:
            cx, cy = int(node.x), int(node.y)
            source_val  = getattr(node.ai_source, "value", str(node.ai_source))
            node_color  = _SOURCE_COLORS.get(source_val, _DEFAULT_COLOR)

            cv2.circle(canvas, (cx, cy), 8, node_color, -1)
            cv2.circle(canvas, (cx, cy), 11, (255, 255, 255), 2)  # white ring
            cv2.putText(
                canvas, node.room_label, (cx + 13, cy + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, node_color, 1, cv2.LINE_AA,
            )

        return self.write(name, canvas)


# ─────────────────────────────────────────────────────────────────────────────
# CLI Entry Point (Developer Tool)
# ─────────────────────────────────────────────────────────────────────────────

def _cli_main() -> None:
    """
    Developer CLI tool: annotate a floorplan image with an AI analysis result.

    Usage:
        python -m src.utils.debug_images --image fp.jpg --analysis result.json

    Run with --help for full argument list.
    """
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m src.utils.debug_images",
        description=(
            "Annotate a floorplan image with the results of a FloorplanAnalysisResult JSON.\n"
            "Useful for manually inspecting AI node and room detection output."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Annotate nodes and rooms from an analysis result
  python -m src.utils.debug_images --image fp.jpg --analysis result.json

  # Only render node overlay, save to custom output folder
  python -m src.utils.debug_images --image fp.jpg --analysis result.json \\
      --output debug_output/my_test/ --overlays nodes

  # Render all overlays
  python -m src.utils.debug_images --image fp.jpg --analysis result.json \\
      --overlays all
""",
    )
    parser.add_argument("--image",    required=True, help="Path to floorplan image (JPEG, PNG, etc.)")
    parser.add_argument("--analysis", required=True, help="Path to FloorplanAnalysisResult JSON file")
    parser.add_argument("--output",   default="debug_output/manual_cli", help="Output directory (default: debug_output/manual_cli)")
    parser.add_argument(
        "--overlays",
        nargs="+",
        choices=["nodes", "rooms", "all"],
        default=["all"],
        help="Which overlays to render: nodes, rooms, or all (default: all)",
    )
    args = parser.parse_args()

    # Validate inputs
    image_path = Path(args.image)
    analysis_path = Path(args.analysis)

    if not image_path.exists():
        print(f"ERROR: Image file not found: {image_path}", file=sys.stderr)
        sys.exit(1)
    if not analysis_path.exists():
        print(f"ERROR: Analysis JSON file not found: {analysis_path}", file=sys.stderr)
        sys.exit(1)

    # Load image
    img_bgr = cv2.imread(str(image_path))
    if img_bgr is None:
        print(f"ERROR: Could not read image: {image_path}", file=sys.stderr)
        sys.exit(1)

    # Load analysis JSON
    with analysis_path.open("r", encoding="utf-8") as f:
        analysis_data = json.load(f)

    # Build a simple prefix from the image stem
    prefix = image_path.stem
    writer = DebugImageWriter(prefix=prefix, enabled=True, output_dir=args.output)

    do_nodes = "all" in args.overlays or "nodes" in args.overlays
    do_rooms = "all" in args.overlays or "rooms" in args.overlays

    # ── Render nodes overlay ──────────────────────────────────────────────────
    if do_nodes and "nodes" in analysis_data:
        canvas = img_bgr.copy()
        _SOURCE_COLORS = {
            "ocr_primary":        (255, 255,   0),
            "room_detection+ocr": (255,  80,  80),
            "room_detection":     (160, 160, 160),
        }
        for node in analysis_data["nodes"]:
            cx, cy = int(node.get("x", 0)), int(node.get("y", 0))
            source = str(node.get("ai_source", "")).lower()
            color = _SOURCE_COLORS.get(source, (0, 0, 220))
            label = node.get("room_label", "?")
            node_type = node.get("node_type", "")
            review = node.get("review_status", "PENDING")
            # Use orange ring for FLAGGED nodes
            ring_color = (0, 140, 255) if review == "FLAGGED" else (255, 255, 255)
            cv2.circle(canvas, (cx, cy), 9, color, -1)
            cv2.circle(canvas, (cx, cy), 12, ring_color, 2)
            cv2.putText(canvas, f"{label} [{node_type}]", (cx + 14, cy + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)
        saved = writer.write("nodes_overlay", canvas)
        print(f"[OK] Nodes overlay saved: {saved}")

    # ── Render rooms overlay ──────────────────────────────────────────────────
    if do_rooms and "rooms" in analysis_data:
        canvas = img_bgr.copy()
        for room in analysis_data["rooms"]:
            polygon = room.get("polygon", [])
            if len(polygon) >= 3:
                pts = np.array([[int(p["x"]), int(p["y"])] for p in polygon], dtype=np.int32)
                cv2.polylines(canvas, [pts], isClosed=True, color=(0, 200, 100), thickness=2)
            centroid = room.get("centroid", {})
            cx, cy = int(centroid.get("x", 0)), int(centroid.get("y", 0))
            label = room.get("label") or room.get("id", "?")
            cv2.circle(canvas, (cx, cy), 4, (0, 100, 255), -1)
            cv2.putText(canvas, label, (cx + 6, cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1, cv2.LINE_AA)
        saved = writer.write("rooms_overlay", canvas)
        print(f"[OK] Rooms overlay saved: {saved}")

    print(f"\nDone. All images written to: {Path(args.output) / prefix}/")


if __name__ == "__main__":
    _cli_main()
