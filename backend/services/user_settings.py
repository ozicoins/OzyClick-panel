"""Kullanıcı ayarları — Telegram bildirim yapılandırması (redis'te saklanır).
Telegram: bot_token + chat_id ile önemli olaylarda mesaj gönderir. Hangi olayların
bildirileceği `events` ile, canlılık uyarı eşiği `liveness_threshold` ile ayarlanır.
"""
import logging

import httpx
import orjson

logger = logging.getLogger("user_settings")

_TG_KEY = "user:telegram"   # redis: {"bot_token","chat_id","enabled","events","liveness_threshold"}

# Bildirilecek olaylar (hepsi varsayılan AÇIK). notify() bunları kontrol eder.
_DEFAULT_EVENTS = {
    "batch_done": True,        # üretim bitti
    "backup_done": True,       # Drive yedeği alındı
    "liveness_alert": True,    # canlılık eşiğin altına düştü
    "daily_summary": True,     # günlük havuz özeti
}
_DEFAULT_THRESHOLD = 80        # canlılık %'si bunun altına düşerse uyar


async def get_telegram(redis, include_secret: bool = False) -> dict:
    """Telegram ayarını döndür. include_secret=False → bot_token maskeli (panelde gösterim için)."""
    cfg = {
        "enabled": False, "bot_token": "", "chat_id": "",
        "events": dict(_DEFAULT_EVENTS), "liveness_threshold": _DEFAULT_THRESHOLD,
    }
    if redis is not None:
        try:
            raw = await redis.get(_TG_KEY)
            if raw:
                cfg.update(orjson.loads(raw))
        except Exception:
            pass
    # events'te eksik anahtar olabilir (eski kayıt) → varsayılanlarla tamamla
    ev = dict(_DEFAULT_EVENTS)
    ev.update(cfg.get("events") or {})
    cfg["events"] = ev
    try:
        cfg["liveness_threshold"] = int(cfg.get("liveness_threshold", _DEFAULT_THRESHOLD))
    except Exception:
        cfg["liveness_threshold"] = _DEFAULT_THRESHOLD

    if not include_secret and cfg.get("bot_token"):
        tok = cfg["bot_token"]
        cfg["bot_token"] = (tok[:6] + "…" + tok[-4:]) if len(tok) > 12 else "••••"
        cfg["configured"] = True
    else:
        cfg["configured"] = bool(cfg.get("bot_token"))
    return cfg


async def set_telegram(redis, bot_token: str, chat_id: str, enabled: bool,
                       events: dict | None = None, liveness_threshold: int | None = None) -> dict:
    """Telegram ayarını kaydet. bot_token boş/maskeli gelirse ESKİSİ korunur (üzerine yazma)."""
    if redis is None:
        return await get_telegram(None)
    cur = await get_telegram(redis, include_secret=True)
    tok = (bot_token or "").strip()
    if not tok or "…" in tok or "•" in tok:   # maskeli/boş → eskisini koru
        tok = cur.get("bot_token", "")
    # events: verilen anahtarları güncelle, verilmeyenleri koru
    ev = dict(cur.get("events") or _DEFAULT_EVENTS)
    if isinstance(events, dict):
        for k in _DEFAULT_EVENTS:
            if k in events:
                ev[k] = bool(events[k])
    thr = cur.get("liveness_threshold", _DEFAULT_THRESHOLD)
    if liveness_threshold is not None:
        try:
            thr = max(0, min(100, int(liveness_threshold)))
        except Exception:
            pass
    cfg = {
        "enabled": bool(enabled), "bot_token": tok, "chat_id": (chat_id or "").strip(),
        "events": ev, "liveness_threshold": thr,
    }
    await redis.set(_TG_KEY, orjson.dumps(cfg))
    return await get_telegram(redis, include_secret=False)


_CAPTCHA_KEY = "config:captcha"   # redis: {"api_key","service","enabled"}


async def get_captcha(redis, include_secret: bool = False) -> dict:
    """Captcha (2captcha) ayarı. include_secret=False → api_key maskeli (panel gösterimi)."""
    cfg = {"enabled": False, "api_key": "", "service": "2captcha"}
    if redis is not None:
        try:
            raw = await redis.get(_CAPTCHA_KEY)
            if raw:
                cfg.update(orjson.loads(raw))
        except Exception:
            pass
    if not include_secret and cfg.get("api_key"):
        k = cfg["api_key"]
        cfg["api_key"] = (k[:4] + "…" + k[-4:]) if len(k) > 10 else "••••"
        cfg["configured"] = True
    else:
        cfg["configured"] = bool(cfg.get("api_key"))
    return cfg


async def set_captcha(redis, api_key: str, enabled: bool, service: str = "2captcha") -> dict:
    """Captcha ayarını kaydet. api_key boş/maskeli gelirse ESKİSİ korunur (üzerine yazma)."""
    if redis is None:
        return await get_captcha(None)
    cur = await get_captcha(redis, include_secret=True)
    k = (api_key or "").strip()
    if not k or "…" in k or "•" in k:   # maskeli/boş → eskisini koru
        k = cur.get("api_key", "")
    cfg = {"enabled": bool(enabled), "api_key": k, "service": (service or "2captcha").strip()}
    await redis.set(_CAPTCHA_KEY, orjson.dumps(cfg))
    return await get_captcha(redis, include_secret=False)


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


async def notify(redis, event: str, text: str) -> bool:
    """Olay-bazlı bildirim: Telegram AÇIK ve bu olay etkinse gönderir. event: batch_done /
    backup_done / liveness_alert / daily_summary."""
    try:
        cfg = await get_telegram(redis, include_secret=True)
    except Exception:
        return False
    if not cfg.get("enabled"):
        return False
    if not (cfg.get("events") or {}).get(event, True):
        return False
    return await send_telegram(redis, text)
