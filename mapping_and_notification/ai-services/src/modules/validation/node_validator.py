"""
node_validator.py
-----------------
NodeValidator — final quality gate for AI-generated nodes before coordinate transformation.

Responsibilities:
  - Validates all generated nodes against hard rules (removes invalid nodes).
  - Validates nodes against soft rules (flags nodes for admin review).
  - Ensures nodes are strictly within the AI workspace.
  - Automatically attempts to recover out-of-bounds or on-wall nodes using the distance transform.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple, Dict, Any

import cv2
import numpy as np

from src.shared.models.v1.domain import AiNode, AiReviewStatus, RoomPolygon
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

class NodeValidator:
    """
    Stateless final validator for AI-generated nodes (Stage 1H).
    Runs in AI space before coordinate transformation.
    """

    def validate(
        self,
        nodes: List[AiNode],
        wall_mask: Optional[np.ndarray],
        rooms: List[RoomPolygon],
        ai_width: int,
        ai_height: int,
        min_confidence: float = 0.30,
        min_separation_px: float = 20.0,
    ) -> Tuple[List[AiNode], Dict[str, int]]:
        """
        Validate and sanitize nodes. Hard failures remove nodes, soft failures flag them.

        Returns:
            (valid_nodes, stats_dict)
        """
        if not nodes:
            return [], {"kept": 0, "removed": 0, "flagged": 0}

        # Precompute distance transform for recovery attempts if we have a wall mask
        dist_transform: Optional[np.ndarray] = None
        if wall_mask is not None:
            inverted = cv2.bitwise_not(wall_mask)
            dist_transform = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)

        # Map rooms for quick lookup by ID
        room_map: Dict[str, RoomPolygon] = {r.id: r for r in rooms if r.id}

        kept_nodes: List[AiNode] = []
        removed = 0
        flagged = 0

        # Phase 1: Hard & Soft Validation with Recovery
        for node in nodes:
            # --- Hard Checks ---
            if not node.room_label or not node.room_label.strip():
                logger.debug("Node rejected: empty label", temp_id=node.temp_id)
                removed += 1
                continue

            if not math.isfinite(node.x) or not math.isfinite(node.y):
                logger.debug("Node rejected: non-finite coordinates", temp_id=node.temp_id)
                removed += 1
                continue

            # Force inside AI bounds (Hard check / Hard fix)
            nx = max(0.0, min(node.x, float(ai_width - 1)))
            ny = max(0.0, min(node.y, float(ai_height - 1)))

            # If node moved during clamping, update it
            if nx != node.x or ny != node.y:
                node = node.model_copy(update={"x": nx, "y": ny})

            # --- Soft Checks & Recovery ---
            is_flagged = False
            reasons = []

            if node.ai_confidence < min_confidence:
                is_flagged = True
                reasons.append("low_confidence")

            # Wall collision check
            on_wall = False
            if dist_transform is not None:
                ix, iy = int(round(nx)), int(round(ny))
                if float(dist_transform[iy, ix]) < 1.0:
                    on_wall = True

            # Room containment check (if applicable)
            outside_room = False
            if node.source_room_id and node.source_room_id in room_map:
                room = room_map[node.source_room_id]
                contour = np.array([[p.x, p.y] for p in room.polygon], dtype=np.float32).reshape(-1, 1, 2)
                if cv2.pointPolygonTest(contour, (nx, ny), False) < 0:
                    outside_room = True

            # Automatic Recovery Attempt
            if on_wall or outside_room:
                recovered_x, recovered_y = self._attempt_recovery(
                    node, dist_transform, room_map.get(node.source_room_id) if node.source_room_id else None, ai_width, ai_height
                )
                if recovered_x is not None and recovered_y is not None:
                    node = node.model_copy(update={"x": recovered_x, "y": recovered_y})
                    logger.debug("Node relocated during validation", temp_id=node.temp_id, reason="on_wall_or_outside_room")
                    # Re-evaluate wall status after recovery
                    ix, iy = int(round(recovered_x)), int(round(recovered_y))
                    if dist_transform is not None and float(dist_transform[iy, ix]) < 1.0:
                        is_flagged = True
                        reasons.append("on_wall")
                else:
                    is_flagged = True
                    reasons.append("on_wall" if on_wall else "outside_room")

            if is_flagged:
                node = node.model_copy(update={"review_status": AiReviewStatus.FLAGGED})
                flagged += 1
                logger.debug("Node flagged", temp_id=node.temp_id, reasons=reasons)

            kept_nodes.append(node)

        # Phase 2: Spatial Separation Check (Flag nodes too close to each other with same label)
        for i in range(len(kept_nodes)):
            if kept_nodes[i].review_status == AiReviewStatus.FLAGGED:
                continue # Already flagged
            
            for j in range(len(kept_nodes)):
                if i == j:
                    continue
                
                n1 = kept_nodes[i]
                n2 = kept_nodes[j]
                
                if self._normalize_label(n1.room_label) == self._normalize_label(n2.room_label):
                    dist = math.hypot(n1.x - n2.x, n1.y - n2.y)
                    if dist < min_separation_px:
                        # Flag the one with lower confidence
                        if n1.ai_confidence <= n2.ai_confidence:
                            kept_nodes[i] = n1.model_copy(update={"review_status": AiReviewStatus.FLAGGED})
                            flagged += 1
                            logger.debug("Node flagged", temp_id=n1.temp_id, reasons=["too_close_duplicate"])
                            break # Move to next node i

        stats = {
            "kept": len(kept_nodes),
            "removed": removed,
            "flagged": flagged
        }
        
        logger.info(
            "Stage 1H: Node validation completed",
            total_input=len(nodes),
            kept=stats["kept"],
            removed=stats["removed"],
            flagged=stats["flagged"]
        )

        return kept_nodes, stats

    @staticmethod
    def _normalize_label(label: str) -> str:
        import string
        import re
        s = str(label).lower()
        s = s.translate(str.maketrans('', '', string.punctuation))
        return re.sub(r'\s+', ' ', s).strip()

    @staticmethod
    def _attempt_recovery(
        node: AiNode,
        dist_transform: Optional[np.ndarray],
        room: Optional[RoomPolygon],
        ai_width: int,
        ai_height: int,
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Attempt to find a safe pixel for the node.
        If a room polygon is provided, search inside it.
        Otherwise, search in a small radius around the node.
        Returns (x, y) if found, else (None, None).
        """
        if dist_transform is None:
            return None, None

        if room is not None:
            # Search within room polygon
            xs = [p.x for p in room.polygon]
            ys = [p.y for p in room.polygon]
            bx1 = max(0, int(math.floor(min(xs))))
            by1 = max(0, int(math.floor(min(ys))))
            bx2 = min(ai_width, int(math.ceil(max(xs))))
            by2 = min(ai_height, int(math.ceil(max(ys))))

            if bx1 < bx2 and by1 < by2:
                # Mask out everything outside the room polygon
                mask = np.zeros((ai_height, ai_width), dtype=np.uint8)
                pts = np.array([[p.x, p.y] for p in room.polygon], dtype=np.int32)
                cv2.fillPoly(mask, [pts], 255)
                
                # Apply mask to distance transform
                dt_masked = cv2.bitwise_and(dist_transform, dist_transform, mask=mask)
                bbox_patch = dt_masked[by1:by2, bx1:bx2]
                
                if bbox_patch.size > 0:
                    _, max_val, _, max_loc = cv2.minMaxLoc(bbox_patch)
                    if float(max_val) >= 1.0: # Just off the wall is enough for recovery
                        return float(bx1 + max_loc[0]), float(by1 + max_loc[1])
        
        # Fallback: search in a small 20px radius
        r = 20
        ix, iy = int(round(node.x)), int(round(node.y))
        x1 = max(0, ix - r)
        y1 = max(0, iy - r)
        x2 = min(ai_width, ix + r)
        y2 = min(ai_height, iy + r)
        
        patch = dist_transform[y1:y2, x1:x2]
        if patch.size > 0:
            _, max_val, _, max_loc = cv2.minMaxLoc(patch)
            if float(max_val) >= 1.0:
                return float(x1 + max_loc[0]), float(y1 + max_loc[1])
                
        return None, None
