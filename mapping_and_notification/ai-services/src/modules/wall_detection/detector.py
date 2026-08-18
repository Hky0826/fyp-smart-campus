"""
wall_detection/detector.py
--------------------------
WallDetector — Python implementation of the campus floorplan wall detection
algorithm, migrated from the browser-side OpenCV.js implementation in
frontend/src/hooks/useOpenCV.js.

Algorithm (identical to the JS version, step-for-step):
  1. Load image bytes → NumPy BGR array
  2. Resize to virtual canvas dimensions (default 800×600)
  3. Convert to greyscale
  4. Apply binary inverse threshold
     Dark walls on light background → white pixels in the mask
  5. Connected Component Analysis (CCA)
     Remove small components (text labels, icons, noise):
       area < 250 px AND width < 50 px AND height < 50 px
  6. Morphological dilation (3×3 kernel, 1 iteration)
     Thickens wall pixels so A* naturally avoids wall edges
  7. Build 2D grid
     Each cell = 8×8 px square; cell = 1 if any pixel is wall

References:
  - useOpenCV.js lines 84–183 (React hook, browser-side original)
  - mapConstants.js: CANVAS_WIDTH=800, CANVAS_HEIGHT=600, GRID_SCALE=8
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import cv2
import numpy as np

from src.shared.domain import WallGrid
from src.utils.grid_utils import build_grid_from_mask, count_wall_cells, grid_dimensions
from src.utils.image_loader import ImageLoadError, load_image_from_bytes, resize_image
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CCA Noise Filter Thresholds (must match useOpenCV.js)
# ─────────────────────────────────────────────────────────────────────────────
_CCA_MAX_AREA   = 250    # Components smaller than this are noise
_CCA_MAX_WIDTH  = 50     # …and narrower than this
_CCA_MAX_HEIGHT = 50     # …and shorter than this


@dataclass
class DetectionResult:
    """
    Container for the wall detection output and associated diagnostics.

    Primary output:
        wall_grid          — 2D binary grid compatible with pathfinding.js (unchanged)

    Extended outputs (used by Phase 1 room detection and node generation):
        wall_mask          — Raw dilated binary mask (uint8 ndarray, 255=wall, 0=space).
                             Operates at full canvas pixel resolution, not grid resolution.
                             Used by room_detection for morphological analysis and by
                             node_generation for centroid validity checking.
        wall_contours      — List of OpenCV contours extracted from the cleaned threshold
                             mask before dilation. Used by room_detection to find enclosed
                             regions and their approximate polygons.
    """

    wall_grid:          WallGrid
    processing_time_ms: float
    wall_cell_count:    int
    total_cells:        int
    sensitivity_used:   int

    # Extended outputs for downstream modules (Phase 1+)
    # These are None when called from the existing /api/v1/wall-detection endpoint
    # so that no breaking change occurs.
    wall_mask:     Optional[np.ndarray] = field(default=None)
    wall_contours: Optional[List[np.ndarray]] = field(default=None)

    @property
    def wall_ratio(self) -> float:
        if self.total_cells == 0:
            return 0.0
        return round(self.wall_cell_count / self.total_cells, 4)


class WallDetector:
    """
    Stateless wall detection processor for campus floorplan images.

    Usage:
        detector = WallDetector()
        result   = detector.detect(image_bytes, sensitivity=120)
        grid     = result.wall_grid.grid   # 2D list compatible with pathfinding.js

    The detector is fully stateless — it creates no persistent state between
    calls and is safe for concurrent use in an async FastAPI context.
    """

    def detect(
        self,
        image_bytes: bytes,
        sensitivity:    int  = 120,
        canvas_width:   int  = 800,
        canvas_height:  int  = 600,
        grid_scale:     int  = 8,
        return_mask:    bool = False,
    ) -> DetectionResult:
        """
        Run wall detection on a raw image and return a binary wall grid.

        Args:
            image_bytes:   Raw bytes of the floorplan image (JPEG / PNG / WEBP).
            sensitivity:   Binary threshold (0–255). Higher → fewer walls detected.
                           Mirrors the wallSensitivity slider in the React editor.
            canvas_width:  Virtual canvas width in pixels (default 800).
            canvas_height: Virtual canvas height in pixels (default 600).
            grid_scale:    Pixels per grid cell (default 8).
            return_mask:   If True, populate `wall_mask` and `wall_contours` on the
                           returned DetectionResult for use by downstream modules
                           (room_detection, node_generation). Defaults to False to
                           preserve zero overhead for the existing wall-detection API.

        Returns:
            DetectionResult containing the WallGrid and diagnostic metrics.
            When return_mask=True, also contains wall_mask (np.ndarray) and
            wall_contours (list of contours).

        Raises:
            ImageLoadError: If the image bytes cannot be decoded.
            RuntimeError:   If OpenCV processing fails.
        """
        t_start = time.perf_counter()

        logger.info(
            "Wall detection started",
            sensitivity=sensitivity,
            canvas=f"{canvas_width}x{canvas_height}",
            grid_scale=grid_scale,
        )

        # ── Step 1: Load image ─────────────────────────────────────────────────
        image = load_image_from_bytes(image_bytes, convert_to_bgr=True)

        # ── Step 2: Resize to virtual canvas ───────────────────────────────────
        # The JS implementation draws the image onto an 800×600 offscreen canvas.
        # We replicate this by resizing here before all subsequent processing.
        image = resize_image(image, canvas_width, canvas_height)

        # ── Step 3: Convert to greyscale ───────────────────────────────────────
        # JS: cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY)
        # Python: image is already BGR from load_image_from_bytes
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # ── Step 4: Binary inverse threshold ──────────────────────────────────
        # Dark wall lines on white background → white pixels (255) in the mask.
        # JS: cv.threshold(gray, thresh, sensitivity, 255, cv.THRESH_BINARY_INV)
        _, thresh = cv2.threshold(
            gray, sensitivity, 255, cv2.THRESH_BINARY_INV
        )

        # ── Step 5: Connected Component Analysis (CCA) — noise removal ────────
        # JS: cv.connectedComponentsWithStats(thresh, labels, stats, centroids, 8, cv.CV_32S)
        # Remove small connected components that represent text, icons, or noise.
        thresh = self._remove_noise_components(thresh)

        # ── Step 5b: Extract contours BEFORE dilation (for room detection) ─────
        # Contours from the un-dilated, noise-cleaned mask trace the actual wall
        # geometry more precisely. Dilation would inflate wall boundaries and make
        # room polygon extraction less accurate.
        contours: Optional[List[np.ndarray]] = None
        if return_mask:
            raw_contours, _ = cv2.findContours(
                thresh, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
            )
            contours = list(raw_contours)

        # ── Step 6: Morphological dilation ─────────────────────────────────────
        # Thickens wall pixels so A* naturally keeps nodes clear of wall edges.
        # JS: kernel = cv.Mat.ones(3, 3, cv.CV_8U); cv.dilate(thresh, dilated, kernel)
        kernel  = np.ones((3, 3), dtype=np.uint8)
        dilated = cv2.dilate(thresh, kernel, iterations=1)

        # ── Step 7: Build 2D binary grid ──────────────────────────────────────
        # Each cell = (grid_scale × grid_scale) px square.
        # Cell = 1 if any pixel within the square is 255 (wall).
        grid_2d = build_grid_from_mask(dilated, canvas_width, canvas_height, grid_scale)

        # ── Assemble result ─────────────────────────────────────────────────────
        gw, gh    = grid_dimensions(canvas_width, canvas_height, grid_scale)
        wall_count = count_wall_cells(grid_2d)
        elapsed_ms = (time.perf_counter() - t_start) * 1000

        logger.info(
            "Wall detection completed",
            grid_size=f"{gw}x{gh}",
            wall_cells=wall_count,
            total_cells=gw * gh,
            wall_ratio=round(wall_count / (gw * gh), 3) if gw * gh > 0 else 0,
            processing_time_ms=round(elapsed_ms, 2),
            return_mask=return_mask,
        )

        wall_grid = WallGrid(
            grid=grid_2d,
            grid_width=gw,
            grid_height=gh,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            grid_scale=grid_scale,
        )

        return DetectionResult(
            wall_grid=wall_grid,
            processing_time_ms=round(elapsed_ms, 2),
            wall_cell_count=wall_count,
            total_cells=gw * gh,
            sensitivity_used=sensitivity,
            wall_mask=dilated if return_mask else None,
            wall_contours=contours,
        )

    @staticmethod
    def _remove_noise_components(thresh: np.ndarray) -> np.ndarray:
        """
        Remove small connected components from the binary mask.

        Mirrors the CCA noise filter in useOpenCV.js (lines 101–132):
          - Components with area < 250 AND width < 50 AND height < 50 are erased.

        These thresholds are calibrated to remove room labels, icons, and
        other small non-structural elements while preserving thick wall lines.

        Args:
            thresh: Binary mask (uint8), 255 = wall, 0 = background.

        Returns:
            Cleaned mask with noise components zeroed out.
        """
        num_components, labels, stats, _ = cv2.connectedComponentsWithStats(
            thresh, connectivity=8, ltype=cv2.CV_32S
        )

        # stats shape: (num_components, 5)
        # Columns: CC_STAT_LEFT, CC_STAT_TOP, CC_STAT_WIDTH, CC_STAT_HEIGHT, CC_STAT_AREA
        # Component 0 is always the background — skip it (range starts at 1).

        noise_mask = np.zeros_like(thresh, dtype=bool)
        for i in range(1, num_components):
            w    = int(stats[i, cv2.CC_STAT_WIDTH])
            h    = int(stats[i, cv2.CC_STAT_HEIGHT])
            area = int(stats[i, cv2.CC_STAT_AREA])

            if area < _CCA_MAX_AREA and w < _CCA_MAX_WIDTH and h < _CCA_MAX_HEIGHT:
                # Mark all pixels of this component for erasure
                noise_mask |= (labels == i)

        # Erase noise components in-place
        cleaned = thresh.copy()
        cleaned[noise_mask] = 0

        removed = int(noise_mask.sum())
        if removed > 0:
            logger.debug(
                "CCA noise removal",
                components_found=num_components - 1,
                pixels_removed=removed,
            )

        return cleaned

    def detect_from_view(
        self,
        wall_view:    np.ndarray,
        ai_width:     int,
        ai_height:    int,
        canvas_width: int = 800,
        canvas_height: int = 600,
        grid_scale:   int = 8,
    ) -> "DetectionResult":
        """
        Run wall detection on a pre-processed wall_view image from ImagePreprocessorService.

        This is the method used by FloorplanAnalyzerService (Phase 1 pipeline).
        It skips the load-from-bytes and canvas-resize steps because the
        ImagePreprocessorService has already done aspect-ratio-preserving resize
        and produced a specialized wall_view binary image.

        The WallGrid is still computed at grid_scale resolution for pathfinding
        compatibility. The wall_mask returned is at ai_width × ai_height resolution
        (AI analysis space) — not 800×600.

        Args:
            wall_view:    Binary image from preprocessor: 255=wall, 0=space.
                          Must already be at ai_width × ai_height resolution.
            ai_width:     Width of the AI analysis image.
            ai_height:    Height of the AI analysis image.
            canvas_width: Frontend canvas width (used only for WallGrid dimensions).
            canvas_height:Frontend canvas height (used only for WallGrid dimensions).
            grid_scale:   Pixels per grid cell (default 8, matches pathfinding.js).

        Returns:
            DetectionResult with wall_mask at AI resolution and WallGrid at grid resolution.
        """
        t_start = time.perf_counter()

        logger.info(
            "Wall detection from preprocessed view",
            ai_size=f"{ai_width}×{ai_height}",
            grid_scale=grid_scale,
        )

        # The wall_view from preprocessor already has CCA noise removal applied.
        # Apply morphological dilation to thicken wall pixels (same as detect()).
        kernel  = np.ones((3, 3), dtype=np.uint8)
        dilated = cv2.dilate(wall_view, kernel, iterations=1)

        # Build the WallGrid at AI-space resolution (not canvas resolution).
        # The grid cell count uses ai_width/ai_height so geometry is correct.
        grid_2d = build_grid_from_mask(dilated, ai_width, ai_height, grid_scale)

        gw, gh     = grid_dimensions(ai_width, ai_height, grid_scale)
        wall_count = count_wall_cells(grid_2d)
        wall_ratio = round(wall_count / (gw * gh), 4) if gw * gh > 0 else 0.0
        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)

        logger.info(
            "Wall detection from view completed",
            grid_size=f"{gw}×{gh}",
            wall_cells=wall_count,
            total_cells=gw * gh,
            wall_ratio=wall_ratio,
            processing_time_ms=elapsed_ms,
        )

        wall_grid = WallGrid(
            grid=grid_2d,
            grid_width=gw,
            grid_height=gh,
            canvas_width=ai_width,    # Grid is in AI space, not canvas space
            canvas_height=ai_height,
            grid_scale=grid_scale,
        )

        return DetectionResult(
            wall_grid=wall_grid,
            processing_time_ms=elapsed_ms,
            wall_cell_count=wall_count,
            total_cells=gw * gh,
            sensitivity_used=0,        # Sensitivity was applied during preprocessing
            wall_mask=dilated,         # Always returned for downstream modules
            wall_contours=None,        # Computed on demand by room detector if needed
        )

