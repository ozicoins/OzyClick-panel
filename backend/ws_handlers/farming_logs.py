import asyncio
from collections import deque
from fastapi import WebSocket, WebSocketDisconnect, FastAPI
from auth import verify_ws_token, is_token_revoked
from config import settings

MAX_SUBSCRIBERS = 50
AUTH_TIMEOUT_SECONDS = 3.0
PENDING_AUTH_MAX = 100      # aynı anda auth bekleyen (henüz doğrulanmamış) bağlantı üst sınırı
SEND_TIMEOUT_SECONDS = 5.0
HISTORY_SIZE = 200          # sayfa yenilendiğinde replay edilecek son log sayısı (UI ile aynı)

_pending_auth = 0


class FarmingLogBroadcaster:
    def __init__(self):
        self._subscribers: list[WebSocket] = []
        self._lock = asyncio.Lock()
        # Son N log'u sunucuda tut → sayfa yenilenince (WS yeniden bağlanınca)
        # istemciye replay edilir; aksi halde loglar React belleğiyle birlikte kaybolurdu.
        self._history: deque = deque(maxlen=HISTORY_SIZE)

    async def subscribe(self, ws: WebSocket) -> tuple[bool, list[dict]]:
        # Abone ekleme + geçmiş snapshot'ı AYNI kilit altında → replay ile canlı
        # yayın arasında ne kayıp ne de kopya olur.
        async with self._lock:
            if len(self._subscribers) >= MAX_SUBSCRIBERS:
                return False, []
            self._subscribers.append(ws)
            return True, list(self._history)

    async def unsubscribe(self, ws: WebSocket):
        async with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not ws]

    async def clear_history(self):
        async with self._lock:
            self._history.clear()

    async def broadcast(self, message: dict):
        # Abone listesini kilit altında snapshot'la; gönderimi kilit DIŞINDA yap →
        # yavaş bir istemci tüm farming pipeline'ını (head-of-line) bloklamaz.
        async with self._lock:
            self._history.append(message)
            targets = list(self._subscribers)

        dead = []
        for ws in targets:
            try:
                await asyncio.wait_for(ws.send_json(message), timeout=SEND_TIMEOUT_SECONDS)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                self._subscribers = [s for s in self._subscribers if s not in dead]


broadcaster = FarmingLogBroadcaster()


def _origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    # Origin yoksa (browser dışı istemci) geçir; varsa CORS listesiyle eşleşmeli.
    return origin is None or origin in settings.cors_origins_list


def setup_ws(app: FastAPI):
    @app.websocket("/ws/farming-logs")
    async def farming_logs_ws(ws: WebSocket):
        global _pending_auth
        await ws.accept()

        # CSWSH koruması: cross-site handshake'i reddet (cookie CORS'tan muaftır).
        if not _origin_allowed(ws):
            await ws.close(code=4403, reason="Origin not allowed")
            return

        # Pre-auth bağlantı taşkını koruması.
        if _pending_auth >= PENDING_AUTH_MAX:
            await ws.close(code=4029, reason="Too many pending connections")
            return

        _pending_auth += 1
        try:
            # Öncelik: httpOnly cookie (same-origin upgrade otomatik gönderir).
            token = ws.cookies.get("iu_token")
            if not token:
                try:
                    first = await asyncio.wait_for(ws.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    await ws.close(code=4001, reason="Auth timeout")
                    return
                except Exception:
                    await ws.close(code=4001, reason="Malformed auth")
                    return
                token = first.get("token") if isinstance(first, dict) else None

            if not token:
                await ws.close(code=4001, reason="Missing token")
                return

            try:
                verify_ws_token(token)
            except Exception:
                await ws.close(code=4003, reason="Invalid token")
                return

            redis = getattr(ws.app.state, "redis", None)
            if await is_token_revoked(redis, token):
                await ws.close(code=4003, reason="Token revoked")
                return
        finally:
            _pending_auth -= 1

        ok, history = await broadcaster.subscribe(ws)
        if not ok:
            await ws.close(code=4029, reason="Too many connections")
            return

        # Sayfa yenilenince biriken loglar hemen geri gelsin (aktif iş görünür kalır).
        for entry in history:
            try:
                await asyncio.wait_for(ws.send_json(entry), timeout=SEND_TIMEOUT_SECONDS)
            except Exception:
                await broadcaster.unsubscribe(ws)
                return

        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await broadcaster.unsubscribe(ws)
