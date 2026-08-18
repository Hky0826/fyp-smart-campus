"""
ocr/ocr_merger.py
-----------------
OcrFragmentMerger — merges multi-line OCR text fragments belonging to the
same room label into a single TextDetection.

Problem:
  PaddleOCR often detects multi-line room names as separate detections:

    ["Commercial", "Training", "Kitchen"]  →  "Commercial Training Kitchen"
    ["Lecture Room 8", "(LR8)"]            →  "Lecture Room 8 (LR8)"

  Without merging, each fragment would either become its own spurious node
  or fail to match any room polygon during association.

Merge algorithm:
  1. Compute axis-aligned bounding-box bounds for every raw detection.
  2. Use union-find to group detections that are "close enough" in both
     vertical (gap) and horizontal (overlap) dimensions.
  3. Within each group, order fragments top→bottom, left→right to preserve
     natural reading order, then join texts with a space.
  4. Produce a new merged TextDetection with a convex-hull (axis-aligned)
     bounding box and an averaged confidence score.
  5. Assign stable IDs ("merged_0", "merged_1", …) for cross-referencing
     by AiNode.source_text_id.

Coordinate System:
  Operates entirely in AI analysis space — the same space returned by
  OcrDetector.detect_text(). No coordinate conversion is performed here.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.shared.models.v1.domain import Point, TextDetection
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Defaults — tunable per-call
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MAX_VERTICAL_GAP_PX        = 30    # Max Y-gap (px, AI space) between two fragments to merge
DEFAULT_MIN_HORIZONTAL_OVERLAP_RATIO = 0.25  # Min X-overlap fraction (relative to narrower bbox)


# ─────────────────────────────────────────────────────────────────────────────
# Union-Find helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_uf(n: int) -> List[int]:
    return list(range(n))


def _find(parent: List[int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]   # path compression
        x = parent[x]
    return x


def _union(parent: List[int], x: int, y: int) -> None:
    parent[_find(parent, x)] = _find(parent, y)


# ─────────────────────────────────────────────────────────────────────────────
# Bounds helper
# ─────────────────────────────────────────────────────────────────────────────

_Bounds = Tuple[float, float, float, float]  # (x_min, y_min, x_max, y_max)


def _bbox_bounds(text: TextDetection) -> _Bounds:
    xs = [p.x for p in text.bbox]
    ys = [p.y for p in text.bbox]
    return min(xs), min(ys), max(xs), max(ys)


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class OcrFragmentMerger:
    """
    Stateless merger — groups spatially proximate OCR fragments and fuses them
    into single TextDetection objects.

    Usage:
        merger = OcrFragmentMerger()
        merged = merger.merge(raw_texts)
    """

    def merge(
        self,
        texts:                        List[TextDetection],
        max_vertical_gap_px:          float = DEFAULT_MAX_VERTICAL_GAP_PX,
        min_horizontal_overlap_ratio: float = DEFAULT_MIN_HORIZONTAL_OVERLAP_RATIO,
    ) -> List[TextDetection]:
        """
        Merge spatially proximate OCR fragments into fused TextDetection objects.

        Args:
            texts:                        Raw TextDetection list from OcrDetector (AI space).
            max_vertical_gap_px:          Maximum Y-gap between two fragments' bounding-box
                                          edges (in AI pixels) for them to be merge-eligible.
                                          Also considers relative gap vs. fragment height.
            min_horizontal_overlap_ratio: Minimum fraction of the *narrower* fragment's width
                                          that must overlap horizontally for merging to occur.

        Returns:
            New TextDetection list, one per merged group (or unchanged if single-fragment).
            Sorted by (center_y, center_x) — top-to-bottom, left-to-right.
            Each result has an ``id`` ("merged_0", …) and correct ``fragment_count``.
        """
        if not texts:
            return []
        if len(texts) == 1:
            result = texts[0].model_copy(update={"id": "merged_0", "fragment_count": 1})
            return [result]

        n = len(texts)
        bounds: List[_Bounds] = [_bbox_bounds(t) for t in texts]
        parent = _make_uf(n)

        # Pairwise merge check
        for i in range(n):
            for j in range(i + 1, n):
                if self._can_merge(
                    bounds[i],
                    bounds[j],
                    max_vertical_gap_px,
                    min_horizontal_overlap_ratio,
                ):
                    _union(parent, i, j)

        # Collect groups
        groups: Dict[int, List[int]] = {}
        for i in range(n):
            root = _find(parent, i)
            groups.setdefault(root, []).append(i)

        # Build merged TextDetections
        result: List[TextDetection] = []
        sorted_roots = sorted(groups.keys())  # deterministic ordering

        for group_idx, root in enumerate(sorted_roots):
            indices = groups[root]
            merged_text_id = f"merged_{group_idx}"

            if len(indices) == 1:
                # Single fragment — pass through with ID set
                frag = texts[indices[0]]
                result.append(frag.model_copy(update={
                    "id":             merged_text_id,
                    "fragment_count": 1,
                }))
                continue

            # Multi-fragment group — sort top→bottom, left→right for reading order
            sorted_indices = sorted(
                indices,
                key=lambda i: (texts[i].center.y, texts[i].center.x),
            )
            merged_text_str = " ".join(texts[i].text for i in sorted_indices)

            # Axis-aligned bounding box = min/max of all fragment bboxes
            all_xs = [p.x for i in indices for p in texts[i].bbox]
            all_ys = [p.y for i in indices for p in texts[i].bbox]
            x_min, y_min = min(all_xs), min(all_ys)
            x_max, y_max = max(all_xs), max(all_ys)

            merged_bbox = [
                Point(x=x_min, y=y_min),   # TL
                Point(x=x_max, y=y_min),   # TR
                Point(x=x_max, y=y_max),   # BR
                Point(x=x_min, y=y_max),   # BL
            ]
            merged_center = Point(
                x=round((x_min + x_max) / 2.0, 2),
                y=round((y_min + y_max) / 2.0, 2),
            )
            avg_confidence = round(
                sum(texts[i].confidence for i in indices) / len(indices), 4
            )

            logger.debug(
                "OCR fragments merged",
                merged_id=merged_text_id,
                fragment_count=len(indices),
                texts=[texts[i].text for i in sorted_indices],
                result=merged_text_str,
            )

            result.append(TextDetection(
                text=merged_text_str,
                bbox=merged_bbox,
                center=merged_center,
                confidence=avg_confidence,
                id=merged_text_id,
                fragment_count=len(indices),
            ))

        # Sort by Y, then X for consistent downstream ordering
        result.sort(key=lambda t: (t.center.y, t.center.x))

        n_merged_groups = sum(1 for root, indices in groups.items() if len(indices) > 1)
        n_single        = sum(1 for root, indices in groups.items() if len(indices) == 1)

        logger.info(
            "Stage 1D: OCR fragment merging completed",
            raw_fragments=len(texts),
            merged_groups=n_merged_groups,
            single_fragments=n_single,
            output_count=len(result),
        )

        return result

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _can_merge(
        bounds_a:                     _Bounds,
        bounds_b:                     _Bounds,
        max_vertical_gap_px:          float,
        min_horizontal_overlap_ratio: float,
    ) -> bool:
        """
        Determine if two bounding boxes are spatially close enough to be merged.

        Two fragments are mergeable when ALL of:
          1. Vertical gap between their edges is small (absolute and relative to height).
          2. They overlap horizontally by at least min_horizontal_overlap_ratio
             of the narrower fragment's width.
        """
        ax_min, ay_min, ax_max, ay_max = bounds_a
        bx_min, by_min, bx_max, by_max = bounds_b

        a_height = max(ay_max - ay_min, 1.0)
        b_height = max(by_max - by_min, 1.0)

        # Vertical gap: distance between the closest edges of the two bboxes
        if ay_min <= by_min:
            # A is above B (or same level)
            v_gap = by_min - ay_max
        else:
            # B is above A
            v_gap = ay_min - by_max

        # Allow negative v_gap (overlapping) and up to max_vertical_gap_px
        # Also allow up to 1.5× the taller fragment's height (handles large text)
        effective_max_gap = max(max_vertical_gap_px, max(a_height, b_height) * 1.5)
        if v_gap > effective_max_gap:
            return False

        # Horizontal overlap
        x_overlap = min(ax_max, bx_max) - max(ax_min, bx_min)
        if x_overlap <= 0:
            return False

        a_width    = max(ax_max - ax_min, 1.0)
        b_width    = max(bx_max - bx_min, 1.0)
        narrower   = min(a_width, b_width)
        overlap_ratio = x_overlap / narrower

        return overlap_ratio >= min_horizontal_overlap_ratio
