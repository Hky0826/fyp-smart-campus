"""Reverse Proxy Router forwarding /api/mapping-notification requests to Node.js Microservice."""

import os
import httpx
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse

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


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_to_mapping_microservice(path: str, request: Request):
    target_url = f"{MAPPING_MICROSERVICE_URL.rstrip('/')}/{path}"
    
    # Filter request headers
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
    }

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
