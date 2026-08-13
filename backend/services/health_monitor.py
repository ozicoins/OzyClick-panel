import logging
from datetime import datetime, timezone

logger = logging.getLogger("health_monitor")


class HealthMonitor:
    def __init__(self, impersonate: str = "chrome120"):
        self._impersonate = impersonate
        self._cffi_available = False
        try:
            from curl_cffi.requests import AsyncSession
            self._cffi_available = True
        except ImportError:
            logger.info("curl-cffi not available, health checks will use httpx")

    async def check_cookie_health(self, cookies: list[dict]) -> dict:
        cookie_header = "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)

        if self._cffi_available:
            return await self._check_with_cffi(cookie_header)
        return await self._check_with_httpx(cookie_header)

    async def _check_with_cffi(self, cookie_header: str) -> dict:
        from curl_cffi.requests import AsyncSession
        try:
            async with AsyncSession(impersonate=self._impersonate) as s:
                r = await s.get(
                    "https://accounts.google.com/CheckCookie",
                    headers={"Cookie": cookie_header},
                    allow_redirects=False,
                    timeout=10,
                )
                is_alive = (r.status_code == 200) or (r.status_code in (301, 302, 303, 307) and "myaccount" in r.headers.get("location", "").lower())
                return {
                    "alive": is_alive,
                    "status_code": r.status_code,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "method": "curl-cffi",
                }
        except Exception as e:
            return {"alive": False, "error": str(e), "method": "curl-cffi"}

    async def _check_with_httpx(self, cookie_header: str) -> dict:
        import httpx
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
                r = await client.get(
                    "https://accounts.google.com/CheckCookie",
                    headers={"Cookie": cookie_header},
                )
                is_alive = (r.status_code == 200) or (r.status_code in (301, 302, 303, 307) and "myaccount" in r.headers.get("location", "").lower())
                return {
                    "alive": is_alive,
                    "status_code": r.status_code,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "method": "httpx",
                }
        except Exception as e:
            return {"alive": False, "error": str(e), "method": "httpx"}
