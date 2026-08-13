import asyncio
import os
import shutil
from fastapi import APIRouter, Request, Depends

from config import settings
from auth import get_current_user

router = APIRouter()


async def _system_stats() -> dict:
    """Host/container CPU% + RAM% — psutil'siz, /proc'tan okunur (ek bağımlılık YOK)."""
    stats: dict = {}
    try:
        mem: dict = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                if v:
                    mem[k.strip()] = int(v.strip().split()[0])  # kB
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        used = max(0, total - avail)
        stats["ram_percent"] = round(used / total * 100, 1) if total else 0
        stats["ram_used_mb"] = round(used / 1024)
        stats["ram_total_mb"] = round(total / 1024)
    except Exception:
        pass
    try:
        def _cpu_sample():
            with open("/proc/stat") as f:
                vals = list(map(int, f.readline().split()[1:]))
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)   # idle + iowait
            return idle, sum(vals)
        i1, t1 = _cpu_sample()
        await asyncio.sleep(0.12)
        i2, t2 = _cpu_sample()
        dt, di = t2 - t1, i2 - i1
        stats["cpu_percent"] = round((1 - di / dt) * 100, 1) if dt > 0 else 0
        stats["cpu_count"] = os.cpu_count() or 1
    except Exception:
        pass
    return stats


def _get_chrome_pool_stats() -> dict:
    from routers.farming import _active_engines
    total_pool = settings.browser_pool_size
    active = 0
    zombies = 0
    for engine in _active_engines.values():
        if engine.pool and engine.pool._browsers:
            active += len(engine.pool._browsers)
    return {"total": total_pool, "active": active, "zombies": zombies}


@router.get("/health")
async def health_check(request: Request):
    redis_ok = False
    try:
        redis = request.app.state.redis
        await redis.ping()
        redis_ok = True
    except Exception:
        pass

    disk = shutil.disk_usage("/")
    disk_free_gb = round(disk.free / (1024**3), 1)
    disk_percent = round((disk.total - disk.free) / disk.total * 100, 1) if disk.total else 0

    sysstats = await _system_stats()

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
        "disk_free_gb": disk_free_gb,
        "disk_percent": disk_percent,
        **sysstats,   # cpu_percent, cpu_count, ram_percent, ram_used_mb, ram_total_mb
    }


@router.get("/health/detailed")
async def health_detailed(
    request: Request,
    _user: dict = Depends(get_current_user),
):
    redis = request.app.state.redis
    redis_info = {}
    try:
        info = await redis.info("memory")
        redis_info = {
            "connected": True,
            "used_memory_mb": round(info.get("used_memory", 0) / (1024**2), 1),
            "keys": await redis.dbsize(),
        }
    except Exception:
        redis_info = {"connected": False}

    disk = shutil.disk_usage("/")
    chrome = _get_chrome_pool_stats()

    keep_alive_status = {"active": False, "last_ping": None, "next_ping": None, "success_rate": 0}
    try:
        ka_data = await redis.get("keep_alive:status")
        if ka_data:
            import orjson
            keep_alive_status = orjson.loads(ka_data)
    except Exception:
        pass

    return {
        "redis": redis_info,
        "disk": {
            "total_gb": round(disk.total / (1024**3), 1),
            "used_gb": round(disk.used / (1024**3), 1),
            "free_gb": round(disk.free / (1024**3), 1),
            "percent_used": round(disk.used / disk.total * 100, 1),
        },
        "chrome_pool": chrome,
        "keep_alive": keep_alive_status,
    }
