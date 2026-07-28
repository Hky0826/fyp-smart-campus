import os
import shutil
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.security import verify_content_admin
from app.models.models import UploadedDocument, DocumentChunk, EmbeddingVector, ChatbotQuery
from app.schemas import schemas

# Determine upload directory based on the location of this file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads", "documents")
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/rag", tags=["RAG Knowledge Base & Documents"])

def background_ingest(document_id: int, force_reindex: bool = False):
    from app.core.database import SessionLocal
    from RagChatbot.services.ingestion_service import ingest_document
    import logging
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        doc = db.query(UploadedDocument).filter_by(document_id=document_id).first()
        if doc:
            doc.chunking_status = "PROCESSING"
            db.commit()
            
        logger.info(f"Starting background ingestion for document_id={document_id} (force_reindex={force_reindex})")
        result = ingest_document(document_id, db, force_reindex=force_reindex)
        logger.info(f"Finished background ingestion for document_id={document_id}")
        
        doc = db.query(UploadedDocument).filter_by(document_id=document_id).first()
        if doc:
            doc.chunking_status = result.status
            db.commit()
    except Exception as e:
        logger.error(f"Failed background ingestion for document_id={document_id}: {e}", exc_info=True)
        doc = db.query(UploadedDocument).filter_by(document_id=document_id).first()
        if doc:
            doc.chunking_status = "FAILED"
            db.commit()
    finally:
        db.close()

# ==========================================
# UPLOADED DOCUMENTS CRUD (CONTENT_ADMIN or SUPER_ADMIN)
# ==========================================
@router.get("/documents", response_model=List[schemas.UploadedDocumentResponse])
def list_documents(db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    return db.query(UploadedDocument).all()

@router.post("/documents", response_model=schemas.UploadedDocumentResponse)
def create_document(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    access_level: str = Form(...),
    uploaded_by: int = Form(...),
    is_active: bool = Form(True),
    file: UploadFile = File(None),
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    filename = ""
    file_path = ""
    if file:
        filename = file.filename
        file_path = os.path.join(UPLOAD_DIR, filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    doc = UploadedDocument(
        title=title,
        filename=filename,
        file_path=file_path,
        uploaded_by=uploaded_by,
        access_level=access_level,
        is_active=is_active
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    if file:
        # Trigger ingestion asynchronously in background
        background_tasks.add_task(background_ingest, doc.document_id, False)
        
    return doc

@router.put("/documents/{document_id}", response_model=schemas.UploadedDocumentResponse)
def update_document(
    document_id: int, 
    background_tasks: BackgroundTasks,
    title: str = Form(None),
    access_level: str = Form(None),
    uploaded_by: int = Form(None),
    is_active: bool = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    doc = db.query(UploadedDocument).filter_by(document_id=document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    if title is not None: doc.title = title
    if access_level is not None: doc.access_level = access_level
    if uploaded_by is not None: doc.uploaded_by = uploaded_by
    if is_active is not None: doc.is_active = is_active
    
    if file:
        filename = file.filename
        file_path = os.path.join(UPLOAD_DIR, filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        doc.filename = filename
        doc.file_path = file_path
        
    db.commit()
    db.refresh(doc)
    
    if file:
        # Trigger re-ingestion in background if a new file is uploaded
        background_tasks.add_task(background_ingest, doc.document_id, True)
        
    return doc


@router.post("/documents/{document_id}/toggle-active")
def toggle_document_active(document_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    doc = db.query(UploadedDocument).filter_by(document_id=document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.is_active = not doc.is_active
    # Toggle chunks active/outdated accordingly
    for chunk in doc.chunks:
        chunk.is_outdated = not doc.is_active
    db.commit()
    from RagChatbot.retrieval.vector_store import vector_store
    if not doc.is_active:
        vector_store.remove_document(document_id)
    elif vector_store.is_loaded:
        vector_store.load_from_db(db)
    return {"detail": f"Document active status toggled. Active: {doc.is_active}"}

@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    doc = db.query(UploadedDocument).filter_by(document_id=document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    from RagChatbot.retrieval.vector_store import vector_store
    vector_store.remove_document(document_id)
    # Cascade delete clears the durable chunks and embedding vectors.
    db.delete(doc)
    db.commit()
    return {"detail": "Document and all corresponding chunks/embeddings deleted successfully"}

# ==========================================
# DOCUMENT CHUNKS (READ-ONLY DIAGNOSTICS)
# ==========================================
@router.get("/chunks", response_model=List[schemas.DocumentChunkResponse])
def list_all_chunks(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    return db.query(DocumentChunk).offset(skip).limit(limit).all()

@router.get("/documents/{document_id}/chunks", response_model=List[schemas.DocumentChunkResponse])
def list_document_chunks(
    document_id: int, 
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    doc = db.query(UploadedDocument).filter_by(document_id=document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc.chunks

# ==========================================
# EMBEDDING VECTORS (READ-ONLY DIAGNOSTICS)
# ==========================================
@router.get("/embeddings", response_model=List[schemas.EmbeddingVectorResponse])
def list_embeddings(
    skip: int = 0, 
    limit: int = 50, 
    chunk_id: Optional[int] = None, 
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    query = db.query(EmbeddingVector)
    if chunk_id is not None:
        query = query.filter_by(chunk_id=chunk_id)
    return query.offset(skip).limit(limit).all()

# ==========================================
# CHATBOT QUERIES (READ-ONLY AUDIT MONITOR)
# ==========================================
@router.get("/chatbot-queries", response_model=List[schemas.ChatbotQueryResponse])
def list_chatbot_queries(
    skip: int = 0, 
    limit: int = 50, 
    user_id: Optional[int] = None,
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    query = db.query(ChatbotQuery)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    return query.order_by(ChatbotQuery.timestamp.desc()).offset(skip).limit(limit).all()
