"""Session Keep-Alive: aktifken periyodik olarak canlı session'ları 'ping'leyip
sayaçları günceller. Toggle açıldığında anında bir tur çalışır (kullanıcı sonucu
hemen görsün), sonra 24 saatte bir tekrarlanır.

Arka plan döngüsü main.py lifespan içinde başlatılır. Ping turu ve toggle aynı
mantığı paylaşır (tek kaynak).
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import orjson

from config import settings

logger = logging.getLogger("keepalive")


def _proxy_dict(proxy_ip: str):
    """Saklı proxy string'ini Playwright proxy dict'ine çevir (kimlik bilgisi dahil)."""
    if not proxy_ip:
        return None
    s = proxy_ip.strip()
    if "://" not in s:
        s = "http://" + s
    try:
        from urllib.parse import urlparse
        u = urlparse(s)
        if not u.hostname:
            return None
        host = u.hostname
        if ":" in host:  # IPv6 → köşeli parantez (aksi halde port adrese karışır)
            host = f"[{host}]"
        server = f"{u.scheme}://{host}"
        if u.port:
            server += f":{u.port}"
        d = {"server": server}
        if u.username:
            d["username"] = u.username
        if u.password:
            d["password"] = u.password
        return d
    except Exception:
        return None

STATUS_KEY = "keep_alive:status"
CHECK_INTERVAL = 60          # döngü bu sıklıkta zamanı gelmiş mi diye bakar (saniye)
PING_PERIOD_HOURS = 24       # iki ping arası

# Aynı anda tek keep-alive turu → toggle + arka plan döngüsü çakışmasın (özellikle ağır
# profil-başına tur iki kez başlamasın).
_cycle_lock = asyncio.Lock()

DEFAULT_STATUS = {
    # Varsayılan AÇIK: üretilen oturumları periyodik uğrayıp canlı tutar (çerez ömrü uzar).
    # Kullanıcı Ayarlar'dan kapatabilir. Ağır per-profil turu ayrı flag ile opt-in kalır.
    "active": True, "last_ping": None, "next_ping": None,
    "success_rate": 0, "success_count": 0, "total_count": 0,
}


async def read_status(redis) -> dict:
    raw = await redis.get(STATUS_KEY)
    return orjson.loads(raw) if raw else dict(DEFAULT_STATUS)


async def write_status(redis, status: dict) -> None:
    await redis.set(STATUS_KEY, orjson.dumps(status))


async def run_ping_cycle(redis) -> dict:
    """Bir keep-alive turu: canlı session'ları say, ping'le, sayaçları+zamanı güncelle.

    Profil-başına keep-alive AÇIK ve GERÇEK modda ise → ağır ama gerçek yenileme turu
    (her profilin çerezini kendi parmak izi+proxy'siyle Google'a uğratır). Aksi halde
    hafif genel ping (redis TTL yenile + Google erişim kontrolü)."""
    from services.runtime_config import get_dry_run
    if _cycle_lock.locked():
        # Zaten bir tur çalışıyor → çakışmayı önle, mevcut durumu döndür.
        return await read_status(redis)

    async with _cycle_lock:
        # Döngünün bu turu tekrar 'due' görüp İKİNCİ kez başlatmasını engelle:
        # next_ping'i turun BAŞINDA ileri al.
        _s = await read_status(redis)
        _s["next_ping"] = (datetime.now(timezone.utc) + timedelta(hours=PING_PERIOD_HOURS)).isoformat()
        await write_status(redis, _s)

        # GERÇEK mod → profil-başına GERÇEK yenileme (tek işlevsel yol). DRY → sentetik sayım.
        # (Eski "generate_204 global ping'i → hepsi %100 canlı" göstermelik iddiası kaldırıldı.)
        if await get_dry_run(redis):
            return await _run_dry_cycle(redis)
        return await run_per_profile_cycle(redis)


async def _run_dry_cycle(redis) -> dict:
    """DRY: sentetik profilleri say + redis TTL'i yenile (rolling takip penceresi).
    Gerçek canlılık DOĞRULANMAZ — sentetik oldukları için hepsi 'canlı' sayılır."""
    status = await read_status(redis)
    try:
        keys = await redis.keys("session:*")
    except Exception:
        keys = []
    total = len(keys)

    ttl = settings.redis_session_ttl
    if ttl and ttl > 0:
        for k in keys:
            try:
                await redis.expire(k, ttl)
            except Exception:
                pass

    now = datetime.now(timezone.utc)
    status["last_ping"] = now.isoformat()
    status["next_ping"] = (now + timedelta(hours=PING_PERIOD_HOURS)).isoformat()
    status["total_count"] = total
    status["success_count"] = total          # sentetik → tanım gereği canlı
    status["success_rate"] = 100.0 if total else 0
    _cur = await read_status(redis)
    if not _cur.get("active", False):
        status["active"] = False
        status["next_ping"] = None
    await write_status(redis, status)

    try:
        from ws_handlers.farming_logs import broadcaster
        await broadcaster.broadcast({
            "message": f"Keep-alive (DRY): {total} sentetik profil takip ediliyor",
            "level": "INFO",
            "timestamp": time.time(),
        })
    except Exception:
        pass
    logger.info("keep-alive dry: %s sentetik profil", total)
    return status


async def run_per_profile_cycle(redis) -> dict:
    """GERÇEK profil-başına keep-alive turu: her üretilmiş profilin çerezlerini KENDİ
    parmak izi (UA+viewport+locale+tz) + KENDİ proxy'siyle bir context'e yükleyip
    Google'a uğratır → oturum sunucu tarafında tazelenir, ömür uzar. Ağırdır (gerçek
    tarayıcı açar); sadece ayardan açıkken ve GERÇEK modda çalışır. Ekran gösterilmez."""
    import glob
    status = await read_status(redis)

    root = settings.cookies_output_dir
    files = glob.glob(os.path.join(root, "*", "profile_*.json"))
    files.sort()                     # deterministik sıra → offset ile ADİL rotasyon
    MAX_PER_CYCLE = 300              # güvenlik: tek turda en fazla bu kadar profil yenile
    total_all = len(files)
    # ROLLING OFFSET (Tur4): sabit files[:300] her 24s turda AYNI baş 300'ü yeniliyordu → 300+
    # profiller HİÇ ziyaret edilmeyip Google'da sessizce ölüyordu (keep-alive'ın amacının tersi).
    # Redis'te dönen bir offset tut, [offset:offset+300] dilimini al ve sar → tüm popülasyon
    # ardışık turlarda kapsanır.
    if total_all > MAX_PER_CYCLE:
        try:
            offset = int(await redis.get("keepalive:ppc_offset") or 0) % total_all
        except Exception:
            offset = 0
        sel = files[offset:offset + MAX_PER_CYCLE]
        if len(sel) < MAX_PER_CYCLE:                 # sona gelindi → baştan sar
            sel += files[:MAX_PER_CYCLE - len(sel)]
        files = sel
        try:
            await redis.set("keepalive:ppc_offset", (offset + MAX_PER_CYCLE) % total_all)
        except Exception:
            pass
    else:
        files = files[:MAX_PER_CYCLE]
    total = len(files)

    # Redis takip penceresini de yenile (rolling) — genel turdaki gibi.
    ttl = settings.redis_session_ttl
    if ttl and ttl > 0:
        try:
            for k in await redis.keys("session:*"):
                await redis.expire(k, ttl)
        except Exception:
            pass

    success = 0
    processed = 0
    # CANLI: tur BAŞLARKEN 'çalışıyor' durumunu yaz → panel gerçek-zamanlı ilerleme görsün
    # (eskiden yalnız tur BİTİNCE yazılıyordu → 24 saat boyunca 'stuck' görünüyordu).
    now0 = datetime.now(timezone.utc)
    status["running"] = True
    status["last_ping"] = now0.isoformat()
    status["total_count"] = total
    status["success_count"] = 0
    status["processed"] = 0
    await write_status(redis, status)
    if total:
        try:
            from patchright.async_api import async_playwright
        except ImportError:
            from playwright.async_api import async_playwright

        # Scrapingbee kimliğini GÜNCEL config'den al — API anahtarı profil dosyasına
        # YAZILMAZ (export edilen profillere sızmasın), burada runtime'da eklenir.
        # ScrapingBee yapılandırmasını bir KEZ yükle; ama sticky proxy'yi profil-BAŞINA,
        # doğum session anahtarıyla kur (#8) — tek global session'sız proxy her turda
        # RASTGELE exit IP verir ve yaşlandırılmış oturumun IP sürekliliğini bozardı.
        _sb_cfg = None
        _sb_ak = ""
        _sb_build = None
        sb_proxy = None  # session'sız yedek (doğum session anahtarı yoksa)
        try:
            from services.proxy_config import load_proxy_settings
            from services.proxy_rotator import build_scrapingbee_proxy
            _cfg = await load_proxy_settings(redis)
            if _cfg.get("provider") == "scrapingbee":
                _keys = _cfg.get("api_keys") or []
                _ak = _keys[_cfg.get("active_index", 0)] if _keys else ""
                if _ak:
                    _sb_cfg, _sb_ak, _sb_build = _cfg, _ak, build_scrapingbee_proxy
                    sb_proxy = build_scrapingbee_proxy(_cfg, _ak)  # session'sız yedek
        except Exception:
            _sb_cfg = None
            sb_proxy = None

        # BİRTH==USE: keep-alive de doğum parmak izini BİREBİR replay etmeli. Sadece context
        # opsiyonları (UA/viewport) YETMEZ — stealth script (userAgentData mobil, WebGL Adreno/Mali,
        # navigator.platform=Linux armv8l, seed'li canvas/webgl/audio de-korelasyon) + Client Hints
        # (Sec-CH-UA-Platform=Android, doğum Chrome sürümü) enjekte EDİLMEZSE, aged mobil çerez
        # GERÇEK headless-Linux cihaz (SwiftShader/Linux x86_64) gibi Google'a gider → oturum yanar
        # (birth/live_check ikisi de enjekte ediyor; keep-alive tek eksikti). Tur3 HIGH.
        from services.fingerprint_service import FingerprintService
        from services.live_check import _fp_from_stored
        _fsvc = FingerprintService()

        # CLASSIC headless (farming ile AYNI). '--headless=new'/headful bu GPU'suz container'da
        # 'browser has been closed' ile ÇÖKÜYOR → keep-alive turu hiç başlamıyordu. Düzeltildi.
        base_args = ["--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        sem = asyncio.Semaphore(2)  # DÜŞÜK eşzamanlılık → backend web sürecini bozmaz (OOM yok)
        async with async_playwright() as p:
            # Sandbox AÇIK dene; ortam desteklemiyorsa --no-sandbox'a düş (farming ile aynı;
            # koşulsuz --no-sandbox güvenlik gerilemesiydi).
            try:
                browser = await p.chromium.launch(headless=True, args=base_args)
            except Exception:
                browser = await p.chromium.launch(headless=True, args=base_args + ["--no-sandbox"])

            async def refresh_one(path):
                nonlocal success, processed
                async with sem:
                    ctx = None
                    try:
                        with open(path, "rb") as fh:
                            data = orjson.loads(fh.read())
                        fp = data.get("fingerprint") or {}
                        cookies = (data.get("storage_state") or {}).get("cookies") or []
                        # Doğum parmak izini nesneye kur → stealth script + Client Hints için (birth==use).
                        fp_obj = _fp_from_stored(fp)
                        opts = {}
                        if fp.get("user_agent"):  opts["user_agent"] = fp["user_agent"]
                        if fp.get("viewport"):    opts["viewport"] = fp["viewport"]
                        if fp.get("locale"):      opts["locale"] = fp["locale"]
                        if fp.get("timezone_id"): opts["timezone_id"] = fp["timezone_id"]
                        # Client Hints (Sec-CH-UA-Platform=Android + doğum Chrome sürümü) — UA-vs-CH
                        # uyuşmazlığını (H1) kapatır; birth/get_context_options + live_check de yapıyor.
                        try:
                            opts["extra_http_headers"] = _fsvc._ua_ch_headers(fp_obj)
                        except Exception:
                            pass
                        # ÖMÜR: doğum parmak izini BİREBİR tekrar kullan (mobil/touch/dpr) —
                        # aksi halde mobil UA + masaüstü context uyumsuzluğu oturumu öldürür.
                        if fp.get("is_mobile") is not None: opts["is_mobile"] = fp["is_mobile"]
                        if fp.get("has_touch") is not None: opts["has_touch"] = fp["has_touch"]
                        if fp.get("device_scale_factor"):   opts["device_scale_factor"] = fp["device_scale_factor"]
                        if fp.get("color_scheme"):          opts["color_scheme"] = fp["color_scheme"]
                        # Proxy'yi çöz: scrapingbee ise kimliği config'den al ve DOĞUM session
                        # anahtarıyla sticky exit-IP'yi tekrar kur (#8); diğerleri (IPv6/list)
                        # profildeki server + creds ile (genelde IP/user-authed).
                        pd = fp.get("proxy") or _proxy_dict(fp.get("proxy_ip") or data.get("proxy_ip") or "")
                        _born_with_proxy = bool(pd)   # doğumda proxy var mıydı? (artık TÜM çerezler proxy-doğumlu)
                        if pd and "scrapingbee" in (pd.get("server") or ""):
                            _sk = fp.get("sb_session_key") or ""
                            if _sb_build is not None and _sk:
                                # doğum sticky exit-IP'sini hedefle → IP sürekliliği korunur
                                pd = _sb_build(_sb_cfg, _sb_ak, session_key=_sk)
                            else:
                                pd = sb_proxy  # eski profil (session anahtarı yok) → session'sız yedek
                        # KRİTİK: doğumda proxy vardı ama şimdi ÇÖZÜLEMEDİ (scrapingbee kapalı/anahtar
                        # yok/config hatası) → proxysiz GİTME. Aksi halde aged mobil oturum sunucunun
                        # datacenter-IP'sinden Google'a gider, IP sürekliliği kırılır ve keep-alive'ın
                        # KORUMAYA çalıştığı çerezi TAM tersine YAKAR. Profili atla → oturum dokunulmaz kalır.
                        if _born_with_proxy and not pd:
                            logger.debug("keep-alive: proxy çözülemedi → profil atlandı (oturum korundu): %s", path)
                            return
                        if pd:
                            opts["proxy"] = pd
                            # Sertifika doğrulamasını YALNIZCA scrapingbee MITM proxy için kapat
                            # (koşulsuz kapatmak MITM'e açık bırakıyordu).
                            if "scrapingbee" in (pd.get("server") or ""):
                                opts["ignore_https_errors"] = True
                        ctx = await browser.new_context(**opts)
                        # STEALTH: doğum JS-cihaz kimliğini enjekte et (userAgentData mobil, WebGL
                        # Adreno/Mali, platform=Linux armv8l, seed'li canvas/webgl/audio de-korelasyon).
                        # Cookie'lerden ÖNCE ve document-start'ta çalışsın (birth/clicker ile aynı sıra).
                        try:
                            await ctx.add_init_script(_fsvc.get_stealth_script(fp_obj))
                        except Exception as _e:
                            logger.debug("keep-alive stealth enjekte edilemedi: %s", _e)
                        if cookies:
                            await ctx.add_cookies(cookies)
                        page = await ctx.new_page()
                        await page.goto("https://myaccount.google.com/",
                                        wait_until="domcontentloaded", timeout=25000)
                        url = page.url or ""
                        # Login sayfasına atmadıysa oturum canlı → tazelendi say.
                        if "myaccount.google.com" in url and "signin" not in url:
                            success += 1
                    except Exception as e:
                        logger.debug("pp keep-alive profil atlandı (%s): %s", path, e)
                    finally:
                        if ctx is not None:
                            try:
                                await ctx.close()
                            except Exception:
                                pass
                        # CANLI İLERLEME: her profil bitince sayaçları güncelle → panel akışı görsün.
                        processed += 1
                        try:
                            status["processed"] = processed
                            status["success_count"] = success
                            status["total_count"] = total
                            await write_status(redis, status)
                        except Exception:
                            pass

            await asyncio.gather(*[refresh_one(f) for f in files])
            try:
                await browser.close()
            except Exception:
                pass

    now = datetime.now(timezone.utc)
    status["running"] = False          # tur bitti (panel 'çalışıyor' göstergesini kapatsın)
    status["processed"] = total
    status["last_ping"] = now.isoformat()
    status["next_ping"] = (now + timedelta(hours=PING_PERIOD_HOURS)).isoformat()
    status["total_count"] = total
    status["success_count"] = success
    status["success_rate"] = round((success / total) * 100, 1) if total else 0
    # Toggle-OFF yarışı: kullanıcı bu tur sırasında keep-alive'ı KAPATTIYSA 'active'ı geri açma.
    _cur = await read_status(redis)
    if not _cur.get("active", False):
        status["active"] = False
        status["next_ping"] = None
    await write_status(redis, status)

    try:
        from ws_handlers.farming_logs import broadcaster
        await broadcaster.broadcast({
            "message": f"Profil-başına keep-alive: {success}/{total} oturum tazelendi",
            "level": "INFO",
            "timestamp": time.time(),
        })
    except Exception:
        pass

    logger.info("pp keep-alive: %s/%s profil", success, total)
    return status


async def keepalive_loop(app) -> None:
    """Arka plan döngüsü: aktifse ve next_ping zamanı geldiyse bir tur çalıştırır."""
    while True:
        try:
            redis = getattr(app.state, "redis", None)
            if redis is not None:
                status = await read_status(redis)
                if status.get("active"):
                    np = status.get("next_ping")
                    due = True
                    if np:
                        try:
                            due = datetime.now(timezone.utc) >= datetime.fromisoformat(np)
                        except Exception:
                            due = True
                    if due:
                        await run_ping_cycle(redis)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("keep-alive loop hatası: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)
