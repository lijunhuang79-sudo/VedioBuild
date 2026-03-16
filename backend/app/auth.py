"""JWT 认证"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# 直接使用 bcrypt，避免 passlib 在部分环境下的 72-byte 初始化报错
try:
    import bcrypt
    def _bcrypt_hash(password: str) -> str:
        p = password.encode("utf-8")[:72]
        return bcrypt.hashpw(p, bcrypt.gensalt()).decode("utf-8")
    def _bcrypt_verify(plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
except Exception:
    from passlib.context import CryptContext
    _pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    def _bcrypt_hash(password: str) -> str:
        return _pwd_ctx.hash(password.encode("utf-8")[:72].decode("utf-8", errors="ignore"))
    def _bcrypt_verify(plain: str, hashed: str) -> bool:
        return _pwd_ctx.verify(plain.encode("utf-8")[:72].decode("utf-8", errors="ignore"), hashed)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _bcrypt_verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return _bcrypt_hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    out = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    if isinstance(out, bytes):
        return out.decode("utf-8")
    return out


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已过期或无效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = int(sub) if isinstance(sub, str) else sub
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user


def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """不抛错，无 token 或无效时返回 None"""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        sub = payload.get("sub")
        if sub is None:
            return None
        user_id = int(sub) if isinstance(sub, str) else sub
    except (JWTError, ValueError):
        return None
    return db.query(User).filter(User.id == user_id).first()
