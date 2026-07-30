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
    oauth2_scheme,
    get_password_hash,
    validate_strong_password,
    issue_password_reset_token,
)
from app.core.rate_limit import client_ip, ensure_login_allowed, record_failed_login, clear_failed_logins
from app.core.security_headers import new_csrf_token
from app.models.models import Admin, User, JWTSession, AuthenticationLog
from app.schemas.schemas import LoginRequest, Token, AdminResponse
from app.schemas import schemas

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
        "admin_id": admin.admin_id,
        "must_change_password": bool(admin.must_change_password),
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
        "admin_id": admin.admin_id,
        "must_change_password": bool(admin.must_change_password),
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


@router.post("/password/change")
def change_password(
    body: dict,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Change a password and revoke every prior session for the account."""
    try:
        password = validate_strong_password(body.get("password", ""), name_parts=(current_admin.user.given_name, current_admin.user.family_name, current_admin.user.email))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Password does not meet security requirements") from exc
    current_admin.password_hash = get_password_hash(password)
    current_admin.must_change_password = False
    current_admin.reset_token_hash = None
    current_admin.reset_token_expires_at = None
    for session in current_admin.user.sessions:
        session.is_revoked = True
    db.commit()
    return {"detail": "Password changed; sign in again"}


@router.post("/password-reset/request")
def request_password_reset(body: schemas.PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    """Always return the same response; delivery is handled out of band."""
    from app.core.rate_limit import enforce_limit
    enforce_limit(f"password-reset:{client_ip(request, settings.TRUSTED_PROXY_IPS)}", 5, 900)
    admin = db.query(Admin).join(User, Admin.user_id == User.user_id).filter(User.email == str(body.email)).first()
    if admin and admin.user.is_active:
        issue_password_reset_token(admin, db)
        db.commit()
        logger.info("password_reset_requested account_hash=%s", hashlib.sha256(str(body.email).encode()).hexdigest()[:16])
    return {"detail": "If the account exists, reset instructions will be sent"}


@router.post("/password-reset/confirm")
def confirm_password_reset(body: schemas.PasswordResetConfirm, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    admin = db.query(Admin).filter(Admin.reset_token_hash == token_hash).first()
    if not admin or not admin.reset_token_expires_at or admin.reset_token_expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")
    try:
        password = validate_strong_password(body.password, name_parts=(admin.user.given_name, admin.user.family_name, admin.user.email))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Password does not meet security requirements") from exc
    admin.password_hash = get_password_hash(password)
    admin.must_change_password = False
    admin.reset_token_hash = None
    admin.reset_token_expires_at = None
    for session in admin.user.sessions:
        session.is_revoked = True
    db.commit()
    return {"detail": "Password reset successful; sign in again"}
