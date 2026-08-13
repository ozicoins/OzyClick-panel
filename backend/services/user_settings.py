"""Kullanıcı ayarları — Telegram bildirim yapılandırması (redis'te saklanır).
Telegram: bot_token + chat_id ile önemli olaylarda (batch bitti, kritik hata) mesaj gönderir.
"""
import logging

import httpx

logger = logging.getLogger("user_settings")

_TG_KEY = "user:telegram"   # redis: {"bot_token": "...", "chat_id": "...", "enabled": true}


async def get_telegram(redis, include_secret: bool = False) -> dict:
    """Telegram ayarını döndür. include_secret=False → bot_token maskeli (panelde gösterim için)."""
    cfg = {"enabled": False, "bot_token": "", "chat_id": ""}
    if redis is not None:
        try:
            import orjson
            raw = await redis.get(_TG_KEY)
            if raw:
                cfg.update(orjson.loads(raw))
        except Exception:
            pass
    if not include_secret and cfg.get("bot_token"):
        tok = cfg["bot_token"]
        cfg["bot_token"] = (tok[:6] + "…" + tok[-4:]) if len(tok) > 12 else "••••"
        cfg["configured"] = True
    else:
        cfg["configured"] = bool(cfg.get("bot_token"))
    return cfg


async def set_telegram(redis, bot_token: str, chat_id: str, enabled: bool) -> dict:
    """Telegram ayarını kaydet. bot_token boş/maskeli gelirse ESKİSİ korunur (üzerine yazma)."""
    if redis is None:
        return {"enabled": False, "bot_token": "", "chat_id": ""}
    import orjson
    cur = await get_telegram(redis, include_secret=True)
    tok = (bot_token or "").strip()
    if not tok or "…" in tok or "•" in tok:   # maskeli/boş → eskisini koru
        tok = cur.get("bot_token", "")
    cfg = {"enabled": bool(enabled), "bot_token": tok, "chat_id": (chat_id or "").strip()}
    await redis.set(_TG_KEY, orjson.dumps(cfg))
    return await get_telegram(redis, include_secret=False)


async def send_telegram(redis, text: str) -> bool:
    """Telegram'a mesaj gönder (enabled + token + chat_id varsa). Sessiz başarısızlık."""
    cfg = await get_telegram(redis, include_secret=True)
    if not (cfg.get("enabled") and cfg.get("bot_token") and cfg.get("chat_id")):
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                json={"chat_id": cfg["chat_id"], "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
            )
            return r.status_code == 200
    except Exception as e:
        logger.debug("telegram gönderilemedi: %s", e)
        return False
