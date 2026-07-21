from fastapi import APIRouter, Depends, Form, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import jwt

from app.core.database import get_db
from app.core.config import settings
from app.core.security import (
    verify_password, 
    create_access_token, 
    get_sha256_hash, 
    get_current_admin,
    oauth2_scheme
)
from app.models.models import Admin, User, JWTSession, AuthenticationLog
from app.schemas.schemas import LoginRequest, Token, AdminResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=Token)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    ip_address = request.client.host if request.client else None
    
    # Locate admin by email (which is on the users table)
    admin = db.query(Admin).join(User, Admin.user_id == User.user_id).filter(
        User.email == email
    ).first()
    
    if not admin or not verify_password(password, admin.Password_hash):
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
    access_token = create_access_token(
        data={"sub": admin.admin_id, "admin_type": admin.admin_type},
        expires_delta=access_token_expires
    )
    
    # Store token hash in database jwt_sessions
    token_hash = get_sha256_hash(access_token)
    expires_at = datetime.utcnow() + access_token_expires
    
    session = JWTSession(
        user_id=admin.user_id,
        token_hash=token_hash,
        issued_at=datetime.utcnow(),
        expires_at=expires_at,
        is_revoked=False
    )
    db.add(session)
    
    db.commit()
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "admin_type": admin.admin_type,
        "email": admin.user.email,
        "full_name": admin.user.full_name,
        "admin_id": admin.admin_id
    }

@router.post("/login-json", response_model=Token)
def login_json(
    request: Request,
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    ip_address = request.client.host if request.client else None
    
    admin = db.query(Admin).join(User, Admin.user_id == User.user_id).filter(
        User.email == login_data.email
    ).first()
    
    if not admin or not verify_password(login_data.password, admin.Password_hash):
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
    access_token = create_access_token(
        data={"sub": admin.admin_id, "admin_type": admin.admin_type},
        expires_delta=access_token_expires
    )
    
    token_hash = get_sha256_hash(access_token)
    expires_at = datetime.utcnow() + access_token_expires
    
    session = JWTSession(
        user_id=admin.user_id,
        token_hash=token_hash,
        issued_at=datetime.utcnow(),
        expires_at=expires_at,
        is_revoked=False
    )
    db.add(session)
    
    db.commit()
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "admin_type": admin.admin_type,
        "email": admin.user.email,
        "full_name": admin.user.full_name,
        "admin_id": admin.admin_id
    }

@router.post("/logout")
def logout(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    token_hash = get_sha256_hash(token)
    session = db.query(JWTSession).filter_by(token_hash=token_hash).first()
    if session:
        session.is_revoked = True
        db.commit()
    return {"detail": "Successfully logged out"}

@router.get("/me", response_model=AdminResponse)
def get_me(current_admin: Admin = Depends(get_current_admin)):
    return current_admin
