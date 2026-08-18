"""
grid_utils.py
-------------
Utility functions for building and manipulating the 2D wall detection grid.

The wall grid is the primary intermediate data structure of the AI pipeline.
It is a 2D list of integers:
  - 0 = passable (open floor)
  - 1 = wall (impassable)

Grid dimensions are derived from the canvas dimensions divided by the grid scale:
  grid_width  = canvas_width  / grid_scale   → default: 800 / 8 = 100
  grid_height = canvas_height / grid_scale   → default: 600 / 8 = 75

These defaults must remain synchronised with the frontend constants:
  mapConstants.js: CANVAS_WIDTH=800, CANVAS_HEIGHT=600, GRID_SCALE=8
"""

from __future__ import annotations

import numpy as np


def build_grid_from_mask(
    dilated_mask: np.ndarray,
    canvas_width: int,
    canvas_height: int,
    grid_scale: int,
) -> list[list[int]]:
    """
    Convert a dilated binary wall mask (uint8) into a 2D integer grid.

    Each grid cell represents a (grid_scale × grid_scale) pixel square.
    A cell is marked as 1 (wall) if **any** pixel in that square is white (255)
    in the mask. This mirrors the exact logic in useOpenCV.js.

    Args:
        dilated_mask:   A single-channel uint8 NumPy array where 255 = wall,
                        0 = passable. Typically the output of cv2.dilate().
        canvas_width:   The virtual canvas width (pixels).
        canvas_height:  The virtual canvas height (pixels).
        grid_scale:     Number of pixels per grid cell.

    Returns:
        A 2D list of shape [grid_height][grid_width] with values 0 or 1.
    """
    grid_width  = canvas_width  // grid_scale
    grid_height = canvas_height // grid_scale

    # Reshape the flat mask into a grid using NumPy for speed.
    # Crop the mask to the exact canvas dimensions first (it may be larger).
    mask_cropped = dilated_mask[:canvas_height, :canvas_width]

    # Reshape into (grid_height, grid_scale, grid_width, grid_scale)
    # then take the max over the two pixel-level axes.
    # This is equivalent to the nested loop in JS but vectorised.
    try:
        blocks = mask_cropped.reshape(
            grid_height, grid_scale,
            grid_width,  grid_scale,
        )
        # max over axis 1 (pixel rows within cell) then axis 2 (pixel cols within cell)
        cell_max = blocks.max(axis=1).max(axis=2)
        grid_np  = (cell_max == 255).astype(np.int8)
        return grid_np.tolist()
    except ValueError:
        # Fallback: canvas size is not evenly divisible by grid_scale.
        # Use the explicit loop (slower but always correct).
        return _build_grid_explicit(
            dilated_mask, canvas_width, canvas_height, grid_scale
        )


def _build_grid_explicit(
    dilated_mask: np.ndarray,
    canvas_width: int,
    canvas_height: int,
    grid_scale: int,
) -> list[list[int]]:
    """
    Explicit loop fallback for grid construction.
    Mirrors the exact JavaScript logic from useOpenCV.js line-for-line.
    """
    grid_width  = canvas_width  // grid_scale
    grid_height = canvas_height // grid_scale
    data        = dilated_mask

    grid: list[list[int]] = []
    for gy in range(grid_height):
        row: list[int] = []
        for gx in range(grid_width):
            is_wall = False
            for dy in range(grid_scale):
                if is_wall:
                    break
                for dx in range(grid_scale):
                    px = gx * grid_scale + dx
                    py = gy * grid_scale + dy
                    if px < canvas_width and py < canvas_height:
                        if data[py, px] == 255:
                            is_wall = True
                            break
            row.append(1 if is_wall else 0)
        grid.append(row)
    return grid


def grid_dimensions(
    canvas_width: int, canvas_height: int, grid_scale: int
) -> tuple[int, int]:
    """
    Returns the (grid_width, grid_height) for the given canvas and scale parameters.

    Args:
        canvas_width:  Canvas width in pixels.
        canvas_height: Canvas height in pixels.
        grid_scale:    Pixels per grid cell.

    Returns:
        Tuple of (grid_width, grid_height).
    """
    return canvas_width // grid_scale, canvas_height // grid_scale


def count_wall_cells(grid: list[list[int]]) -> int:
    """
    Count the number of wall cells (value == 1) in the grid.
    Useful for validation and testing.
    """
    return sum(cell for row in grid for cell in row)
