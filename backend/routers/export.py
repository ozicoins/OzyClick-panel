import os
import shutil
import orjson
from fastapi import APIRouter, Query, HTTPException, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse, ORJSONResponse
from pydantic import BaseModel, Field
from config import settings
from services.exporter import ExporterService
from auth import get_current_user

router = APIRouter()
exporter = ExporterService()


def _sanitize_email(email: str) -> str:
    if "/" in email or "\\" in email or ".." in email or "\x00" in email:
        raise HTTPException(status_code=400, detail="Geçersiz email")
    return email.replace("@", "_at_").replace(".", "_")


def _safe_join(email: str, *parts: str) -> str:
    """Email'den türetilen yolun cookies_output_dir içinde kaldığını doğrular."""
    sanitized = _sanitize_email(email)
    base_real = os.path.realpath(settings.cookies_output_dir)
    full = os.path.realpath(os.path.join(base_real, sanitized, *parts))
    if full != base_real and not full.startswith(base_real + os.sep):
        raise HTTPException(status_code=400, detail="Geçersiz yol")
    return full


@router.get("/export/manifest")
async def download_manifest(
    email: str = Query(...),
    _user: dict = Depends(get_current_user),
):
    from datetime import datetime, timezone
    output_dir = _safe_join(email)
    if not os.path.isdir(output_dir):
        raise HTTPException(status_code=404, detail="Bu hesap için henüz profil üretilmedi. Lütfen önce üretimi başlatın.")

    path = os.path.join(output_dir, "batch_manifest.json")
    profile_files = sorted([
        f for f in os.listdir(output_dir) if f.startswith("profile_") and f.endswith(".json")
    ])
    # Manifest'i disk'ten yeniden kur: dosya YOK ise VEYA BOŞ/bozuk ise VEYA sayısı disk'teki
    # gerçek profil sayısıyla UYUŞMUYORSA. Eskiden yalnız 'dosya yok' durumunda kuruluyordu →
    # boş-üzerine-yazılmış manifest (günlük-limit/çökme kaynaklı) olduğu gibi 0 profil servis
    # ediyordu, oysa diskte gerçek çerezler duruyordu → "üretiyor ama kaydetmiyor" görüntüsü (C).
    _need_rebuild = True
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            with open(path, "rb") as f:
                _m = orjson.loads(f.read())
            _need_rebuild = int(_m.get("totalProfiles", -1)) != len(profile_files)
        except Exception:
            _need_rebuild = True
    if _need_rebuild:
        if not profile_files:
            raise HTTPException(status_code=404, detail="İndirilecek profil dosyası bulunamadı. Lütfen önce üretimi başlatın.")
        manifest = {
            "accountEmail": email,
            "totalProfiles": len(profile_files),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "profiles": [{"file": f} for f in profile_files],
        }
        with open(path, "wb") as f:
            f.write(orjson.dumps(manifest, option=orjson.OPT_INDENT_2))

    return FileResponse(path, filename="batch_manifest.json", media_type="application/json")


@router.get("/export/gologin")
async def download_gologin_cookies(
    email: str = Query(...),
    profile_index: int = Query(1, ge=1),
    _user: dict = Depends(get_current_user),
):
    """Tek profilin çerezlerini GoLogin/AdsPager/Multilogin-uyumlu JSON dizisi olarak döndürür.
    GoLogin profilinde 'Cookies' alanına yapıştırılır (veya dosya olarak import edilir)."""
    path = _safe_join(email, f"profile_{profile_index:05d}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Profil bulunamadı")
    with open(path, "rb") as f:
        profile = orjson.loads(f.read())
    cookies = (profile.get("storage_state") or {}).get("cookies") or []
    gologin = exporter.to_gologin_cookies(cookies)
    sanitized = _sanitize_email(email)
    return ORJSONResponse(
        content=gologin,
        headers={"Content-Disposition": f"attachment; filename={sanitized}_p{profile_index}_gologin.json"},
    )


@router.get("/export/adswhite")
async def download_adswhite_cookies(
    email: str = Query(...),
    profile_index: int = Query(1, ge=1),
    _user: dict = Depends(get_current_user),
):
    """Tek profilin çerezlerini adswhite/Playwright add_cookies-uyumlu JSON dizisi olarak döndürür.
    adswhite'ın 'Cookie Klasörü'ne konacak dosya (sameSite=None → secure=True güvenli)."""
    path = _safe_join(email, f"profile_{profile_index:05d}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Profil bulunamadı")
    with open(path, "rb") as f:
        profile = orjson.loads(f.read())
    cookies = (profile.get("storage_state") or {}).get("cookies") or []
    adsw = exporter.build_export(profile, cookies, "adswhite")   # TAM fingerprint + proxy + çerez
    sanitized = _sanitize_email(email)
    return ORJSONResponse(
        content=adsw,
        headers={"Content-Disposition": f"attachment; filename={sanitized}_p{profile_index}_adswhite.json"},
    )


@router.get("/export/single")
async def download_single(
    email: str = Query(...),
    profile_index: int = Query(1, ge=1),
    format: str = Query("adswhite", pattern="^(adswhite|gologin|universal|netscape|raw)$"),
    _user: dict = Depends(get_current_user),
):
    """Tek profili SEÇİLEN formatta indir: adswhite/gologin/universal (JSON) veya netscape (cookies.txt)."""
    path = _safe_join(email, f"profile_{profile_index:05d}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Profil bulunamadı")
    with open(path, "rb") as f:
        profile = orjson.loads(f.read())
    cookies = (profile.get("storage_state") or {}).get("cookies") or []
    sanitized = _sanitize_email(email)
    if format == "netscape":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            exporter.to_netscape_format(cookies),
            headers={"Content-Disposition": f"attachment; filename={sanitized}_p{profile_index}.txt"},
        )
    data = exporter.build_export(profile, cookies, format)
    return ORJSONResponse(
        content=data,
        headers={"Content-Disposition": f"attachment; filename={sanitized}_p{profile_index}_{format}.json"},
    )


@router.get("/session/check-live")
async def check_live(
    request: Request,
    email: str = Query(...),
    profile_index: int = Query(1, ge=1),
    _user: dict = Depends(get_current_user),
):
    """CANLI KONTROL: profilin çerezini DOĞDUĞU parmak izi + Türk proxy ile Google'a yükleyip
    oturum HÂLÂ AKTİF mi doğrular. Döner: {alive, url, detail}."""
    path = _safe_join(email, f"profile_{profile_index:05d}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Profil bulunamadı")
    with open(path, "rb") as f:
        profile = orjson.loads(f.read())

    # Proxy'yi (kimlik bilgili) config'den kurtar: doğum host:port ile eşleşeni, yoksa ilk Türk proxy.
    from services.proxy_config import load_proxy_settings
    from urllib.parse import urlparse
    cfg = await load_proxy_settings(request.app.state.redis)

    def _hp(u):
        try:
            p = urlparse(u if "://" in u else "http://" + u)
            return ((p.hostname or "").strip("[]"), p.port)
        except Exception:
            return (None, None)

    fp = profile.get("fingerprint") or {}
    birth = fp.get("proxy_ip") or profile.get("proxy_ip") or ""
    stored_proxy = fp.get("proxy") if isinstance(fp.get("proxy"), dict) else None
    proxy_dict = None
    proxy_full = None

    # ScrapingBee mi? SADECE DOĞUM verisinden karar ver (aktif config provider'ından DEĞİL) —
    # keepalive ile aynı. Aksi halde residential-doğumlu bir çerez, operatör provider'ı sonradan
    # scrapingbee'ye çevirdiğinde yanlışlıkla scrapingbee exit-IP'sinden kontrol edilip doğum
    # residential IP'sinden sapardı → yanlış 'pasif' (Tur5). Scrapingbee-doğumlu profiller zaten
    # hem stored_proxy.server hem proxy_ip'de 'proxy.scrapingbee.com' taşıdığından eşleşir.
    _is_sb = ("scrapingbee" in ((stored_proxy or {}).get("server") or "")) \
        or ("scrapingbee" in birth)
    if _is_sb:
        # ScrapingBee: doğum STICKY exit-IP'sini sb_session_key'den YENİDEN kur (keepalive #8 ile
        # aynı). Residential 'proxies' listesi scrapingbee'de BOŞ → eski kod eşleşme bulamayıp
        # proxysiz/datacenter-IP'den kontrol ediyordu (yanlış 'pasif' + oturumu yakma). Tur3 #A.
        _sk = fp.get("sb_session_key") or ""
        _keys = cfg.get("api_keys") or []
        _ak = _keys[cfg.get("active_index", 0)] if _keys else ""
        if _sk and _ak:
            from services.proxy_rotator import build_scrapingbee_proxy
            proxy_dict = build_scrapingbee_proxy(cfg, _ak, session_key=_sk)
    elif stored_proxy and stored_proxy.get("server"):
        # list/csv: doğum proxy'sini creds'iyle BİREBİR kullan (#15 tam saklıyor → doğum IP'si).
        if stored_proxy.get("username") or stored_proxy.get("password"):
            proxy_dict = stored_proxy
        else:
            # server-only (eski profil): config'den host:port ile creds'i tamamla; yoksa IP-authed varsay.
            _tgt = _hp(stored_proxy["server"])
            for pu in (cfg.get("proxies") or []):
                if _hp(pu) == _tgt and _tgt[0]:
                    proxy_full = pu
                    break
            if not proxy_full:
                proxy_dict = stored_proxy
    else:
        # doğum proxy dict'i yok → proxy_ip host:port ile config'de eşleştir (eski profil).
        _tgt = _hp(birth) if birth else (None, None)
        for pu in (cfg.get("proxies") or []):
            if _hp(pu) == _tgt and _tgt[0]:
                proxy_full = pu
                break

    # FAIL-CLOSED: doğumda proxy vardı ama HİÇBİRİ çözülemedi → proxysiz kontrol YAPMA. Aged mobil
    # oturumu sunucunun datacenter-IP'sinden açmak IP sürekliliğini kırar, yanlış 'pasif' verir ve
    # kontrol ettiği oturumu YAKAR (farming/keepalive de bu noktada fail-closed). Tur3 #A.
    if birth and not (proxy_dict or proxy_full):
        return {
            "alive": None, "skipped": True, "url": "",
            "detail": "Doğum proxy'si çözülemedi — canlı kontrol ATLANDI (oturum korundu; 'pasif' DEĞİL)",
        }

    from services.live_check import check_profile_live
    return await check_profile_live(profile, proxy_full, proxy_dict=proxy_dict)


@router.get("/proxy-map")
async def get_proxy_map(
    email: str = Query(...),
    _user: dict = Depends(get_current_user),
):
    output_dir = _safe_join(email)
    path = os.path.join(output_dir, "cookie_proxy_map.json")
    if not os.path.exists(path):
        return ORJSONResponse(content=[])
    with open(path, "rb") as f:
        data = orjson.loads(f.read())
    return ORJSONResponse(content=data)


@router.post("/export/purge")
async def purge_account_output(
    email: str = Query(...),
    _user: dict = Depends(get_current_user),
):
    """Seçili hesabın üretilmiş tüm profillerini (cookies_output/<email>) siler."""
    output_dir = _safe_join(email)
    base_real = os.path.realpath(settings.cookies_output_dir)
    # Güvenlik: asla kök çıktı klasörünü silme, yalnızca hesap alt-klasörünü.
    if output_dir == base_real or not output_dir.startswith(base_real + os.sep):
        raise HTTPException(status_code=400, detail="Geçersiz yol")
    if not os.path.isdir(output_dir):
        return {"deleted_files": 0}
    deleted = sum(1 for _ in os.scandir(output_dir))
    shutil.rmtree(output_dir, ignore_errors=True)
    return {"deleted_files": deleted}


@router.get("/export/zip")
async def download_zip(
    email: str = Query(...),
    _user: dict = Depends(get_current_user),
):
    output_dir = _safe_join(email)
    if not os.path.isdir(output_dir) or not os.listdir(output_dir):
        raise HTTPException(status_code=404, detail="Bu hesap için henüz indirilecek profil üretilmedi. Lütfen önce üretimi başlatın.")

    sanitized = _sanitize_email(email)
    stream = exporter.create_streaming_zip(output_dir)
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={sanitized}_profiles.zip"},
    )


@router.get("/export/stats")
async def export_stats(_user: dict = Depends(get_current_user)):
    """Havuzdaki TOPLAM üretilmiş profil (cookie) sayısı + hesap kırılımı."""
    return exporter.output_stats(settings.cookies_output_dir)


@router.get("/export/backups")
async def export_backups(_user: dict = Depends(get_current_user)):
    """Google Drive'a alınan ŞİFRELİ çerez yedeklerinin durumu.
    rclone + gdrive kimliği HOST'ta (container'da yok) → host cron'u `logs/backup_status.json`
    yazar; backend onu okuyup panele servis eder. Dosya yoksa 'henüz yok' döner (hata değil)."""
    path = os.path.join(os.path.realpath(settings.log_dir), "backup_status.json")
    if not os.path.exists(path):
        return ORJSONResponse(content={
            "enabled": False, "count": 0, "total_size": 0, "backups": [],
            "detail": "Yedek durumu henüz oluşmadı (ilk otomatik yedek bekleniyor).",
        })
    try:
        with open(path, "rb") as f:
            return ORJSONResponse(content=orjson.loads(f.read()))
    except Exception:
        return ORJSONResponse(content={
            "enabled": False, "count": 0, "total_size": 0, "backups": [],
            "detail": "Yedek durumu okunamadı.",
        })


@router.post("/export/backup-now")
async def backup_now(_user: dict = Depends(get_current_user)):
    """MANUEL yedek tetikler. Container rclone/gdrive'a erişemez (güvenlik: anahtar+token HOST'ta)
    → `logs/backup_request` tetik dosyası yazar; host systemd path-unit onu ANINDA görüp
    ozy_cookie_backup.sh'ı çalıştırır (tar+şifrele+Drive'a yükle). Panel getBackups ile takip eder."""
    flag = os.path.join(os.path.realpath(settings.log_dir), "backup_request")
    try:
        with open(flag, "w") as f:
            f.write("manual")
        return {"started": True, "detail": "Yedekleme tetiklendi — birkaç saniye içinde Drive'a alınır."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yedek tetiklenemedi: {e}")


@router.post("/export/scan-live")
async def start_live_scan(
    request: Request,
    auto_delete: bool | None = Query(None),
    _user: dict = Depends(get_current_user),
):
    """TOPLU CANLILIK TARAMASI: havuzdaki TÜM çerezleri kendi doğum-proxy'siyle Google'a uğratıp
    aktif mi kontrol eder (arka plan, hesap kırılımlı). Zaten çalışıyorsa yeni tur başlatmaz.
    auto_delete verilmezse otomatik-temizlik ayarı kullanılır (ölü çerezleri siler)."""
    from services import livescan
    from services.automation_config import get_auto_cleanup
    redis = request.app.state.redis
    ad = bool(auto_delete) if auto_delete is not None else await get_auto_cleanup(redis)
    started = livescan.start_scan(redis, auto_delete=ad)
    return {
        "started": started,
        "auto_delete": ad,
        "detail": ("Tarama başladı" + (" — ölüler silinecek." if ad else " — sonuç birkaç dakikada dolar."))
        if started else "Tarama zaten çalışıyor.",
    }


@router.get("/export/scan-live")
async def get_live_scan(request: Request, _user: dict = Depends(get_current_user)):
    """Son/aktif toplu canlılık taramasının durumu (ilerleme + hesap kırılımı)."""
    from services import livescan
    return await livescan.read_scan(request.app.state.redis)


class BackupConfigReq(BaseModel):
    interval_hours: int = Field(6, ge=1, le=168)   # 1 saat – 7 gün
    retention_days: int = Field(14, ge=1, le=365)


@router.get("/export/backup-config")
async def get_backup_config_ep(_user: dict = Depends(get_current_user)):
    """Yedek sıklığı (saat) + saklama süresi (gün). Host cron bu dosyadan okur."""
    from services.automation_config import get_backup_config
    return get_backup_config()


@router.put("/export/backup-config")
async def put_backup_config_ep(req: BackupConfigReq, _user: dict = Depends(get_current_user)):
    """Yedek sıklığı/saklama süresini güncelle. logs/backup_config.json'a yazılır; host uygulayıcı
    cron'u yeni sıklığa göre günceller (~5 dk içinde), retention'ı yedek script'i her turda okur."""
    from services.automation_config import set_backup_config
    return set_backup_config(req.interval_hours, req.retention_days)


@router.get("/export/failed-accounts")
async def get_failed_accounts(request: Request, _user: dict = Depends(get_current_user)):
    """Login veremeyen SORUNLU hesaplar (2FA ek-doğrulama / Google REDDETTİ / parola) — email+sebep+zaman.
    Üretim sırasında KALICI kaydedilir; panel yenilense de kalır. Kullanıcı düzeltince temizler."""
    redis = request.app.state.redis
    out = []
    try:
        raw = await redis.hgetall("farming:failed_accounts")
        for email, val in (raw or {}).items():
            em = email.decode() if isinstance(email, (bytes, bytearray)) else email
            try:
                d = orjson.loads(val)
            except Exception:
                d = {"reason": (val.decode() if isinstance(val, (bytes, bytearray)) else str(val)), "at": ""}
            out.append({"email": em, "reason": d.get("reason", ""), "at": d.get("at", "")})
    except Exception:
        pass
    out.sort(key=lambda x: x.get("at", ""), reverse=True)
    return {"accounts": out, "count": len(out)}


@router.post("/export/failed-accounts/clear")
async def clear_failed_accounts(request: Request, _user: dict = Depends(get_current_user)):
    """Sorunlu hesap listesini temizle (hesapları düzelttikten sonra)."""
    try:
        await request.app.state.redis.delete("farming:failed_accounts")
    except Exception:
        pass
    return {"cleared": True}


@router.post("/export/failed-accounts/remove")
async def remove_failed_account(request: Request, email: str = Query(...),
                                _user: dict = Depends(get_current_user)):
    """Tek bir sorunlu hesabı listeden çıkar (o hesabı düzelttiysen)."""
    try:
        await request.app.state.redis.hdel("farming:failed_accounts", email)
    except Exception:
        pass
    return {"removed": email}


@router.get("/export/all")
async def download_all(
    format: str = Query("adswhite", pattern="^(adswhite|gologin|universal|netscape|raw)$"),
    _user: dict = Depends(get_current_user),
):
    """TÜM hesaplardaki TÜM profilleri seçilen formatta tek ZIP olarak indirir.
    adswhite → 'Cookie Klasörü'; gologin/universal → GoLogin/AdsPower/Dolphin/Octo; netscape → cookies.txt; raw → Playwright."""
    base = os.path.realpath(settings.cookies_output_dir)
    stats = exporter.output_stats(base)
    if stats["total_profiles"] == 0:
        raise HTTPException(status_code=404, detail="Havuzda henüz üretilmiş profil yok.")
    stream = exporter.stream_all_transformed(base, format)
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=havuz_tumu_{format}.zip"},
    )


@router.post("/export/purge-all")
async def purge_all_output(_user: dict = Depends(get_current_user)):
    """Havuzdaki TÜM hesapların üretilmiş profillerini siler (yalnızca cookies_output içi)."""
    base_real = os.path.realpath(settings.cookies_output_dir)
    if not os.path.isdir(base_real):
        return {"deleted_accounts": 0, "deleted_profiles": 0}
    stats = exporter.output_stats(base_real)
    deleted_profiles = stats["total_profiles"]
    deleted_accounts = 0
    for entry in os.scandir(base_real):
        full = os.path.realpath(entry.path)
        # Güvenlik: yalnızca cookies_output ALTINDAKİ klasörleri sil.
        if entry.is_dir() and full.startswith(base_real + os.sep):
            shutil.rmtree(full, ignore_errors=True)
            deleted_accounts += 1
    return {"deleted_accounts": deleted_accounts, "deleted_profiles": deleted_profiles}
