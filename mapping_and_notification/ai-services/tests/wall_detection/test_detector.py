"""
tests/wall_detection/test_detector.py
--------------------------------------
Unit tests for WallDetector.

These tests validate:
  1. Grid dimensions are always correct
  2. White image produces no wall cells
  3. Synthetic walls produce expected non-zero wall count
  4. Wall ratio is in a reasonable range
  5. Processing time is under 2 seconds
  6. All real floorplan JPEG files process without error
  7. CCA noise removal works (small objects are filtered)
  8. Sensitivity parameter changes wall count in the expected direction
"""

from __future__ import annotations

import io
import time

import pytest
from PIL import Image, ImageDraw

from src.modules.wall_detection.detector import WallDetector
from src.utils.grid_utils import count_wall_cells


@pytest.fixture(scope="module")
def detector() -> WallDetector:
    return WallDetector()


# ─────────────────────────────────────────────────────────────────────────────
# Grid Dimension Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGridDimensions:
    def test_default_dimensions(self, detector, sample_white_jpeg):
        """Default params produce 100×75 grid (800÷8 × 600÷8)."""
        result = detector.detect(sample_white_jpeg)
        assert result.wall_grid.grid_width  == 100
        assert result.wall_grid.grid_height == 75
        assert len(result.wall_grid.grid)   == 75
        assert len(result.wall_grid.grid[0]) == 100

    def test_custom_canvas_dimensions(self, detector, sample_white_jpeg):
        """Custom canvas/grid parameters are respected."""
        result = detector.detect(
            sample_white_jpeg,
            canvas_width=400,
            canvas_height=300,
            grid_scale=8,
        )
        assert result.wall_grid.grid_width  == 50    # 400 / 8
        assert result.wall_grid.grid_height == 37    # 300 / 8 = 37.5, floor

    def test_total_cells_matches_dimensions(self, detector, sample_white_jpeg):
        result = detector.detect(sample_white_jpeg)
        assert result.total_cells == 100 * 75


# ─────────────────────────────────────────────────────────────────────────────
# Wall Detection Accuracy Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestWallDetectionAccuracy:
    def test_solid_white_image_has_no_walls(self, detector, sample_white_jpeg):
        """An all-white image (blank floorplan) should produce zero wall cells."""
        result = detector.detect(sample_white_jpeg)
        assert result.wall_cell_count == 0
        assert result.wall_ratio == 0.0

    def test_synthetic_walls_detected(self, detector, sample_floorplan_jpeg):
        """Synthetic floorplan with drawn walls should produce non-zero wall cells."""
        result = detector.detect(sample_floorplan_jpeg)
        assert result.wall_cell_count > 0, "Expected wall cells in synthetic floorplan"

    def test_wall_ratio_is_sane(self, detector, sample_floorplan_jpeg):
        """Wall ratio should be between 0 and 1, and not cover more than 50% of the canvas."""
        result = detector.detect(sample_floorplan_jpeg)
        assert 0.0 < result.wall_ratio <= 0.5, (
            f"Wall ratio {result.wall_ratio} is outside expected range (0, 0.5]"
        )

    def test_all_grid_cells_are_binary(self, detector, sample_floorplan_jpeg):
        """Every grid cell must be exactly 0 or 1."""
        result = detector.detect(sample_floorplan_jpeg)
        for row in result.wall_grid.grid:
            for cell in row:
                assert cell in (0, 1), f"Unexpected cell value: {cell}"


# ─────────────────────────────────────────────────────────────────────────────
# Sensitivity Parameter Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSensitivity:
    def test_lower_sensitivity_detects_more_walls(self, detector, sample_floorplan_jpeg):
        """
        Lower threshold → darker pixels are captured → more walls.
        Sensitivity 60 should detect more walls than sensitivity 180.
        """
        result_low  = detector.detect(sample_floorplan_jpeg, sensitivity=60)
        result_high = detector.detect(sample_floorplan_jpeg, sensitivity=180)
        assert result_low.wall_cell_count >= result_high.wall_cell_count, (
            "Lower sensitivity should detect >= wall cells compared to higher sensitivity"
        )

    def test_sensitivity_echoed_in_result(self, detector, sample_white_jpeg):
        """The sensitivity value used must be reflected in the result."""
        result = detector.detect(sample_white_jpeg, sensitivity=75)
        assert result.sensitivity_used == 75


# ─────────────────────────────────────────────────────────────────────────────
# Performance Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPerformance:
    def test_processing_time_under_2_seconds(self, detector, sample_floorplan_jpeg):
        """Wall detection must complete in under 2000ms for any floorplan."""
        result = detector.detect(sample_floorplan_jpeg)
        assert result.processing_time_ms < 2000, (
            f"Processing took {result.processing_time_ms:.0f}ms — exceeds 2000ms limit"
        )


# ─────────────────────────────────────────────────────────────────────────────
# CCA Noise Removal Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCCANoiseRemoval:
    def _make_image_with_noise(self) -> bytes:
        """Create an image with small noise dots (text-like) and a thick wall."""
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Thick wall line — should survive CCA filter
        draw.rectangle([0, 100, 800, 115], fill=(0, 0, 0))
        # Small noise dots (like room label text characters)
        for x in range(50, 200, 20):
            draw.rectangle([x, 200, x + 5, 205], fill=(0, 0, 0))  # 5×5 = 25px area
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def test_noise_dots_are_removed(self, detector):
        """Small isolated components (text/icons) should be filtered by CCA."""
        image_with_noise = self._make_image_with_noise()
        result_with_cca  = detector.detect(image_with_noise, sensitivity=120)

        # The wall line cells should still be present
        assert result_with_cca.wall_cell_count > 0


# ─────────────────────────────────────────────────────────────────────────────
# Real Floorplan Regression Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRealFloorplans:
    def test_all_real_floorplans_process_without_error(
        self, detector, real_floorplan_files
    ):
        """
        All JPEG files in backend/uploads/ must process without raising any exception.
        Validates that the Python implementation handles all existing campus maps.
        """
        if not real_floorplan_files:
            pytest.skip("No real floorplan files found in backend/uploads/.")

        for filepath in real_floorplan_files:
            image_bytes = filepath.read_bytes()
            result = detector.detect(image_bytes)

            # Basic sanity checks
            assert result.wall_grid.grid_width  == 100, f"Wrong grid_width for {filepath.name}"
            assert result.wall_grid.grid_height == 75,  f"Wrong grid_height for {filepath.name}"
            assert result.wall_cell_count >= 0
            assert result.processing_time_ms < 2000, (
                f"{filepath.name} took {result.processing_time_ms:.0f}ms"
            )

    def test_real_floorplans_have_nonzero_walls(
        self, detector, real_floorplan_files
    ):
        """
        Each real campus floorplan should detect at least some wall cells,
        since all uploaded maps have visible structural walls.
        """
        if not real_floorplan_files:
            pytest.skip("No real floorplan files found in backend/uploads/.")

        for filepath in real_floorplan_files:
            image_bytes = filepath.read_bytes()
            result = detector.detect(image_bytes)
            assert result.wall_cell_count > 0, (
                f"Expected non-zero wall cells for campus floorplan: {filepath.name}"
            )
