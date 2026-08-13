"""Çalışma-zamanı ayarları — .env üstüne redis override (yeniden başlatmadan değişir).

Şimdilik DRY_RUN: gerçek tarayıcı/proxy kullanmadan sentetik üretim aç/kapa.
"""
import orjson
from config import settings

DRYRUN_KEY = "runtime:dry_run"


async def get_dry_run(redis) -> bool:
    if redis is not None:
        try:
            raw = await redis.get(DRYRUN_KEY)
            if raw is not None:
                return bool(orjson.loads(raw))
        except Exception:
            pass
    return settings.dry_run


async def set_dry_run(redis, value: bool) -> bool:
    if redis is not None:
        await redis.set(DRYRUN_KEY, orjson.dumps(bool(value)))
    return await get_dry_run(redis)
