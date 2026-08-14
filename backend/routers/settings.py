import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal

from auth import get_current_user
from services.user_settings import get_telegram, set_telegram, send_telegram, get_captcha, set_captcha
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


# ---------- Captcha (CapSolver) ----------
class CaptchaRequest(BaseModel):
    api_key: str = ""
    enabled: bool = False
    service: str = "capsolver"


@router.get("/captcha")
async def captcha_get(request: Request, _user: dict = Depends(get_current_user)):
    return await get_captcha(request.app.state.redis, include_secret=False)


@router.put("/captcha")
async def captcha_put(req: CaptchaRequest, request: Request, _user: dict = Depends(get_current_user)):
    return await set_captcha(request.app.state.redis, req.api_key, req.enabled, req.service)


class CaptchaTestRequest(BaseModel):
    api_key: str = ""


@router.post("/captcha/test")
async def captcha_test(req: CaptchaTestRequest, request: Request, _user: dict = Depends(get_current_user)):
    """CapSolver bakiyesini sorgula. Alana YAZILAN anahtar öncelikli (kaydetmeden test edilebilir);
    boş/maskeli ise KAYITLI anahtar denenir."""
    import httpx
    key = (req.api_key or "").strip()
    if not key or "…" in key or "•" in key:      # yazılmadı/maskeli → kayıtlıyı kullan
        cfg = await get_captcha(request.app.state.redis, include_secret=True)
        key = cfg.get("api_key", "")
    if not key:
        return {"ok": False, "detail": "Anahtar girilmemiş — alana yaz ya da Kaydet."}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post("https://api.capsolver.com/getBalance",
                                  json={"clientKey": key})
            data = r.json()
        if not data.get("errorId"):
            _bal = data.get("balance")
            _bal_txt = f"${_bal}" if _bal is not None else "bilinmiyor"
            return {"ok": True, "detail": f"Anahtar geçerli · bakiye {_bal_txt}"}
        return {"ok": False, "detail": f"CapSolver: {data.get('errorDescription') or data.get('errorCode')}"}
    except Exception as e:
        return {"ok": False, "detail": f"Sorgulanamadı: {e}"}


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


@router.get("/schedule/status")
async def schedule_status(request: Request, _user: dict = Depends(get_current_user)):
    """Zamanlayıcının CANLI durumu: açık mı, SONRAKİ çalışma (Türkiye saati), SON çalışma,
    ve şu an aktif üretim var mı (çakışma göstergesi). Panel bunu poll'lar."""
    from datetime import datetime, timedelta
    from services.automation_config import get_schedule_runtime
    from services.scheduler import TR_TZ, WINDOW_MIN, _parse_hhmm

    redis = request.app.state.redis
    sched = await get_schedule(redis)
    rt = await get_schedule_runtime(redis)
    now = datetime.now(TR_TZ)

    next_run = None
    hm = _parse_hhmm(sched.get("time"))
    if sched.get("enabled") and hm:
        today = now.strftime("%Y-%m-%d")
        today_dt = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
        window_end = today_dt + timedelta(minutes=WINDOW_MIN)
        farmed_today = (rt.get("last_farm_date") == today)          # bugün üretildi (manuel/zamanlı)
        ran_window = (rt.get("last_run") == f"{today} {sched['time']}")
        will_run_today = (not farmed_today) and (not ran_window) and (now < window_end)
        next_run = today_dt if will_run_today else (today_dt + timedelta(days=1))

    # Aktif üretim var mı (manuel VEYA zamanlanan) → çakışma/işlem göstergesi.
    try:
        from routers.farming import _active_engines
        running = len(_active_engines) > 0
    except Exception:
        running = False

    return {
        "enabled": bool(sched.get("enabled")),
        "time": sched.get("time"),
        "next_run": next_run.isoformat() if next_run else None,
        "last_run": rt.get("last_run"),
        "last_summary": rt.get("last_summary"),
        "running": running,
        "now_tr": now.isoformat(),
    }


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
