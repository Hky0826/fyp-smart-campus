import os
import json
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from typing import List, Optional

from app.core.database import get_db
from app.core.security import verify_content_admin
from app.models.models import UploadedDocument, DocumentChunk, EmbeddingVector, ChatbotQuery, User, SpeechLanguage, SpeechAdaptationPhrase
from app.schemas import schemas
from app.core.config import settings
from app.core.private_storage import save_upload, safe_existing_path, ALLOWED_DOCUMENT_EXTENSIONS
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

def _parse_form_roles(raw_roles: Optional[str], fallback_access_level: Optional[str] = None) -> List[str]:
    """Helper to parse allowed_roles form parameter."""
    valid_roles = {"VISITOR", "STUDENT", "LECTURER", "STAFF", "ADMIN"}
    parsed: List[str] = []
    if raw_roles:
        try:
            val = json.loads(raw_roles)
            if isinstance(val, list):
                parsed = [str(r).upper() for r in val if str(r).upper() in valid_roles]
            elif isinstance(val, str) and val.upper() in valid_roles:
                parsed = [val.upper()]
        except Exception:
            parsed = [r.strip().upper() for r in raw_roles.split(",") if r.strip().upper() in valid_roles]

    if not parsed and fallback_access_level:
        lvl = str(fallback_access_level).upper()
        if lvl == "PUBLIC":
            parsed = ["VISITOR"]
        elif lvl in valid_roles:
            parsed = [lvl]

    return parsed if parsed else ["VISITOR"]


@router.post("/documents", response_model=schemas.UploadedDocumentResponse)
async def create_document(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    access_level: Optional[str] = Form(None),
    allowed_roles: Optional[str] = Form(None),
    uploaded_by: int = Form(...),
    category: str = Form("GENERAL"),
    faculty_code: Optional[str] = Form(None),
    target_audience: str = Form("ALL"),
    validity_year: Optional[int] = Form(None),
    is_active: bool = Form(True),
    file: UploadFile = File(None),
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    filename = ""
    file_path = ""
    if file:
        filename, stored_path = await save_upload(file, "documents", ALLOWED_DOCUMENT_EXTENSIONS, settings.MAX_DOCUMENT_BYTES)
        file_path = filename

    resolved_roles = _parse_form_roles(allowed_roles, access_level)
    primary_role = resolved_roles[0] if resolved_roles else "VISITOR"

    doc = UploadedDocument(
        title=title,
        filename=filename,
        file_path=file_path,
        uploaded_by=current_admin.user_id,
        access_level=primary_role,
        allowed_roles=resolved_roles,
        category=category,
        faculty_code=faculty_code,
        target_audience=target_audience,
        validity_year=validity_year,
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
async def update_document(
    document_id: int, 
    background_tasks: BackgroundTasks,
    title: str = Form(None),
    access_level: Optional[str] = Form(None),
    allowed_roles: Optional[str] = Form(None),
    uploaded_by: int = Form(None),
    category: Optional[str] = Form(None),
    faculty_code: Optional[str] = Form(None),
    target_audience: Optional[str] = Form(None),
    validity_year: Optional[int] = Form(None),
    is_active: bool = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    doc = db.query(UploadedDocument).filter_by(document_id=document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    if title is not None: doc.title = title
    if category is not None: doc.category = category
    if faculty_code is not None: doc.faculty_code = faculty_code
    if target_audience is not None: doc.target_audience = target_audience
    if validity_year is not None: doc.validity_year = validity_year

    if allowed_roles is not None or access_level is not None:
        resolved_roles = _parse_form_roles(allowed_roles, access_level)
        doc.allowed_roles = resolved_roles
        doc.access_level = resolved_roles[0] if resolved_roles else "VISITOR"
        for chunk in doc.chunks:
            chunk.allowed_roles = resolved_roles
            chunk.access_level = doc.access_level

    doc.uploaded_by = current_admin.user_id
    if is_active is not None: doc.is_active = is_active
    
    if file:
        filename, stored_path = await save_upload(file, "documents", ALLOWED_DOCUMENT_EXTENSIONS, settings.MAX_DOCUMENT_BYTES)
        file_path = filename
        doc.filename = filename
        doc.file_path = file_path
        
    db.commit()
    db.refresh(doc)
    
    if file:
        # Trigger re-ingestion in background if a new file is uploaded
        background_tasks.add_task(background_ingest, doc.document_id, True)
    elif allowed_roles is not None or access_level is not None:
        from RagChatbot.retrieval.vector_store import vector_store
        if vector_store.is_loaded:
            vector_store.load_from_db(db)
        
    return doc


@router.get("/documents/{document_id}/download", include_in_schema=False)
def download_document(document_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    doc = db.query(UploadedDocument).filter_by(document_id=document_id, is_active=True).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = safe_existing_path("documents", doc.file_path)
    return FileResponse(path, media_type="application/octet-stream", filename="document", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


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
    limit: int = 100, 
    user_id: Optional[int] = None,
    category: Optional[str] = None,
    is_navigational: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db), 
    current_admin=Depends(verify_content_admin)
):
    query = db.query(ChatbotQuery).options(
        joinedload(ChatbotQuery.user).joinedload(User.roles)
    )
    if user_id is not None:
        query = query.filter(ChatbotQuery.user_id == user_id)
    if category is not None and category.upper() != "ALL":
        query = query.filter(ChatbotQuery.query_category == category.lower())
    if is_navigational is not None:
        query = query.filter(ChatbotQuery.is_navigational == is_navigational)
    if search:
        search_pattern = f"%{search}%"
        query = query.join(ChatbotQuery.user, isouter=True).filter(
            or_(
                ChatbotQuery.query_text.ilike(search_pattern),
                ChatbotQuery.response_text.ilike(search_pattern),
                User.given_name.ilike(search_pattern),
                User.family_name.ilike(search_pattern),
                User.email.ilike(search_pattern),
            )
        )
    records = query.order_by(ChatbotQuery.timestamp.desc()).offset(skip).limit(limit).all()

    results = []
    for r in records:
        user_name = r.user.full_name if r.user else "Anonymous Visitor"
        user_email = r.user.email if r.user else None
        user_role = r.user.roles[0].role_name if (r.user and r.user.roles) else ("VISITOR" if not r.user else "USER")
        results.append(schemas.ChatbotQueryResponse(
            query_id=r.query_id,
            session_id=r.session_id,
            user_id=r.user_id,
            query_text=r.query_text,
            query_category=r.query_category,
            response_text=r.response_text,
            retrieved_chunks=r.retrieved_chunks,
            response_time_ms=r.response_time_ms,
            is_navigational=r.is_navigational,
            timestamp=r.timestamp,
            user_name=user_name,
            user_email=user_email,
            user_role=user_role
        ))
    return results


# ==========================================
# SPEECH LANGUAGES & SPEECH ADAPTATION PHRASES
# ==========================================

@router.get("/speech-languages", response_model=List[schemas.SpeechLanguageResponse])
def list_speech_languages(db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    return db.query(SpeechLanguage).order_by(SpeechLanguage.is_default.desc(), SpeechLanguage.language_name.asc()).all()

@router.post("/speech-languages", response_model=schemas.SpeechLanguageResponse, status_code=status.HTTP_201_CREATED)
def create_speech_language(
    payload: schemas.SpeechLanguageCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_content_admin)
):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    code = payload.language_code.lower().strip()
    if not code:
        raise HTTPException(status_code=400, detail="Language code cannot be empty.")
    if len(code) > 10:
        raise HTTPException(status_code=400, detail="Language code cannot exceed 10 characters.")
    
    existing = db.query(SpeechLanguage).filter(SpeechLanguage.language_code == code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Language code '{code}' already exists.")
    
    name = payload.language_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Language name cannot be empty.")

    lang = SpeechLanguage(
        language_code=code,
        language_name=name,
        is_default=payload.is_default,
        is_active=payload.is_active,
    )
    db.add(lang)
    db.commit()
    db.refresh(lang)
    return lang

@router.delete("/speech-languages/{code}", status_code=status.HTTP_200_OK)
def delete_speech_language(
    code: str,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_content_admin)
):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    clean_code = code.lower().strip()
    lang = db.query(SpeechLanguage).filter(SpeechLanguage.language_code == clean_code).first()
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found.")
    
    db.delete(lang)
    db.commit()
    return {"message": f"Language '{clean_code}' deleted successfully."}

@router.post("/speech-languages/{code}/toggle-default", response_model=schemas.SpeechLanguageResponse)
def toggle_language_default(code: str, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    lang = db.query(SpeechLanguage).filter(SpeechLanguage.language_code == code.lower().strip()).first()
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found")
    lang.is_default = not lang.is_default
    if lang.is_default:
        lang.is_active = True
    db.commit()
    db.refresh(lang)
    return lang

@router.post("/speech-languages/{code}/toggle-active", response_model=schemas.SpeechLanguageResponse)
def toggle_language_active(code: str, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    lang = db.query(SpeechLanguage).filter(SpeechLanguage.language_code == code.lower().strip()).first()
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found")
    lang.is_active = not lang.is_active
    if not lang.is_active:
        lang.is_default = False
    db.commit()
    db.refresh(lang)
    return lang

@router.get("/adaptation-phrases", response_model=List[schemas.SpeechAdaptationPhraseResponse])
def list_adaptation_phrases(
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_content_admin)
):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    query = db.query(SpeechAdaptationPhrase)
    if category and category.upper() != "ALL":
        query = query.filter(SpeechAdaptationPhrase.language_category == category.upper().strip())
    if is_active is not None:
        query = query.filter(SpeechAdaptationPhrase.is_active == is_active)
    if q:
        pat = f"%{q.strip()}%"
        query = query.filter(
            or_(
                SpeechAdaptationPhrase.phrase.ilike(pat),
                SpeechAdaptationPhrase.description.ilike(pat),
                SpeechAdaptationPhrase.language_category.ilike(pat),
            )
        )
    return query.order_by(SpeechAdaptationPhrase.language_category.asc(), SpeechAdaptationPhrase.phrase.asc()).offset(skip).limit(limit).all()

@router.get("/adaptation-phrases/categories")
def get_adaptation_categories(db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    records = db.query(SpeechAdaptationPhrase.language_category).distinct().all()
    categories = sorted({r[0].upper() for r in records if r[0]})
    base_cats = ["CAMPUS", "ACADEMIC", "ENGLISH", "MALAY", "CHINESE", "CANTONESE", "GENERAL"]
    all_cats = sorted(set(base_cats + categories))
    return {"categories": all_cats}

@router.post("/adaptation-phrases", response_model=schemas.SpeechAdaptationPhraseResponse)
def create_adaptation_phrase(payload: schemas.SpeechAdaptationPhraseCreate, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    cleaned_phrase = payload.phrase.strip()
    if not cleaned_phrase:
        raise HTTPException(status_code=400, detail="Phrase cannot be empty")
    cat = (payload.language_category or "GENERAL").upper().strip()
    existing = db.query(SpeechAdaptationPhrase).filter(SpeechAdaptationPhrase.phrase.ilike(cleaned_phrase)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Phrase '{cleaned_phrase}' already exists")
    record = SpeechAdaptationPhrase(
        phrase=cleaned_phrase,
        language_category=cat,
        description=payload.description.strip() if payload.description else None,
        is_active=payload.is_active,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record

@router.put("/adaptation-phrases/{phrase_id}", response_model=schemas.SpeechAdaptationPhraseResponse)
def update_adaptation_phrase(phrase_id: int, payload: schemas.SpeechAdaptationPhraseUpdate, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    record = db.query(SpeechAdaptationPhrase).filter_by(phrase_id=phrase_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Phrase not found")
    if payload.phrase is not None:
        cleaned = payload.phrase.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Phrase cannot be empty")
        existing = db.query(SpeechAdaptationPhrase).filter(SpeechAdaptationPhrase.phrase.ilike(cleaned), SpeechAdaptationPhrase.phrase_id != phrase_id).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Phrase '{cleaned}' already exists")
        record.phrase = cleaned
    if payload.language_category is not None:
        record.language_category = payload.language_category.upper().strip()
    if payload.description is not None:
        record.description = payload.description.strip() if payload.description else None
    if payload.is_active is not None:
        record.is_active = payload.is_active
    db.commit()
    db.refresh(record)
    return record

@router.delete("/adaptation-phrases/{phrase_id}")
def delete_adaptation_phrase(phrase_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    record = db.query(SpeechAdaptationPhrase).filter_by(phrase_id=phrase_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Phrase not found")
    db.delete(record)
    db.commit()
    return {"status": "deleted", "phrase_id": phrase_id}

@router.post("/adaptation-phrases/{phrase_id}/toggle-active", response_model=schemas.SpeechAdaptationPhraseResponse)
def toggle_adaptation_phrase_active(phrase_id: int, db: Session = Depends(get_db), current_admin=Depends(verify_content_admin)):
    from app.db_init import ensure_speech_tables_and_seed
    ensure_speech_tables_and_seed(db)
    record = db.query(SpeechAdaptationPhrase).filter_by(phrase_id=phrase_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Phrase not found")
    record.is_active = not record.is_active
    db.commit()
    db.refresh(record)
    return record

