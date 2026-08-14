import asyncio
import logging
import os
import random
import sys
import time
import zlib
from asyncio import Queue

import aiofiles
import orjson

from config import settings
from services.fingerprint_service import FingerprintService
from services.keyword_manager import KeywordManager
from services.proxy_rotator import ProxyRotator
from services.session_generator import SessionGenerator
from services.warming_service import WarmingService
from services.exporter import ExporterService
from ws_handlers.farming_logs import broadcaster

logger = logging.getLogger("farming_engine")


def _resolve_render_mode():
    """GERÇEK RENDER modunu çöz — ekran GÖSTERMEDEN gerçek Chrome render motoru.

    Döner: (launch_headless: bool, extra_args: list[str], label: str)
      • real_render kapalı            → klasik headless (eski davranış)
      • Linux + DISPLAY (Xvfb) var    → tam headful, görünmez sanal ekrana çizer (en gerçekçi)
      • macOS / DISPLAY yok           → new-headless: gerçek render, pencere AÇILMAZ
    """
    # TAM HEADFUL (en gerçekçi): yalnızca Xvfb sanal ekranı kuruluysa (use_xvfb + DISPLAY).
    # Görünür pencere açmaz (sanal ekrana çizer), en yüksek stealth.
    if settings.use_xvfb and sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        return False, [], "headful-xvfb"
    # Aksi halde KLASİK headless — her yerde STABİL. (new-headless: headless=False+--headless=new
    # bazı Chromium build'lerinde (patchright/Docker) açılışta 'browser has been closed' ile
    # ÇÖKÜYOR → kullanmıyoruz. Gerçek render için Xvfb kurulmalı.)
    return True, [], "classic-headless"


def _target_host_blocked(url: str) -> bool:
    """Ziyaret-anı hafif SSRF kontrolü (literal IP/localhost). DNS çözümü set_targets'ta yapılır."""
    from urllib.parse import urlparse
    import ipaddress
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return True
    if not host or host in {"localhost", "ip6-localhost", "metadata.google.internal", "metadata"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
    except ValueError:
        return False


_aaaa_cache: dict[str, bool] = {}


async def _host_has_ipv6(host: str) -> bool:
    """Host'un AAAA (IPv6) kaydı var mı — sonuç cache'lenir. Proxy IPv6-only olduğundan,
    IPv6'sız hedef sitelere bağlanmak timeout verir; önceden atlamak için."""
    import socket
    if not host:
        return False
    if host in _aaaa_cache:
        return _aaaa_cache[host]
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, 443, family=socket.AF_INET6, proto=socket.IPPROTO_TCP)
        _aaaa_cache[host] = bool(infos)
    except Exception:
        _aaaa_cache[host] = False
    return _aaaa_cache[host]


def _proxy_is_ipv6_only(server: str) -> bool:
    """Proxy sunucusu IPv6-only bir literal mı? Playwright server formatı IPv6 için
    'http://[<literal>]:<port>' — urlparse.hostname parantezleri soyar. String-sniff
    ('::'/'ipv6') SIKIŞTIRILMAMIŞ literalleri (2a0d:...:11, tüm 8 grup dolu) KAÇIRIRDI;
    ipaddress ile ayrıştırıp sürüm==6 bakmak sağlamdır. Ad-tabanlı IPv6-only gateway'ler
    (nadir) için ayrı bir explicit-flag gerekir; buradaki literal-tespiti prod'u kapsar."""
    if not server:
        return False
    import ipaddress
    from urllib.parse import urlparse
    try:
        host = urlparse(server if "://" in server else "http://" + server).hostname or ""
        return ipaddress.ip_address(host).version == 6
    except (ValueError, TypeError):
        return False


_selectors = None

def _load_selectors():
    global _selectors
    if _selectors is None:
        sel_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "selectors.json")
        if os.path.exists(sel_path):
            with open(sel_path, "rb") as f:
                _selectors = orjson.loads(f.read())
        else:
            _selectors = {}
    return _selectors

# Sadece AĞIR/işlevsiz kaynakları blokla. gstatic/fonts.googleapis Google login+arama
# JS'i için GEREKLİ — bloklanırsa "Next" çalışmaz. stylesheet/other/websocket de bloklanmaz.
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
BLOCKED_DOMAINS = [
    "googlevideo.com", "youtube.com", "doubleclick.net", "googleadservices.com",
]


class WriteQueue:
    def __init__(self, concurrency: int = 20):
        self._queue: Queue = Queue(maxsize=500)
        self._writers = concurrency
        self._tasks: list[asyncio.Task] = []

    async def enqueue(self, path: str, data: dict):
        await self._queue.put((path, data))

    async def _writer_task(self):
        while True:
            path, data = await self._queue.get()
            try:
                async with aiofiles.open(path, "wb") as f:
                    await f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))
            except Exception as e:
                logger.error(f"WriteQueue error for {path}: {e}")
            self._queue.task_done()

    async def start(self):
        for _ in range(self._writers):
            self._tasks.append(asyncio.create_task(self._writer_task()))

    async def drain(self):
        await self._queue.join()

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()


class PersistentBrowserPool:
    def __init__(self, pool_size: int = 10):
        self.pool_size = pool_size
        self._browsers: list = []
        self._playwright = None
        self._semaphore = asyncio.Semaphore(pool_size)
        self._sem_holders: set = set()  # kilit tutan context'ler (deterministik release için)

    async def initialize(self):
        try:
            from patchright.async_api import async_playwright
        except ImportError:
            from playwright.async_api import async_playwright

        self._playwright = await async_playwright().__aenter__()
        base_args = [
            "--disable-dev-shm-usage",
            "--disable-webrtc",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--no-first-run",
            "--max-old-space-size=256",
            # Anti-detection: navigator.webdriver otomasyon sinyalini kaldırır (Google login için kritik).
            "--disable-blink-features=AutomationControlled",
        ]
        # GERÇEK RENDER modu: hangi headless/headful ile açılacağını çöz (ekran gösterilmez).
        launch_headless, render_extra, render_label = _resolve_render_mode()

        # browser_no_sandbox=False → sandbox AÇIK denenir. Container desteklemiyorsa
        # (unprivileged user namespaces yoksa) güvenli şekilde --no-sandbox'a düşülür;
        # böylece sandbox mümkün olan her yerde kullanılır ama farming asla kırılmaz.
        use_no_sandbox = settings.browser_no_sandbox

        async def _launch(no_sandbox: bool):
            args = base_args + render_extra + (["--no-sandbox"] if no_sandbox else [])
            return await self._playwright.chromium.launch(headless=launch_headless, args=args)

        for _ in range(self.pool_size):
            try:
                browser = await _launch(use_no_sandbox)
            except Exception as e:
                if not use_no_sandbox:
                    logger.warning(
                        "Chromium sandbox ile başlatılamadı (%s); --no-sandbox'a düşülüyor. "
                        "Sandbox için container'da unprivileged user namespaces gerekir.", e,
                    )
                    use_no_sandbox = True
                    browser = await _launch(True)
                else:
                    raise
            self._browsers.append(browser)
        logger.info(
            "Browser pool initialized: %d instances (sandbox=%s, render=%s)",
            self.pool_size, "off" if use_no_sandbox else "on", render_label,
        )

    async def get_context(self, proxy: dict | None, context_options: dict):
        # Semaphore'u context'in TÜM ömrü boyunca tut → aynı anda en fazla pool_size
        # canlı context olur. (Eski hali 'async with ... return' ile kilidi hemen bırakıyordu;
        # TURBO'da num_workers kadar (~80) context aynı anda açılıp OOM/flag riski yaratıyordu.)
        await self._semaphore.acquire()
        try:
            browser = random.choice(self._browsers)
            opts = {**context_options}
            if proxy:
                opts["proxy"] = proxy
                # ScrapingBee proxy mode TLS'i MITM eder → sertifika hatalarını yoksay.
                if "scrapingbee" in proxy.get("server", ""):
                    opts["ignore_https_errors"] = True
            context = await browser.new_context(**opts)
        except BaseException:
            self._semaphore.release()
            raise
        # Kilit, caller'ın finally'sinde release_slot ile DETERMİNİSTİK bırakılır. ('close'
        # event'ine güvenmek ANİ browser/OOM çökmesinde event ateşlenmediği için permit
        # sızdırıyor ve havuzu açlığa sokuyordu.)
        self._sem_holders.add(context)
        return context

    def release_slot(self, context):
        """Context'in tuttuğu havuz kilidini TAM BİR KEZ bırak (caller finally'sinden)."""
        if context in self._sem_holders:
            self._sem_holders.discard(context)
            self._semaphore.release()

    async def close(self):
        for browser in self._browsers:
            try:
                await browser.close()
            except Exception:
                pass
        self._browsers.clear()
        self._sem_holders.clear()
        if self._playwright:
            # __aenter__() ile alınan Playwright nesnesi .stop() ile durdurulur; __aexit__
            # yalnızca CM nesnesinde var (o atılmıştı) → eski çağrı her seferinde AttributeError
            # atıp node alt-sürecini sızdırıyordu.
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


class FarmingEngine:
    def __init__(self):
        self.pool: PersistentBrowserPool | None = None
        self.write_queue = WriteQueue(concurrency=20)
        self.fingerprint_service = FingerprintService()
        self.keyword_manager = KeywordManager()
        self.proxy_rotator = ProxyRotator()
        self.session_generator = SessionGenerator()
        self.warming_service = WarmingService()
        self.exporter = ExporterService()
        self._stop_event = asyncio.Event()
        self._active_workers = 0
        self._completed = 0
        self._failed = 0
        self._redis = None
        self._dry_run = settings.dry_run  # batch başında runtime değeriyle override edilir
        self._target_urls = []  # login sonrası gezilecek ekstra hedef siteler (gerçek çerez hasadı)
        self._recovery_email = ""  # 2FA'sız ama "kurtarma adresini onayla" isteyen hesaplar için
        self._totp_secret = ""  # hesabın TOTP (authenticator) secret'ı — 2FA adımında kod üretir
        self._acct_stats: dict[str, dict] = {}   # email -> {"ok":n,"fail":n} (hesap bazlı görünürlük)
        self._skipped: dict[str, int] = {}       # email -> günlük limit dolduğu için atlanan
        self._planned_total = 0                  # günlük-limit kırpımından SONRA gerçek hedef profil
        self._deadlogin: dict[str, str] = {}     # email -> sebep: DETERMİNİSTİK login hatası (yanlış TOTP/
        #  reddedildi/hesap yok) alan hesap → kalan worker'ları BOŞA deneme, browser bile açma.
        self._red_skipped: dict[str, int] = {}   # email -> strike: KIRMIZI olduğu için bu batch'te atlanan hesap
        self._reddetti_count: dict[str, int] = {}  # email -> bu batch'te kaç REDDETTİ (storm sınırı; strike DEĞİL)
        self._captcha_key: str = ""              # CapSolver anahtarı (batch başında redis'ten yüklenir)
        self._captcha_service: str = "capsolver"
        self._captcha_enabled: bool = False

    def _record(self, email: str, ok: bool) -> None:
        """Hesap bazlı başarı/başarısızlık sayacı (panelde hangi hesap sorunlu görünür)."""
        s = self._acct_stats.setdefault(email, {"ok": 0, "fail": 0})
        s["ok" if ok else "fail"] += 1

    async def _load_captcha_cfg(self, redis) -> None:
        """Batch başında CapSolver ayarını yükle. ÖNCELİK: panel (redis config:captcha). Panelde yoksa
        .env (settings.captcha_api_key) YEDEK olarak kullanılır. Kapalı/anahtarsızsa çözücü no-op kalır
        (login akışı ASLA değişmez). Hata olursa sessizce devre dışı."""
        self._captcha_key = ""
        self._captcha_service = "capsolver"
        self._captcha_enabled = False
        try:
            from services.user_settings import get_captcha
            cap = await get_captcha(redis, include_secret=True)
            if cap.get("enabled") and cap.get("api_key"):
                self._captcha_enabled = True
                self._captcha_key = cap.get("api_key", "")
                self._captcha_service = cap.get("service", "capsolver")
            elif getattr(settings, "captcha_api_key", ""):
                # .env YEDEĞİ: panelde anahtar yoksa ama .env'e konduysa onu kullan (aktif say).
                self._captcha_enabled = True
                self._captcha_key = settings.captcha_api_key
                self._captcha_service = getattr(settings, "captcha_service", "capsolver") or "capsolver"
        except Exception:
            pass

    async def _solve_captcha_if_present(self, page) -> None:
        """Login adımında inline resim-captcha varsa çöz + doldur. Captcha yoksa/anahtar yoksa
        anında döner (normal akış etkilenmez). Her hata yutulur → login'i ASLA bozmaz."""
        if not self._captcha_enabled or not self._captcha_key:
            return
        try:
            from services.captcha_solver import solve_image_captcha
            # SERT ÜST SINIR: captcha çözümü bir worker'ı EN FAZLA ~20sn tutabilir. Screenshot/CapSolver
            # hang'i (30sn timeout) tüm batch'i kilitlemesin — captcha YOKSA zaten anında döner (no-op).
            await asyncio.wait_for(
                solve_image_captcha(page, self._captcha_key, self._captcha_service, log=self._log),
                timeout=20,
            )
        except Exception:
            pass

    @staticmethod
    async def _human_type(locator, text: str):
        """İnsan gibi karakter-karakter yaz (anti-detection; .fill() anında yazar)."""
        try:
            await locator.press_sequentially(text, delay=random.randint(60, 130))
        except Exception:
            try:
                await locator.type(text, delay=random.randint(60, 130))
            except Exception:
                await locator.fill(text)

    def _existing_max_index(self, output_dir: str) -> int:
        """Klasördeki en yüksek profile_XXXXX index'i (yoksa 0). Yeni profiller bunun ÜSTÜNDEN
        numaralanır → mevcut çerezlerin ÜZERİNE YAZILMAZ (append). Aksi halde re-run
        profile_00001..0000n'i eskisinin üstüne yazar, sayı artmaz ('üretildi ama eklenmemiş')."""
        mx = 0
        try:
            for name in os.listdir(output_dir):
                if name.startswith("profile_") and name.endswith(".json"):
                    try:
                        mx = max(mx, int(name[len("profile_"):-len(".json")]))
                    except Exception:
                        pass
        except Exception:
            pass
        return mx

    async def _collect_profiles_for_manifest(self, output_dir: str, in_memory: list[dict],
                                             max_index: int | None = None) -> list[dict]:
        """Manifest/proxy-map için profilleri topla — bellekteki taze kayıtları (all_profiles)
        disk'teki profile_*.json'larla profile_index üzerinden birleştirir. Çökme-resume'da
        yalnızca devam eden dilim bellektedir; önceki dilimler disk'ten kurtarılır (#14).
        max_index verilirse (mevcut batch'in count'u), o aralığın DIŞINDAKİ dosyalar (aynı
        e-posta dizininde kalan DAHA BÜYÜK önceki batch artıkları) manifesti ŞİŞİRMESİN diye
        dışlanır. Disk'ten yalnızca hafif üst-alanlar okunur (storage_state kullanılmaz)."""
        by_idx: dict[int, dict] = {}
        for p in in_memory:                        # önce bellektekiler (tam kayıt)
            i = p.get("profile_index")
            if i is not None and (max_index is None or i <= max_index):
                by_idx[i] = p
        try:
            names = [n for n in os.listdir(output_dir)
                     if n.startswith("profile_") and n.endswith(".json")]
        except OSError:
            names = []
        for name in names:
            try:
                idx = int(name[len("profile_"):-len(".json")])
            except ValueError:
                continue
            if max_index is not None and idx > max_index:   # önceki daha büyük batch artığı → dışla
                continue
            if idx in by_idx:                      # bellekteki tam kayıt önceliklidir
                continue
            try:
                async with aiofiles.open(os.path.join(output_dir, name), "rb") as fh:
                    d = orjson.loads(await fh.read())
            except Exception:
                continue
            by_idx[idx] = {                        # yalnızca manifest/proxy-map alanları
                "profile_index": d.get("profile_index", idx),
                "session_id": d.get("session_id", ""),
                "proxy_ip": d.get("proxy_ip", ""),
                "created_at": d.get("created_at", 0),
                "expires_at": d.get("expires_at", 0),
                "status": d.get("status", "active"),
                "cookie_count": d.get("cookie_count", 0),
                "user_agent": d.get("user_agent", ""),
                "device": d.get("device", ""),
            }
        return [by_idx[i] for i in sorted(by_idx)]

    @staticmethod
    def _fp_dict(fp, proxy, session_key: str = "") -> dict:
        """ÖMÜR: çerezi tüketen tarafın BİREBİR tekrar kullanması gereken doğum parmak izi.
        Aynı UA + viewport + locale + timezone + proxy ile kullanılırsa oturum uzun yaşar."""
        return {
            "user_agent": fp.user_agent,
            "viewport": fp.viewport,
            "screen": fp.viewport,                          # antidetect araçları 'screen' de ister
            "locale": fp.locale,
            "languages": ["tr-TR", "tr", "en-US", "en"],
            "timezone_id": fp.timezone_id,
            "platform": fp.platform,                        # navigator.platform (Linux armv8l / iPhone)
            "webgl_vendor": fp.gpu_vendor,                  # WebGL unmasked vendor
            "webgl_renderer": fp.gpu_renderer,              # WebGL unmasked renderer (GPU)
            "hardware_concurrency": fp.hardware_concurrency,
            "is_mobile": fp.is_mobile,
            "has_touch": fp.has_touch,
            "device_scale_factor": fp.device_scale_factor,
            "device_memory": fp.device_memory,
            "device": fp.device_name,
            "os_type": fp.os_type,
            # Client Hints alanları — export/live-check UA'dan tahmin etmesin, BİREBİR saklansın
            "model": fp.model,
            "os_version": fp.os_version,
            "browser_version": fp.browser_version,
            "canvas_noise": fp.canvas_noise,
            "color_scheme": fp.color_scheme,
            # DE-KORELASYON tohumu — çerezi tüketen taraf AYNI seed ile canvas/webgl/audio
            # gürültüsünü BİREBİR üretmeli; yoksa doğum-hash'i ile kullanım-hash'i çelişir (#2/de-corr).
            "noise_seed": getattr(fp, "noise_seed", 0) or 0,
            "proxy_ip": proxy["server"] if proxy else "",
            # ScrapingBee → SADECE server sakla (API anahtarı=username profil dosyasına SIZMASIN);
            # keep-alive/clicker kimliği config'den ekler. Kimlik-doğrulamalı residential (CSV/liste)
            # proxy → creds'i DE sakla, yoksa çerezi tüketen taraf doğum-IP'sine bağlanamaz (#15).
            "proxy": (
                {"server": proxy["server"]}
                if not proxy
                or "proxy.scrapingbee.com" in proxy.get("server", "")
                else {
                    "server": proxy["server"],
                    **({"username": proxy["username"]} if proxy.get("username") else {}),
                    **({"password": proxy["password"]} if proxy.get("password") else {}),
                }
            ) if proxy else None,
            # DOĞUM ScrapingBee session anahtarı — keep-alive AYNI key ile build_scrapingbee_proxy
            # çağırıp doğum sticky exit-IP'sini tekrar kullanmalı; yoksa her turda RASTGELE exit IP →
            # yaşlandırılmış oturumun IP sürekliliği bozulur, Google re-verify tetikler (#8).
            "sb_session_key": session_key,
        }

    async def start_batch(
        self,
        email: str,
        password: str,
        count: int,
        mode: str,
        sector: str,
        keywords: list[str],
        proxy_urls: list[str],
        lifespan_days: int = 5,
        redis=None,
    ) -> dict:
        self._redis = redis
        self._stop_event.clear()
        self._completed = 0
        self._failed = 0
        self._acct_stats = {}
        self._skipped = {}
        self._deadlogin = {}       # her batch TEMİZ başlar (oto-iyileşme)
        self._red_skipped = {}
        self._reddetti_count = {}
        await self._load_captcha_cfg(redis)

        # Günlük-limit clamp'i checkpoint/start_index BİLİNDİKTEN SONRA uygulanır (aşağıda) —
        # resume'da count'un start_index'in ALTINA düşüp range'i boşaltmasını önlemek için (Tur3 #E).

        self.proxy_rotator.load_proxies(proxy_urls)
        keywords = keywords or self.keyword_manager.get_keywords(sector)

        worker_counts = {"SAFE": settings.safe_worker_count, "FAST": settings.fast_worker_count, "TURBO": settings.turbo_worker_count}
        # Pool boyutundan fazla worker PLANLAMA → fazlası get_context'te semaphore'da bloklanıp
        # worker_timeout'a kadar bekler (starvation → boşa timeout). num_workers'ı pool'a sabitle.
        num_workers = min(worker_counts.get(mode, settings.safe_worker_count), settings.browser_pool_size)

        self.pool = PersistentBrowserPool(pool_size=num_workers)
        # try/finally: herhangi bir hata olsa da browser pool + writer task'lar temizlenir
        # (aksi halde her başarısız batch ~10 Chromium + 20 writer task leak eder).
        try:
            if not self._dry_run:
                await self.pool.initialize()
            await self.write_queue.start()

            sanitized = email.replace("@", "_at_").replace(".", "_").replace("/", "_").replace("\\", "_")
            output_dir = os.path.join(settings.cookies_output_dir, sanitized)
            os.makedirs(output_dir, exist_ok=True)

            checkpoint = await self._load_checkpoint(output_dir)
            # ÜZERİNE YAZMA KORUMASI: checkpoint VEYA disk'teki mevcut en yüksek index'ten SONRA başla.
            # Batch bitince checkpoint silindiği için re-run'da 1'e düşüp mevcut profilleri ezerdi.
            start_index = max(checkpoint.get("last_completed_index", 0) + 1,
                              self._existing_max_index(output_dir) + 1)

            # Aşırı-farmlama koruması: günlük limiti aşma. RESUME-GÜVENLİ: 'used' (redis günlük sayaç)
            # zaten bu batch'in üretilmiş (start_index-1) profilini içerir; bu yüzden count'u YENİ-üretim
            # olarak değil MUTLAK üst-index olarak kırp = already_done + kalan headroom. Aksi halde
            # (eski kod) count = min(count, remaining) count'u start_index'in altına indirip range'i
            # BOŞALTIYOR (resume 0 üretir) ve manifest max_index=count ile üretilmiş dilimi kırpıyordu.
            limit = settings.per_account_daily_limit
            if limit and limit > 0 and redis is not None and not self._dry_run:
                from services.account_store import get_daily_count
                used = await get_daily_count(redis, email)
                already_done = start_index - 1
                remaining = limit - used                      # bugün EK üretilebilecek adet
                if remaining <= 0:
                    self._skipped[email] = used
                    count = min(count, already_done)          # yeni üretim yok; mevcut dilim manifeste girsin
                else:
                    count = min(count, already_done + remaining)
            self._planned_total = max(0, count - (start_index - 1))

            master_cookies = None
            if mode == "TURBO" and not self._dry_run:
                master_cookies = await self._master_login(email, password, proxy_urls)

            all_profiles = []
            tasks = []
            task_idx = {}       # task -> idx (checkpoint için hangi idx bitti bilinmeli)
            processed = set()   # tamamlanan (başarılı VEYA başarısız) idx'ler

            async def _handle_done(done_tasks):
                for t in done_tasks:
                    i = task_idx.pop(t, None)
                    if i is not None:
                        processed.add(i)
                    try:
                        result = t.result()
                        if result:
                            all_profiles.append(result)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        # Worker worker_timeout'u aştı (login/ısıtma bitmeden kesildi) → GÖRÜNÜR ✗ log
                        # (eskiden sessizce _failed++ oluyordu, panelde HİÇ görünmüyordu — D).
                        self._failed += 1
                        await self._log(f"Worker-{(i or 0):02d} ✗ Zaman aşımı ({settings.worker_timeout}s) — login/ısıtma tamamlanamadı (yavaş proxy/2FA?)", "ERROR")
                    except Exception as exc:
                        self._failed += 1
                        await self._log(f"Worker-{(i or 0):02d} ✗ Hata: {str(exc)[:120]}", "ERROR")
                        logger.error(f"Worker task error: {exc}")

            for idx in range(start_index, count + 1):
                if self._stop_event.is_set():
                    break
                task = asyncio.create_task(
                    asyncio.wait_for(
                        self._farm_single(
                            idx, email, password, mode, keywords,
                            output_dir, lifespan_days, master_cookies,
                        ),
                        timeout=settings.worker_timeout,
                    )
                )
                task_idx[task] = idx
                tasks.append(task)

                if len(tasks) >= num_workers:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    await _handle_done(done)
                    tasks = list(pending)

                if settings.checkpoint_interval and idx % settings.checkpoint_interval == 0:
                    # KESİNTİSİZ tamamlanan en yüksek idx'i yaz (scheduling idx'i DEĞİL) →
                    # resume'da henüz bitmemiş profiller ATLANMAZ.
                    cp = start_index - 1
                    while (cp + 1) in processed:
                        cp += 1
                    if cp >= start_index:
                        await self._write_checkpoint(output_dir, cp, count)

            if tasks:
                done, _ = await asyncio.wait(tasks)
                await _handle_done(done)

            # Batch bitti (veya durduruldu) → checkpoint'i sil. Aynı e-postayla YENİ batch
            # eski checkpoint yüzünden profilleri atlamasın; checkpoint yalnızca çökme-resume içindir.
            try:
                cp_path = os.path.join(output_dir, ".checkpoint.json")
                if os.path.exists(cp_path):
                    os.remove(cp_path)
            except Exception:
                pass

            await self.write_queue.drain()

            # RESUME BÜTÜNLÜĞÜ (#14): manifest/proxy-map yalnızca BU çalıştırmanın dilimini
            # değil, disk'teki TÜM başarılı profilleri yansıtmalı. Çökme-resume'da all_profiles
            # sadece devam eden dilimi tutar → önceki profiller manifesttan düşer, sayım eksik olur.
            # Manifest = disk'teki TÜM geçerli profiller (max_index YOK). count=0 (günlük-limit dolu)
            # re-run'da max_index=count=0 tüm disk profillerini DIŞLAYIP manifest'i boşaltıyordu (Tur4
            # HIGH: 50 geçerli çerezin kaydı siliniyordu). Disk'teki profiller zaten gerçek/kullanılabilir
            # çerez; hepsi manifeste girmeli. Resume dilimi de disk'ten okunduğundan #14 korunur.
            manifest_profiles = await self._collect_profiles_for_manifest(output_dir, all_profiles)
            if manifest_profiles:   # üretilecek/kaydedilecek profil yoksa mevcut manifesti EZME (boş-yazma yok)
                await self.exporter.write_batch_manifest(output_dir, email, manifest_profiles, sector, keywords, lifespan_days)
                await self.exporter.write_proxy_map(output_dir, manifest_profiles)

            return {
                "total": count,
                "completed": self._completed,
                "failed": self._failed,
                "output_dir": output_dir,
            }
        finally:
            try:
                await self.pool.close()
            except Exception:
                pass
            try:
                await self.write_queue.stop()
            except Exception:
                pass

    async def start_batch_multi(
        self,
        accounts: list[dict],          # her biri: email, password, totp_secret, recovery_email, proxy_ip
        count_per_account: int,
        mode: str,
        sector: str,
        keywords: list[str],
        proxy_urls: list[str],
        lifespan_days: int = 5,
        redis=None,
    ) -> dict:
        """Havuzdaki TÜM hesapları TEK batch'te işler — her worker FARKLI hesaba girer
        (TOTP çakışması yok, tam paralel). Her hesap kendi cookies_output/<email> klasörüne yazar."""
        from services.account_store import get_daily_count, get_fail_count
        self._redis = redis
        self._stop_event.clear()
        self._completed = 0
        self._failed = 0
        self._acct_stats = {}
        self._skipped = {}
        self._deadlogin = {}       # her batch TEMİZ başlar → geçen batch'te işaretlenen hesap yeniden denenir (oto-iyileşme)
        self._red_skipped = {}     # bu batch'te KIRMIZI olduğu için atlanan hesaplar {email: strike}
        self._reddetti_count = {}  # bu batch'te hesap-başı REDDETTİ sayacı (storm sınırı)
        await self._load_captcha_cfg(redis)
        self.proxy_rotator.load_proxies(proxy_urls)
        base_keywords = keywords or self.keyword_manager.get_keywords(sector)

        # TURBO klon-modeli çoklu-hesapta işlemez (her worker kendi hesabına GERÇEK login yapar)
        # → FAST'e indir, aksi halde tüm worker'lar "master yok" diye fail ederdi.
        if mode == "TURBO":
            mode = "FAST"
        worker_counts = {"SAFE": settings.safe_worker_count, "FAST": settings.fast_worker_count, "TURBO": settings.turbo_worker_count}
        num_workers = min(worker_counts.get(mode, settings.safe_worker_count), settings.browser_pool_size)
        self.pool = PersistentBrowserPool(pool_size=num_workers)

        # İş listesi: her hesap × count_per_account — AMA günlük limiti aşan hesap kırpılır/atlanır
        # (aşırı-farmlama koruması; Google flag'lemesini azaltır).
        limit = settings.per_account_daily_limit
        dirs = {}
        acct_n = []   # [(acc, n, start)] — start = mevcut en yüksek index (ÜZERİNE YAZMA koruması)
        for acc in accounts:
            em = acc["email"]
            # KIRMIZI (2 kez üst üste sorunlu) hesap → işlem sırasından ÇIKAR (browser bile açma, boşa deneme yok).
            # Panelden temizlenince VEYA başarılı üretimde (reset_fail_count) tekrar sıraya girer.
            _fc = await get_fail_count(redis, em)
            if _fc >= settings.account_red_strikes:
                self._red_skipped[em] = _fc
                continue
            odir = os.path.join(settings.cookies_output_dir, em.replace("@", "_at_").replace(".", "_").replace("/", "_").replace("\\", "_"))
            os.makedirs(odir, exist_ok=True)
            dirs[em] = odir
            n = count_per_account
            if limit and limit > 0:
                used = await get_daily_count(redis, em)
                n = max(0, min(count_per_account, limit - used))
                if n == 0:
                    self._skipped[em] = used   # günlük limit dolu → bugün atla
                    continue
            # ÜZERİNE YAZMA KORUMASI: yeni profiller mevcut en yüksek index'ten SONRA numaralanır (append).
            # Aksi halde re-run profile_00001..0000n'i eskisinin üstüne yazar → sayı ARTMAZ (kayıp bug).
            acct_n.append((acc, n, self._existing_max_index(odir)))

        # ROUND-ROBIN diziliş: [A,B,C,...(tüm hesaplar TUR 1)..., A,B,...(TUR 2)...] — hesap-gruplu
        # ([A×50, B×50,...]) DEĞİL. Aksi halde ilk num_workers worker AYNI hesaba (A) eşzamanlı login
        # yapıyordu → Google "çok deneme" flag'liyordu (REDDETTİ). Round-robin'de her tur her hesaptan
        # 1 profil; hesap sayısı ≥ worker sayısı iken bir hesaba ASLA 2 worker aynı anda girmez.
        # Index = start + tur → mevcut çerezlerin üstüne YAZMAZ.
        work = []
        _max_n = max((n for _, n, _ in acct_n), default=0)
        for _r in range(1, _max_n + 1):
            for acc, n, start in acct_n:
                if _r <= n:
                    work.append((acc, start + _r))

        self._planned_total = len(work)   # gerçek hedef (kırpımdan sonra) → panelde doğru toplam
        per_acct = {}   # email -> profiles
        failed_transient = []   # (acc, li) — geçici hata (timeout/crash) → 1 kez retry
        try:
            if not self._dry_run:
                await self.pool.initialize()
            await self.write_queue.start()

            tasks = []
            task_meta = {}

            async def _handle(done_tasks):
                for t in done_tasks:
                    meta = task_meta.pop(t, None)
                    em2 = meta[0]["email"] if meta else None
                    li2 = meta[1] if meta else 0
                    try:
                        r = t.result()
                        if r and em2:
                            per_acct.setdefault(em2, []).append(r)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        self._failed += 1
                        if em2:
                            self._record(em2, False)
                        if meta:
                            failed_transient.append(meta)   # geçici → retry adayı
                        await self._log(f"✗ {em2 or '?'} ·Zaman aşımı ({settings.worker_timeout}s) — login/ısıtma tamamlanamadı (yavaş proxy/2FA?)", "ERROR")
                    except Exception as exc:
                        self._failed += 1
                        if em2:
                            self._record(em2, False)
                        if meta:
                            failed_transient.append(meta)
                        await self._log(f"✗ {em2 or '?'} ·Hata: {str(exc)[:120]}", "ERROR")
                        logger.error(f"Multi worker error: {exc}")

            for acc, li in work:
                if self._stop_event.is_set():
                    break
                task = asyncio.create_task(
                    asyncio.wait_for(
                        self._farm_single(
                            li, acc["email"], acc.get("password", ""), mode, base_keywords,
                            dirs[acc["email"]], lifespan_days, None,
                            acc.get("totp_secret", "") or None, acc.get("recovery_email", "") or None,
                        ),
                        timeout=settings.worker_timeout,
                    )
                )
                task_meta[task] = (acc, li)
                tasks.append(task)
                if len(tasks) >= num_workers:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    await _handle(done)
                    tasks = list(pending)

            if tasks:
                done, _ = await asyncio.wait(tasks)
                await _handle(done)

            # RETRY: sadece GEÇİCİ hatalar (timeout/crash) 1 kez tekrar denenir — login-fail
            # (yanlış TOTP vb. deterministik) retry EDİLMEZ. İlk sayımı geri alıp yeniden say.
            if failed_transient and not self._stop_event.is_set():
                retry = list(failed_transient)
                failed_transient.clear()
                await self._log(f"↻ {len(retry)} geçici hata tekrar deneniyor...")
                rtasks = []
                for acc, li in retry:
                    if self._stop_event.is_set():
                        break
                    # İlk sayımı SADECE gerçekten yeniden çalıştırdığımız item için geri al
                    # (durdurulup çalıştırılmayanlar failed olarak kalsın → status yanlış COMPLETED olmasın).
                    self._failed = max(0, self._failed - 1)
                    _st = self._acct_stats.get(acc["email"])
                    if _st and _st.get("fail", 0) > 0:
                        _st["fail"] -= 1
                    task = asyncio.create_task(
                        asyncio.wait_for(
                            self._farm_single(
                                li, acc["email"], acc.get("password", ""), mode, base_keywords,
                                dirs[acc["email"]], lifespan_days, None,
                                acc.get("totp_secret", "") or None, acc.get("recovery_email", "") or None,
                            ),
                            timeout=settings.worker_timeout,
                        )
                    )
                    task_meta[task] = (acc, li)
                    rtasks.append(task)
                    if len(rtasks) >= num_workers:
                        done, pending = await asyncio.wait(rtasks, return_when=asyncio.FIRST_COMPLETED)
                        await _handle(done)
                        rtasks = list(pending)
                if rtasks:
                    done, _ = await asyncio.wait(rtasks)
                    await _handle(done)

            await self.write_queue.drain()

            for em, odir in dirs.items():
                try:
                    # Manifest'i disk'teki TÜM geçerli profillerden kur (bellekteki dilimden DEĞİL).
                    # Günlük-limit dolu (skipped) hesap bu turda 0 üretir; eskiden per_acct[em]=[] ile
                    # write_batch_manifest çağrılıp mevcut dolu manifesti BOŞ'a eziyordu (Tur4 HIGH:
                    # disk'te duran 50 çerezin kaydı siliniyordu). Disk'ten kur + boşsa EZME.
                    profs = await self._collect_profiles_for_manifest(odir, per_acct.get(em, []))
                    if not profs:
                        continue
                    await self.exporter.write_batch_manifest(odir, em, profs, sector, base_keywords, lifespan_days)
                    await self.exporter.write_proxy_map(odir, profs)
                except Exception:
                    pass

            return {"total": len(work), "completed": self._completed, "failed": self._failed, "accounts": len(accounts)}
        finally:
            try:
                await self.pool.close()
            except Exception:
                pass
            try:
                await self.write_queue.stop()
            except Exception:
                pass

    async def _farm_single(
        self,
        index: int,
        email: str,
        password: str,
        mode: str,
        keywords: list[str],
        output_dir: str,
        lifespan_days: int,
        master_cookies: list[dict] | None,
        totp_secret: str | None = None,
        recovery_email: str | None = None,
    ) -> dict | None:
        self._active_workers += 1
        start_time = time.time()
        proxy = None  # except bloklarında referans edilir; atanmadan hata olursa UnboundLocalError olmasın

        try:
            # DETERMİNİSTİK-ÖLÜ HESAP: bu hesap login veremiyor (yanlış TOTP / reddedildi / hesap yok).
            # Kalan worker'ları BOŞA deneme — browser bile açma, hemen atla (yalnız sayaç; ilk hata
            # zaten loglandı → log SEL'i olmaz). "boşa üretmek istemem" + TOTP hata seli çözümü.
            if not self._dry_run and email in self._deadlogin:
                self._failed += 1
                self._record(email, False)
                return None
            # DRY-RUN: gerçek tarayıcı/login YOK — sentetik profil üret, pipeline'ın geri
            # kalanını (proxy rotator, write queue, redis, sayaçlar, WS log) gerçekten çalıştır.
            if self._dry_run:
                await asyncio.sleep(random.uniform(0.03, 0.15))
                # Hesap-başına benzersiz seed (canlı yol ile aynı) → dry profiller de birbirinden
                # farklı fingerprint alsın, de-korelasyon davranışı canlıyla tutarlı kalsın (#2).
                fp = self.fingerprint_service.generate(seed=zlib.crc32(f"{email}:{index}".encode()))
                proxy = await self.proxy_rotator.get_proxy(session_key=f"{email}:{index}")
                profile = self.session_generator.generate_storage_state(
                    email=email, profile_index=index, keywords=keywords,
                    proxy_ip=proxy["server"] if proxy else "", lifespan_days=lifespan_days,
                    user_agent=fp.user_agent, device=fp.device_name,
                    fingerprint=self._fp_dict(fp, proxy, session_key=f"{email}:{index}"),
                )
                filepath = os.path.join(output_dir, f"profile_{index:05d}.json")
                await self.write_queue.enqueue(filepath, profile)
                if self._redis:
                    await self._redis.set(
                        f"session:{profile['token_hash']}", email, ex=settings.redis_session_ttl
                    )
                self._completed += 1
                self._record(email, True)
                elapsed = round(time.time() - start_time, 2)
                await self._log(
                    f"[DRY] {email} · #{index:05d} → {profile['cookie_count']} çerez | {fp.device_name} | {elapsed}s"
                )
                return profile

            # Seed HESAP-BAŞINA benzersiz (email:index) → farklı hesaplar AYNI cihaz fingerprint'i
            # almasın ('same device across accounts' ban sinyali: Tur1 #2). index tek başına yetmezdi.
            fp = self.fingerprint_service.generate(seed=zlib.crc32(f"{email}:{index}".encode()))
            ctx_options = self.fingerprint_service.get_context_options(fp)
            proxy = await self.proxy_rotator.get_proxy(session_key=f"{email}:{index}")
            if proxy is None:   # FAIL-CLOSED (CRIT #1): proxysiz login = GERÇEK datacenter-IP'den →
                self._failed += 1  # yaşlandırılmış hesap yanar + sunucu IP sızar + geo/tz uyumsuz.
                self._record(email, False)
                await self._log(f"✗ {email} ·Proxy yok — direkt bağlantı ENGELLENDİ (hesap korundu)", "ERROR")
                return None
            context = await self.pool.get_context(proxy, ctx_options)

            try:
                stealth = self.fingerprint_service.get_stealth_script(fp)
                await context.add_init_script(stealth)

                page = await context.new_page()
                # NOT: kaynak engelleme login'den SONRA kurulur (login JS'ini bozmamak için).

                if master_cookies:
                    await context.add_cookies(master_cookies)
                elif mode in ("SAFE", "FAST"):
                    from services.totp_handler import TOTPHandler
                    totp = TOTPHandler()
                    logged_in, _why = await self._login(page, email, password, totp, totp_secret, recovery_email)
                    if not logged_in:
                        self._failed += 1
                        self._record(email, False)
                        await self._log(f"✗ {email} · Login FAILED: {_why or 'bilinmeyen sebep'}", "ERROR")
                        # HATA YÖNLENDİRME (kullanıcı isteği — hesabı haksız yere suçlama):
                        #  • "Google REDDETTİ" (IP/hesap işaretli) = PROXY/IP sorunu → strike YOK, deadlogin YOK
                        #    (başka proxy'yle tekrar). Aynı proxy tekrarlarsa proxy'yi flag'le. Bir hesap bu batch'te
                        #    ÇOK REDDETTİ alırsa STRIKE'sız olarak bu batch'te durdurulur (kredi/havuz yakma sınırı).
                        #  • "2FA geçmedi" = hesabın KENDİ deterministik sorunu (TOTP/2FA bozuk) → strike +1;
                        #    2. strike'ta KIRMIZI + sonraki üretimlerde sıradan çıkar.
                        #  • "parola adımı gelmedi" = BELİRSİZ (yavaş proxy 20sn timeout'u da bunu tetikler) →
                        #    strike YOK (iyi hesabı yanlışlıkla KIRMIZI yapma); sadece bu batch'te kalanları atla.
                        _reason = _why or ""
                        _r = getattr(self, "_redis", None)
                        if "REDDETTİ" in _reason:
                            try:
                                _srv = (proxy or {}).get("server", "") or ""
                                if _srv and "scrapingbee" not in _srv.lower():
                                    _flagged = await self.proxy_rotator.mark_rejected_server(
                                        _srv, max_rejects=settings.proxy_reddetti_max
                                    )
                                    if _flagged:
                                        await self._log(
                                            f"🚩 Proxy flag'lendi (REDDETTİ tekrarı) — {email} SUÇLANMADI, "
                                            f"başka proxy'yle devam eder", "WARNING",
                                        )
                                if _r is not None:
                                    _at = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 3 * 3600))
                                    await _r.hset("farming:rejected_ip", email,
                                                  orjson.dumps({"reason": _reason, "at": _at, "proxy": _srv}))
                                # STORM SINIRI: hesap bu batch'te çok REDDETTİ aldıysa kalan worker'larını durdur
                                # (STRIKE YOK — hesabın suçu değil). ScrapingBee kredi yakmasını + CSV'de tek bozuk
                                # hesabın havuzu banlayıp İYİ hesapları aç bırakmasını sınırlar. Sonraki batch tekrar dener.
                                self._reddetti_count[email] = self._reddetti_count.get(email, 0) + 1
                                if (self._reddetti_count[email] >= settings.account_reddetti_cap
                                        and email not in self._deadlogin):
                                    self._deadlogin[email] = "REDDETTİ (çok tekrar — bu batch atlandı)"
                                    await self._log(
                                        f"⏭ {email} · {self._reddetti_count[email]}× REDDETTİ — bu batch atlanıyor "
                                        f"(STRIKE YOK, sonraki batch'te tekrar denenir)", "WARNING",
                                    )
                            except Exception:
                                pass
                            return None
                        if "2FA" in _reason:
                            # DETERMİNİSTİK hesap sorunu (TOTP/2FA bozuk) → strike + KIRMIZI olabilir.
                            if email not in self._deadlogin:
                                self._deadlogin[email] = _reason
                                await self._log(
                                    f"⛔ {email} login veremiyor ({_reason}) — bu hesabın KALAN worker'ları "
                                    f"atlanıyor (boşa TOTP hatası yok). Hesabın secret'ını/durumunu düzeltin.",
                                    "ERROR",
                                )
                                # KALICI KAYIT + strike: sorunlu hesabı redis'e yaz (Çıktılar'da gösterilir,
                                # panel yenilense de kalır). HSET/HINCRBY atomik → eşzamanlı worker'larda yarış yok.
                                try:
                                    if _r is not None:
                                        from services.account_store import incr_fail_count
                                        _strikes = await incr_fail_count(_r, email)
                                        _red = _strikes >= settings.account_red_strikes
                                        _at = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 3 * 3600))
                                        await _r.hset("farming:failed_accounts", email,
                                                      orjson.dumps({"reason": _reason, "at": _at,
                                                                    "strikes": _strikes, "red": _red}))
                                        if _red:
                                            await self._log(
                                                f"🔴 {email} {_strikes}. kez sorunlu → KIRMIZI, sonraki üretimlerde "
                                                f"ATLANACAK (panelden temizleyince tekrar sıraya girer)", "ERROR",
                                            )
                                except Exception:
                                    pass
                        elif "parola adımı gelmedi" in _reason:
                            # BELİRSİZ/geçici (yavaş proxy de tetikler) → STRIKE YOK, KIRMIZI YOK. Sadece bu batch'te
                            # kalan worker'ları atla (boşa deneme yok); sonraki batch hesabı tekrar dener.
                            if email not in self._deadlogin:
                                self._deadlogin[email] = _reason
                                await self._log(
                                    f"⏭ {email} · parola adımı gelmedi (çoğunlukla yavaş proxy) — bu batch atlanıyor, "
                                    f"STRIKE YOK (sonraki batch'te tekrar denenir)", "WARNING",
                                )
                        return None
                else:
                    # TURBO ama master login başarısız → anonim (girişsiz) session ÜRETME.
                    self._failed += 1
                    self._record(email, False)
                    await self._log(f"✗ {email} ·Master oturum yok (TURBO) → atlandı", "ERROR")
                    return None

                # Login tamamlandı → ısıtma için ağır kaynakları şimdi blokla (hız).
                await self._setup_resource_blocking(page)
                await self.warming_service.warm_session(page, keywords, mode)
                # HEDEF SİTELER: giriş sonrası ekstra siteleri gez → GERÇEK çerezlerini topla.
                # Proxy GERÇEKTEN IPv6-only literal mi? → AAAA ön-kapısı yalnız o zaman (#16).
                # (String-sniff yerine ipaddress ile sağlam tespit; sıkıştırılmamış literalleri kaçırmaz.)
                _psrv = (proxy or {}).get("server", "") if proxy else ""
                await self._visit_targets(page, proxy_is_ipv6_only=_proxy_is_ipv6_only(_psrv))
                # GERÇEK storage_state (çerez + localStorage origin'leri). cookies() sadece çerez verir →
                # export gerçek çerezleri UYDURMA origin'lerle eşliyordu (#9). storage_state ikisini de alır.
                state = await context.storage_state()
                cookies = state.get("cookies", [])

                # KALİTE KAPISI (#3): çekirdek Google AUTH çerezleri yoksa = yarı-login → ATLA. (Eskiden
                # validate_cookies sonucu yok sayılıp yarı-login oturum SUCCESS sayılıp export ediliyordu.)
                _CORE_AUTH = {"SID", "HSID", "SSID", "APISID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID"}
                if _CORE_AUTH - {c.get("name") for c in cookies}:
                    self._failed += 1
                    self._record(email, False)
                    await self._log(f"✗ {email} ·Auth çerez eksik (yarı-login) → atlandı", "ERROR")
                    return None

                profile = self.session_generator.generate_storage_state(
                    email=email,
                    profile_index=index,
                    keywords=keywords,
                    proxy_ip=proxy["server"] if proxy else "",
                    lifespan_days=lifespan_days,
                    user_agent=fp.user_agent,
                    device=fp.device_name,
                    fingerprint=self._fp_dict(fp, proxy, session_key=f"{email}:{index}"),
                )
                profile["storage_state"] = state           # GERÇEK çerez + origin (#9)
                profile["cookie_count"] = len(cookies)      # GERÇEK sayı, sentetik değil (#10)

                filepath = os.path.join(output_dir, f"profile_{index:05d}.json")
                await self.write_queue.enqueue(filepath, profile)

                if self._redis:
                    await self._redis.set(
                        f"session:{profile['token_hash']}",
                        email,
                        ex=settings.redis_session_ttl,
                    )

                self._completed += 1
                self._record(email, True)
                try:
                    from services.account_store import incr_daily_count, reset_fail_count
                    await incr_daily_count(self._redis, email)   # aşırı-farmlama sayacı
                    # OTO-İYİLEŞME: hesap TEKRAR çalıştı → sorunlu listesinden çıkar + strike sıfırla
                    # + ölü-işaretten çıkar. (redis hdel yoksa no-op; her başarıda ucuz, korumalı.)
                    if self._redis is not None:
                        await self._redis.hdel("farming:failed_accounts", email)
                        await self._redis.hdel("farming:rejected_ip", email)   # IP-reddi bayat kaydını da temizle
                        await reset_fail_count(self._redis, email)
                    self._deadlogin.pop(email, None)
                    self._reddetti_count.pop(email, None)
                except Exception:
                    pass
                elapsed = round(time.time() - start_time, 1)
                await self._log(
                    f"✓ {email} · #{index:05d} → {len(cookies)} çerez | {fp.device_name} | {elapsed}s"
                )
                return profile

            finally:
                try:
                    await context.close()
                except Exception:
                    pass
                self.pool.release_slot(context)

        except asyncio.TimeoutError:
            self._failed += 1
            self._record(email, False)
            # Timeout çoğu zaman ölü/yavaş proxy → art arda 3'te DEAD işaretle (rotasyondan düşer).
            if proxy and proxy.get("server"):
                try: await self.proxy_rotator.mark_dead_server(proxy["server"])
                except Exception: pass
            await self._log(f"✗ {email} ·TIMEOUT → skip", "WARNING")
            return None
        except Exception as e:
            self._failed += 1
            self._record(email, False)
            msg = str(e).lower()
            if proxy and proxy.get("server") and any(k in msg for k in ("proxy", "net::err", "econnrefused", "tunnel", "timed out", "connection")):
                try: await self.proxy_rotator.mark_dead_server(proxy["server"])
                except Exception: pass
            await self._log(f"✗ {email} ·{e}", "ERROR")
            return None
        finally:
            self._active_workers -= 1

    async def _master_login(self, email: str, password: str, proxy_urls: list[str]) -> list[dict] | None:
        await self._log("Master session login başlatılıyor...")
        context = None
        try:
            proxy = await self.proxy_rotator.get_proxy(session_key="master")
            if proxy is None:   # FAIL-CLOSED (CRIT #1 — master yolu): master login GERÇEK
                # password+TOTP auth'ıdır; proxysiz = sunucunun datacenter-IP'sinden Gmail'e
                # giriş → yaşlandırılmış master hesap ANINDA yanar. Direkt bağlantı ENGELLENİR.
                await self._log("Master login ✗ Proxy yok — direkt bağlantı ENGELLENDİ (master hesap korundu)", "ERROR")
                return None
            # seed e-posta-başına benzersiz (0 DEĞİL) → farklı hesapların master login'i AYNI
            # cihaz fingerprint'iyle görünmesin ('same device across accounts' ban sinyali: Tur1 #2).
            fp = self.fingerprint_service.generate(seed=zlib.crc32(email.encode()))
            ctx_options = self.fingerprint_service.get_context_options(fp)
            context = await self.pool.get_context(proxy, ctx_options)
            # KRİTİK (Tur4): master login GERÇEK password+TOTP girişidir. get_context_options
            # HTTP'de Sec-CH-UA-Mobile=?1/Platform=Android gönderir AMA stealth script enjekte
            # EDİLMEZSE JS tarafı ham headless-sunucu kimliğini (userAgentData.mobile=false,
            # platform=Linux, SwiftShader GPU) raporlar → CH-vs-JS uyuşmazlığı Google'ın giriş
            # risk motorunu tetikler ve MASTER hesabı yakar (tüm TURBO batch ölür). Worker yolu
            # (768-769) enjekte ediyor; master da BİREBİR aynı olmalı.
            await context.add_init_script(self.fingerprint_service.get_stealth_script(fp))
            page = await context.new_page()

            from services.totp_handler import TOTPHandler
            totp = TOTPHandler()
            success, _why = await self._login(page, email, password, totp)
            if not success:
                await self._log(f"Master login ✗ BAŞARISIZ: {_why or 'bilinmeyen sebep'}", "ERROR")
                return None

            cookies = await context.cookies()
            await self._log(f"Master session alındı: {len(cookies)} cookie")
            return cookies
        except Exception as e:
            await self._log(f"Master login hatası: {e}", "ERROR")
            return None
        finally:
            # context HER durumda kapanmalı ve havuz kilidi bırakılmalı — aksi halde
            # havuz zamanla açlığa girer.
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
                self.pool.release_slot(context)

    async def _proxy_provider_error(self, page) -> bool:
        """Proxy sağlayıcı (ScrapingBee) hata sayfası mı döndü? (kredi/limit bitti vb.)
        Böyle bir durumda 'Login FAILED' yerine NET hata verir ve varsa sonraki
        anahtara geçer (failover)."""
        try:
            txt = (await page.content())[:3000].lower()
        except Exception:
            return False
        if ("monthly api calls limit" in txt or "api calls limit reached" in txt
                or ("scrapingbee" in txt and "\"message\"" in txt)):
            await self._log(
                "PROXY HATASI: ScrapingBee anahtarı tükenmiş/limit dolmuş görünüyor. "
                "Ayarlar → yeni API anahtarı ekleyin veya 'sonraki anahtara geç'.",
                "ERROR",
            )
            try:
                from services.proxy_config import rotate_key
                if self._redis is not None:
                    await rotate_key(self._redis)  # varsa sonraki anahtara geç (bir sonraki batch kullanır)
            except Exception:
                pass
            return True
        return False

    async def _login(self, page, email: str, password: str, totp,
                     totp_secret: str | None = None, recovery_email: str | None = None) -> tuple[bool, str]:
        # Döner: (başarı, sebep). Sebep panelde "Worker-XX ✗ Login FAILED: <sebep>" olarak gösterilir
        # → operatör NEDEN başarısız olduğunu (proxy timeout / 2FA / captcha / reddedildi) GÖRÜR (D).
        # Çoklu-hesap: kimlik per-worker geçilir; verilmezse tek-hesap instance değerine düşer.
        ts = self._totp_secret if totp_secret is None else totp_secret
        rc = self._recovery_email if recovery_email is None else recovery_email
        sel = _load_selectors()
        login_sel = sel.get("google_login", {})
        try:
            await page.goto(
                "https://accounts.google.com/v3/signin/identifier?flowName=GlifWebSignIn&flowEntry=ServiceLogin",
                # 30sn yavaş residential/ScrapingBee proxy'lerde yetmiyordu → Google giriş sayfası
                # yüklenemeden 'Page.goto: Timeout' ile Login FAILED oluyordu. 60sn tampon (proxy
                # yavaşsa bile ilk navigasyon tamamlansın; proxy GERÇEKTEN ölüyse yine başarısız olur).
                wait_until="domcontentloaded", timeout=60000,
            )
            await asyncio.sleep(random.uniform(1, 2))

            # Proxy sağlayıcı hata sayfası mı? (Google yerine ScrapingBee limit hatası)
            if await self._proxy_provider_error(page):
                return False, "proxy sağlayıcı hata sayfası (ScrapingBee kredi/limit bitmiş olabilir)"

            consent = page.locator(sel.get("google_search", {}).get("consent_accept", "#L2AGLb"))
            if await consent.count() > 0:
                try:
                    await consent.first.click()
                    await asyncio.sleep(1)
                except Exception:
                    pass

            # --- E-posta adımı ---
            email_input = page.locator(login_sel.get("email_input", "#identifierId")).first
            await email_input.wait_for(state="visible", timeout=20000)
            await email_input.click()
            await self._human_type(email_input, email)  # insan gibi yaz
            await asyncio.sleep(random.uniform(0.4, 0.9))
            await self._solve_captcha_if_present(page)   # inline resim-captcha varsa çöz (yoksa no-op)
            nxt = page.locator(login_sel.get("email_next", "#identifierNext")).first
            if await nxt.count() > 0:
                await nxt.click()
            else:
                await email_input.press("Enter")

            # --- Parola adımı (alan görünene kadar bekle) ---
            pass_input = page.locator(login_sel.get("password_input", 'input[type="password"]')).first
            try:
                await pass_input.wait_for(state="visible", timeout=20000)
            except Exception:
                u = page.url.lower()
                # POST-SUBMIT CAPTCHA: parola gelmedi + (URL'de 'captcha' VEYA sayfada GÖRÜNÜR resim-captcha).
                # Çözücü açık+anahtarlıysa DENE — CapSolver BURADA çağrılır. Çözülürse cevabı gönder +
                # parola alanını TEKRAR bekle. Captcha yoksa/çözülemezse eski davranış (aşağıda) aynen çalışır.
                if self._captcha_enabled and self._captcha_key:
                    try:
                        from services.captcha_solver import captcha_present, solve_image_captcha
                        if "captcha" in u or await captcha_present(page):
                            _st, _ = await asyncio.wait_for(
                                solve_image_captcha(page, self._captcha_key, self._captcha_service, log=self._log),
                                timeout=25,
                            )
                            if _st == "solved":
                                try:
                                    await page.keyboard.press("Enter")   # captcha cevabını gönder
                                except Exception:
                                    pass
                                try:
                                    await pass_input.wait_for(state="visible", timeout=20000)
                                    u = "__solved__"   # parola alanı geldi → captcha aşıldı, akışa devam
                                except Exception:
                                    u = page.url.lower()
                    except Exception:
                        pass
                if u == "__solved__":
                    pass   # captcha aşıldı → aşağıdaki parola girişine devam et
                elif "rejected" in u:
                    await self._log(
                        "Google girişi REDDETTİ (signin/rejected): hesaba çok fazla otomatik deneme "
                        "yapıldığı için Google hesabı/IP'yi işaretledi. Bir süre bekleyin, taze hesap "
                        "kullanın ve aynı hesabı üst üste denemeyin.", "ERROR",
                    )
                    return False, "Google REDDETTİ (hesap/IP işaretli — çok deneme)"
                elif "captcha" in u:
                    await self._log("Google CAPTCHA istedi — çözülemedi/geçilemedi (flag'li IP olabilir).", "ERROR")
                    return False, "CAPTCHA istendi (otomatik giriş engellendi)"
                else:
                    logger.warning("Parola alanı gelmedi (url=%s)", page.url)
                    return False, "parola adımı gelmedi (e-posta reddedildi ya da akış değişti)"
            await asyncio.sleep(random.uniform(0.5, 1))
            await pass_input.click()
            await self._human_type(pass_input, password)  # insan gibi yaz
            await asyncio.sleep(random.uniform(0.4, 0.9))
            await self._solve_captcha_if_present(page)   # parola adımında resim-captcha varsa çöz (yoksa no-op)
            pnxt = page.locator(login_sel.get("password_next", "#passwordNext")).first
            if await pnxt.count() > 0:
                await pnxt.click()
            else:
                await pass_input.press("Enter")
            await asyncio.sleep(random.uniform(3, 5))

            # --- Doğrulama / challenge (önce KURTARMA E-POSTASI, sonra TOTP) ---
            url_low = page.url.lower()
            if "challenge" in url_low or "2-step" in url_low:
                handled = False
                reason = ""
                # 1) Kurtarma e-postası ile doğrulama (hesap 'kurtarma maili' ile işaretliyse).
                if rc:
                    handled = await self._handle_recovery_email(page, login_sel, rc)
                    if handled and "challenge" in page.url.lower():
                        handled = False
                    if not handled:
                        reason = f"kurtarma e-postası doğrulaması geçmedi (URL={page.url})"
                # 2) TOTP (kurtarma yoksa / işe yaramadıysa) — GERÇEK sebebi al.
                if not handled:
                    ok2, r2 = await totp.handle_2fa(page, ts)
                    handled = ok2
                    if not ok2:
                        reason = r2 or reason
                if not handled:
                    # Parola DOĞRU ama 2FA geçmedi → SPESİFİK sebebi panele yaz.
                    # Cihaz-onaylı (telefon 'evet') hesabı işaretle → panelde "otomatikleşmez" görünür.
                    if "CİHAZ-ONAYLI" in (reason or "").upper() or "CIHAZ-ONAYLI" in (reason or "").upper():
                        try:
                            from services.account_store import flag_device_prompt
                            await flag_device_prompt(self._redis, email)
                        except Exception:
                            pass
                    await self._log(f"2FA BAŞARISIZ (parola doğru): {reason}", "ERROR")
                    return False, f"2FA geçmedi — {reason}"
                await asyncio.sleep(random.uniform(2, 4))

            # --- Başarı tespiti (eski kod 'google.com in url' ile HEP true dönerdi) ---
            final = page.url.lower()
            if any(k in final for k in ("myaccount", "mail.google", "/webhp", "consent")):
                return True, ""
            # Hâlâ giriş/challenge/hata sayfasındaysa başarısız
            if any(k in final for k in ("signin", "identifier", "challenge", "pwd", "rejected", "disabled", "deniedsi")):
                return False, "giriş tamamlanamadı (hâlâ signin/challenge sayfasında)"
            return True, ""

        except Exception as e:
            # Proxy hata sayfası (kredi/limit) yüklenmiş ama bir adım fill edilemediyse yakala.
            try:
                if await self._proxy_provider_error(page):
                    return False, "proxy sağlayıcı hata sayfası (kredi/limit)"
            except Exception:
                pass
            es = str(e).lower()
            if any(k in es for k in ("proxy", "err_tunnel", "err_proxy", "econnrefused", "err_connection")):
                await self._log(
                    "PROXY HATASI: proxy bağlantısı başarısız (ScrapingBee kredisi/anahtarı sorunu olabilir). "
                    "Ayarlar → yeni anahtar ekleyin.", "ERROR",
                )
                _r = "proxy bağlantı hatası (kredi/anahtar?)"
            elif "timeout" in es:
                _r = "giriş sayfası açılamadı — zaman aşımı (proxy yavaş/ölü)"
            else:
                _r = f"beklenmedik hata: {str(e)[:80]}"
            masked = email.split("@")[0][:3] + "***@" + email.split("@")[-1] if "@" in email else "***"
            logger.error(f"Login failed for {masked}: {e}")
            return False, _r

    async def _handle_recovery_email(self, page, login_sel, recovery_email: str | None = None) -> bool:
        """Google 'kurtarma e-postanı onayla/gir' adımını doldurur (2FA'sız hesaplar için).
        Varsa 'Confirm your recovery email / Kurtarma e-postanı onayla' seçeneğini tıklar,
        sonra kurtarma adresini yazıp ilerler. Başarıyı çağıran taraf URL ile doğrular."""
        rec = ((recovery_email if recovery_email is not None else self._recovery_email) or "").strip()
        if not rec:
            return False
        try:
            # a) "Nasıl doğrulamak istersin" listesi çıktıysa kurtarma-maili seçeneğini seç.
            opt = page.locator(login_sel.get("recovery_email_option", "text=/recovery e-?mail|kurtarma/i"))
            if await opt.count() > 0:
                try:
                    await opt.first.click()
                    await asyncio.sleep(random.uniform(1.5, 2.5))
                except Exception:
                    pass
            # b) Kurtarma e-postası alanını doldur (insan gibi).
            inp = page.locator(login_sel.get("recovery_email_input", 'input[type="email"]')).first
            await inp.wait_for(state="visible", timeout=10000)
            await inp.click()
            await self._human_type(inp, rec)
            await asyncio.sleep(random.uniform(0.4, 0.9))
            # c) İlerle (buton yoksa Enter).
            nxt = page.locator(login_sel.get(
                "recovery_email_next", '#next button, #next, button:has-text("Next"), button:has-text("İleri")')).first
            if await nxt.count() > 0:
                try:
                    await nxt.click()
                except Exception:
                    await inp.press("Enter")
            else:
                await inp.press("Enter")
            await asyncio.sleep(random.uniform(3, 5))
            await self._log("Kurtarma e-postası doğrulaması denendi.", "INFO")
            return True
        except Exception as e:
            logger.debug("kurtarma e-postası adımı başarısız: %s", e)
            return False

    async def _visit_targets(self, page, proxy_is_ipv6_only: bool = False):
        """Giriş sonrası hedef havuzundan RASTGELE bir alt küme gez → her cookie farklı
        parmak izi taşısın (temel siteler + kullanıcının eklediği ekstralar).
        proxy_is_ipv6_only: yalnızca IPv6-only proxy'de AAAA ön-kapısı uygulanır (#16)."""
        pool = [u.strip() for u in (self._target_urls or []) if (u or "").strip()]
        if not pool:
            return
        # Her profilde rastgele 2–5 site (havuz küçükse tamamı), rastgele sırayla.
        k = random.randint(min(2, len(pool)), min(5, len(pool)))
        chosen = random.sample(pool, k)
        for u in chosen:
            if not u.startswith("http"):
                u = "https://" + u
            # SSRF backstop: hedef havuzuna bir şekilde iç/loopback URL sızmışsa ziyaret etme.
            if _target_host_blocked(u):
                logger.debug("Hedef site engellendi (iç/loopback): %s", u)
                continue
            # IPv6-only proxy → IPv6'sız hedef timeout verir; önceden atla (hızlı).
            # AMA bu AAAA kontrolü sunucu-yerel DNS ile bakar ve proxy IPv4 ise (ScrapingBee
            # ya da IPv4/hostname liste proxy) YANLIŞ pozitif verip erişilebilir IPv4 hedefi
            # atlardı (#16). Yalnızca proxy GERÇEKTEN IPv6-only iken uygula.
            if proxy_is_ipv6_only:
                from urllib.parse import urlparse as _up
                if not await _host_has_ipv6((_up(u).hostname or "").lower()):
                    logger.debug("Hedef IPv6 desteklemiyor, atlandı: %s", u)
                    continue
            try:
                await page.goto(u, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(random.uniform(1.5, 3.0))
                # Organik davranış: hafif kaydırma → bot sinyali azalır, oturum daha uzun yaşar.
                for _ in range(random.randint(1, 3)):
                    try:
                        await page.mouse.wheel(0, random.randint(300, 1100))
                        await asyncio.sleep(random.uniform(0.4, 1.1))
                    except Exception:
                        break
            except Exception as e:
                logger.debug("Hedef site atlandı (%s): %s", u, e)

    async def _setup_resource_blocking(self, page):
        async def route_handler(route):
            req = route.request
            # Üst-seviye sayfa (document) navigasyonunu ASLA engelleme — aksi halde
            # hedef site açılışı abort olurdu (ör. youtube.com BLOCKED_DOMAINS'te olduğu
            # için DEFAULT_TARGETS'taki YouTube hedefi hiç çerez üretmezdi). Sadece
            # alt-kaynaklar (script/xhr/tracker) domain bazında bloklanır.
            if req.resource_type == "document":
                # Redirect dahil her üst-seviye navigasyonu literal iç-IP'ye karşı doğrula
                # (SSRF: public URL 30x ile 169.254.169.254'e yönlendirebilir).
                if _target_host_blocked(req.url):
                    await route.abort()
                else:
                    await route.continue_()
            elif req.resource_type in BLOCKED_RESOURCE_TYPES:
                await route.abort()
            elif any(d in req.url for d in BLOCKED_DOMAINS):
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", route_handler)

    async def _load_checkpoint(self, output_dir: str) -> dict:
        path = os.path.join(output_dir, ".checkpoint.json")
        if os.path.exists(path):
            async with aiofiles.open(path, "rb") as f:
                return orjson.loads(await f.read())
        return {}

    async def _write_checkpoint(self, output_dir: str, last_index: int, total: int):
        path = os.path.join(output_dir, ".checkpoint.json")
        data = {"last_completed_index": last_index, "total_target": total, "status": "IN_PROGRESS"}
        async with aiofiles.open(path, "wb") as f:
            await f.write(orjson.dumps(data))

    async def _log(self, message: str, level: str = "INFO"):
        log_entry = {"message": message, "level": level, "timestamp": time.time()}
        logger.log(getattr(logging, level, logging.INFO), message)
        await broadcaster.broadcast(log_entry)

    def stop(self):
        self._stop_event.set()
