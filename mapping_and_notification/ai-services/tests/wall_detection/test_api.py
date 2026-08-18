"""
tests/wall_detection/test_api.py
----------------------------------
Integration tests for POST /api/v1/wall-detection.

Tests the full HTTP layer: request parsing, validation, response schema,
error handling, and end-to-end correctness using the FastAPI TestClient.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image


# ─────────────────────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_endpoint_returns_ok(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data
        assert "version" in data


# ─────────────────────────────────────────────────────────────────────────────
# Wall Detection — Happy Path
# ─────────────────────────────────────────────────────────────────────────────


class TestWallDetectionSuccess:
    def test_basic_request_returns_200(self, client: TestClient, sample_white_jpeg: bytes):
        """A valid image upload should return HTTP 200."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("test.jpg", sample_white_jpeg, "image/jpeg")},
        )
        assert response.status_code == 200

    def test_response_schema(self, client: TestClient, sample_white_jpeg: bytes):
        """Response must contain all required fields with correct types."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("test.jpg", sample_white_jpeg, "image/jpeg")},
        )
        data = response.json()
        payload = data["data"]

        assert data["status"] == "success"
        assert isinstance(payload["grid"], list)
        assert isinstance(payload["grid_width"], int)
        assert isinstance(payload["grid_height"], int)
        assert isinstance(payload["canvas_width"], int)
        assert isinstance(payload["canvas_height"], int)
        assert isinstance(payload["grid_scale"], int)
        assert isinstance(payload["sensitivity_used"], int)
        assert isinstance(data["processing_time_ms"], float)
        assert isinstance(payload["wall_cell_count"], int)
        assert isinstance(payload["total_cells"], int)
        assert isinstance(payload["wall_ratio"], float)

    def test_default_grid_dimensions(self, client: TestClient, sample_white_jpeg: bytes):
        """Default parameters produce a 100×75 grid."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("test.jpg", sample_white_jpeg, "image/jpeg")},
        )
        data = response.json()
        payload = data["data"]
        assert payload["grid_width"]  == 100
        assert payload["grid_height"] == 75
        assert len(payload["grid"])   == 75
        assert len(payload["grid"][0]) == 100

    def test_white_image_zero_wall_cells(self, client: TestClient, sample_white_jpeg: bytes):
        """All-white image should produce zero wall cells."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("blank.jpg", sample_white_jpeg, "image/jpeg")},
        )
        data = response.json()
        payload = data["data"]
        assert payload["wall_cell_count"] == 0

    def test_synthetic_floorplan_has_walls(self, client: TestClient, sample_floorplan_jpeg: bytes):
        """Synthetic floorplan should produce non-zero wall cells."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("floor.jpg", sample_floorplan_jpeg, "image/jpeg")},
        )
        data = response.json()
        payload = data["data"]
        assert payload["wall_cell_count"] > 0

    def test_custom_sensitivity_parameter(self, client: TestClient, sample_white_jpeg: bytes):
        """Custom sensitivity is echoed back in the response."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("test.jpg", sample_white_jpeg, "image/jpeg")},
            data={"sensitivity": "80"},
        )
        data = response.json()
        payload = data["data"]
        assert payload["sensitivity_used"] == 80

    def test_custom_canvas_parameters(self, client: TestClient, sample_white_jpeg: bytes):
        """Custom canvas dimensions are reflected in the grid shape."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("test.jpg", sample_white_jpeg, "image/jpeg")},
            data={"canvas_width": "400", "canvas_height": "300", "grid_scale": "8"},
        )
        data = response.json()
        payload = data["data"]
        assert payload["grid_width"]  == 50
        assert payload["grid_height"] == 37

    def test_all_grid_cells_are_binary(self, client: TestClient, sample_floorplan_jpeg: bytes):
        """Every cell in the returned grid must be 0 or 1."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("floor.jpg", sample_floorplan_jpeg, "image/jpeg")},
        )
        data = response.json()
        payload = data["data"]
        for row in payload["grid"]:
            for cell in row:
                assert cell in (0, 1)

    def test_wall_ratio_calculation(self, client: TestClient, sample_floorplan_jpeg: bytes):
        """wall_ratio should equal wall_cell_count / total_cells."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("floor.jpg", sample_floorplan_jpeg, "image/jpeg")},
        )
        data = response.json()
        payload = data["data"]
        expected_ratio = payload["wall_cell_count"] / payload["total_cells"]
        assert abs(payload["wall_ratio"] - expected_ratio) < 0.0001

    def test_processing_time_reported(self, client: TestClient, sample_white_jpeg: bytes):
        """processing_time_ms must be a positive number."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("test.jpg", sample_white_jpeg, "image/jpeg")},
        )
        data = response.json()
        assert data["processing_time_ms"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Wall Detection — Error Handling
# ─────────────────────────────────────────────────────────────────────────────


class TestWallDetectionErrors:
    def test_empty_file_returns_400(self, client: TestClient):
        """Uploading an empty file should return HTTP 400."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
        )
        assert response.status_code == 400

    def test_invalid_binary_returns_400(self, client: TestClient):
        """Uploading random bytes (not a valid image) should return HTTP 400."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("garbage.jpg", b"\x00\x01\x02\x03\xFF\xFE", "image/jpeg")},
        )
        assert response.status_code == 400

    def test_sensitivity_out_of_range_returns_422(self, client: TestClient, sample_white_jpeg: bytes):
        """Sensitivity > 255 should return HTTP 422 (Pydantic validation error)."""
        response = client.post(
            "/api/v1/wall-detection",
            files={"file": ("test.jpg", sample_white_jpeg, "image/jpeg")},
            data={"sensitivity": "999"},
        )
        assert response.status_code == 422

    def test_missing_file_returns_422(self, client: TestClient):
        """No file uploaded should return HTTP 422."""
        response = client.post("/api/v1/wall-detection")
        assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Real Floorplan Regression Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRealFloorplansAPI:
    def test_all_real_floorplans_via_api(self, client: TestClient, real_floorplan_files):
        """All real campus JPEG files must return HTTP 200 with valid schema."""
        if not real_floorplan_files:
            pytest.skip("No real floorplan files found in backend/uploads/.")

        for filepath in real_floorplan_files:
            image_bytes = filepath.read_bytes()
            response = client.post(
                "/api/v1/wall-detection",
                files={"file": (filepath.name, image_bytes, "image/jpeg")},
            )
            assert response.status_code == 200, (
                f"Expected 200 for {filepath.name}, got {response.status_code}: "
                f"{response.text}"
            )
            data = response.json()
            payload = data["data"]
            assert data["status"] == "success"
            assert payload["grid_width"]  == 100
            assert payload["grid_height"] == 75
