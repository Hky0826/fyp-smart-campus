"""
image_loader.py
---------------
Robust image loading utilities for the AI service.

Handles reading raw bytes (from FastAPI UploadFile) into NumPy arrays
that OpenCV can consume, with consistent error handling and format
normalisation across all image types (JPEG, PNG, WEBP, BMP).

All OpenCV operations in this project should obtain their input images
through this module — never directly from user-provided bytes.
"""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class ImageLoadError(Exception):
    """Raised when an image cannot be decoded or is in an unsupported format."""


def load_image_from_bytes(data: bytes, convert_to_bgr: bool = True) -> np.ndarray:
    """
    Decode raw image bytes into a NumPy array suitable for OpenCV processing.

    Uses Pillow for robust format detection and initial decoding, then converts
    to a NumPy BGR array for use with `cv2` functions.

    Args:
        data:           Raw image bytes from an UploadFile.
        convert_to_bgr: If True (default), returns a BGR array.
                        If False, returns RGB.

    Returns:
        A NumPy uint8 array of shape (H, W, 3) in BGR (or RGB) colour space.

    Raises:
        ImageLoadError: If the bytes cannot be decoded as a valid image.
    """
    if not data:
        raise ImageLoadError("Received empty image bytes.")

    try:
        pil_image = Image.open(io.BytesIO(data))
        # Ensure RGBA sources are flattened to RGB on a white background
        if pil_image.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", pil_image.size, (255, 255, 255))
            alpha = pil_image.convert("RGBA").split()[-1]
            background.paste(pil_image.convert("RGB"), mask=alpha)
            pil_image = background
        elif pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        np_image = np.array(pil_image, dtype=np.uint8)

        if convert_to_bgr:
            np_image = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)

        logger.debug(
            "Image loaded",
            width=np_image.shape[1],
            height=np_image.shape[0],
            channels=np_image.shape[2] if np_image.ndim == 3 else 1,
        )
        return np_image

    except UnidentifiedImageError as exc:
        raise ImageLoadError(f"Unsupported or corrupt image format: {exc}") from exc
    except Exception as exc:
        raise ImageLoadError(f"Failed to load image: {exc}") from exc


def resize_image(
    image: np.ndarray,
    target_width: int,
    target_height: int,
    interpolation: int = cv2.INTER_AREA,
) -> np.ndarray:
    """
    Resize an image to the target dimensions.

    Uses INTER_AREA interpolation by default, which gives the best quality
    when shrinking images (e.g., scaling a high-res floorplan to 800×600).

    Args:
        image:         Input NumPy image array.
        target_width:  Target width in pixels.
        target_height: Target height in pixels.
        interpolation: OpenCV interpolation flag.

    Returns:
        Resized NumPy image array.
    """
    h, w = image.shape[:2]
    if w == target_width and h == target_height:
        return image

    logger.debug(
        "Resizing image",
        from_size=(w, h),
        to_size=(target_width, target_height),
    )
    return cv2.resize(image, (target_width, target_height), interpolation=interpolation)
