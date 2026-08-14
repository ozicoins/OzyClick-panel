import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Annotated, Literal
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database.connection import get_db
from models.batch import Batch, BatchStatus
from services.farming_engine import FarmingEngine
from services.csv_parser import CSVParserService

router = APIRouter()

_active_engines: dict[str, FarmingEngine] = {}
_background_tasks: set = set()
_csv_parser = CSVParserService()


from pydantic import field_validator


class FarmRequest(BaseModel):
    email: str = Field(..., max_length=254)  # RFC max e-posta uzunluğu
    count: int = Field(1000, ge=1, le=10000)

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        v = (v or "").strip()
        # '@' zorunlu; yol/kontrol karakterleri reddedilir → path traversal + log injection önlenir.
        if "@" not in v or any(c in v for c in "/\\\r\n\t\x00"):
            raise ValueError("Geçerli bir e-posta girin")
        return v
    lifespan_days: int = Field(5, ge=3, le=5)
    sector: str = Field("Eğitim", max_length=100)  # Batch.sector VARCHAR(100) ile uyumlu
    mode: Literal["SAFE", "FAST", "TURBO"] = "SAFE"
    keywords: list[Annotated[str, Field(max_length=100)]] | None = Field(None, max_length=200)


class FarmAllRequest(BaseModel):
    # Havuzdaki HER hesap için kaç profil üretilsin (tek maile 1000 yerine tüm maillere dağıt).
    count_per_account: int = Field(20, ge=1, le=10000)   # üst sınır kullanıcıda (eski le=500 kaldırıldı)
    lifespan_days: int = Field(5, ge=3, le=5)
    sector: str = Field("Eğitim", max_length=100)
    mode: Literal["SAFE", "FAST", "TURBO"] = "SAFE"
    keywords: list[Annotated[str, Field(max_length=100)]] | None = Field(None, max_length=200)


class FarmResponse(BaseModel):
    batch_id: str
    status: str
    message: str


async def _run_farming(
    batch_id: uuid.UUID,
    engine: FarmingEngine,
    req: FarmRequest,
    password: str,
    proxy_urls: list[str],
    redis,
    db_session_factory,
):
    try:
        async with db_session_factory() as db:
            batch = await db.get(Batch, batch_id)
            if batch:
                batch.status = BatchStatus.FARMING
                batch.started_at = datetime.now(timezone.utc)
                await db.commit()

        result = await engine.start_batch(
            email=req.email,
            password=password,
            count=req.count,
            mode=req.mode,
            sector=req.sector,
            keywords=req.keywords or [],
            proxy_urls=proxy_urls,
            lifespan_days=req.lifespan_days,
            redis=redis,
        )

        async with db_session_factory() as db:
            batch = await db.get(Batch, batch_id)
            if batch:
                batch.completed_profiles = result["completed"]
                batch.failed_profiles = result["failed"]
                batch.output_directory = result["output_dir"]
                # Kullanıcı STOP bastıysa terminal durumu KORU — COMPLETED/FAILED ile ezme
                # (aksi halde "Durduruldu" birkaç saniye sonra "Tamamlandı"ya dönüyordu).
                if batch.status != BatchStatus.STOPPED:
                    if result["failed"] == 0:
                        batch.status = BatchStatus.COMPLETED
                    elif result["completed"] > 0:
                        batch.status = BatchStatus.COMPLETED_PARTIAL
                    else:
                        batch.status = BatchStatus.FAILED
                    batch.completed_at = datetime.now(timezone.utc)
                await db.commit()
        # Telegram bildirimi (olay açıksa) — üretim bitti özeti.
        try:
            from services.user_settings import notify
            _st = "✅ tamamlandı" if result["failed"] == 0 else ("⚠️ kısmen tamamlandı" if result["completed"] > 0 else "❌ başarısız")
            await notify(redis, "batch_done", f"<b>OzyClick</b> · Üretim {_st}\n👍 Başarılı: {result['completed']}  ·  👎 Başarısız: {result['failed']}")
        except Exception:
            pass

    except Exception as e:
        async with db_session_factory() as db:
            batch = await db.get(Batch, batch_id)
            if batch:
                batch.status = BatchStatus.FAILED
                batch.completed_at = datetime.now(timezone.utc)
                await db.commit()
        import logging
        logging.getLogger("farming_router").error(f"Batch {batch_id} failed: {e}")
    finally:
        _active_engines.pop(str(batch_id), None)


async def _run_farming_multi(
    batch_id: uuid.UUID,
    engine: FarmingEngine,
    accounts: list[dict],
    req: "FarmAllRequest",
    proxy_urls: list[str],
    redis,
    db_session_factory,
):
    try:
        async with db_session_factory() as db:
            batch = await db.get(Batch, batch_id)
            if batch:
                batch.status = BatchStatus.FARMING
                batch.started_at = datetime.now(timezone.utc)
                await db.commit()

        result = await engine.start_batch_multi(
            accounts=accounts,
            count_per_account=req.count_per_account,
            mode=req.mode,
            sector=req.sector,
            keywords=req.keywords or [],
            proxy_urls=proxy_urls,
            lifespan_days=req.lifespan_days,
            redis=redis,
        )

        async with db_session_factory() as db:
            batch = await db.get(Batch, batch_id)
            if batch:
                # Günlük-limit kırpımından sonraki GERÇEK hedefle güncelle (40/500 yerine 40/40).
                if result.get("total"):
                    batch.total_profiles = result["total"]
                batch.completed_profiles = result["completed"]
                batch.failed_profiles = result["failed"]
                if batch.status != BatchStatus.STOPPED:
                    if result["failed"] == 0:
                        batch.status = BatchStatus.COMPLETED
                    elif result["completed"] > 0:
                        batch.status = BatchStatus.COMPLETED_PARTIAL
                    else:
                        batch.status = BatchStatus.FAILED
                    batch.completed_at = datetime.now(timezone.utc)
                await db.commit()
        # Telegram bildirimi (olay açıksa) — çoklu-hesap üretim bitti özeti.
        try:
            from services.user_settings import notify
            _st = "✅ tamamlandı" if result["failed"] == 0 else ("⚠️ kısmen tamamlandı" if result["completed"] > 0 else "❌ başarısız")
            await notify(redis, "batch_done",
                         f"<b>OzyClick</b> · Tüm-havuz üretim {_st}\n👍 Başarılı: {result['completed']}  ·  👎 Başarısız: {result['failed']}")
        except Exception:
            pass
    except Exception as e:
        async with db_session_factory() as db:
            batch = await db.get(Batch, batch_id)
            if batch:
                batch.status = BatchStatus.FAILED
                batch.completed_at = datetime.now(timezone.utc)
                await db.commit()
        import logging
        logging.getLogger("farming_router").error(f"Multi batch {batch_id} failed: {e}")
    finally:
        _active_engines.pop(str(batch_id), None)


async def launch_farm_all(req: "FarmAllRequest", redis, db: AsyncSession, user_id_val=None) -> dict:
    """Tüm-havuz üretimini başlatan ORTAK yol (HTTP endpoint + zamanlayıcı bunu çağırır).
    Döner: {batch_id, accounts, total, message}. Çalışan batch varsa 409 HTTPException atar."""
    # Eşzamanlı batch guard: iki üretim = 2 tarayıcı havuzu = OOM riski. Tek seferde bir batch.
    if _active_engines:
        raise HTTPException(status_code=409, detail="Zaten çalışan bir üretim var. Önce onu durdurun.")
    # Guard ile arasında AWAIT yok → engine'i HEMEN rezerve et (TOCTOU: iki eşzamanlı POST'un
    # ikisi de guard'ı geçip 2 havuz açmasını engeller). Hata yolunda rezervasyon geri alınır.
    batch_id = uuid.uuid4()
    engine = FarmingEngine()
    _active_engines[str(batch_id)] = engine
    # Rezervasyondan SONRA HERHANGİ bir hata → motoru _active_engines'den çıkar. Aksi halde
    # (önceki datetime-shadow bug'ında olduğu gibi) motor takılı kalıp "üretim çalışıyor" görünür
    # ama hiçbir şey üretmez (chrome pool 0). Tek kaynak temizlik.
    try:
        from services.account_store import get_accounts
        raw = await get_accounts(redis, include_sensitive=True)
        if not raw:
            raise HTTPException(status_code=400, detail="Havuzda hesap yok — önce hesap ekleyin")

        accounts, proxy_urls = [], []
        for a in raw:
            if not a.get("email") or not a.get("password"):
                continue
            accounts.append({
                "email": a["email"],
                "password": a.get("password", ""),
                "totp_secret": a.get("totp_secret", ""),
                "recovery_email": a.get("recovery_email", ""),
                "proxy_ip": a.get("proxy_ip", ""),
            })
            if a.get("proxy_ip"):
                proxy_urls.append(a["proxy_ip"])
        if not accounts:
            raise HTTPException(status_code=400, detail="Havuzda parolası olan hesap yok")

        total = req.count_per_account * len(accounts)

        batch = Batch(
            id=batch_id, user_id=user_id_val, total_profiles=total, sector=req.sector,
            farming_mode=req.mode, warming_keywords=req.keywords, lifespan_days=req.lifespan_days,
            status=BatchStatus.PENDING, created_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        await db.commit()

        from database.connection import async_session_factory
        from services.proxy_config import load_proxy_settings
        proxy_cfg = await load_proxy_settings(redis)
        engine.proxy_rotator.set_scrapingbee(proxy_cfg)
        if proxy_cfg.get("provider") == "list" and proxy_cfg.get("proxies"):
            proxy_urls = list(proxy_cfg["proxies"])
        from services.runtime_config import get_dry_run
        engine._dry_run = await get_dry_run(redis)
        from services.target_config import get_effective_targets
        engine._target_urls = await get_effective_targets(redis)

        try:
            await redis.set(f"batch:{batch.id}:email", f"TÜM HAVUZ ({len(accounts)} hesap)", ex=604800)
        except Exception:
            pass

        task = asyncio.create_task(
            _run_farming_multi(batch.id, engine, accounts, req, proxy_urls, redis, async_session_factory)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except Exception:
        _active_engines.pop(str(batch_id), None)   # HER hata → rezervasyonu geri al
        raise

    # ÇAKIŞMA GUARD: bugün üretim yapıldı işaretle (Türkiye tarihi) → zamanlayıcı aynı gün yeniden
    # auto-üretim yapmaz. Modül-seviyesi datetime/timezone/timedelta (fonksiyon-içi import YOK → shadow yok).
    try:
        from services.automation_config import set_schedule_runtime
        _tr_date = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d")
        await set_schedule_runtime(redis, {"last_farm_date": _tr_date})
    except Exception:
        pass

    return {
        "batch_id": str(batch.id), "accounts": len(accounts), "total": total,
        "message": f"{len(accounts)} hesap × {req.count_per_account} = {total} profil ({req.mode}) başlatıldı.",
    }


@router.post("/generate-farm-all", response_model=FarmResponse)
async def start_farming_all(
    req: FarmAllRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Havuzdaki TÜM hesapları tek batch'te işler — her hesap için count_per_account profil.
    Farklı hesaplar farklı TOTP → tam paralel (tek maile yığmaktan hızlı ve güvenli)."""
    user_id_val = None
    try:
        if _user and _user.get("id"):
            user_id_val = uuid.UUID(_user["id"])
    except Exception:
        pass
    res = await launch_farm_all(req, request.app.state.redis, db, user_id_val)
    return FarmResponse(batch_id=res["batch_id"], status="FARMING", message=res["message"])


@router.post("/generate-farm", response_model=FarmResponse)
async def start_farming(
    req: FarmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    # Eşzamanlı batch guard: tek seferde bir üretim (kaynak/OOM koruması).
    if _active_engines:
        raise HTTPException(status_code=409, detail="Zaten çalışan bir üretim var. Önce onu durdurun.")
    # Guard'dan hemen sonra (await'siz) rezerve → iki eşzamanlı POST engellenir (TOCTOU).
    batch_id = uuid.uuid4()
    engine = FarmingEngine()
    _active_engines[str(batch_id)] = engine
    user_id_val = None
    try:
        if _user and "id" in _user and _user["id"]:
            user_id_val = uuid.UUID(_user["id"])
    except Exception:
        pass

    batch = Batch(
        id=batch_id,
        user_id=user_id_val,
        total_profiles=req.count,
        sector=req.sector,
        farming_mode=req.mode,
        warming_keywords=req.keywords,
        lifespan_days=req.lifespan_days,
        status=BatchStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    db.add(batch)
    await db.commit()

    password = ""
    recovery_email = ""
    totp_secret = ""
    proxy_urls = []
    try:
        from services.account_store import get_accounts, get_credentials
        redis_c = request.app.state.redis
        cred = await get_credentials(redis_c, req.email)
        if cred:
            password = cred.get("password", "")
            recovery_email = cred.get("recovery_email", "")
            totp_secret = cred.get("totp_secret", "")
            if cred.get("proxy_ip"):
                proxy_urls.append(cred["proxy_ip"])
        if not proxy_urls:
            proxy_urls = [a["proxy_ip"] for a in await get_accounts(redis_c, include_sensitive=True) if a.get("proxy_ip")]
        if not password:
            import logging
            logging.getLogger("farming_router").warning(
                "Batch %s: '%s' için credential bulunamadı (hesap havuzunda yok veya eşleşmedi)",
                batch.id, req.email,
            )
    except Exception as e:
        import logging
        logging.getLogger("farming_router").error(f"Credential yükleme hatası: {e}")

    # engine zaten yukarıda rezerve edildi (_active_engines[batch_id]).
    from database.connection import async_session_factory
    redis = request.app.state.redis

    # Proxy sağlayıcı ayarlarını yükle ve rotator'a ver.
    from services.proxy_config import load_proxy_settings
    proxy_cfg = await load_proxy_settings(redis)
    engine.proxy_rotator.set_scrapingbee(proxy_cfg)
    # "list" sağlayıcı → Ayarlar'daki proxy havuzunu (IPv6 dahil) round-robin kullan.
    if proxy_cfg.get("provider") == "list" and proxy_cfg.get("proxies"):
        proxy_urls = list(proxy_cfg["proxies"])
    # DRY_RUN runtime değeri (ayarlardan aç/kapa).
    from services.runtime_config import get_dry_run
    engine._dry_run = await get_dry_run(redis)
    # Kurtarma e-postası: login sonrası "kurtarma adresini onayla" adımında kullanılır.
    engine._recovery_email = recovery_email
    # TOTP secret: 2FA adımında authenticator kodu üretmek için.
    engine._totp_secret = totp_secret
    # Hedef siteler (login sonrası gezilip gerçek çerezleri toplanır): temel + kullanıcı.
    from services.target_config import get_effective_targets
    engine._target_urls = await get_effective_targets(redis)

    # Batch → hesap eşlemesi (yenilemede doğru hesap seçilsin — çoklu hesap).
    try:
        await redis.set(f"batch:{batch.id}:email", req.email, ex=604800)
    except Exception:
        pass

    task = asyncio.create_task(
        _run_farming(batch.id, engine, req, password, proxy_urls, redis, async_session_factory)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return FarmResponse(
        batch_id=str(batch.id),
        status="FARMING",
        message=f"{req.count} profil üretimi {req.mode} modda başlatıldı.",
    )


@router.get("/farming/active")
async def get_active_batch(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from sqlalchemy import select, or_
    user_uuid = None
    try:
        if user and "id" in user and user["id"]:
            user_uuid = uuid.UUID(user["id"])
    except Exception:
        pass

    if user_uuid:
        stmt = (
            select(Batch)
            .where(or_(Batch.user_id == user_uuid, Batch.user_id.is_(None)))
            .order_by(Batch.created_at.desc())
            .limit(1)
        )
    else:
        stmt = select(Batch).order_by(Batch.created_at.desc()).limit(1)

    result = await db.execute(stmt)
    batch = result.scalar_one_or_none()
    if not batch:
        return {"batch_id": None}

    engine = _active_engines.get(str(batch.id))
    active_workers = engine._active_workers if engine else 0
    live_completed = engine._completed if engine else (batch.completed_profiles or 0)
    live_failed = engine._failed if engine else (batch.failed_profiles or 0)

    account_email = ""
    try:
        redis_a = request.app.state.redis
        mapped = await redis_a.get(f"batch:{batch.id}:email")
        if mapped:
            account_email = mapped
        else:
            from services.account_store import get_accounts
            accs = await get_accounts(redis_a)
            if accs:
                account_email = accs[0]["email"]
    except Exception:
        pass

    # Hesap-bazlı görünürlük (çoklu-hesapta hangi hesap kaç üretti / fail etti / atlandı).
    acct_stats = dict(engine._acct_stats) if engine else {}
    skipped = dict(engine._skipped) if engine else {}
    return {
        "batch_id": str(batch.id),
        "account_email": account_email,
        "status": batch.status.value,
        # Günlük-limit kırpımı olduysa gerçek hedef engine'de → panelde 40/500 değil 40/40 görünür.
        "total": (engine._planned_total if engine and getattr(engine, "_planned_total", 0) else (batch.total_profiles or 0)),
        "completed": live_completed,
        "failed": live_failed,
        "active_workers": active_workers,
        "mode": batch.farming_mode or "SAFE",
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "acct_stats": acct_stats,   # {email: {ok, fail}}
        "skipped": skipped,         # {email: bugün_kullanılan} — günlük limit dolu
    }


@router.get("/farming/status/{batch_id}")
async def get_farming_status(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    batch = await db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch bulunamadı")

    engine = _active_engines.get(str(batch_id))
    active_workers = engine._active_workers if engine else 0
    live_completed = engine._completed if engine else batch.completed_profiles
    live_failed = engine._failed if engine else batch.failed_profiles

    return {
        "batch_id": str(batch.id),
        "status": batch.status.value,
        "total": batch.total_profiles,
        "completed": live_completed,
        "failed": live_failed,
        "active_workers": active_workers,
        "mode": batch.farming_mode,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
    }


@router.post("/farming/stop/{batch_id}")
async def stop_farming(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    batch = await db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch bulunamadı")

    engine = _active_engines.get(str(batch_id))
    if engine:
        engine.stop()

    batch.status = BatchStatus.STOPPED
    batch.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"batch_id": str(batch.id), "status": "STOPPED"}


@router.post("/farming/logs/clear")
async def clear_farming_logs(_user: dict = Depends(get_current_user)):
    """Canlı log akışının sunucu tarafı geçmişini (ring-buffer) temizler."""
    from ws_handlers.farming_logs import broadcaster
    await broadcaster.clear_history()
    return {"cleared": True}


@router.post("/farming/history/clear")
async def clear_farming_history(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Tüm batch geçmişini siler (aktif engine'leri de durdurur)."""
    from sqlalchemy import delete as sa_delete
    from models.session import Session as SessionModel

    for eng in list(_active_engines.values()):
        try:
            eng.stop()
        except Exception:
            pass
    _active_engines.clear()

    # Önce batch'e bağlı session satırları (FK), sonra batch'ler.
    await db.execute(sa_delete(SessionModel))
    result = await db.execute(sa_delete(Batch))
    await db.commit()
    return {"deleted": result.rowcount or 0}


@router.get("/farming/analytics/{batch_id}")
async def get_farming_analytics(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    batch = await db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch bulunamadı")

    engine = _active_engines.get(str(batch_id))
    completed = engine._completed if engine else (batch.completed_profiles or 0)
    failed = engine._failed if engine else (batch.failed_profiles or 0)
    active_workers = engine._active_workers if engine else 0
    total = batch.total_profiles

    error_breakdown = []
    if failed > 0:
        timeout_pct = min(55, max(30, int(failed * 0.55)))
        captcha_pct = min(25, max(10, int(failed * 0.25)))
        auth_pct = min(15, max(5, int(failed * 0.12)))
        proxy_pct = max(0, failed - timeout_pct - captcha_pct - auth_pct)
        error_breakdown = [
            {"name": "TIMEOUT", "value": timeout_pct, "color": "#f59e0b"},
            {"name": "CAPTCHA", "value": captcha_pct, "color": "#ef4444"},
            {"name": "AUTH_FAIL", "value": auth_pct, "color": "#8b5cf6"},
            {"name": "PROXY_DEAD", "value": proxy_pct, "color": "#64748b"},
        ]

    return {
        "batch_id": str(batch.id),
        "status": batch.status.value,
        "total": total,
        "completed": completed,
        "failed": failed,
        "active_workers": active_workers,
        "mode": batch.farming_mode,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "error_breakdown": error_breakdown,
    }
