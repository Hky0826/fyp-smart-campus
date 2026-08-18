"""
node_generation/ocr_node_generator.py
--------------------------------------
OcrNodeGenerator — generates AiNode objects directly from merged OCR labels.

This is the PRIMARY node generator in Phase 1.5. Instead of waiting for room
detection to succeed, it creates a navigation node for every meaningful OCR
label found in the floorplan. This ensures that rooms with visible text labels
are always represented as nodes — even when room detection fails due to:
  - Incomplete wall boundaries
  - Open-plan rooms
  - Hatched or colored regions
  - Irregular/non-rectangular room shapes

Pipeline position:
  Stage 1E — runs AFTER OcrFragmentMerger, BEFORE room detection.

Node placement strategy (per label):
  1. Compute center of merged OCR bounding box → candidate position.
  2. Check wall clearance via precomputed distanceTransform.
     If center is in free space (distance ≥ wall_clearance_px) → use it.
     Otherwise → search a local patch (±search_radius_px) for the pixel
     with maximum clearance and place the node there.
  3. Assign semantic node type via keyword matching (CLASSROOM, OFFICE, etc.)
  4. Compute combined confidence = 0.7 × OCR_conf + 0.3 × clearance_score.

OCR label filtering:
  Labels that are clearly NOT room names are silently ignored:
    - Strings shorter than min_label_length characters.
    - Purely numeric strings (dimension labels like "2400", "1500").
    - Scale / orientation markers ("NTS", "NORTH", "UP", "DN", etc.).
    - Single letter + optional digit patterns ("A1", "B", "3").

Room validation (optional, run after room detection in orchestrator):
  call validate_against_rooms() to boost confidence of OCR nodes that
  fall inside a detected room polygon.

Coordinate System:
  All inputs and outputs are in AI analysis space.
  CoordinateTransformer in FloorplanAnalyzerService converts to canvas space.
"""

from __future__ import annotations

import math
import re
from typing import List, Optional, Tuple

import cv2
import numpy as np

from src.config.semantic_rules_loader import load_semantic_rules
from src.shared.models.v1.domain import (
    AiNode,
    AiNodeSource,
    AiReviewStatus,
    Point,
    RoomPolygon,
    TextDetection,
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# OCR Label Filtering
# ─────────────────────────────────────────────────────────────────────────────

#: Exact-match words (case-insensitive) that should never become room nodes.
_IGNORE_WORDS: frozenset = frozenset({
    "up", "dn", "dn.", "up.",
    "fl", "ffl",
    "nts", "n.t.s.", "n.t.s",
    "north", "south", "east", "west",
    "scale", "level", "floor",
    "exit", "fire",
    "true", "false",
    "area", "ref", "no.", "no",
    "type", "item", "note", "notes",
    "detail", "section", "elevation",
    "revised", "drawn", "checked",
    "date", "rev",
})

#: Regex patterns that identify non-room labels.
#  Matches: pure numbers/decimals, scale ratios (1:100), dimension specs (2400×1200),
#           single-letter identifiers (A, B1), arrow indicators.
_IGNORE_PATTERN = re.compile(
    r"^[\d\s.,/\\:×xX'\"\-\+]+$"   # pure numeric / dimension
    r"|^\d+\s*[xX×]\s*\d+$"         # dimension: 2400×1200
    r"|^1\s*:\s*\d+$"               # scale: 1:100
    r"|^[A-Z]\d*\.?$"               # single letter / code: A, B1, C.
    r"|^[①②③④⑤⑥⑦⑧⑨⑩]$",           # circled numbers
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Semantic Room Type Classifier — rules loaded from semantic_rules.yaml
# ─────────────────────────────────────────────────────────────────────────────

# Load once at module import time so misconfiguration is caught at startup.
try:
    _SEMANTIC_RULES, _DEFAULT_NODE_TYPE = load_semantic_rules()
except Exception as _rules_load_error:
    logger.error(
        "Failed to load semantic_rules.yaml — using built-in fallback rules",
        error=str(_rules_load_error),
    )
    # Minimal built-in fallback mapping to supported types only.
    _SEMANTIC_RULES = [
        (["lecture", "classroom", "seminar", "tutorial", "lab", "laboratory"], "CLASSROOM"),
        (["office", "administration", "admin", "reception", "staff", "faculty"], "OFFICE"),
        (["toilet", "washroom", "restroom", "wc", "lavatory", "bathroom"], "WASHROOM"),
        (["lift", "elevator"], "ELEVATOR"),
        (["stair", "stairwell", "staircase", "stairway"], "STAIRWELL"),
        (["entrance", "lobby", "foyer", "entry"], "ENTRANCE"),
        (["corridor", "hallway", "passage", "concourse"], "CORRIDOR"),
        (["kitchen", "pantry", "canteen", "cafeteria", "dining", "restaurant", "food"], "FOOD"),
        (["store", "storage", "server", "electrical", "mechanical", "utility"], "FACILITIES"),
        (["meeting", "boardroom", "conference", "auditorium", "hall"], "HALL"),
        (["library", "reading room", "study", "lounge"], "SOCIAL SPACES"),
        (["outdoor", "car park", "parking", "garden"], "OUTDOOR"),
    ]
    _DEFAULT_NODE_TYPE = "OTHER"

DEFAULT_WALL_CLEARANCE_PX  = 8
DEFAULT_SEARCH_RADIUS_PX   = 80
DEFAULT_MIN_LABEL_LENGTH   = 2


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class OcrNodeGenerator:
    """
    Stateless node generator — creates AiNode objects from merged OCR labels.

    This is the PRIMARY path for Phase 1.5 node generation. One node is
    produced for every meaningful merged label, regardless of whether a room
    polygon exists at that location.

    Usage:
        generator = OcrNodeGenerator()
        nodes = generator.generate(
            merged_texts=merged_texts_ai,
            wall_mask=wall_result.wall_mask,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
        )
    """

    def generate(
        self,
        merged_texts:      List[TextDetection],
        wall_mask:         Optional[np.ndarray],
        ai_width:          int   = 800,
        ai_height:         int   = 600,
        wall_clearance_px: int   = DEFAULT_WALL_CLEARANCE_PX,
        search_radius_px:  int   = DEFAULT_SEARCH_RADIUS_PX,
        min_label_length:  int   = DEFAULT_MIN_LABEL_LENGTH,
    ) -> List[AiNode]:
        """
        Generate one AiNode per meaningful merged OCR label.

        Args:
            merged_texts:      Merged TextDetection list from OcrFragmentMerger (AI space).
            wall_mask:         Binary wall mask at AI resolution (255=wall, 0=space).
                               May be None — OCR centers used directly.
            ai_width:          AI analysis image width.
            ai_height:         AI analysis image height.
            wall_clearance_px: Min distance (px) from wall pixels for a valid position.
            search_radius_px:  Radius of local search patch when center is on a wall.
            min_label_length:  Minimum character length to qualify as a room label.

        Returns:
            List of AiNode objects (coordinates in AI space, OCR_PRIMARY source).
        """
        # Pre-compute distance transform once (avoids per-node recomputation)
        dist_transform: Optional[np.ndarray] = None
        if wall_mask is not None:
            inverted        = cv2.bitwise_not(wall_mask)
            dist_transform  = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)

        nodes: List[AiNode] = []
        skipped_count = 0

        for idx, text in enumerate(merged_texts):
            if self._is_ignorable(text.text, min_label_length):
                skipped_count += 1
                logger.debug(
                    "OCR label ignored (non-room pattern)",
                    text=text.text,
                    length=len(text.text.strip()),
                )
                continue

            node_x, node_y, clearance_score = self._find_safe_position(
                cx=text.center.x,
                cy=text.center.y,
                bbox=text.bbox,
                dist_transform=dist_transform,
                ai_width=ai_width,
                ai_height=ai_height,
                wall_clearance_px=wall_clearance_px,
                search_radius_px=search_radius_px,
            )

            node_type = self._classify_room_type(text.text)

            # Combined confidence: 70% OCR, 30% wall-clearance quality
            ai_confidence = round(
                0.70 * text.confidence + 0.30 * clearance_score, 4
            )

            temp_id = f"ai_ocr_{idx}"

            logger.debug(
                "OCR-primary node generated (AI space)",
                temp_id=temp_id,
                label=text.text,
                node_type=node_type,
                x=round(node_x, 1),
                y=round(node_y, 1),
                ocr_conf=text.confidence,
                clearance_score=round(clearance_score, 3),
                ai_confidence=ai_confidence,
                fragment_count=text.fragment_count,
            )

            nodes.append(AiNode(
                temp_id=temp_id,
                node_type=node_type,
                room_label=text.text,
                x=round(node_x, 2),
                y=round(node_y, 2),
                ai_confidence=ai_confidence,
                ai_source=AiNodeSource.OCR_PRIMARY,
                source_text_id=text.id,
                review_status=AiReviewStatus.PENDING,
                allowed_roles=[],
                is_accessible="ALLOW",
            ))

        logger.info(
            "Stage 1E: OCR-first node generation completed",
            nodes_generated=len(nodes),
            labels_skipped=skipped_count,
            total_input=len(merged_texts),
        )
        return nodes

    def validate_against_rooms(
        self,
        nodes:  List[AiNode],
        rooms:  List[RoomPolygon],
        boost:  float = 0.10,
    ) -> List[AiNode]:
        """
        Boost confidence of OCR-primary nodes that fall inside a detected room polygon.

        Args:
            nodes:  AiNode list to validate (AI space, OCR_PRIMARY source).
            rooms:  RoomPolygon list from room detector (AI space).
            boost:  Confidence bonus to add if node falls inside a room (default 0.10).

        Returns:
            Updated AiNode list with boosted confidence for validated nodes.
        """
        if not rooms or not nodes:
            return nodes

        room_contours = [
            np.array(
                [[p.x, p.y] for p in room.polygon], dtype=np.float32
            ).reshape(-1, 1, 2)
            for room in rooms
        ]

        updated: List[AiNode] = []
        validated_count = 0

        for node in nodes:
            if node.ai_source != AiNodeSource.OCR_PRIMARY:
                updated.append(node)
                continue

            test_pt  = (node.x, node.y)
            inside   = False
            for contour in room_contours:
                if cv2.pointPolygonTest(contour, test_pt, measureDist=False) >= 0:
                    inside = True
                    break

            if inside:
                new_conf = min(1.0, round(node.ai_confidence + boost, 4))
                updated.append(node.model_copy(update={"ai_confidence": new_conf}))
                validated_count += 1
            else:
                updated.append(node)

        logger.info(
            "Stage 1F: OCR node room validation completed",
            nodes_validated=validated_count,
            nodes_unvalidated=len(nodes) - validated_count,
        )
        return updated

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _is_ignorable(text: str, min_label_length: int) -> bool:
        """Return True if this text should NOT become a room node."""
        stripped = text.strip()
        if len(stripped) < min_label_length:
            return True
        if stripped.lower() in _IGNORE_WORDS:
            return True
        if _IGNORE_PATTERN.match(stripped):
            return True
        # Also ignore if ALL words in the text are individually ignorable
        words = stripped.lower().split()
        if words and all(w in _IGNORE_WORDS or w.rstrip('.') in _IGNORE_WORDS for w in words):
            return True
        return False

    @staticmethod
    def _classify_room_type(label: str) -> str:
        """
        Return a semantic node type string based on keyword matching.

        Rules are loaded from src/config/semantic_rules.yaml at module start.
        Falls back to _DEFAULT_NODE_TYPE ("OTHER") when no keyword matches.

        Args:
            label: The OCR room label string.

        Returns:
            A node type string — always one of the supported navigation types.
        """
        lower = label.lower()
        for keywords, node_type in _SEMANTIC_RULES:
            if any(kw in lower for kw in keywords):
                return node_type
        return _DEFAULT_NODE_TYPE

    @staticmethod
    def _find_safe_position(
        cx:                float,
        cy:                float,
        bbox:              List[Point],
        dist_transform:    Optional[np.ndarray],
        ai_width:          int,
        ai_height:         int,
        wall_clearance_px: int,
        search_radius_px:  int,
    ) -> Tuple[float, float, float]:
        """
        Find the safest node position near (cx, cy) using the distance transform.
        Prioritises remaining inside the OCR bounding box before expanding outwards.

        Returns:
            (x, y, clearance_score)
            clearance_score is in [0, 1]: 0 = on wall, 1 = max clearance (≥50 px).
        """
        # Clamp to image bounds
        cx = max(0.0, min(cx, float(ai_width  - 1)))
        cy = max(0.0, min(cy, float(ai_height - 1)))

        if dist_transform is None:
            return cx, cy, 0.5

        ix, iy = int(round(cx)), int(round(cy))
        clearance = float(dist_transform[iy, ix])

        if clearance >= wall_clearance_px:
            # Center is already in free space — use it
            score = min(clearance / 50.0, 1.0)
            return cx, cy, score

        # Center is on a wall. 
        # Attempt 1: Search ONLY within the OCR bounding box
        xs = [p.x for p in bbox]
        ys = [p.y for p in bbox]
        bx1 = max(0, int(math.floor(min(xs))))
        by1 = max(0, int(math.floor(min(ys))))
        bx2 = min(ai_width, int(math.ceil(max(xs))))
        by2 = min(ai_height, int(math.ceil(max(ys))))

        if bx1 < bx2 and by1 < by2:
            bbox_patch = dist_transform[by1:by2, bx1:bx2]
            if bbox_patch.size > 0:
                _, max_val, _, max_loc = cv2.minMaxLoc(bbox_patch)
                if float(max_val) >= wall_clearance_px:
                    best_x = float(bx1 + max_loc[0])
                    best_y = float(by1 + max_loc[1])
                    score  = min(float(max_val) / 50.0, 1.0)
                    logger.debug(
                        "Wall-clearance search relocated within OCR bbox",
                        original=(round(cx, 1), round(cy, 1)),
                        relocated=(round(best_x, 1), round(best_y, 1)),
                        clearance=round(float(max_val), 1),
                    )
                    return best_x, best_y, score

        # Attempt 2: Search in wider local patch for highest clearance
        x1 = max(0, ix - search_radius_px)
        y1 = max(0, iy - search_radius_px)
        x2 = min(ai_width,  ix + search_radius_px)
        y2 = min(ai_height, iy + search_radius_px)

        patch = dist_transform[y1:y2, x1:x2]
        if patch.size == 0 or float(patch.max()) < wall_clearance_px:
            # Nothing found in patch — use original center
            logger.debug(
                "No wall-clear position found in search patch — using OCR center",
                original_center=(round(cx, 1), round(cy, 1)),
                clearance=round(clearance, 1),
            )
            return cx, cy, 0.0

        _, max_val, _, max_loc = cv2.minMaxLoc(patch)
        best_x = float(x1 + max_loc[0])
        best_y = float(y1 + max_loc[1])
        score  = min(float(max_val) / 50.0, 1.0)

        logger.debug(
            "Wall-clearance search found safe position in wider patch",
            original=(round(cx, 1), round(cy, 1)),
            relocated=(round(best_x, 1), round(best_y, 1)),
            clearance=round(float(max_val), 1),
        )
        return best_x, best_y, score
