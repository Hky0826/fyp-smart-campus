"""
tests/conftest.py
-----------------
pytest fixtures shared across all test modules.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.main import app


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Test Client
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """
    FastAPI synchronous test client (httpx-backed).
    Session-scoped so the app starts up only once per test run.
    """
    with TestClient(app) as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# Sample Images
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def sample_white_jpeg() -> bytes:
    """A simple 800×600 solid white JPEG — represents an empty floorplan."""
    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def sample_floorplan_jpeg() -> bytes:
    """
    A synthetic floorplan-like image: white background with black rectangles
    representing walls. Used to verify that wall detection produces non-empty output.
    """
    img = Image.new("RGB", (800, 600), color=(255, 255, 255))

    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    # Draw thick horizontal and vertical wall lines
    draw.rectangle([0, 0, 800, 10], fill=(0, 0, 0))      # Top wall
    draw.rectangle([0, 590, 800, 600], fill=(0, 0, 0))   # Bottom wall
    draw.rectangle([0, 0, 10, 600], fill=(0, 0, 0))      # Left wall
    draw.rectangle([790, 0, 800, 600], fill=(0, 0, 0))   # Right wall
    draw.rectangle([200, 0, 210, 400], fill=(0, 0, 0))   # Interior vertical wall
    draw.rectangle([0, 300, 200, 310], fill=(0, 0, 0))   # Interior horizontal wall

    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def real_floorplan_files() -> list[Path]:
    """
    Returns paths to the actual campus floorplan JPEG files stored in
    backend/uploads/. Used for regression testing against real data.

    Returns an empty list if the uploads directory is not accessible
    (e.g., in a CI environment without the backend data).
    """
    uploads_dir = Path(__file__).parent.parent.parent / "backend" / "uploads"
    if not uploads_dir.exists():
        return []
    return sorted(uploads_dir.glob("*.jpeg")) + sorted(uploads_dir.glob("*.jpg"))
