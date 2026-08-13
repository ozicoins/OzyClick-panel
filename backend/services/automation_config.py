"""Otomasyon yapılandırmaları — üretim zamanlayıcı + otomatik ölü-çerez temizliği (redis),
ve yedek sıklığı/retention (host cron'un okuduğu dosya)."""
import os

import orjson

from config import settings

SCHEDULE_KEY = "config:schedule"           # SADECE kullanıcı ayarları (API yazar)
RUNTIME_KEY = "config:schedule:runtime"    # SADECE scheduler çalışma durumu (döngü yazar)
CLEANUP_KEY = "config:auto_cleanup"

# Kullanıcı-editli ayarlar (last_run/last_summary BURADA DEĞİL → ayrı anahtarda, çakışma yok).
DEFAULT_SCHEDULE = {
    "enabled": False,
    "time": "03:00",              # HH:MM — TÜRKİYE saati (UTC+3); scheduler bu saate göre eşleştirir
    "count_per_account": 20,
    "mode": "FAST",
    "lifespan_days": 5,
    "sector": "Alışveriş (E-Ticaret Harmanı)",
    "daily_summary": True,        # her gün özet Telegram'a gitsin mi
    "summary_time": "09:00",      # günlük özet saati (Türkiye)
}
_SCHED_KEYS = tuple(DEFAULT_SCHEDULE.keys())


async def get_schedule(redis) -> dict:
    cfg = dict(DEFAULT_SCHEDULE)
    if redis is not None:
        try:
            raw = await redis.get(SCHEDULE_KEY)
            if raw:
                stored = orjson.loads(raw)
                # SADECE bilinen anahtarlar → eski blob'daki last_run_date/last_summary_date gibi
                # kalıntılar yok sayılır (bir sonraki set_schedule'da kalıcı temizlenir = auto-migration).
                for k in _SCHED_KEYS:
                    if k in stored:
                        cfg[k] = stored[k]
        except Exception:
            pass
    return cfg


async def set_schedule(redis, patch: dict) -> dict:
    cur = await get_schedule(redis)
    for k in _SCHED_KEYS:
        if k in patch and patch[k] is not None:
            cur[k] = patch[k]
    if redis is not None:
        await redis.set(SCHEDULE_KEY, orjson.dumps(cur))
    return cur


async def get_schedule_runtime(redis) -> dict:
    """Scheduler çalışma durumu: last_run/last_summary = 'YYYY-MM-DD HH:MM' işaretçisi.
    Kullanıcı config'inden AYRI → API kaydı bu değerleri EZMEZ (çift-çalıştırma önlenir)."""
    rt = {"last_run": None, "last_summary": None}
    if redis is not None:
        try:
            raw = await redis.get(RUNTIME_KEY)
            if raw:
                rt.update(orjson.loads(raw))
        except Exception:
            pass
    return rt


async def set_schedule_runtime(redis, patch: dict) -> dict:
    cur = await get_schedule_runtime(redis)
    for k in ("last_run", "last_summary"):
        if k in patch:
            cur[k] = patch[k]
    if redis is not None:
        await redis.set(RUNTIME_KEY, orjson.dumps(cur))
    return cur


async def get_auto_cleanup(redis) -> bool:
    if redis is not None:
        try:
            raw = await redis.get(CLEANUP_KEY)
            if raw is not None:
                return bool(orjson.loads(raw))
        except Exception:
            pass
    return False


async def set_auto_cleanup(redis, value: bool) -> bool:
    if redis is not None:
        await redis.set(CLEANUP_KEY, orjson.dumps(bool(value)))
    return await get_auto_cleanup(redis)


# --- Yedek yapılandırması: host cron okur → dosya tabanlı (log_dir, container+host ortak) ---
DEFAULT_BACKUP = {"interval_hours": 6, "retention_days": 14}


def _backup_cfg_path() -> str:
    return os.path.join(os.path.realpath(settings.log_dir), "backup_config.json")


def get_backup_config() -> dict:
    cfg = dict(DEFAULT_BACKUP)
    try:
        p = _backup_cfg_path()
        if os.path.exists(p):
            with open(p, "rb") as f:
                cfg.update(orjson.loads(f.read()))
    except Exception:
        pass
    cfg["interval_hours"] = int(cfg.get("interval_hours", 6))
    cfg["retention_days"] = int(cfg.get("retention_days", 14))
    return cfg


def set_backup_config(interval_hours: int, retention_days: int) -> dict:
    ih = max(1, min(168, int(interval_hours)))     # 1 saat – 7 gün
    rd = max(1, min(365, int(retention_days)))
    cfg = {"interval_hours": ih, "retention_days": rd}
    p = _backup_cfg_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(orjson.dumps(cfg))
    try:
        os.chmod(p, 0o644)   # host cron (root) + backend okuyabilsin
    except Exception:
        pass
    return cfg
