from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.private_storage import safe_existing_path
from app.core.security import verify_system_admin
from ..ai.wall_detection import wall_cache

router = APIRouter(tags=["Mapping and notification wall detection"])


@router.post("/floorplans/{floorplan_id}/wall-detection")
def detect_walls(floorplan_id: int, sensitivity: int = 120, canvas_width: int = 800, canvas_height: int = 600, grid_scale: int = 8, db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    from app.models.models import Floorplan
    row = db.query(Floorplan).filter(Floorplan.floorplan_id == floorplan_id).first()
    if not row:
        raise HTTPException(404, "Floorplan not found")
    path = safe_existing_path("floorplans", row.image_path)
    try:
        return wall_cache.get_or_detect(path.read_bytes(), asset_version=f"{floorplan_id}:{row.image_path}", sensitivity=sensitivity, canvas_width=canvas_width, canvas_height=canvas_height, grid_scale=grid_scale)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc))
