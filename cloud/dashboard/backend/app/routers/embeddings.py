from typing import Literal
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import verify_system_admin
from app.services.multi_model_embeddings import MultiModelEmbeddingService, SFACE, ARCFACE
try:
    import sys as _sys, os as _os
    _cloud_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "..", ".."))
    if _cloud_root not in _sys.path:
        _sys.path.insert(0, _cloud_root)
    from sync.cloud_to_edge.cloud_sync_service import push_sync_to_all_edges
except Exception:
    push_sync_to_all_edges = None
router = APIRouter(prefix='/embeddings', tags=['Face Embeddings'])
@router.post('/reembed-all')
def reembed_all(models: list[Literal['openvc_sface','arcface_r50']] | None = None, background_tasks: BackgroundTasks = None, db: Session = Depends(get_db), current_admin=Depends(verify_system_admin)):
    result = MultiModelEmbeddingService().reembed_all(db, tuple(models or (SFACE, ARCFACE)))
    if push_sync_to_all_edges and background_tasks:
        background_tasks.add_task(push_sync_to_all_edges, db)
    return result
