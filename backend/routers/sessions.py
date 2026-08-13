"""Session router — yalnızca Keep-Alive.

Not: eski refresh/kill/freeze/bulk/purge-dead endpoint'leri, hiç doldurulmayan bir
Session tablosu üzerinde çalıştığı için her zaman 404/0 dönüyordu (ölü kod) ve
kaldırıldı. Gerçek session-yönetimi istenirse farming sırasında Session satırları
üretilmeli + UI eklenmeli (ayrı bir özellik).
"""
import asyncio

from fastapi import APIRouter, Depends, Request

from auth import get_current_user
from services.keepalive_service import read_status, write_status, run_ping_cycle

router = APIRouter()

# Arka plan tur görevleri (GC'lenmesin diye referans tutulur).
_bg_tasks: set = set()


@router.post("/keep-alive/toggle")
async def toggle_keep_alive(
    request: Request,
    _user: dict = Depends(get_current_user),
):
    redis = request.app.state.redis
    status = await read_status(redis)
    new_active = not status.get("active", False)
    status["active"] = new_active
    await write_status(redis, status)
    if new_active:
        # İlk turu ARKA PLANDA çalıştır → ağır profil-başına tur (300 profile kadar
        # tarayıcı açabilir) HTTP isteğini bloklamaz/timeout etmez. Sonuç sayaçları
        # frontend 30 sn'de bir status çekerek görür.
        task = asyncio.create_task(run_ping_cycle(redis))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
    else:
        status["next_ping"] = None
        await write_status(redis, status)
    return status


@router.post("/keep-alive/ping-now")
async def keep_alive_ping_now(
    request: Request,
    _user: dict = Depends(get_current_user),
):
    """Keep-alive turunu 24 saati BEKLEMEDEN hemen (arka planda) tetikle. Durum 30 saniyede bir
    çekilerek güncellenir; 'canlı/başarısız' gerçek zamanlı görünsün diye elle tazeleme."""
    redis = request.app.state.redis
    status = await read_status(redis)
    if not status.get("active", False):
        return {"started": False, "detail": "Keep-alive KAPALI — önce açın."}
    task = asyncio.create_task(run_ping_cycle(redis))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"started": True, "detail": "Keep-alive turu başlatıldı — sonuç birazdan güncellenecek."}


@router.get("/keep-alive/status")
async def get_keep_alive_status(
    request: Request,
    _user: dict = Depends(get_current_user),
):
    return await read_status(request.app.state.redis)
