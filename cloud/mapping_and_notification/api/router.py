from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_system_admin
from ..mapping.navigation_service import NavigationService, DestinationAmbiguous, NoRouteError, StartLocationRequired
from ..notifications.builder import build_notification
from ..notifications.service import NotificationService
from . import buildings, maps, navigation, notifications, wall_detection
from .schemas import RouteAndNotifyRequest

router = APIRouter()
router.include_router(buildings.router)
router.include_router(maps.router)
router.include_router(navigation.router)
router.include_router(notifications.router)
router.include_router(wall_detection.router)


@router.post("/routes-and-notify", tags=["Mapping and notification notifications"])
def route_and_notify(payload: RouteAndNotifyRequest, db: Session = Depends(get_db), admin=Depends(verify_system_admin)):
    try:
        route = NavigationService(db).calculate(destination_node_id=payload.canonical_destination_id(), destination_label=payload.destination_label, start_node_id=payload.canonical_start(), user=admin.user, walking_speed=payload.walking_speed, roles={str(getattr(r, "role_name", r)).upper() for r in (getattr(admin.user, "roles", None) or ())}, allow_explicit_start=True)
    except DestinationAmbiguous as exc:
        raise HTTPException(409, {"message": str(exc), "candidates": exc.candidates})
    except (NoRouteError, StartLocationRequired) as exc:
        raise HTTPException(422, str(exc))
    summary = route["route_summary"]
    row = NotificationService(db).create_and_publish(build_notification(recipient_user_id=payload.recipient_user_id, title=payload.title, body=f"Route to {summary['destination_label']}", event_type=payload.event_type))
    route["notification"] = {"notification_id": row.notification_id, "message_id": row.message_id, "status": row.status}
    return route


# Compatibility aliases delegate to the canonical Python implementation and are
# intentionally kept in one router so they can be removed after cutover.
router.add_api_route("/navigate", navigation.calculate_route, methods=["POST"], deprecated=True, operation_id="legacy_navigate")
router.add_api_route("/navigate/admin-test", navigation.preview_route, methods=["POST"], deprecated=True, operation_id="legacy_navigate_admin_preview")
router.add_api_route("/floorplans", maps.list_floorplans, methods=["GET"], deprecated=True, operation_id="legacy_floorplans")
router.add_api_route("/notifications", notifications.list_notifications, methods=["GET"], deprecated=True, operation_id="legacy_notifications")
