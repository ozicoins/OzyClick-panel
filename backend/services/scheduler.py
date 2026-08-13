"""Üretim zamanlayıcı + günlük özet döngüsü. main.py lifespan içinde başlatılır.

Her 60 sn'de bir yapılandırmayı okur; zamanlanan saat geldiyse (10 dk'lık pencere, tick kaçarsa
yakalar) ve bu (gün+saat) için henüz çalışmadıysa TÜM-HAVUZ üretimini başlatır. Çalışma durumu
(last_run/last_summary) KULLANICI CONFIG'İNDEN AYRI redis anahtarında tutulur (API kaydı ezmez).
İşaretçi 'YYYY-MM-DD HH:MM' → saat değiştirilince aynı gün yeni saatte çalışır, ama aynı saatin
tekrar kaydı çift-çalıştırmaz. İşaretçi üretim BAŞARIYLA başladıktan SONRA yazılır → geçici hata
(DB/redis hazır değil, hesap yok) sonraki tick'te retry eder, günü sessizce atlamaz.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("scheduler")

CHECK_INTERVAL = 60
WINDOW_MIN = 10   # zamanlanan saatten sonra bu kadar dakika içinde çalıştır (tick kaçarsa yakala)
# TÜRKİYE saati: kalıcı UTC+3 (2016'dan beri DST yok) → sabit offset, tzdata bağımlılığı gerekmez.
# Zamanlanan HH:MM ve günlük özet saati KULLANICININ girdiği Türkiye saatidir (sunucu UTC olsa da).
TR_TZ = timezone(timedelta(hours=3))


def _parse_hhmm(s):
    try:
        h, m = str(s).split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except Exception:
        pass
    return None


def _matched_window_date(now: datetime, hhmm):
    """Eşleşen pencerenin BAŞLANGIÇ tarihini (YYYY-MM-DD) döndürür; pencere dışıysa None.
    Gece yarısını aşan pencereyi de yakalar (dün 23:5x → bugün 00:0x)."""
    hm = _parse_hhmm(hhmm)
    if not hm:
        return None
    for day_off in (0, 1):   # önce bugünün penceresi, sonra dünün (gece yarısı aşımı)
        base = (now - timedelta(days=day_off)).replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
        if base <= now < base + timedelta(minutes=WINDOW_MIN):
            return base.strftime("%Y-%m-%d")
    return None


# Geriye dönük/test amaçlı basit pencere kontrolü.
def _in_window(now: datetime, hhmm) -> bool:
    return _matched_window_date(now, hhmm) is not None


async def _maybe_farm(redis, sched, rt, now):
    if not sched.get("enabled"):
        return
    wdate = _matched_window_date(now, sched.get("time"))
    if wdate is None:
        return
    marker = f"{wdate} {sched.get('time')}"
    if rt.get("last_run") == marker:
        return
    from routers.farming import _active_engines, launch_farm_all, FarmAllRequest
    if _active_engines:
        # Aktif üretim var → bu tick atla. İşaretçi YAZILMAZ; pencere içinde sonraki tick tekrar dener.
        logger.info("scheduler: aktif üretim var → zamanlanan tur bu tick'te atlandı")
        return
    try:
        req = FarmAllRequest(
            count_per_account=int(sched.get("count_per_account", 20)),
            lifespan_days=int(sched.get("lifespan_days", 5)),
            sector=str(sched.get("sector", "Eğitim"))[:100],
            mode=sched.get("mode", "FAST"),
            keywords=None,
        )
        from database.connection import async_session_factory
        async with async_session_factory() as db:
            res = await launch_farm_all(req, redis, db, None)
        # BAŞARI → işaretçi yaz (aynı gün+saat tekrar etmesin). Koşu sırasında _active_engines zaten korur.
        from services.automation_config import set_schedule_runtime
        await set_schedule_runtime(redis, {"last_run": marker})
        logger.info("scheduler: zamanlanan üretim başladı: %s", res.get("message"))
        try:
            from services.user_settings import notify
            await notify(redis, "batch_done", f"<b>OzyClick</b> · ⏰ Zamanlanan üretim başladı\n{res.get('message')}")
        except Exception:
            pass
    except Exception as e:
        # İşaretçi YAZILMADI → geçici hataysa (DB/redis/hesap) sonraki tick retry eder (pencere içinde).
        logger.warning("scheduler: zamanlanan üretim başlatılamadı (tick'te retry edilecek): %s", e)


async def _compose_summary(redis) -> str:
    import os
    import orjson
    from config import settings as _s
    from services.exporter import ExporterService
    stats = ExporterService().output_stats(_s.cookies_output_dir)
    live = ""
    try:
        raw = await redis.get("livescan:status")
        if raw:
            d = orjson.loads(raw)
            ch = int(d.get("alive", 0)) + int(d.get("dead", 0))
            if ch:
                live = f"\n🩺 Canlılık: {d.get('alive', 0)}/{ch} (%{round(d['alive'] / ch * 100)})"
    except Exception:
        pass
    bk = ""
    try:
        p = os.path.join(os.path.realpath(_s.log_dir), "backup_status.json")
        if os.path.exists(p):
            with open(p, "rb") as f:
                b = orjson.loads(f.read())
            bk = f"\n💾 Drive yedek: {b.get('count', 0)} adet"
    except Exception:
        pass
    return (f"<b>OzyClick · Günlük Özet</b>\n"
            f"🍪 Çerez: {stats['total_profiles']} · {stats['accounts']} hesap{live}{bk}")


async def _maybe_summary(redis, sched, rt, now):
    if not sched.get("daily_summary"):
        return
    wdate = _matched_window_date(now, sched.get("summary_time"))
    if wdate is None:
        return
    marker = f"{wdate} {sched.get('summary_time')}"
    if rt.get("last_summary") == marker:
        return
    try:
        text = await _compose_summary(redis)
        from services.user_settings import notify
        sent = await notify(redis, "daily_summary", text)
        # Telegram kapalıysa bile işaretle (her tick tekrar denemesin); sadece işaretçiyi yaz.
        from services.automation_config import set_schedule_runtime
        await set_schedule_runtime(redis, {"last_summary": marker})
        if sent:
            logger.info("scheduler: günlük özet gönderildi")
    except Exception as e:
        logger.warning("scheduler: günlük özet başarısız (retry edilecek): %s", e)


async def scheduler_loop(app) -> None:
    while True:
        try:
            redis = getattr(app.state, "redis", None)
            if redis is not None:
                from services.automation_config import get_schedule, get_schedule_runtime
                now = datetime.now(TR_TZ)   # Türkiye saati — zamanlanan HH:MM bu saate göre eşleşir
                sched = await get_schedule(redis)
                rt = await get_schedule_runtime(redis)
                await _maybe_farm(redis, sched, rt, now)
                rt = await get_schedule_runtime(redis)   # farm last_run'ı güncellemiş olabilir
                await _maybe_summary(redis, sched, rt, now)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("scheduler loop hatası: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)
