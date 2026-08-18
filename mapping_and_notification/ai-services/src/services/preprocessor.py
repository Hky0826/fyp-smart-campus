"""
services/preprocessor.py
------------------------
ImagePreprocessorService — converts a raw floorplan image into several
specialized machine-friendly analysis views while preserving the original.

Key design principles:
  1. The original image is never modified or discarded.
  2. The AI analysis image uses a SINGLE uniform scale factor → aspect ratio
     is preserved → morphological operations and area measurements are correct.
  3. Different pipeline stages receive different image representations:
       wall_view  — for WallDetector (emphasises structural lines)
       room_view  — for RoomDetector (closed walkable space)
       ocr_view   — for PaddleOCR   (text contrast optimised)
     One binary threshold image is not appropriate for all tasks.
  4. All debug images are optionally saved to disk when debug_mode=True.

Preprocessing steps (in order):
  1. Load original image
  2. Uniform-scale resize → AI analysis image (aspect-ratio preserved)
  3. Grayscale conversion
  4. Bilateral denoising (edge-preserving, does not blur wall lines)
  5. CLAHE contrast enhancement
  6. Wall view  : adaptive + global threshold merged, CCA noise removal
  7. Room view  : wall view inverted + morphological gap-closing
  8. OCR view   : contrast-enhanced + gentle sharpening kernel
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict

import cv2
import numpy as np

from src.utils.debug_images import DebugImageWriter
from src.utils.image_loader import load_image_from_bytes
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Default Parameters (all configurable per-request)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MAX_AI_WIDTH  = 1200
DEFAULT_MAX_AI_HEIGHT = 900

_BILATERAL_D           = 9
_BILATERAL_SIGMA_COLOR = 75
_BILATERAL_SIGMA_SPACE = 75

_CLAHE_CLIP_LIMIT = 2.0
_CLAHE_TILE_SIZE  = (8, 8)

_ADAPTIVE_BLOCK_SIZE = 15    # Must be odd
_ADAPTIVE_C          = 4

# Gentle sharpening kernel for OCR view
_SHARPEN_KERNEL = np.array(
    [[0, -1, 0],
     [-1, 5, -1],
     [0, -1, 0]], dtype=np.float32
)

# CCA noise removal — remove components smaller than these thresholds
_NOISE_MAX_AREA   = 250
_NOISE_MAX_WIDTH  = 50
_NOISE_MAX_HEIGHT = 50


# ─────────────────────────────────────────────────────────────────────────────
# Output Dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PreprocessedViews:
    """
    All specialized analysis views produced by ImagePreprocessorService.

    All NumPy arrays are at ai_width × ai_height resolution.
    All coordinates are in AI analysis space (not the original or canvas space).
    Use CoordinateTransformer to convert to frontend 800×600 canvas space.
    """

    # ── Source Images ─────────────────────────────────────────────────────────
    original_bgr:      np.ndarray  # Unchanged at AI resolution (BGR)
    grayscale:         np.ndarray  # Simple grayscale
    denoised:          np.ndarray  # Bilateral-filtered grayscale
    contrast_enhanced: np.ndarray  # CLAHE-enhanced grayscale

    # ── Analysis Views ────────────────────────────────────────────────────────
    wall_view:  np.ndarray  # Binary: 255=wall,     0=space — for WallDetector
    room_view:  np.ndarray  # Binary: 255=walkable, 0=wall  — for RoomDetector
    ocr_view:   np.ndarray  # Grayscale, sharpened           — for PaddleOCR

    # ── Dimension Metadata ────────────────────────────────────────────────────
    original_width:   int
    original_height:  int
    ai_width:         int
    ai_height:        int
    ai_uniform_scale: float  # Uniform scale: min(max_w/orig_w, max_h/orig_h)

    # ── Debug ─────────────────────────────────────────────────────────────────
    debug_paths:           Dict[str, str] = field(default_factory=dict)
    preprocessing_time_ms: float          = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class ImagePreprocessorService:
    """
    Converts a raw floorplan image into specialized analysis views.

    Usage:
        service = ImagePreprocessorService()
        views = service.preprocess(
            image_bytes=raw_bytes,
            sensitivity=120,
            room_gap_close_px=25,
            debug_mode=False,
        )
    """

    def preprocess(
        self,
        image_bytes:       bytes,
        max_ai_width:      int   = DEFAULT_MAX_AI_WIDTH,
        max_ai_height:     int   = DEFAULT_MAX_AI_HEIGHT,
        sensitivity:       int   = 120,
        room_gap_close_px: int   = 25,
        debug_mode:        bool  = False,
        debug_prefix:      str   = "unknown",
    ) -> PreprocessedViews:
        """
        Run the full preprocessing pipeline on a raw floorplan image.

        Args:
            image_bytes:       Raw bytes (JPEG/PNG/WEBP/BMP).
            max_ai_width:      Maximum AI analysis width (default 1200).
            max_ai_height:     Maximum AI analysis height (default 900).
            sensitivity:       Wall threshold 0–255 for global thresholding.
            room_gap_close_px: Morphological closing kernel for room view.
            debug_mode:        Save intermediate images to debug_output/.
            debug_prefix:      Subdirectory name within debug_output/.

        Returns:
            PreprocessedViews with all analysis representations.
        """
        t_start = time.perf_counter()
        dbg = DebugImageWriter(prefix=debug_prefix, enabled=debug_mode)

        # ── Step 1: Load ───────────────────────────────────────────────────────
        original_bgr = load_image_from_bytes(image_bytes, convert_to_bgr=True)
        original_height, original_width = original_bgr.shape[:2]

        logger.info(
            "Preprocessing started",
            original=f"{original_width}×{original_height}",
            max_ai=f"{max_ai_width}×{max_ai_height}",
            sensitivity=sensitivity,
            room_gap_close_px=room_gap_close_px,
        )

        # ── Step 2: Aspect-Ratio-Preserving Resize ─────────────────────────────
        ai_scale = min(
            max_ai_width  / original_width,
            max_ai_height / original_height,
        )
        # Never upscale — upscaling adds no information and wastes memory
        ai_scale = min(ai_scale, 1.0)

        ai_width  = max(1, round(original_width  * ai_scale))
        ai_height = max(1, round(original_height * ai_scale))

        if ai_width == original_width and ai_height == original_height:
            ai_bgr = original_bgr
        else:
            ai_bgr = cv2.resize(
                original_bgr, (ai_width, ai_height),
                interpolation=cv2.INTER_AREA,  # Best quality for downscaling
            )

        logger.info(
            "Stage 1A: aspect-ratio-preserving resize",
            original=f"{original_width}×{original_height}",
            ai=f"{ai_width}×{ai_height}",
            uniform_scale=round(ai_scale, 4),
            aspect_ratio_preserved=True,
        )

        dbg.write("01_original", ai_bgr)

        # ── Step 3: Grayscale ──────────────────────────────────────────────────
        gray = cv2.cvtColor(ai_bgr, cv2.COLOR_BGR2GRAY)
        dbg.write("02_grayscale", gray)

        # ── Step 4: Bilateral Denoising ────────────────────────────────────────
        # Bilateral filter preserves sharp wall edges while removing noise
        denoised = cv2.bilateralFilter(
            gray, _BILATERAL_D, _BILATERAL_SIGMA_COLOR, _BILATERAL_SIGMA_SPACE
        )
        dbg.write("03_denoised", denoised)

        # ── Step 5: CLAHE Contrast Enhancement ────────────────────────────────
        clahe = cv2.createCLAHE(
            clipLimit=_CLAHE_CLIP_LIMIT, tileGridSize=_CLAHE_TILE_SIZE
        )
        contrast_enhanced = clahe.apply(denoised)
        dbg.write("04_contrast_enhanced", contrast_enhanced)

        # ── Step 6: Wall View ──────────────────────────────────────────────────
        wall_view = self._build_wall_view(contrast_enhanced, sensitivity, dbg)

        # ── Step 7: Room View ──────────────────────────────────────────────────
        room_view = self._build_room_view(wall_view, room_gap_close_px, dbg)

        # ── Step 8: OCR View ───────────────────────────────────────────────────
        ocr_view = self._build_ocr_view(contrast_enhanced, dbg)

        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
        logger.info("Preprocessing complete", time_ms=elapsed_ms)

        return PreprocessedViews(
            original_bgr=ai_bgr,
            grayscale=gray,
            denoised=denoised,
            contrast_enhanced=contrast_enhanced,
            wall_view=wall_view,
            room_view=room_view,
            ocr_view=ocr_view,
            original_width=original_width,
            original_height=original_height,
            ai_width=ai_width,
            ai_height=ai_height,
            ai_uniform_scale=round(ai_scale, 6),
            debug_paths=dbg.paths,
            preprocessing_time_ms=elapsed_ms,
        )

    # ── Private Builders ──────────────────────────────────────────────────────

    @staticmethod
    def _build_wall_view(
        contrast_enhanced: np.ndarray,
        sensitivity: int,
        dbg: DebugImageWriter,
    ) -> np.ndarray:
        """
        Build the wall analysis view: binary 255=wall, 0=space.

        Combines global thresholding (mirrors existing WallDetector logic) with
        adaptive thresholding (handles uneven brightness in scanned floorplans).
        The union of both captures walls detected by either method.
        CCA noise removal then strips small components (labels, symbols, dots).
        """
        # Global threshold (fast, works well for clean digital floorplans)
        _, global_thresh = cv2.threshold(
            contrast_enhanced, sensitivity, 255, cv2.THRESH_BINARY_INV
        )

        # Adaptive threshold (works better for scans with uneven illumination)
        adaptive_thresh = cv2.adaptiveThreshold(
            contrast_enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            _ADAPTIVE_BLOCK_SIZE,
            _ADAPTIVE_C,
        )

        # Union: a pixel is a wall if EITHER method detected it
        merged = cv2.bitwise_or(global_thresh, adaptive_thresh)

        # Remove small noise components (text characters, symbols, scan artefacts)
        wall_view = ImagePreprocessorService._remove_small_components(merged)

        dbg.write("05_wall_view", wall_view)
        return wall_view

    @staticmethod
    def _build_room_view(
        wall_view: np.ndarray,
        room_gap_close_px: int,
        dbg: DebugImageWriter,
    ) -> np.ndarray:
        """
        Build the room analysis view: binary 255=enclosed walkable space, 0=wall.

        Strategy:
          1. Dilate the wall mask to thicken wall lines and close narrow door/entrance gaps.
             We work on the wall mask (255=wall) so dilation expands wall pixels,
             bridging small gaps between wall segments.
          2. Invert the thickened wall mask: enclosed rooms become white (255),
             walls and exterior become black (0).
          3. Use a two-pass approach:
             - Pass 1: small dilation (3–5px) to close genuine wall gaps
             - Pass 2: close any remaining tiny noise holes in the room regions

        This is more controlled than closing the walkable space because:
          - Wall lines are thin → small kernels are sufficient
          - Closing walkable space with a large kernel merges rooms into one blob
          - Dilating walls with a small kernel reliably bridges door gaps only

        Args:
            wall_view:         Binary 255=wall, 0=space (from _build_wall_view).
            room_gap_close_px: Target gap size to bridge (converted to kernel size).
            dbg:               Debug image writer.
        """
        # Clamp kernel to reasonable range: dilation kernel for walls needs to be
        # smaller than for walkable-space closing. A 5–15px wall-dilation kernel
        # is usually sufficient to bridge door gaps (typical gap = 2–8px).
        # We halve the user-requested gap close value as a heuristic, min 5px.
        wall_dilation_ksize = max(5, min(room_gap_close_px // 2, 20))

        # Step 1: Dilate wall mask to close gaps
        gap_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (wall_dilation_ksize, wall_dilation_ksize)
        )
        thickened_walls = cv2.dilate(wall_view, gap_kernel, iterations=1)

        # Step 2: Invert → enclosed rooms become white, exterior+walls become black
        room_view = cv2.bitwise_not(thickened_walls)

        # Step 3: Light erosion to clean up noise pixels at room boundaries
        clean_kernel = np.ones((3, 3), dtype=np.uint8)
        room_view = cv2.morphologyEx(room_view, cv2.MORPH_OPEN, clean_kernel)

        dbg.write("06_room_view", room_view)
        return room_view


    @staticmethod
    def _build_ocr_view(
        contrast_enhanced: np.ndarray,
        dbg: DebugImageWriter,
    ) -> np.ndarray:
        """
        Build the OCR analysis view: sharpened grayscale optimized for text.

        Uses contrast-enhanced grayscale with a gentle sharpening kernel to
        make text stroke edges more pronounced. PaddleOCR accepts grayscale.
        """
        sharpened = cv2.filter2D(contrast_enhanced, ddepth=-1, kernel=_SHARPEN_KERNEL)
        ocr_view  = np.clip(sharpened, 0, 255).astype(np.uint8)

        dbg.write("07_ocr_view", ocr_view)
        return ocr_view

    @staticmethod
    def _remove_small_components(binary_mask: np.ndarray) -> np.ndarray:
        """
        Remove small connected components from a binary mask.

        Components with area < _NOISE_MAX_AREA AND width < _NOISE_MAX_WIDTH
        AND height < _NOISE_MAX_HEIGHT are treated as noise (room labels, dots,
        small symbols) and erased. This mirrors WallDetector._remove_noise_components.
        """
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            binary_mask, connectivity=8, ltype=cv2.CV_32S
        )
        cleaned = binary_mask.copy()
        for i in range(1, num_labels):
            area   = int(stats[i, cv2.CC_STAT_AREA])
            width  = int(stats[i, cv2.CC_STAT_WIDTH])
            height = int(stats[i, cv2.CC_STAT_HEIGHT])
            if area < _NOISE_MAX_AREA and width < _NOISE_MAX_WIDTH and height < _NOISE_MAX_HEIGHT:
                cleaned[labels == i] = 0
        return cleaned
