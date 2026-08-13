"""Redis tabanlı basit fixed-window rate limiter.

Ek bir bağımlılık gerektirmez; mevcut Redis bağlantısını (app.state.redis) kullanır.
Redis erişilemezse fail-open davranır (kilitlenmeyi önlemek için) ve loglar.
"""
import logging

from fastapi import Request, HTTPException, status

logger = logging.getLogger("rate_limit")


def _client_ip(request: Request) -> str:
    # X-Forwarded-For'un SOL ucu istemci-kontrollüdür (proxy append eder, overwrite etmez).
    # Sadece güvenilen proxy sayısı kadar sağdan içeri say; aksi halde doğrudan bağlantı IP'si.
    from config import settings
    tpc = getattr(settings, "trusted_proxy_count", 0)
    if tpc > 0:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            parts = [p.strip() for p in fwd.split(",") if p.strip()]
            if len(parts) >= tpc:
                return parts[-tpc]
    return request.client.host if request.client else "unknown"


def rate_limit(max_calls: int, window_seconds: int, prefix: str):
    """Endpoint için rate-limit dependency üretir."""

    async def _dependency(request: Request) -> None:
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            logger.warning("Redis yok — rate limit uygulanamadı (%s)", prefix)
            return

        key = f"ratelimit:{prefix}:{_client_ip(request)}"
        try:
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, window_seconds)
        except Exception as exc:  # Redis hatası login'i bloklamasın
            logger.warning("Rate limit Redis hatası: %s", exc)
            return

        if current > max_calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Çok fazla deneme yapıldı. Lütfen bir süre sonra tekrar deneyin.",
                headers={"Retry-After": str(window_seconds)},
            )

    return _dependency
