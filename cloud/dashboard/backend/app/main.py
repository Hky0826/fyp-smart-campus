import os
import sys

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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse

from app.routers import auth, iam, rag, infrastructure, academics, references, embeddings
from app.routers.edge_auth import router as edge_auth_router
from sync.cloud_to_edge import cloud_sync_service as downstream_sync
from sync.edge_to_cloud import cloud_sync_service as upstream_sync
from app.core.database import Base, engine
from RagChatbot.router import router as chatbot_router

# Create the FastAPI app instance
app = FastAPI(
    title="Smart Campus Administrative Dashboard Backend",
    description="Enterprise-grade administrative API and database manager.",
    version="1.0.0"
)

# CORS Middleware Configuration
# Allows React frontend (e.g. running on Vite dev server port 5173) to consume APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict to trusted domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# Redirect root to /dashboard/
@app.get("/")
def redirect_to_dashboard():
    return RedirectResponse(url="/dashboard/")

# Mount the static files directory to serve the CDN-based React SPA
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

@app.get("/dashboard/{full_path:path}", include_in_schema=False)
def dashboard_spa_fallback(full_path: str):
    return FileResponse(os.path.join(static_dir, "index.html"))

# Mount the folder under '/dashboard' path. 
# Anything in the 'static' folder (like index.html) will be served.
app.mount("/static", StaticFiles(directory=static_dir), name="static-assets")
app.mount("/dashboard", StaticFiles(directory=static_dir, html=True), name="static")

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Smart Campus Dashboard API"}
