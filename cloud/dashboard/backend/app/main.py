import os
import sys
import uuid
import logging

# Add the parent directory of 'app' to sys.path so Python can find the 'app' module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Add project root directory to sys.path to import sync modules from the 'sync' folder
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Add the 'cloud' directory to sys.path so RagChatbot package can be resolved
cloud_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if cloud_root not in sys.path:
    sys.path.insert(0, cloud_root)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, PlainTextResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

from app.routers import auth, iam, rag, infrastructure, academics, references, embeddings
from app.routers.edge_auth import router as edge_auth_router
from sync.cloud_to_edge import cloud_sync_service as downstream_sync
from sync.edge_to_cloud import cloud_sync_service as upstream_sync
from app.core.database import Base, engine, SessionLocal
from app.core.config import settings
from app.core.csrf import CSRFMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from RagChatbot.router import router as chatbot_router
from cloud.mapping_and_notification.api.router import router as mapping_notification_router

# Create the FastAPI app instance
app = FastAPI(
    title="Smart Campus Administrative Dashboard Backend",
    description="Enterprise-grade administrative API and database manager.",
    version="1.0.0"
)
logger = logging.getLogger("smart-campus.api")


@app.middleware("http")
async def correlation_context(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID")
    if not correlation_id or len(correlation_id) > 64 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in correlation_id):
        correlation_id = uuid.uuid4().hex
    request.state.correlation_id = correlation_id
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request failure correlation_id=%s method=%s path=%s", correlation_id, request.method, request.url.path)
        response = JSONResponse(status_code=500, content={"detail": "Request could not be completed", "correlation_id": correlation_id})
    response.headers["X-Correlation-ID"] = correlation_id
    return response
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)


@app.middleware("http")
async def block_legacy_private_paths(request, call_next):
    if request.url.path.startswith(("/static/uploads", "/dashboard/uploads")):
        return PlainTextResponse("Not found", status_code=404)
    return await call_next(request)

@app.on_event("startup")
def load_vector_store():
    settings.validate_security()
    from RagChatbot.retrieval.vector_store import vector_store
    with SessionLocal() as db:
        vector_store.load_from_db(db)

# CORS Middleware Configuration
# Allows React frontend (e.g. running on Vite dev server port 5173) to consume APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.DASHBOARD_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Device-ID", "X-Device-Timestamp", "X-Device-Nonce", "X-Device-Signature"],
)

# Register API routers with '/api' prefix
app.include_router(auth.router, prefix="/api")
app.include_router(iam.router, prefix="/api")
app.include_router(embeddings.router, prefix="/api")
app.include_router(rag.router, prefix="/api")
app.include_router(infrastructure.router, prefix="/api")
app.include_router(academics.router, prefix="/api")
app.include_router(references.router, prefix="/api")
app.include_router(downstream_sync.router, prefix="/api")
app.include_router(upstream_sync.router, prefix="/api")

# Edge authentication: issues user JWTs after face recognition
app.include_router(edge_auth_router, prefix="/api")

# RAG Chatbot endpoints – available to edge devices and admin UI
app.include_router(chatbot_router, prefix="/api")
app.include_router(mapping_notification_router, prefix="/api/mapping-notification")


# Redirect root to /dashboard/
@app.get("/")
def redirect_to_dashboard():
    return RedirectResponse(url="/dashboard/")

# Mount the static files directory to serve the locally built dashboard SPA
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

@app.get("/dashboard/{full_path:path}", include_in_schema=False)
def dashboard_spa_fallback(full_path: str):
    return FileResponse(os.path.join(static_dir, "index.html"))

# Only the built dashboard assets are served here. Private uploads are stored
# under settings.PRIVATE_STORAGE_ROOT and have authenticated download routes.
app.mount("/static", StaticFiles(directory=static_dir), name="static-assets")
app.mount("/dashboard", StaticFiles(directory=static_dir, html=True), name="static")

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Smart Campus Dashboard API"}
