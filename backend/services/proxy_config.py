"""Proxy ayarları — ScrapingBee ÇOK-ANAHTARLI havuz + kalite + failover.

- api_keys: birden fazla API anahtarı (elle veya txt ile eklenir). active_index
  aktif olanı gösterir; biri tükenince rotate_key ile sonrakine geçilir.
- quality: classic (1 kredi) / premium (~10-25 kredi) / stealth (~75 kredi).
- Anahtarlar redis'te; GET yanıtı anahtarları ASLA ham döndürmez (son 4 hane preview).
"""
import re
from urllib.parse import quote
import orjson
from config import settings

SETTINGS_KEY = "proxy:settings"
_STORED_FIELDS = ("provider", "country", "render_js", "quality", "api_keys", "active_index", "proxies")
QUALITIES = ("classic", "premium", "stealth")
PROVIDERS = ("csv", "scrapingbee", "list")

_IPV6_RE = re.compile(r"^\[([0-9a-fA-F:]+)\]:(\d+)(?::(.+?):(.+))?$")


def normalize_proxy(raw: str) -> str:
    """Kullanıcı girdisini proxy URL'sine çevirir. IPv6 KÖŞELİ PARANTEZLE:
      IPv4/host : host:port  |  host:port:user:pass
      IPv6      : [2001:db8::1]:8080  |  [2001:db8::1]:8080:user:pass
      Tam URL   : http://... / socks5://...  → olduğu gibi.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    if raw.startswith("["):  # IPv6
        m = _IPV6_RE.match(raw)
        if not m:
            return ""
        addr, port, user, pw = m.groups()
        auth = f"{quote(user, safe='')}:{quote(pw, safe='')}@" if user else ""
        return f"http://{auth}[{addr}]:{port}"
    parts = raw.split(":")
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    if len(parts) >= 4:
        host, port, user, pw = parts[0], parts[1], parts[2], ":".join(parts[3:])
        return f"http://{quote(user, safe='')}:{quote(pw, safe='')}@{host}:{port}"
    return ""


def mask_proxy(url: str) -> str:
    """Listede göstermek için parolayı gizle: http://user:***@host:port."""
    try:
        if "@" in url and "://" in url:
            scheme, rest = url.split("://", 1)
            auth, hostpart = rest.split("@", 1)
            user = auth.split(":", 1)[0]
            return f"{scheme}://{user}:***@{hostpart}"
    except Exception:
        pass
    return url


def _defaults() -> dict:
    keys = [settings.scrapingbee_api_key] if settings.scrapingbee_api_key else []
    return {
        "provider": settings.proxy_provider,
        "country": settings.scrapingbee_country,
        "render_js": settings.scrapingbee_render_js,
        "quality": "premium" if settings.scrapingbee_premium else "classic",
        "api_keys": keys,
        "active_index": 0,
        "proxies": [],
    }


async def load_proxy_settings(redis) -> dict:
    """Rotator için tam config (aktif anahtar dahil)."""
    cfg = _defaults()
    if redis is not None:
        try:
            raw = await redis.get(SETTINGS_KEY)
            if raw:
                override = orjson.loads(raw)
                for k in _STORED_FIELDS:
                    if override.get(k) is not None:
                        cfg[k] = override[k]
        except Exception:
            pass
    keys = cfg.get("api_keys") or []
    cfg["active_index"] = (cfg.get("active_index", 0) % len(keys)) if keys else 0
    cfg["active_key"] = keys[cfg["active_index"]] if keys else ""
    return cfg


def public_view(cfg: dict) -> dict:
    """HTTP yanıtı: ham anahtar YOK; proxy parolaları maskeli."""
    keys = cfg.get("api_keys") or []
    proxies = cfg.get("proxies") or []
    previews = [("…" + k[-4:]) if len(k) >= 4 else "…" for k in keys]
    return {
        "provider": cfg["provider"],
        "country": cfg["country"],
        "render_js": cfg["render_js"],
        "quality": cfg.get("quality", "classic"),
        "api_key_count": len(keys),
        "active_index": cfg.get("active_index", 0) if keys else 0,
        "api_key_previews": previews,
        "api_key_configured": len(keys) > 0,
        "proxy_count": len(proxies),
        "proxy_previews": [mask_proxy(p) for p in proxies],
    }


async def _write(redis, cfg: dict) -> None:
    keys = cfg.get("api_keys") or []
    stored = {
        "provider": cfg["provider"],
        "country": cfg["country"],
        "render_js": cfg["render_js"],
        "quality": cfg.get("quality", "classic"),
        "api_keys": keys,
        "active_index": (cfg.get("active_index", 0) % len(keys)) if keys else 0,
        "proxies": cfg.get("proxies") or [],
    }
    if redis is not None:
        await redis.set(SETTINGS_KEY, orjson.dumps(stored))


async def save_proxy_settings(redis, patch: dict) -> dict:
    cfg = await load_proxy_settings(redis)

    for k in ("provider", "country", "render_js", "quality"):
        if patch.get(k) is not None:
            cfg[k] = patch[k]

    keys = list(cfg.get("api_keys") or [])

    if patch.get("set_api_keys") is not None:
        keys = []
        for k in patch["set_api_keys"]:
            k = (k or "").strip()
            if k and k not in keys:
                keys.append(k)
        cfg["active_index"] = 0

    if patch.get("add_api_keys"):
        for k in patch["add_api_keys"]:
            k = (k or "").strip()
            if k and k not in keys:
                keys.append(k)

    if patch.get("remove_api_key_index") is not None:
        idx = patch["remove_api_key_index"]
        if isinstance(idx, int) and 0 <= idx < len(keys):
            keys.pop(idx)
            # Aktif index'i sil edilen konuma göre kaydır (yanlışlıkla başa dönme).
            ai = cfg.get("active_index", 0)
            if idx < ai:
                ai -= 1
            elif idx == ai:
                ai = 0
            cfg["active_index"] = max(0, ai)

    cfg["api_keys"] = keys

    if patch.get("active_index") is not None:
        cfg["active_index"] = patch["active_index"]

    # --- Proxy listesi (IPv6 destekli) ---
    proxies = list(cfg.get("proxies") or [])
    if patch.get("set_proxies") is not None:
        proxies = []
        for p in patch["set_proxies"]:
            n = normalize_proxy(p)
            if n and n not in proxies:
                proxies.append(n)
    if patch.get("add_proxies"):
        for p in patch["add_proxies"]:
            n = normalize_proxy(p)
            if n and n not in proxies:
                proxies.append(n)
    if patch.get("remove_proxy_index") is not None:
        idx = patch["remove_proxy_index"]
        if isinstance(idx, int) and 0 <= idx < len(proxies):
            proxies.pop(idx)
    cfg["proxies"] = proxies

    await _write(redis, cfg)
    return public_view(await load_proxy_settings(redis))


async def rotate_key(redis) -> dict:
    """Bir anahtar tükendiğinde sonrakine geç (failover)."""
    cfg = await load_proxy_settings(redis)
    keys = cfg.get("api_keys") or []
    if len(keys) <= 1:
        return public_view(cfg)
    return await save_proxy_settings(redis, {"active_index": (cfg.get("active_index", 0) + 1) % len(keys)})
