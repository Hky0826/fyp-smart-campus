"""
tests/manual_test_floorplan.py
-------------------------------
Developer manual testing script for the AI floorplan analysis pipeline.

This script runs the full Phase 1.5 analysis pipeline on a local floorplan
image and prints a detailed result summary. It is NOT an automated pytest test
and does not get discovered or run by pytest.

Usage:
    python tests/manual_test_floorplan.py --image path/to/floorplan.jpg

    python tests/manual_test_floorplan.py \\
        --image path/to/floorplan.jpg \\
        --sensitivity 110 \\
        --min-room-area 1500 \\
        --min-ocr-confidence 0.55 \\
        --debug \\
        --output debug_output/manual_test/

Run with --help for all options.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── Ensure the project root is on sys.path ────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def run_analysis(args: argparse.Namespace) -> None:
    from src.services.floorplan_analyzer import FloorplanAnalyzerService

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"[ERROR] Image not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  AI Floorplan Analysis — Manual Test Runner")
    print(f"{'='*60}")
    print(f"  Image:             {image_path.name}")
    print(f"  Sensitivity:       {args.sensitivity}")
    print(f"  Min Room Area:     {args.min_room_area} px²")
    print(f"  Min OCR Conf:      {args.min_ocr_confidence}")
    print(f"  Wall Clearance:    {args.wall_clearance} px")
    print(f"  Max AI Width:      {args.max_ai_width}")
    print(f"  Max AI Height:     {args.max_ai_height}")
    print(f"  Debug Mode:        {args.debug}")
    print(f"{'='*60}\n")

    with image_path.open("rb") as f:
        image_bytes = f.read()

    analyzer = FloorplanAnalyzerService()

    print("Running analysis pipeline...")
    result = analyzer.analyze(
        image_bytes=image_bytes,
        sensitivity=args.sensitivity,
        min_room_area_px=args.min_room_area,
        min_ocr_confidence=args.min_ocr_confidence,
        wall_clearance_px=args.wall_clearance,
        max_ai_width=args.max_ai_width,
        max_ai_height=args.max_ai_height,
        debug_mode=args.debug,
        debug_prefix=f"manual_{image_path.stem}",
    )

    print("\n── Results ──────────────────────────────────────────────")
    summary = result.summary
    print(f"  Processing time:       {result.processing_time_ms:.1f} ms")
    print(f"  Pipeline stages:       {result.pipeline_stages_completed}")
    print(f"  Rooms detected:        {summary.rooms_detected}")
    print(f"  Rooms with labels:     {summary.rooms_with_labels}")
    print(f"  Texts detected:        {summary.texts_detected}")
    print(f"  Texts after merge:     {summary.texts_after_merge}")
    print(f"  Nodes generated:       {summary.nodes_generated}")
    print(f"    From OCR:            {summary.nodes_from_ocr}")
    print(f"    From Room Detection: {summary.nodes_from_room_detection}")
    print(f"    Flagged:             {summary.nodes_flagged}")
    print()

    print("── Nodes ────────────────────────────────────────────────")
    if result.nodes:
        for i, node in enumerate(result.nodes):
            flag = " ⚑ FLAGGED" if node.review_status == "FLAGGED" else ""
            print(
                f"  [{i+1:2d}] {node.room_label:<40} "
                f"type={node.node_type:<14} "
                f"src={str(node.ai_source).replace('AiNodeSource.', ''):<20} "
                f"conf={node.ai_confidence:.2f} "
                f"pos=({node.x:.0f},{node.y:.0f})"
                f"{flag}"
            )
    else:
        print("  No nodes generated.")

    print()

    # Optionally save the full JSON result
    if args.output:
        output_path = Path(args.output)
        output_path.mkdir(parents=True, exist_ok=True)
        json_path = output_path / f"{image_path.stem}_result.json"
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=2, default=str)
        print(f"  Full result JSON saved: {json_path}")

    print("\nDone.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python tests/manual_test_floorplan.py",
        description="Manually run the AI floorplan analysis pipeline on a local image.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--image", required=True,
        help="Path to the floorplan image (JPEG, PNG, WEBP, or BMP).",
    )
    parser.add_argument(
        "--sensitivity", type=int, default=120,
        help="Wall detection threshold (0–255). Higher = fewer walls detected.",
    )
    parser.add_argument(
        "--min-room-area", type=int, default=2000,
        help="Minimum room area in AI pixels². Smaller regions are rejected.",
    )
    parser.add_argument(
        "--min-ocr-confidence", type=float, default=0.60,
        help="Minimum PaddleOCR confidence (0.0–1.0).",
    )
    parser.add_argument(
        "--wall-clearance", type=int, default=8,
        help="Minimum clearance (px) from walls for generated node positions.",
    )
    parser.add_argument(
        "--max-ai-width", type=int, default=1200,
        help="Maximum AI analysis image width (aspect-ratio preserved).",
    )
    parser.add_argument(
        "--max-ai-height", type=int, default=900,
        help="Maximum AI analysis image height (aspect-ratio preserved).",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help=(
            "Enable debug image output. Note: also requires ENABLE_DEBUG_IMAGES=true "
            "in the server configuration (.env). Ignored if the server flag is false."
        ),
    )
    parser.add_argument(
        "--output", default=None,
        help="Directory to save the full result JSON. If omitted, only prints to console.",
    )
    args = parser.parse_args()
    run_analysis(args)


if __name__ == "__main__":
    main()
