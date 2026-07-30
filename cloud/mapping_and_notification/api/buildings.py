from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_system_admin
from app.models.models import Building

router = APIRouter(tags=["Buildings"])


@router.get("/buildings")
def list_buildings(db: Session = Depends(get_db)):
    buildings = db.query(Building).order_by(Building.building_name).all()
    return [
        {"building_id": b.building_id, "building_name": b.building_name}
        for b in buildings
    ]


@router.post("/buildings", status_code=201)
def create_building(data: dict, db: Session = Depends(get_db), _admin=Depends(verify_system_admin)):
    name = (data.get("building_name") or "").strip()
    if not name:
        raise HTTPException(422, "Building name is required")
    existing = db.query(Building).filter(Building.building_name == name).first()
    if existing:
        return {"building_id": existing.building_id, "building_name": existing.building_name}
    b = Building(building_name=name)
    db.add(b)
    db.commit()
    db.refresh(b)
    return {"building_id": b.building_id, "building_name": b.building_name}
