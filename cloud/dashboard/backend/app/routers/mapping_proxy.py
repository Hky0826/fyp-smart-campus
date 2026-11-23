"""Reverse Proxy Router forwarding /api/mapping-notification requests to Node.js Microservice."""

import os
import time
import httpx
import jwt
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_admin
from app.models.models import Admin

router = APIRouter(tags=["Mapping & Notification Microservice Proxy"])

MAPPING_MICROSERVICE_URL = os.getenv("MAPPING_MICROSERVICE_URL", "http://127.0.0.1:5000")

# Hop-by-hop headers that should not be forwarded
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

def _requires_admin(method: str, path: str) -> bool:
    if path.startswith("api/"):
        path = path[4:]
    head, _, tail = path.partition("/")
    if head in {"notifications", "notification-users", "global-nodes", "wall-detection", "analyze-floorplan"}:
        return True
    if head in {"navigate", "routes"}:
        return tail == "admin-test"
    if head == "floorplans":
        return method in {"POST", "PUT", "PATCH", "DELETE"}
    if head == "map-data":
        return method != "GET" or not tail
    return False


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_to_mapping_microservice(path: str, request: Request, db: Session = Depends(get_db)):
    target_url = f"{MAPPING_MICROSERVICE_URL.rstrip('/')}/{path}"
    
    # Filter request headers
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in {"host", "cookie"}
    }

    if _requires_admin(request.method, path):
        if not settings.MAPPING_JWT_SECRET:
            raise HTTPException(status_code=503, detail="Mapping administrator token signing is not configured")
        admin: Admin = get_current_admin(request, db)
        cloud_token = request.cookies.get(settings.ACCESS_COOKIE_NAME) or request.headers.get("Authorization", "")[7:].strip()
        try:
            payload = jwt.decode(cloud_token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            remaining_seconds = int(payload["exp"] - time.time())
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        if remaining_seconds <= 0:
            raise HTTPException(status_code=401, detail="Session has expired or has been logged out")
        mapping_token = jwt.encode(
            {"email": admin.user.email, "type": admin.admin_type, "exp": int(time.time()) + min(remaining_seconds, 300)},
            settings.MAPPING_JWT_SECRET,
            algorithm="HS256",
        )
        headers["authorization"] = f"Bearer {mapping_token}"

    body = await request.body()
    params = request.query_params

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            microservice_response = await client.request(
                method=request.method,
                url=target_url,
                params=params,
                headers=headers,
                content=body,
            )

        # Filter response headers
        response_headers = {
            key: value
            for key, value in microservice_response.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "content-length"
        }

        return Response(
            content=microservice_response.content,
            status_code=microservice_response.status_code,
            headers=response_headers,
            media_type=microservice_response.headers.get("content-type"),
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Mapping & Navigation Microservice is unavailable. Ensure the Node.js service is running on port 5000.",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Mapping & Navigation Microservice request timed out.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Mapping Microservice proxy error: {str(exc)}",
        )
