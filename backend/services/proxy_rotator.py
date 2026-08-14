import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("proxy_rotator")


def _redact(proxy_url: str) -> str:
    """Log'lar için proxy URL'sindeki user:password kısmını gizler."""
    if "@" in proxy_url:
        return "***@" + proxy_url.split("@", 1)[1]
    return proxy_url


SCRAPINGBEE_HOST = "proxy.scrapingbee.com"
SCRAPINGBEE_PORT = 8886


def build_scrapingbee_proxy(cfg: dict, api_key: str, session_key: str | None = None) -> dict | None:
    """ScrapingBee Proxy Mode → Playwright proxy dict.

    username = API anahtarı, password = parametreler (country_code, render_js, ...).
    https://www.scrapingbee.com/documentation/#proxy-mode
    """
    if not api_key:
        return None
    params = [
        f"render_js={'true' if cfg.get('render_js') else 'false'}",
        f"country_code={cfg.get('country', 'tr')}",
    ]
    # Kalite → kredi maliyeti: classic=1, premium=~10-25, stealth=~75 kredi.
    quality = cfg.get("quality", "classic")
    if quality == "premium":
        params.append("premium_proxy=true")
    elif quality == "stealth":
        params.append("stealth_proxy=true")
    # Sticky oturum: aynı session_key → aynı çıkış IP'si (ScrapingBee session_id).
    if session_key:
        import zlib
        params.append(f"session_id={zlib.crc32(session_key.encode()) % 1_000_000}")
    return {
        "server": f"http://{SCRAPINGBEE_HOST}:{SCRAPINGBEE_PORT}",
        "username": api_key,
        "password": "&".join(params),
    }


class ProxyStatus(str, Enum):
    ALIVE = "ALIVE"
    DEAD = "DEAD"
    BANNED = "BANNED"


@dataclass
class ProxyEntry:
    url: str
    status: ProxyStatus = ProxyStatus.ALIVE
    fail_count: int = 0
    ban_until: float = 0.0
    reject_count: int = 0   # "Google REDDETTİ" (IP/hesap işaretli) kaç kez → eşik aşılınca geçici flag


class ProxyRotator:
    def __init__(self):
        self._proxies: list[ProxyEntry] = []
        self._index: int = 0
        self._lock = asyncio.Lock()
        self._sticky: dict[str, str] = {}
        self._sb_cfg: dict | None = None  # ScrapingBee runtime ayarları (batch başında set edilir)

    def set_scrapingbee(self, cfg: dict | None):
        self._sb_cfg = cfg

    def load_proxies(self, proxy_urls: list[str]):
        self._proxies = [ProxyEntry(url=u) for u in proxy_urls if u]
        self._index = 0

    async def get_proxy(self, session_key: str | None = None) -> dict | None:
        # ScrapingBee sağlayıcısı seçiliyse ve aktif anahtar varsa API proxy'sini kullan.
        if self._sb_cfg and self._sb_cfg.get("provider") == "scrapingbee":
            sb = build_scrapingbee_proxy(self._sb_cfg, self._sb_cfg.get("active_key", ""), session_key)
            if sb:
                return sb
            # Anahtar yoksa sessizce CSV proxy'lerine düş (sistem çalışmaya devam etsin).
        async with self._lock:
            import time
            now = time.time()
            for p in self._proxies:
                if p.status == ProxyStatus.BANNED and p.ban_until and now >= p.ban_until:
                    p.status = ProxyStatus.ALIVE
                    p.ban_until = 0.0
                    p.fail_count = 0
                    p.reject_count = 0   # süre dolunca REDDETTİ sayacı da sıfırlanır → temiz başlangıç

            if session_key and session_key in self._sticky:
                url = self._sticky[session_key]
                entry = next((p for p in self._proxies if p.url == url and p.status == ProxyStatus.ALIVE), None)
                if entry:
                    return self._to_playwright_proxy(entry.url)

            alive = [p for p in self._proxies if p.status == ProxyStatus.ALIVE]
            if not alive:
                logger.error("Proxy havuzu tükendi — sağlıklı proxy kalmadı")
                return None

            proxy = alive[self._index % len(alive)]
            self._index += 1

            if session_key:
                self._sticky[session_key] = proxy.url

            return self._to_playwright_proxy(proxy.url)

    async def mark_dead(self, proxy_url: str):
        async with self._lock:
            for p in self._proxies:
                if p.url == proxy_url:
                    p.fail_count += 1
                    if p.fail_count >= 3:
                        p.status = ProxyStatus.DEAD
                        logger.warning(f"Proxy DEAD olarak işaretlendi: {_redact(proxy_url)}")
                    break

    async def mark_dead_server(self, server: str):
        """Playwright 'server' string'inden (kimlik-bilgisiz host:port) eşleşen proxy'yi işaretle.
        Motor elinde tam URL değil server dict'i olduğundan host:port ile eşleştirir."""
        if not server:
            return
        from urllib.parse import urlparse
        try:
            s = urlparse(server)
            target = ((s.hostname or "").strip("[]"), s.port)
        except Exception:
            return
        async with self._lock:
            for p in self._proxies:
                try:
                    pu = urlparse(p.url)
                    if ((pu.hostname or "").strip("[]"), pu.port) == target:
                        p.fail_count += 1
                        if p.fail_count >= 3:
                            p.status = ProxyStatus.DEAD
                            logger.warning(f"Proxy DEAD (art arda hata): {_redact(p.url)}")
                        return
                except Exception:
                    continue

    async def mark_rejected_server(self, server: str, max_rejects: int = 2, ban_seconds: int = 21600) -> bool:
        """'Google REDDETTİ' (hesap/IP işaretli, çok deneme) → HESABIN değil PROXY'nin sorunu.
        Bu proxy üzerinden max_rejects kez REDDETTİ gelirse proxy'yi GEÇİCİ flag'ler (rotasyondan
        çıkar). KALICI DEAD değil uzun BAN (Google IP-flag'i zamanla düşer → havuz tükenmesin).
        Flag'lendiyse True döner (log/telegram için). ScrapingBee server'ları bu yolu KULLANMAZ."""
        if not server:
            return False
        from urllib.parse import urlparse
        import time
        try:
            s = urlparse(server)
            target = ((s.hostname or "").strip("[]"), s.port)
        except Exception:
            return False
        async with self._lock:
            for p in self._proxies:
                try:
                    pu = urlparse(p.url)
                    if ((pu.hostname or "").strip("[]"), pu.port) == target:
                        p.reject_count += 1
                        if p.reject_count >= max_rejects and p.status != ProxyStatus.BANNED:
                            p.status = ProxyStatus.BANNED
                            p.ban_until = time.time() + ban_seconds
                            logger.warning(
                                f"Proxy FLAGGED (REDDETTİ x{p.reject_count}): {_redact(p.url)} "
                                f"→ {ban_seconds // 3600}s rotasyon dışı"
                            )
                            return True
                        return False
                except Exception:
                    continue
        return False

    async def mark_banned(self, proxy_url: str, ban_seconds: int = 1800):
        async with self._lock:
            import time
            for p in self._proxies:
                if p.url == proxy_url:
                    p.status = ProxyStatus.BANNED
                    p.ban_until = time.time() + ban_seconds
                    logger.warning(f"Proxy BANNED: {_redact(proxy_url)} ({ban_seconds}s)")
                    break

    def get_stats(self) -> dict:
        alive = sum(1 for p in self._proxies if p.status == ProxyStatus.ALIVE)
        dead = sum(1 for p in self._proxies if p.status == ProxyStatus.DEAD)
        banned = sum(1 for p in self._proxies if p.status == ProxyStatus.BANNED)
        flagged = sum(1 for p in self._proxies if p.reject_count > 0)  # REDDETTİ almış proxy sayısı
        return {"total": len(self._proxies), "alive": alive, "dead": dead, "banned": banned, "flagged": flagged}

    @staticmethod
    def _to_playwright_proxy(url: str) -> dict:
        from urllib.parse import urlparse, unquote
        try:
            parsed = urlparse(url)
        except Exception:
            return {"server": url}
        host = parsed.hostname
        if not host:
            return {"server": url}
        if ":" in host:  # IPv6 → Playwright server'ında köşeli parantez şart
            host = f"[{host}]"
        server = f"{parsed.scheme}://{host}:{parsed.port}" if parsed.port else f"{parsed.scheme}://{host}"
        proxy = {"server": server}
        if parsed.username:
            proxy["username"] = unquote(parsed.username)   # URL-encode edilen kullanıcı adı geri çözülür
        if parsed.password:
            proxy["password"] = unquote(parsed.password)
        return proxy
