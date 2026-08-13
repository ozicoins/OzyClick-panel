"""Toplu Canlılık Taraması — havuzdaki TÜM çerezleri kendi DOĞUM parmak izi + proxy'siyle
Google'a uğratıp oturumun aktif olup olmadığını doğrular, HESAP KIRILIMLI özet üretir.

check_profile_live'ı (live_check.py — kendi Semaphore(2) throttle'ı var) ve check_live'ın
doğum-proxy çözüm mantığını yeniden kullanır (tek kaynak, drift yok). İlerleme redis'e yazılır;
panel poll eder. auto_delete=True → ölü profiller silinir (opsiyonel otomatik temizlik).
"""
import asyncio
import glob
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import orjson

from config import settings

SCAN_KEY = "livescan:status"
_scan_task = None                       # GC'lenmesin diye modül-seviyesi referans
_gate = asyncio.Semaphore(4)            # aynı anda en fazla 4 profil BELLEKTE (yükle+kontrol)


def _empty() -> dict:
    return {
        "running": False, "done": False, "total": 0, "checked": 0,
        "alive": 0, "dead": 0, "skipped": 0, "deleted": 0,
        "per_account": {}, "auto_delete": False,
        "started_at": None, "updated_at": None,
    }


async def read_scan(redis) -> dict:
    raw = await redis.get(SCAN_KEY)
    return orjson.loads(raw) if raw else _empty()


async def _write(redis, st: dict) -> None:
    await redis.set(SCAN_KEY, orjson.dumps(st))


def _hp(u: str):
    """host:port ayıkla (IPv6 köşeli parantez toleranslı)."""
    try:
        p = urlparse(u if "://" in u else "http://" + u)
        return ((p.hostname or "").strip("[]"), p.port)
    except Exception:
        return (None, None)


async def _resolve_proxy(profile: dict, cfg: dict):
    """Doğum proxy'sini çöz → (proxy_full, proxy_dict, skip). export.check_live ile AYNI mantık:
    ScrapingBee kararı SADECE doğum verisinden; list/csv doğum server+creds; FAIL-CLOSED skip."""
    fp = profile.get("fingerprint") or {}
    birth = fp.get("proxy_ip") or profile.get("proxy_ip") or ""
    stored_proxy = fp.get("proxy") if isinstance(fp.get("proxy"), dict) else None
    proxy_dict = None
    proxy_full = None

    _is_sb = ("scrapingbee" in ((stored_proxy or {}).get("server") or "")) or ("scrapingbee" in birth)
    if _is_sb:
        _sk = fp.get("sb_session_key") or ""
        _keys = cfg.get("api_keys") or []
        _ak = _keys[cfg.get("active_index", 0)] if _keys else ""
        if _sk and _ak:
            from services.proxy_rotator import build_scrapingbee_proxy
            proxy_dict = build_scrapingbee_proxy(cfg, _ak, session_key=_sk)
    elif stored_proxy and stored_proxy.get("server"):
        if stored_proxy.get("username") or stored_proxy.get("password"):
            proxy_dict = stored_proxy
        else:
            _tgt = _hp(stored_proxy["server"])
            for pu in (cfg.get("proxies") or []):
                if _hp(pu) == _tgt and _tgt[0]:
                    proxy_full = pu
                    break
            if not proxy_full:
                proxy_dict = stored_proxy
    else:
        _tgt = _hp(birth) if birth else (None, None)
        for pu in (cfg.get("proxies") or []):
            if _hp(pu) == _tgt and _tgt[0]:
                proxy_full = pu
                break

    # FAIL-CLOSED: doğumda proxy vardı ama çözülemedi → kontrol ATLA (oturumu datacenter-IP'den açıp yakma).
    if birth and not (proxy_dict or proxy_full):
        return (None, None, True)
    return (proxy_full, proxy_dict, False)


async def run_full_scan(redis, auto_delete: bool = False) -> dict:
    """Havuzdaki TÜM profilleri tara. Her profil: doğum proxy'si çöz → check_profile_live →
    alive/dead/skipped. auto_delete ise ölüleri sil. İlerleme her profilde redis'e yazılır."""
    from services.proxy_config import load_proxy_settings
    from services.live_check import check_profile_live

    base = os.path.realpath(settings.cookies_output_dir)
    files = sorted(glob.glob(os.path.join(base, "*", "profile_*.json")))
    cfg = await load_proxy_settings(redis)
    total = len(files)

    now = datetime.now(timezone.utc).isoformat()
    per: dict = {}                        # acct -> {alive, dead, skipped, deleted}
    st = {
        "running": True, "done": False, "total": total, "checked": 0,
        "alive": 0, "dead": 0, "skipped": 0, "deleted": 0,
        "per_account": per, "auto_delete": bool(auto_delete),
        "started_at": now, "updated_at": now,
    }
    await _write(redis, st)
    lock = asyncio.Lock()

    async def _one(path: str):
        acct = os.path.basename(os.path.dirname(path))
        outcome = "skipped"
        deleted = False
        async with _gate:                 # bellek sınırı: aynı anda en fazla 4 profil yüklü
            try:
                with open(path, "rb") as f:
                    profile = orjson.loads(f.read())
            except Exception:
                profile = None
            if profile is not None:
                proxy_full, proxy_dict, skip = await _resolve_proxy(profile, cfg)
                if not skip:
                    # SİLME İZNİ: çerez KENDİ doğum-proxy'sinden kontrol edilmeli. Proxy çözülemeyip
                    # datacenter-IP'den kontrol edilen çerez, Google'ı YANLIŞ signin-yönlendirmesine
                    # itip 'kesin ölü' gibi görünebilir → o yüzden proxysiz kontrolde ASLA silme.
                    has_proxy = bool(proxy_full or proxy_dict)
                    try:
                        res = await check_profile_live(profile, proxy_full, proxy_dict=proxy_dict)
                    except Exception:
                        res = None
                    if res is None:
                        outcome = "skipped"                    # kontrol hatası → belirsiz, SİLME
                    elif res.get("alive"):
                        outcome = "alive"
                    else:
                        # SİLME GÜVENLİĞİ: yalnız KESİN ölü (Google login sayfasına yönlendi) → dead.
                        # Timeout/ağ hatası/boş url/interstitial → belirsiz → 'skipped' (canlıyı YAKMA).
                        _url = (res.get("url") or "").lower()
                        _definitive_dead = any(
                            k in _url for k in ("signin", "servicelogin", "identifier", "/v3/signin")
                        )
                        if _definitive_dead:
                            outcome = "dead"
                            if auto_delete and has_proxy:      # KESİN ölü + doğum-proxy'sinden → sil
                                try:
                                    os.remove(path)
                                    deleted = True
                                except Exception:
                                    deleted = False
                        else:
                            outcome = "skipped"
        async with lock:
            a = per.setdefault(acct, {"alive": 0, "dead": 0, "skipped": 0, "deleted": 0})
            a[outcome] += 1
            if deleted:
                a["deleted"] += 1
            st["checked"] += 1
            st["alive"] = sum(x["alive"] for x in per.values())
            st["dead"] = sum(x["dead"] for x in per.values())
            st["skipped"] = sum(x["skipped"] for x in per.values())
            st["deleted"] = sum(x["deleted"] for x in per.values())
            st["per_account"] = per
            st["updated_at"] = datetime.now(timezone.utc).isoformat()
            await _write(redis, st)

    if files:
        await asyncio.gather(*[_one(f) for f in files])

    st["running"] = False
    st["done"] = True
    st["updated_at"] = datetime.now(timezone.utc).isoformat()
    await _write(redis, st)

    # Canlılık eşik uyarısı (Telegram) — kontrol edilebilenlerin canlı %'si eşiğin altındaysa.
    try:
        from services.user_settings import get_telegram, notify
        tg = await get_telegram(redis, include_secret=True)
        thr = int(tg.get("liveness_threshold", 80))
        checkable = st["alive"] + st["dead"]
        if checkable:
            alive_pct = round(st["alive"] / checkable * 100)
            if alive_pct < thr:
                extra = f" · {st['deleted']} ölü silindi" if st.get("deleted") else ""
                await notify(
                    redis, "liveness_alert",
                    f"<b>OzyClick</b> · ⚠️ Canlılık düştü: %{alive_pct} "
                    f"({st['alive']}/{checkable} canlı, {st['dead']} ölü){extra} — eşik %{thr}",
                )
    except Exception:
        pass
    return st


def start_scan(redis, auto_delete: bool = False) -> bool:
    """Taramayı arka planda başlat. Zaten çalışıyorsa False döner."""
    global _scan_task
    if _scan_task and not _scan_task.done():
        return False
    _scan_task = asyncio.create_task(run_full_scan(redis, auto_delete))
    return True
