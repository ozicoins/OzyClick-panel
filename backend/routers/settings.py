import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal

from auth import get_current_user
from services.user_settings import get_telegram, set_telegram, send_telegram
from services.automation_config import get_schedule, set_schedule, get_auto_cleanup, set_auto_cleanup

router = APIRouter()

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------- Telegram ----------
class TelegramEvents(BaseModel):
    batch_done: Optional[bool] = None
    backup_done: Optional[bool] = None
    liveness_alert: Optional[bool] = None
    daily_summary: Optional[bool] = None


class TelegramRequest(BaseModel):
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = False
    events: Optional[TelegramEvents] = None
    liveness_threshold: Optional[int] = Field(None, ge=0, le=100)


@router.get("/telegram")
async def telegram_get(request: Request, _user: dict = Depends(get_current_user)):
    return await get_telegram(request.app.state.redis, include_secret=False)


@router.put("/telegram")
async def telegram_put(req: TelegramRequest, request: Request, _user: dict = Depends(get_current_user)):
    events = req.events.model_dump(exclude_none=True) if req.events else None
    return await set_telegram(
        request.app.state.redis, req.bot_token, req.chat_id, req.enabled,
        events=events, liveness_threshold=req.liveness_threshold,
    )


@router.post("/telegram/test")
async def telegram_test(request: Request, _user: dict = Depends(get_current_user)):
    ok = await send_telegram(request.app.state.redis, "✅ OzyClick test mesajı — Telegram bildirimleri çalışıyor.")
    if ok:
        return {"ok": True, "detail": "Test mesajı gönderildi — Telegram'ı kontrol edin."}
    return {"ok": False, "detail": "Gönderilemedi. bot_token / chat_id doğru mu ve bildirim AÇIK mı?"}


# ---------- Üretim Zamanlayıcı ----------
class ScheduleRequest(BaseModel):
    enabled: Optional[bool] = None
    time: Optional[str] = None
    count_per_account: Optional[int] = Field(None, ge=1, le=10000)
    mode: Optional[Literal["SAFE", "FAST", "TURBO"]] = None
    lifespan_days: Optional[int] = Field(None, ge=3, le=5)
    sector: Optional[str] = Field(None, max_length=100)
    daily_summary: Optional[bool] = None
    summary_time: Optional[str] = None

    @field_validator("time", "summary_time")
    @classmethod
    def _v_time(cls, v):
        if v is None:
            return v
        v = v.strip()
        # fullmatch: '$' sondaki \n'i de kabul ederdi → "03:00\n" geçip parse'ta None'a düşerdi.
        if not _HHMM.fullmatch(v):
            raise ValueError("Saat HH:MM biçiminde olmalı (00:00–23:59)")
        return v


@router.get("/schedule")
async def schedule_get(request: Request, _user: dict = Depends(get_current_user)):
    return await get_schedule(request.app.state.redis)


@router.put("/schedule")
async def schedule_put(req: ScheduleRequest, request: Request, _user: dict = Depends(get_current_user)):
    # Sadece kullanıcı ayarları güncellenir; scheduler çalışma durumu (last_run) AYRI anahtarda
    # tutulduğu için buradan ezilmez. İşaretçi 'gün+saat' bazlı → saat değişince aynı gün yeni
    # saatte çalışır, aynı ayarın tekrar kaydı çift-çalıştırmaz (reset hack'ine gerek yok).
    patch = req.model_dump(exclude_none=True)
    return await set_schedule(request.app.state.redis, patch)


# ---------- Otomatik ölü-çerez temizliği ----------
class CleanupRequest(BaseModel):
    enabled: bool = False


@router.get("/auto-cleanup")
async def cleanup_get(request: Request, _user: dict = Depends(get_current_user)):
    return {"enabled": await get_auto_cleanup(request.app.state.redis)}


@router.put("/auto-cleanup")
async def cleanup_put(req: CleanupRequest, request: Request, _user: dict = Depends(get_current_user)):
    return {"enabled": await set_auto_cleanup(request.app.state.redis, req.enabled)}
