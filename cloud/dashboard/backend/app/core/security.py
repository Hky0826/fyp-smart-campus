import hashlib
import uuid
from datetime import datetime, timedelta
import jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.models.models import Admin, JWTSession, User

# We support OAuth2 password flow
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: timedelta = None, *, session_uuid: str | None = None, jti: str | None = None) -> str:
    to_encode = data.copy()
    now = datetime.utcnow()
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": jti or uuid.uuid4().hex,
        "session_id": session_uuid or uuid.uuid4().hex,
        "principal_type": data.get("principal_type", "ADMIN"),
    })
    settings.validate_security()
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def get_sha256_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def _token_from_request(request: Request) -> str | None:
    cookie = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if cookie:
        return cookie
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> Admin:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _token_from_request(request)
    if not token:
        raise credentials_exception
    try:
        settings.validate_security()
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        admin_id: str = str(payload.get("sub")) if payload.get("sub") is not None else ""
        jti = payload.get("jti")
        session_uuid = payload.get("session_id")
        if not admin_id or not jti or not session_uuid or payload.get("principal_type") != "ADMIN":
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    token_hash = get_sha256_hash(token)
    session = db.query(JWTSession).filter_by(jti=jti, session_uuid=session_uuid, is_revoked=False).first()
    # Legacy sessions are accepted only until the migration/rotation window is
    # closed; new sessions always use jti + session_uuid.
    if session is None:
        session = db.query(JWTSession).filter_by(token_hash=token_hash, is_revoked=False).first()
    if not session or session.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or has been logged out",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    admin = db.query(Admin).filter_by(admin_id=admin_id).first()
    if not admin:
        raise credentials_exception
        
    if session.user_id != admin.user_id:
        raise credentials_exception
        
    if not admin.user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin account is deactivated")
        
    return admin

# Privilege Tier Route Guards
def verify_super_admin(admin: Admin = Depends(get_current_admin)):
    if admin.admin_type != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unprivileged access: SUPER_ADMIN level required"
        )
    return admin

def verify_system_admin(admin: Admin = Depends(get_current_admin)):
    if admin.admin_type not in ["SUPER_ADMIN", "SYSTEM_ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unprivileged access: SYSTEM_ADMIN level required"
        )
    return admin

def verify_content_admin(admin: Admin = Depends(get_current_admin)):
    if admin.admin_type not in ["SUPER_ADMIN", "CONTENT_ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unprivileged access: CONTENT_ADMIN level required"
        )
    return admin
