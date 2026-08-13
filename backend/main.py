import asyncio
import logging
import os
import stat
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database.connection import init_db, close_db, get_redis, close_redis

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# GÜVENLİK: bu süreçin oluşturduğu TÜM dosyalar (profil JSON'ları = canlı Google
# çerezleri, loglar) yalnızca sahibe okunur/yazılır olsun (0600 dosya / 0700 dizin).
# Aksi halde çok kullanıcılı sunucuda başka bir yerel kullanıcı çerezleri okuyabilirdi.
os.umask(0o077)

logger = logging.getLogger("startup")


def _check_credential_file_perms():
    """Hassas dosyalar (gmail.csv, .env) grup/diğer kullanıcılarca okunabilirse uyar."""
    base = os.path.dirname(__file__)
    parent = os.path.dirname(base)
    candidates = [
        os.path.join(base, "gmail.csv"),
        os.path.join(parent, "gmail.csv"),
        os.path.join(base, ".env"),
        os.path.join(parent, ".env"),
    ]
    for path in candidates:
        if os.path.exists(path):
            mode = os.stat(path).st_mode
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                logger.warning(
                    "GÜVENLİK: %s grup/diğer kullanıcılar tarafından erişilebilir. "
                    "`chmod 600 %s` çalıştırın.",
                    path, os.path.basename(path),
                )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_credential_file_perms()
    # GÜVENLİK: CREDENTIAL_KEY yoksa hesap parolaları/2FA sırları Redis'e DÜZ METİN yazılır.
    from services import crypto
    if not crypto.is_enabled():
        logger.warning(
            "GÜVENLİK: CREDENTIAL_KEY ayarlı değil — hesap parolaları/2FA sırları at-rest "
            "ŞİFRELENMEDEN saklanıyor. Üretimde .env'e CREDENTIAL_KEY ekleyin "
            "(python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")."
        )
    await init_db()
    app.state.redis = await get_redis()
    # Keep-alive arka plan döngüsü — aktifse periyodik ping atar.
    from services.keepalive_service import keepalive_loop
    app.state.keepalive_task = asyncio.create_task(keepalive_loop(app))
    yield
    task = getattr(app.state, "keepalive_task", None)
    if task:
        task.cancel()
    await close_redis()
    await close_db()


app = FastAPI(
    title="OzyClick — Gmail Cookie & Playwright Storage State Generator",
    version="2.0.0",
    lifespan=lifespan,
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
        return response


class OriginEnforcementMiddleware(BaseHTTPMiddleware):
    """CSRF backstop: state-changing isteklerde Origin'i doğrular.

    Cookie-auth ile, SameSite=strict'e ek olarak sunucu-taraflı bir kontrol.
    Multipart CSV upload gibi preflight'ı atlayan istekleri de kapsar.
    Origin yoksa (browser dışı API istemcisi) geçirilir; varsa CORS listesinde olmalı.
    """
    _SAFE = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request: Request, call_next):
        if request.method not in self._SAFE:
            origin = request.headers.get("origin")
            if origin is not None and origin not in settings.cors_origins_list:
                return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(OriginEnforcementMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# TÜM modeller burada import edilmeli: relationship("Session") gibi string referanslar
# ancak sınıf kayıtlıysa çözülür. (Eskiden Session'ı routers/sessions.py dolaylı olarak
# import ediyordu; o kaldırılınca mapper "failed to locate 'Session'" hatası verdi.)
import models.user  # noqa: E402, F401
import models.session  # noqa: E402, F401
import models.batch  # noqa: E402, F401
import models.audit_log  # noqa: E402, F401
from routers import auth, farming, inspector, keywords, export, upload, sessions, system, proxy, runtime, targets, settings as settings_router  # noqa: E402

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])
app.include_router(farming.router, prefix="/api/v1", tags=["Farming"])
app.include_router(inspector.router, prefix="/api/v1", tags=["Inspector"])
app.include_router(keywords.router, prefix="/api/v1", tags=["Keywords"])
app.include_router(export.router, prefix="/api/v1", tags=["Export"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Sessions"])
app.include_router(proxy.router, prefix="/api/v1", tags=["Proxy"])
app.include_router(runtime.router, prefix="/api/v1", tags=["Runtime"])
app.include_router(targets.router, prefix="/api/v1", tags=["Targets"])
app.include_router(settings_router.router, prefix="/api/v1/settings", tags=["Settings"])
app.include_router(system.router, tags=["System"])

from ws_handlers.farming_logs import setup_ws  # noqa: E402

setup_ws(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, loop="uvloop")
