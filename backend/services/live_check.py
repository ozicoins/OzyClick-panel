"""Canlı çerez kontrolü — üretilen bir profilin çerezini DOĞDUĞU parmak izi + Türk proxy ile
Google'a yükleyip oturumun HÂLÂ AKTİF olup olmadığını doğrular ('live cookie' garantisi).

Ağır (profil başına gerçek tarayıcı) → eşzamanlılık düşük tutulur (OOM yok).
"""
import asyncio
import logging

logger = logging.getLogger("live_check")

_sem = asyncio.Semaphore(2)   # aynı anda en fazla 2 canlı-kontrol tarayıcısı


def _proxy_to_pw(url: str):
    if not url:
        return None
    s = url.strip()
    if "://" not in s:
        s = "http://" + s
    try:
        from urllib.parse import urlparse, unquote
        u = urlparse(s)
        if not u.hostname:
            return None
        host = u.hostname
        if ":" in host:
            host = f"[{host}]"
        server = f"{u.scheme}://{host}:{u.port}" if u.port else f"{u.scheme}://{host}"
        d = {"server": server}
        if u.username:
            d["username"] = unquote(u.username)
        if u.password:
            d["password"] = unquote(u.password)
        return d
    except Exception:
        return None


def _sanitize_cookies(cookies: list[dict]) -> list[dict]:
    """add_cookies patlamasın: sameSite=None → secure=True; geçersiz sameSite düzeltilir."""
    out = []
    for c in cookies:
        ss = c.get("sameSite")
        if ss not in ("Strict", "Lax", "None"):
            ss = None
        ck = {k: c[k] for k in ("name", "value", "domain", "path") if c.get(k) is not None}
        if "expires" in c and isinstance(c["expires"], (int, float)) and c["expires"] > 0:
            ck["expires"] = c["expires"]
        ck["httpOnly"] = bool(c.get("httpOnly", False))
        ck["secure"] = bool(c.get("secure", False))
        if ss:
            if ss == "None":
                ck["secure"] = True
            ck["sameSite"] = ss
        if ck.get("name") and ck.get("domain"):
            out.append(ck)
    return out


def _fp_from_stored(fp: dict):
    """Saklı fingerprint dict'inden BrowserFingerprint kur → stealth+Client Hints birebir uygulanır."""
    import re
    from services.fingerprint_service import BrowserFingerprint, gpu_for_model
    ua = fp.get("user_agent", "") or ""
    cver = (re.search(r"Chrome/(\d+)", ua) or [None, "131"])[1] if "Chrome/" in ua else "131"
    mm = re.search(r"Android \d+; ([^)]+)\)", ua)
    av = re.search(r"Android (\d+)", ua)
    _device = fp.get("device", "") or ""
    _model = fp.get("model") or (mm.group(1).strip() if mm else "SM-S911B")
    # WebGL: saklıysa BİREBİR kullan; yoksa model/cihazdan GERÇEK GPU'yu katalogdan çöz (eski
    # profiller webgl saklamıyordu, sabit Adreno-740 default'u Samsung A-serisinde İMKANSIZ
    # eşleşme veriyordu, Tur4). Katalog bulamazsa nötr ARM/Mali default'una düş (Adreno-flagship DEĞİL).
    _wv = fp.get("webgl_vendor")
    _wr = fp.get("webgl_renderer")
    if not (_wv and _wr):
        _gv, _gr = gpu_for_model(_model, _device)
        _wv = _wv or _gv or "ARM"
        _wr = _wr or _gr or "Mali-G78"
    return BrowserFingerprint(
        user_agent=ua,
        viewport=fp.get("viewport") or {"width": 390, "height": 844},
        hardware_concurrency=fp.get("hardware_concurrency", 8),
        device_memory=fp.get("device_memory", 8),
        device_scale_factor=fp.get("device_scale_factor", 3.0),
        is_mobile=bool(fp.get("is_mobile", True)),
        has_touch=bool(fp.get("has_touch", True)),
        platform=fp.get("platform", "Linux armv8l"),
        gpu_vendor=_wv,
        gpu_renderer=_wr,
        device_name=_device,
        locale=fp.get("locale", "tr-TR"),
        timezone_id=fp.get("timezone_id", "Europe/Istanbul"),
        model=_model,
        os_version=fp.get("os_version") or (av.group(1) if av else "14"),
        browser_version=str(cver),
        canvas_noise=int(fp.get("canvas_noise", 1) or 1),
        # DE-KORELASYON tohumunu DA geri yükle — yoksa live-check zayıf canvas yoluna düşer,
        # doğum (seed'li güçlü canvas/webgl/audio) ile FARKLI hash üretir → aynı hesap iki cihaz
        # gibi görünür, re-verify riski artar (H3 doğum==kontrol garantisi kırılırdı).
        noise_seed=int(fp.get("noise_seed", 0) or 0),
    )


async def check_profile_live(profile: dict, proxy_full: str | None, timeout_s: int = 35,
                             proxy_dict: dict | None = None) -> dict:
    """Döner: {alive: bool, url: str, detail: str}. alive=True → oturum aktif (Google girişli).
    Kontrol tarayıcısı da DOĞUM parmak izi + stealth + Client Hints ile kurulur → geçerli oturum
    yanlışlıkla 'pasif' görünmez (H3 fix).
    proxy_dict: önceden kurulmuş Playwright proxy dict'i (ScrapingBee gibi username=api_key/
    password=params olan, basit URL'ye sığmayan proxy'ler için). Verilirse proxy_full yerine
    o kullanılır — doğum exit-IP'sini BİREBİR replay etmek için (Tur3 #A)."""
    from patchright.async_api import async_playwright
    from services.fingerprint_service import FingerprintService

    fp = profile.get("fingerprint") or {}
    cookies = _sanitize_cookies((profile.get("storage_state") or {}).get("cookies") or [])
    if not cookies:
        return {"alive": False, "url": "", "detail": "çerez yok"}

    fp_obj = _fp_from_stored(fp)
    fsvc = FingerprintService()
    stealth = fsvc.get_stealth_script(fp_obj)
    ch_headers = fsvc._ua_ch_headers(fp_obj)
    ua = fp_obj.user_agent
    vp = fp_obj.viewport
    # Önceden kurulmuş dict (ScrapingBee sticky exit vb.) öncelikli; yoksa URL string'i çöz.
    proxy = proxy_dict if proxy_dict else (_proxy_to_pw(proxy_full) if proxy_full else None)

    async with _sem:
        browser = None
        try:
            async with async_playwright() as p:
                try:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=["--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
                    )
                except Exception:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
                    )
                ctx_opts = {
                    "user_agent": ua,
                    "viewport": vp,
                    "locale": fp_obj.locale,
                    "timezone_id": fp_obj.timezone_id,
                    "is_mobile": fp_obj.is_mobile,
                    "has_touch": fp_obj.has_touch,
                    "device_scale_factor": fp_obj.device_scale_factor,
                    "extra_http_headers": ch_headers,   # MOBİL Client Hints (H1)
                }
                if proxy:
                    ctx_opts["proxy"] = proxy
                    # Sertifika doğrulamasını YALNIZCA scrapingbee MITM proxy için kapat (Tur3 #D).
                    # Koşulsuz kapatmak, canlı AUTH çerezleri yüklüyken non-MITM/residential
                    # proxy yolunda sahte-sertifikayı kabul edip çerez sızıntısına (MITM) açık bırakıyordu.
                    if "scrapingbee" in (proxy.get("server") or ""):
                        ctx_opts["ignore_https_errors"] = True
                ctx = await browser.new_context(**ctx_opts)
                try:
                    await ctx.add_init_script(stealth)   # webdriver/userAgentData/webgl (H3)
                except Exception:
                    pass
                try:
                    await ctx.add_cookies(cookies)
                except Exception as e:
                    return {"alive": False, "url": "", "detail": f"çerez yüklenemedi: {str(e)[:40]}"}
                page = await ctx.new_page()
                try:
                    await page.goto("https://myaccount.google.com/", wait_until="domcontentloaded", timeout=timeout_s * 1000)
                except Exception:
                    pass
                await asyncio.sleep(2.5)
                url = page.url.lower()
                # Aktif: myaccount'ta kaldı; Pasif: signin/ServiceLogin'e atıldı.
                alive = ("myaccount.google.com" in url) and not any(
                    k in url for k in ("signin", "servicelogin", "identifier", "/v3/signin")
                )
                return {"alive": alive, "url": page.url, "detail": "aktif oturum" if alive else "pasif / giriş istiyor"}
        except Exception as e:
            return {"alive": False, "url": "", "detail": f"kontrol hatası: {str(e)[:60]}"}
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
