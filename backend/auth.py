import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from passlib.context import CryptContext
from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    # Benzersiz token kimliği → her token farklı; revocation kesin çalışır
    # (aynı saniyedeki iki login artık aynı token'ı üretmez).
    to_encode["jti"] = secrets.token_urlsafe(16)
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )
    return payload


def revocation_key(token: str) -> str:
    return "revoked:" + hashlib.sha256(token.encode()).hexdigest()


async def is_token_revoked(redis, token: str) -> bool:
    if redis is None:
        return False
    try:
        return bool(await redis.exists(revocation_key(token)))
    except Exception:
        return False


COOKIE_NAME = "iu_token"


def extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    # Öncelik: Authorization header (API istemcileri) → httpOnly cookie (tarayıcı).
    if credentials is not None:
        return credentials.credentials
    return request.cookies.get(COOKIE_NAME)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    token = extract_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = decode_token(token)
    redis = getattr(request.app.state, "redis", None)
    if await is_token_revoked(redis, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token iptal edildi",
        )
    return payload


def verify_ws_token(token: str) -> dict:
    return decode_token(token)
