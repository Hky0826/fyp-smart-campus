from fastapi import APIRouter, Depends, Form, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import jwt
import uuid
import logging
import hashlib

from app.core.database import get_db
from app.core.config import settings
from app.core.security import (
    verify_password, 
    create_access_token, 
    get_sha256_hash, 
    get_current_admin,
    oauth2_scheme
)
from app.core.rate_limit import client_ip, ensure_login_allowed, record_failed_login, clear_failed_logins
from app.core.security_headers import new_csrf_token
from app.models.models import Admin, User, JWTSession, AuthenticationLog
from app.schemas.schemas import LoginRequest, Token, AdminResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

@router.post("/login", response_model=Token)
def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    ip_address = client_ip(request, settings.TRUSTED_PROXY_IPS)
    login_key = f"{ip_address}:{email.strip().lower()}"
    ensure_login_allowed(login_key)
    
    # Locate admin by email (which is on the users table)
    admin = db.query(Admin).join(User, Admin.user_id == User.user_id).filter(
        User.email == email
    ).first()
    
    if not admin or not verify_password(password, admin.Password_hash):
        record_failed_login(login_key)
        logger.warning("failed_login ip_hash=%s account_hash=%s", hashlib.sha256(ip_address.encode()).hexdigest()[:16], hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not admin.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is deactivated"
        )
        
    # Successful Login
    # Create token payload with admin_id as sub
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    session_uuid = uuid.uuid4().hex
    jti = uuid.uuid4().hex
    expires_at = datetime.utcnow() + access_token_expires
    
    session = JWTSession(
        user_id=admin.user_id,
        token_hash="pending",
        issued_at=datetime.utcnow(),
        expires_at=expires_at,
        is_revoked=False,
        session_uuid=session_uuid,
        jti=jti,
        principal_type="ADMIN",
    )
    db.add(session)
    db.flush()
    access_token = create_access_token(
        data={"sub": str(admin.admin_id), "user_id": admin.user_id, "admin_type": admin.admin_type, "principal_type": "ADMIN"},
        expires_delta=access_token_expires, session_uuid=session_uuid, jti=jti
    )
    session.token_hash = get_sha256_hash(access_token)
    db.commit()
    clear_failed_logins(login_key)
    response.set_cookie(settings.ACCESS_COOKIE_NAME, access_token, httponly=True, secure=settings.COOKIE_SECURE, samesite="lax", max_age=int(access_token_expires.total_seconds()), path="/")
    response.set_cookie(settings.CSRF_COOKIE_NAME, new_csrf_token(), httponly=False, secure=settings.COOKIE_SECURE, samesite="lax", max_age=int(access_token_expires.total_seconds()), path="/")
    
    return {
        "access_token": None,
        "token_type": "bearer",
        "admin_type": admin.admin_type,
        "email": admin.user.email,
        "full_name": admin.user.full_name,
        "admin_id": admin.admin_id
    }

@router.post("/login-json", response_model=Token)
def login_json(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    ip_address = client_ip(request, settings.TRUSTED_PROXY_IPS)
    login_key = f"{ip_address}:{login_data.email.strip().lower()}"
    ensure_login_allowed(login_key)
    
    admin = db.query(Admin).join(User, Admin.user_id == User.user_id).filter(
        User.email == login_data.email
    ).first()
    
    if not admin or not verify_password(login_data.password, admin.Password_hash):
        record_failed_login(login_key)
        logger.warning("failed_login ip_hash=%s account_hash=%s", hashlib.sha256(ip_address.encode()).hexdigest()[:16], hashlib.sha256(login_data.email.strip().lower().encode()).hexdigest()[:16])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
        
    if not admin.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is deactivated"
        )
        
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    session_uuid = uuid.uuid4().hex
    jti = uuid.uuid4().hex
    expires_at = datetime.utcnow() + access_token_expires
    
    session = JWTSession(
        user_id=admin.user_id,
        token_hash="pending",
        issued_at=datetime.utcnow(),
        expires_at=expires_at,
        is_revoked=False,
        session_uuid=session_uuid,
        jti=jti,
        principal_type="ADMIN",
    )
    db.add(session)
    db.flush()
    access_token = create_access_token(
        data={"sub": str(admin.admin_id), "user_id": admin.user_id, "admin_type": admin.admin_type, "principal_type": "ADMIN"},
        expires_delta=access_token_expires, session_uuid=session_uuid, jti=jti
    )
    session.token_hash = get_sha256_hash(access_token)
    db.commit()
    clear_failed_logins(login_key)
    response.set_cookie(settings.ACCESS_COOKIE_NAME, access_token, httponly=True, secure=settings.COOKIE_SECURE, samesite="lax", max_age=int(access_token_expires.total_seconds()), path="/")
    response.set_cookie(settings.CSRF_COOKIE_NAME, new_csrf_token(), httponly=False, secure=settings.COOKIE_SECURE, samesite="lax", max_age=int(access_token_expires.total_seconds()), path="/")
    
    return {
        "access_token": None,
        "token_type": "bearer",
        "admin_type": admin.admin_type,
        "email": admin.user.email,
        "full_name": admin.user.full_name,
        "admin_id": admin.admin_id
    }

@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    if not token:
        return {"detail": "Successfully logged out"}
    token_hash = get_sha256_hash(token)
    session = db.query(JWTSession).filter_by(token_hash=token_hash).first()
    if session:
        session.is_revoked = True
        db.commit()
    response.delete_cookie(settings.ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/")
    return {"detail": "Successfully logged out"}

@router.get("/me", response_model=AdminResponse)
def get_me(current_admin: Admin = Depends(get_current_admin)):
    return current_admin
