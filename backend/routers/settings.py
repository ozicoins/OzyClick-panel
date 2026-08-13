from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from auth import get_current_user
from services.user_settings import get_telegram, set_telegram, send_telegram

router = APIRouter()


class TelegramRequest(BaseModel):
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = False


@router.get("/telegram")
async def telegram_get(request: Request, _user: dict = Depends(get_current_user)):
    return await get_telegram(request.app.state.redis, include_secret=False)


@router.put("/telegram")
async def telegram_put(req: TelegramRequest, request: Request, _user: dict = Depends(get_current_user)):
    return await set_telegram(request.app.state.redis, req.bot_token, req.chat_id, req.enabled)


@router.post("/telegram/test")
async def telegram_test(request: Request, _user: dict = Depends(get_current_user)):
    ok = await send_telegram(request.app.state.redis, "✅ OzyClick test mesajı — Telegram bildirimleri çalışıyor.")
    if ok:
        return {"ok": True, "detail": "Test mesajı gönderildi — Telegram'ı kontrol edin."}
    return {"ok": False, "detail": "Gönderilemedi. bot_token / chat_id doğru mu ve bildirim AÇIK mı?"}
