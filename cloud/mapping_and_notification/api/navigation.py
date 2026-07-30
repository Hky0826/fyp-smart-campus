from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_admin
from ..mapping.navigation_service import DestinationAmbiguous, NavigationService, NoRouteError, StartLocationRequired
from .schemas import RouteRequest

router = APIRouter(tags=["Mapping and notification navigation"])


def _calculate(payload: RouteRequest, db: Session, admin, *, preview: bool):
    try:
        user = admin.user if admin else None
        roles = {str(getattr(r, "role_name", r)).upper() for r in (getattr(user, "roles", None) or ())}
        if preview and payload.rbac_role:
            roles = {payload.rbac_role.upper()}
        return NavigationService(db).calculate(destination_node_id=payload.canonical_destination_id(), destination_label=payload.destination_label, start_node_id=payload.canonical_start(), user=user, walking_speed=payload.walking_speed, roles=roles, allow_explicit_start=preview)
    except DestinationAmbiguous as exc:
        raise HTTPException(409, {"message": str(exc), "candidates": exc.candidates})
    except StartLocationRequired as exc:
        raise HTTPException(422, str(exc))
    except NoRouteError as exc:
        raise HTTPException(404, str(exc))


@router.post("/routes")
def calculate_route(payload: RouteRequest, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    return _calculate(payload, db, admin, preview=False)


@router.post("/routes/admin-preview")
def preview_route(payload: RouteRequest, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    if getattr(admin, "admin_type", "") not in {"SUPER_ADMIN", "SYSTEM_ADMIN"}:
        raise HTTPException(403, "Route preview requires a system administrator")
    return _calculate(payload, db, admin, preview=True)
