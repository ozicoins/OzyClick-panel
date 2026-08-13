import hmac
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from auth import (
    create_access_token,
    verify_password,
    hash_password,
    decode_token,
    revocation_key,
    extract_token,
    get_current_user,
    security,
    COOKIE_NAME,
)
from config import settings
from rate_limit import rate_limit

router = APIRouter()

# Admin parola doğrulaması bcrypt üzerinden yapılır. Tercihen ADMIN_PASSWORD_HASH
# (bcrypt hash) kullanılır; yoksa ADMIN_PASSWORD başlangıçta bir kez hash'lenir.
_ADMIN_HASH = settings.admin_password_hash or hash_password(settings.admin_password)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _set_auth_cookie(response: Response, token: str) -> None:
    # httpOnly → JavaScript okuyamaz (XSS token çalamaz).
    # SameSite=strict → CSRF koruması. Secure → yalnızca HTTPS (production).
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )


_PW_KEY = "admin:password_hash"   # kullanıcı panelden değiştirirse buraya yazılır (redis-first)


async def _active_hash(redis) -> str:
    """Aktif parola hash'i: kullanıcı panelden değiştirdiyse redis'teki, yoksa .env'deki."""
    if redis is not None:
        try:
            stored = await redis.get(_PW_KEY)
            if stored:
                return stored.decode() if isinstance(stored, (bytes, bytearray)) else stored
        except Exception:
            pass
    return _ADMIN_HASH


async def _authenticate(req: LoginRequest, redis) -> str:
    # verify_password her durumda çalıştırılır (kullanıcı adı yanlış olsa bile)
    # → timing üzerinden kullanıcı adı sızıntısını önler.
    username_ok = hmac.compare_digest(
        req.username.encode("utf-8"), settings.admin_username.encode("utf-8")
    )
    password_ok = verify_password(req.password, await _active_hash(redis))
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return create_access_token({"sub": req.username, "role": "admin"})


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    _rl: None = Depends(rate_limit(5, 60, "login")),
):
    token = await _authenticate(req, getattr(request.app.state, "redis", None))
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token)


@router.post("/token", response_model=TokenResponse)
async def refresh_token(
    req: LoginRequest,
    request: Request,
    response: Response,
    _rl: None = Depends(rate_limit(5, 60, "login")),
):
    token = await _authenticate(req, getattr(request.app.state, "redis", None))
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    _user: dict = Depends(get_current_user),
):
    redis = getattr(request.app.state, "redis", None)
    if not verify_password(req.current_password, await _active_hash(redis)):
        raise HTTPException(status_code=400, detail="Mevcut şifre yanlış")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Yeni şifre en az 8 karakter olmalı")
    if redis is None:
        raise HTTPException(status_code=503, detail="Depolama yok — şifre değiştirilemedi")
    await redis.set(_PW_KEY, hash_password(req.new_password))
    return {"status": "ok", "detail": "Şifre değiştirildi. Bir sonraki girişte yeni şifreyi kullanın."}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Tarayıcı, httpOnly cookie geçerli mi diye bunu çağırır (token'ı JS okuyamaz)."""
    return {"authenticated": True, "username": user.get("sub"), "role": user.get("role")}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    token = extract_token(request, credentials)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(token)  # imzayı doğrular

    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        ttl = int(payload.get("exp", 0) - time.time())
        if ttl > 0:
            try:
                await redis.set(revocation_key(token), "1", ex=ttl)
            except Exception:
                pass

    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "logged_out"}
