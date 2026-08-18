"""
services/floorplan_analyzer.py
-------------------------------
FloorplanAnalyzerService — orchestrates the Phase 1.5 OCR-first AI pipeline.

Phase 1.5 pipeline (8 stages):

  Stage 1A — ImagePreprocessorService
    Aspect-ratio-preserving resize to AI space. Produces wall_view, room_view,
    ocr_view. Optionally saves debug images.

  Stage 1B — WallDetector.detect_from_view()
    Runs on wall_view at AI resolution. Returns wall_mask and WallGrid.

  Stage 1C — OcrDetector.detect_text()
    Runs PaddleOCR on ocr_view. Returns raw TextDetection list in AI space.

  Stage 1D — OcrFragmentMerger.merge()
    Clusters nearby multi-line OCR fragments (e.g. "Commercial" + "Training"
    + "Kitchen") into single merged labels. Returns merged TextDetection list.

  Stage 1E — OcrNodeGenerator.generate()    ← PRIMARY node generation
    Generates one AiNode per meaningful merged label using:
      • Distance-transform wall clearance (avoids placing nodes on walls).
      • Semantic room type classification (CLASSROOM, OFFICE, WASHROOM, …).
      • Source = AiNodeSource.OCR_PRIMARY.
    Does NOT depend on room detection — nodes are created for all visible text.

  Stage 1F — RoomDetector.detect()           ← VALIDATION + GAP-FILL
    Detects room polygons from room_view. Used for two purposes:
      a) Validate OCR nodes — boost confidence of nodes inside room polygons.
      b) Gap-fill — generate "Unknown Room" nodes for detected rooms with no
         nearby OCR node (admin renames them later).
    OcrDetector.associate_labels_to_rooms() also runs here (for room metadata).

  Stage 1F deduplication — _deduplicate_nodes()
    Merges OCR-primary nodes and room-detection gap-fill nodes.
    OCR node wins when a room node is within threshold_px in AI space.

  Stage 1G — CoordinateTransformer
    Converts all AI-space node/room/text coordinates to 800×600 canvas space.
    This is the ONLY place coordinate conversion happens.

  Stage 1H — Assemble and return FloorplanAnalysisResult
    All coordinates are in canvas space at this point.

Coordinate System:
  All detection runs in AI analysis space (aspect-ratio preserved).
  Only the final output (Stage 1G onward) is in 800×600 canvas space.
"""

from __future__ import annotations

import math
import time
from typing import List, Optional

from src.modules.node_generation.generator import NodeGenerator
from src.modules.node_generation.ocr_node_generator import OcrNodeGenerator
from src.modules.ocr.detector import OcrDetector
from src.modules.ocr.ocr_merger import OcrFragmentMerger
from src.modules.room_detection.detector import RoomDetector
from src.modules.wall_detection.detector import WallDetector
from src.modules.validation.node_validator import NodeValidator
from src.services.preprocessor import ImagePreprocessorService
from src.shared.models.v1.domain import (
    AiNode,
    AiNodeSource,
    AnalysisSummary,
    FloorplanAnalysisResult,
    ImageMetadata,
    WallGrid,
)
from src.utils.coord_transform import CoordinateTransformer
from src.utils.debug_images import DebugImageWriter
from src.utils.logging_config import get_logger
from src.config_settings import settings  # noqa: E402 — settings singleton

logger = get_logger(__name__)


class FloorplanAnalyzerService:
    """
    Orchestrates the Phase 1.5 OCR-first floorplan analysis pipeline.

    All sub-components are stateless and reusable across requests.
    They are held as instance attributes to avoid re-instantiation overhead.
    """

    def __init__(self) -> None:
        self._preprocessor     = ImagePreprocessorService()
        self._wall_detector    = WallDetector()
        self._ocr_detector     = OcrDetector()
        self._ocr_merger       = OcrFragmentMerger()
        self._ocr_node_gen     = OcrNodeGenerator()
        self._room_detector    = RoomDetector()
        self._node_generator   = NodeGenerator()
        self._validator        = NodeValidator()

    def analyze(
        self,
        image_bytes:          bytes,
        canvas_width:         int   = 800,
        canvas_height:        int   = 600,
        sensitivity:          int   = 120,
        grid_scale:           int   = 8,
        room_gap_close_px:    int   = 25,
        min_room_area_px:     int   = 1500,
        max_room_area_ratio:  float = 0.35,
        min_ocr_confidence:   float = 0.60,
        wall_clearance_px:    int   = 8,
        ocr_search_radius_px: int   = 80,
        dedup_threshold_px:   float = 50.0,
        max_ai_width:         int   = 1200,
        max_ai_height:        int   = 900,
        debug_mode:           bool  = False,
        debug_prefix:         str   = "analysis",
    ) -> FloorplanAnalysisResult:
        """
        Run the full Phase 1.5 OCR-first analysis pipeline on a raw floorplan image.

        Args:
            image_bytes:          Raw image bytes (JPEG/PNG/WEBP/BMP).
            canvas_width:         Frontend canvas width (default 800).
            canvas_height:        Frontend canvas height (default 600).
            sensitivity:          Wall detection threshold 0–255 (default 120).
            grid_scale:           Pixels per WallGrid cell (default 8).
            room_gap_close_px:    Morphological closing kernel for room view.
            min_room_area_px:     Minimum room area in AI pixels² (default 1500).
            max_room_area_ratio:  Max room area fraction of AI image (default 0.35).
            min_ocr_confidence:   Minimum PaddleOCR confidence (default 0.60).
            wall_clearance_px:    Min wall clearance for node positions (default 8).
            ocr_search_radius_px: Search radius (px) when OCR center is on a wall.
            dedup_threshold_px:   Distance (AI px) below which room node is dropped
                                  if an OCR node already exists nearby (default 50).
            max_ai_width:         Max AI analysis width — preserves aspect ratio.
            max_ai_height:        Max AI analysis height — preserves aspect ratio.
            debug_mode:           Save intermediate images to debug_output/.
            debug_prefix:         Subdirectory name for debug output.

        Returns:
            FloorplanAnalysisResult with all coordinates in 800×600 canvas space.
        """
        t_pipeline_start = time.perf_counter()

        logger.info(
            "Phase 1.5 OCR-first pipeline started",
            canvas=f"{canvas_width}×{canvas_height}",
            max_ai=f"{max_ai_width}×{max_ai_height}",
            sensitivity=sensitivity,
            room_gap_close_px=room_gap_close_px,
            dedup_threshold_px=dedup_threshold_px,
            debug_mode=debug_mode,
        )

        # ── Stage 1A: Multi-View Preprocessing ────────────────────────────────
        logger.info("Stage 1A: image preprocessing")
        views = self._preprocessor.preprocess(
            image_bytes=image_bytes,
            max_ai_width=max_ai_width,
            max_ai_height=max_ai_height,
            sensitivity=sensitivity,
            room_gap_close_px=room_gap_close_px,
            debug_mode=debug_mode,
            debug_prefix=debug_prefix,
        )
        logger.info(
            "Stage 1A complete",
            original=f"{views.original_width}×{views.original_height}",
            ai=f"{views.ai_width}×{views.ai_height}",
            uniform_scale=views.ai_uniform_scale,
        )

        # Build debug writer for downstream stages.
        # Gated by the server-side master switch (settings.enable_debug_images).
        # Even if the client requests debug_mode=True, images are skipped in
        # production when ENABLE_DEBUG_IMAGES=false.
        effective_debug = debug_mode and settings.enable_debug_images
        dbg = DebugImageWriter(prefix=debug_prefix, enabled=effective_debug)

        # ── Stage 1B: Wall Detection ───────────────────────────────────────────
        logger.info("Stage 1B: wall detection")
        wall_result = self._wall_detector.detect_from_view(
            wall_view=views.wall_view,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            grid_scale=grid_scale,
        )
        logger.info(
            "Stage 1B complete",
            wall_ratio=wall_result.wall_ratio,
            wall_cells=wall_result.wall_cell_count,
        )
        dbg.write("05b_wall_mask_dilated", wall_result.wall_mask)

        # ── Stage 1C: OCR Text Detection ───────────────────────────────────────
        logger.info("Stage 1C: OCR text detection")
        raw_texts_ai = self._ocr_detector.detect_text(
            ocr_view=views.ocr_view,
            min_confidence=min_ocr_confidence,
        )
        dbg.write_ocr_detections("10_ocr_raw_detections", views.original_bgr, raw_texts_ai)
        logger.info("Stage 1C complete", raw_texts_detected=len(raw_texts_ai))

        # ── Stage 1D: OCR Fragment Merging ─────────────────────────────────────
        logger.info("Stage 1D: OCR fragment merging")
        merged_texts_ai = self._ocr_merger.merge(raw_texts_ai)
        dbg.write_merged_fragments("10b_ocr_merged", views.original_bgr, raw_texts_ai, merged_texts_ai)
        logger.info(
            "Stage 1D complete",
            raw_count=len(raw_texts_ai),
            merged_count=len(merged_texts_ai),
        )

        # ── Stage 1E: OCR-First Node Generation ───────────────────────────────
        logger.info("Stage 1E: OCR-first node generation (primary)")
        ocr_nodes_ai = self._ocr_node_gen.generate(
            merged_texts=merged_texts_ai,
            wall_mask=wall_result.wall_mask,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
            wall_clearance_px=wall_clearance_px,
            search_radius_px=ocr_search_radius_px,
        )
        logger.info("Stage 1E complete", ocr_nodes_generated=len(ocr_nodes_ai))

        # ── Stage 1F: Room Detection (Validation + Gap-Fill) ──────────────────
        logger.info("Stage 1F: room detection (validation + gap-fill)")

        rooms_ai = self._room_detector.detect(
            room_view=views.room_view,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
            min_room_area_px=min_room_area_px,
            max_room_area_ratio=max_room_area_ratio,
            debug_writer=dbg,
            original_bgr=views.original_bgr,
        )
        logger.info("Stage 1F (room detection) complete", rooms_detected=len(rooms_ai))

        # 1F-a: Validate OCR nodes against detected room polygons (confidence boost)
        ocr_nodes_ai = self._ocr_node_gen.validate_against_rooms(
            nodes=ocr_nodes_ai,
            rooms=rooms_ai,
        )

        # 1F-b: Associate merged labels to rooms (for room metadata / gap-fill)
        merged_texts_ai, rooms_ai = self._ocr_detector.associate_labels_to_rooms(
            texts=merged_texts_ai,
            rooms=rooms_ai,
        )
        dbg.write_labeled_rooms("11_room_label_associations", views.original_bgr, rooms_ai)

        # 1F-c: Generate gap-fill nodes for rooms with no nearby OCR node
        room_nodes_ai = self._node_generator.generate(
            rooms=rooms_ai,
            wall_mask=wall_result.wall_mask,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
            wall_clearance_px=wall_clearance_px,
        )

        # 1F-d: Deduplicate — Semantic, Priority, and Spatial (3 passes)
        all_nodes_ai = _deduplicate_nodes_v2(
            ocr_nodes=ocr_nodes_ai,
            room_nodes=room_nodes_ai,
            threshold_px=dedup_threshold_px,
        )

        n_from_ocr  = sum(1 for n in all_nodes_ai if n.ai_source == AiNodeSource.OCR_PRIMARY)
        n_from_room = len(all_nodes_ai) - n_from_ocr

        logger.info(
            "Stage 1G complete (Semantic Deduplication)",
            total_nodes=len(all_nodes_ai),
            from_ocr=n_from_ocr,
            from_room_detection=n_from_room,
        )

        # ── Stage 1H: Node Validation (Hard/Soft Checks & Recovery) ───────────
        logger.info("Stage 1H: node validation")
        all_nodes_ai, val_stats = self._validator.validate(
            nodes=all_nodes_ai,
            wall_mask=wall_result.wall_mask,
            rooms=rooms_ai,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
        )

        # Write combined debug image with all valid nodes
        dbg.write_labeled_nodes("12_nodes_final", views.original_bgr, all_nodes_ai)

        # ── Stage 1I: Coordinate Transformation: AI space → 800×600 canvas ────
        transformer = CoordinateTransformer(
            original_width=views.original_width,
            original_height=views.original_height,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )
        nodes_canvas  = transformer.transform_nodes(all_nodes_ai)
        rooms_canvas  = transformer.transform_rooms(rooms_ai)
        texts_canvas  = transformer.transform_texts(merged_texts_ai)

        logger.info(
            "Stage 1G: coordinate transformation applied",
            ai=f"{views.ai_width}×{views.ai_height}",
            canvas=f"{canvas_width}×{canvas_height}",
            scale_x=round(transformer.canvas_scale_x, 4),
            scale_y=round(transformer.canvas_scale_y, 4),
        )

        # ── Stage 1H: Assemble Result ──────────────────────────────────────────
        total_ms = round((time.perf_counter() - t_pipeline_start) * 1000, 2)

        summary = AnalysisSummary(
            rooms_detected=len(rooms_canvas),
            rooms_with_labels=sum(1 for r in rooms_canvas if r.label is not None),
            rooms_without_labels=sum(1 for r in rooms_canvas if r.label is None),
            nodes_generated=len(nodes_canvas),
            nodes_from_ocr=n_from_ocr,
            nodes_from_room_detection=n_from_room,
            nodes_flagged=val_stats["flagged"],
            texts_detected=len(raw_texts_ai),
            texts_after_merge=len(merged_texts_ai),
        )

        image_meta = ImageMetadata(
            original_width=views.original_width,
            original_height=views.original_height,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            channels=views.original_bgr.shape[2] if len(views.original_bgr.shape) > 2 else 1,
            format="JPEG",
            aspect_ratio=round(
                views.original_width / views.original_height, 4
            ) if views.original_height > 0 else 1.0,
            scale_x=round(canvas_width  / views.original_width,  6),
            scale_y=round(canvas_height / views.original_height, 6),
            ai_width=views.ai_width,
            ai_height=views.ai_height,
            ai_uniform_scale=views.ai_uniform_scale,
            canvas_scale_x=round(transformer.canvas_scale_x, 6),
            canvas_scale_y=round(transformer.canvas_scale_y, 6),
        )

        canvas_wall_grid = WallGrid(
            grid=wall_result.wall_grid.grid,
            grid_width=wall_result.wall_grid.grid_width,
            grid_height=wall_result.wall_grid.grid_height,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            grid_scale=grid_scale,
        )

        logger.info(
            "Phase 1.5 pipeline completed",
            total_ms=total_ms,
            ocr_nodes=n_from_ocr,
            gap_fill_nodes=n_from_room,
            total_nodes=len(nodes_canvas),
            texts_raw=len(raw_texts_ai),
            texts_merged=len(merged_texts_ai),
            rooms=len(rooms_canvas),
        )

        all_debug_paths = {**views.debug_paths, **dbg.paths} if debug_mode else None

        return FloorplanAnalysisResult(
            status="success",
            processing_time_ms=total_ms,
            pipeline_stages_completed=10,
            image=image_meta,
            wall_grid=canvas_wall_grid,
            rooms=rooms_canvas,
            text_detections=texts_canvas,
            nodes=nodes_canvas,
            summary=summary,
            debug_image_paths=all_debug_paths,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication helper
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_label(label: str) -> str:
    import string
    import re
    s = str(label).lower()
    s = s.translate(str.maketrans('', '', string.punctuation))
    return re.sub(r'\s+', ' ', s).strip()

def _deduplicate_nodes_v2(
    ocr_nodes:    List[AiNode],
    room_nodes:   List[AiNode],
    threshold_px: float = 50.0,
) -> List[AiNode]:
    """
    Merge OCR-primary nodes and room-detection gap-fill nodes using semantic
    deduplication (One Room = One Node).

    Pass 1 & 2: Group by normalized label and keep the highest priority source.
    Priority: OCR_PRIMARY > ROOM_DETECTION_OCR > ROOM_DETECTION.

    Pass 3: Spatial clustering. If nodes still share the same label and are within
    threshold_px, keep the one with the highest confidence.

    Args:
        ocr_nodes:    Nodes from OcrNodeGenerator (source = OCR_PRIMARY).
        room_nodes:   Nodes from NodeGenerator (source = ROOM_DETECTION / ROOM_DETECTION_OCR).
        threshold_px: Spatial proximity threshold.

    Returns:
        List of semantically deduplicated nodes.
    """
    all_candidates = ocr_nodes + room_nodes
    if not all_candidates:
        return []

    source_priority = {
        AiNodeSource.OCR_PRIMARY: 3,
        AiNodeSource.ROOM_DETECTION_OCR: 2,
        AiNodeSource.ROOM_DETECTION: 1,
    }

    # Pass 1 & 2: Group by label and source priority
    # For nodes with identical normalized labels, if they have different sources,
    # we only keep the ones from the highest priority source.
    label_groups = {}
    for node in all_candidates:
        norm_label = _normalize_label(node.room_label)
        # We group "Unknown Room" (empty/generic) separately using their instance ID so they don't deduplicate against each other
        if norm_label == "unknown room" or not norm_label:
            norm_label = f"unknown_{id(node)}"
        label_groups.setdefault(norm_label, []).append(node)

    filtered_candidates = []
    for norm_label, group in label_groups.items():
        if norm_label.startswith("unknown_") or len(group) == 1:
            filtered_candidates.extend(group)
            continue
            
        # Find max priority
        max_priority = max(source_priority.get(n.ai_source, 0) for n in group)
        highest_priority_nodes = [n for n in group if source_priority.get(n.ai_source, 0) == max_priority]
        filtered_candidates.extend(highest_priority_nodes)

    # Pass 3: Spatial clustering for remaining identical labels
    final_nodes = []
    spatial_groups = {}
    for node in filtered_candidates:
        norm_label = _normalize_label(node.room_label)
        if norm_label == "unknown room" or not norm_label:
            final_nodes.append(node)
            continue
            
        # Find if it belongs to an existing spatial cluster for this label
        placed = False
        if norm_label in spatial_groups:
            for cluster in spatial_groups[norm_label]:
                rep_node = cluster[0]
                if math.hypot(rep_node.x - node.x, rep_node.y - node.y) < threshold_px:
                    cluster.append(node)
                    placed = True
                    break
        if not placed:
            spatial_groups.setdefault(norm_label, []).append([node])
            
    # Resolve clusters
    for norm_label, clusters in spatial_groups.items():
        for cluster in clusters:
            if len(cluster) == 1:
                final_nodes.append(cluster[0])
            else:
                # Rank by confidence, keep best
                best_node = max(cluster, key=lambda n: n.ai_confidence)
                final_nodes.append(best_node)

    logger.info(
        "Stage 1G: Semantic Deduplication complete",
        input_nodes=len(all_candidates),
        output_nodes=len(final_nodes),
        removed=len(all_candidates) - len(final_nodes),
    )
    return final_nodes
