from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator
from typing import Literal
import json

# Bilinen güvensiz placeholder değerler — bunlar production'da reddedilir.
_PLACEHOLDERS = {
    "",
    "change-me-to-a-256-bit-random-secret",
    "change-me-admin-password",
}
# Substring işaretçileri — .env.example placeholder'ları ve yaygın kalıplar.
# Enumerate etmek yerine "işaret içeriyorsa reddet" yaklaşımı (denylist senkron kalır).
_PLACEHOLDER_MARKERS = (
    "change-me", "changeme", "__degistirin", "degistirin",
    "your-", "your_", "xxxx", "placeholder", "example",
)
_WEAK_DB_MARKERS = ("iu_secret_2026",)


def _looks_placeholder(v: str) -> bool:
    low = v.lower()
    return v in _PLACEHOLDERS or any(m in low for m in _PLACEHOLDER_MARKERS)


class Settings(BaseSettings):
    # Database
    database_url: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_session_ttl: int = 432000  # 5 days in seconds

    # JWT
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440  # 1 gün (kısa ömür → çalınan token az işe yarar)

    # Auth cookie 'Secure' bayrağı. TLS yoksa (düz HTTP) False olmalı — aksi halde
    # tarayıcı cookie'yi düşürür ve login çalışmaz. TLS eklendiğinde True yapın.
    cookie_secure: bool = True

    # Admin — ya ADMIN_PASSWORD ya da (tercihen) ADMIN_PASSWORD_HASH set edilmeli
    admin_username: str = "admin"
    admin_password: str = ""
    admin_password_hash: str = ""

    # Farming
    default_farming_mode: Literal["SAFE", "FAST", "TURBO"] = "SAFE"
    max_concurrent_batches: int = 3
    # 8 vCPU / 8GB-container'a göre optimize (ölçüm: ~64MB/browser floor, ~350MB peak target-site).
    # num_workers = min(mode, browser_pool_size) → turbo pool tavanı=14 (14×350MB≈4.9GB < 8GB).
    turbo_worker_count: int = 14   # MAX — master-login+klon; aynı anda 14 tarayıcı
    fast_worker_count: int = 10    # dengeli
    safe_worker_count: int = 4     # hafif
    master_session_refresh_minutes: int = 90
    checkpoint_interval: int = 100
    worker_timeout: int = 300  # saniye/profil — gerçek 2FA login + TOTP seri-bekleme + ısıtma + hedef
    # (aynı hesaba count>1 verilince TOTP replay-kapısı worker'ları ~30sn arayla sıraya sokar).

    # Aşırı-farmlama koruması: bir hesaptan GÜNDE en fazla kaç profil (çoklu-hesapta hesap başına).
    # NOT: worker sayısı = PARALEL HIZ; bu = hesap/gün. Toplam = hesap sayısı × bu limit.
    # Tek hesaba worker eklemek üretimi artırmaz (Google hesabı zaten sınırlar) → çok HESAP gerekir.
    # Gerçekçi aralık: 30-60 (üstü hesabı hızla yakar). 0 = sınırsız. .env: PER_ACCOUNT_DAILY_LIMIT
    per_account_daily_limit: int = 50

    # DRY-RUN: gerçek tarayıcı/Google login OLMADAN tüm pipeline'ı çalıştırır
    # (login+warming yerine sentetik cookie). Orkestrasyon/çıktı testi içindir.
    dry_run: bool = False

    # Playwright
    playwright_browser: str = "chromium"
    browser_pool_size: int = 14   # MAX eşzamanlı Chromium tavanı (8 vCPU / 8GB-container güvenli sınırı)
    headless: bool = True
    # GERÇEK RENDER: tarayıcı gerçek Chrome render motorunu kullanır (bot tespiti düşer,
    # Google login başarısı + oturum ömrü artar). Ekran GÖSTERİLMEZ:
    #   • Linux + DISPLAY (Xvfb) → tam headful, görünmez sanal ekrana çizer (en gerçekçi)
    #   • macOS / DISPLAY yok    → new-headless (gerçek render, pencere açılmaz)
    # Kapatılırsa (False) eski klasik headless'a döner.
    real_render: bool = True
    # Tam-headful yalnızca bu AÇIKÇA True iken (Xvfb sanal ekran kurulu sunucu) kullanılır.
    # False iken DISPLAY olsa bile new-headless kullanılır → yanlışlıkla GÖRÜNÜR pencere açılmaz.
    use_xvfb: bool = False
    # Chromium sandbox varsayılan AÇIK (secure-by-default). Container desteklemezse
    # farming_engine otomatik --no-sandbox'a düşer (fallback). Zorla kapatmak için True.
    browser_no_sandbox: bool = False

    # Proxy
    default_proxy_location: str = "TR"

    # Proxy sağlayıcı: "csv" (gmail.csv'deki proxy_ip) veya "scrapingbee" (API proxy mode).
    # ScrapingBee: https://www.scrapingbee.com/documentation/#proxy-mode
    proxy_provider: Literal["csv", "scrapingbee"] = "csv"
    scrapingbee_api_key: str = ""          # API anahtarı (gizli — .env / secret)
    scrapingbee_country: str = "tr"        # ISO ülke kodu: tr, us, gb, de, fr...
    scrapingbee_render_js: bool = False    # JS render (cookie üretimi için genelde gereksiz)
    scrapingbee_premium: bool = True       # premium/residential proxy havuzu

    # TLS / Anti-detect
    curl_cffi_impersonate: str = "chrome"   # curl_cffi'nin en yeni desteklediği Chrome TLS'i (sabit eski sürüm=tell)
    stealth_enabled: bool = True

    # Captcha (optional) — tek marka CapSolver (clicker paneliyle aynı)
    captcha_api_key: str = ""
    captcha_service: str = "capsolver"

    # Sorunlu-hesap / proxy stratejisi
    account_red_strikes: int = 2      # bu kadar üretimde login veremeyen hesap KIRMIZI + sıradan çıkar
    proxy_reddetti_max: int = 2       # bir proxy bu kadar "Google REDDETTİ" üretirse rotasyondan çıkar
    account_reddetti_cap: int = 3     # bir hesap bu batch'te bu kadar REDDETTİ alırsa kalanı atlanır (strike YOK, kredi/havuz koruması)

    # Credential at-rest encryption (opsiyonel).
    # Fernet anahtarı; production'da runtime'da (secret manager / docker secret)
    # inject edilmeli, diske yazılmamalı. Boşsa gmail.csv düz metin okunur.
    credential_key: str = ""

    # Telegram (optional)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # SMS 2FA (optional)
    sms_api_key: str = ""
    sms_service: str = "5sim"

    # Disk monitoring
    disk_warning_percent: int = 80
    disk_critical_percent: int = 90

    # Uploads
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB

    # Paths
    cookies_output_dir: str = "./cookies_output"
    log_dir: str = "./logs"

    # CORS
    cors_origins: str = '["http://localhost:3000","http://localhost:5173"]'

    # Ortam — "production" ise güvenlik kontrolleri sıkılaşır
    environment: Literal["development", "production"] = "production"

    # Rate-limit için güvenilen reverse-proxy sayısı. 0 → X-Forwarded-For'a GÜVENME
    # (doğrudan bağlantı IP'si kullanılır). Nginx arkasındaysa 1 yapın.
    trusted_proxy_count: int = 0

    # WebSocket/CSRF için izin verilen origin'ler CORS listesiyle aynıdır.

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        if _looks_placeholder(v):
            raise ValueError(
                "JWT_SECRET_KEY ayarlanmalı (placeholder değer kullanılamaz). "
                "Öneri: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY en az 32 karakter olmalı")
        return v

    @field_validator("database_url")
    @classmethod
    def _validate_db(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL ayarlanmalı")
        if _looks_placeholder(v) or any(marker in v for marker in _WEAK_DB_MARKERS):
            raise ValueError(
                "DATABASE_URL örnek/placeholder/varsayılan parola içeriyor — gerçek bir parola ile değiştirin"
            )
        return v

    @model_validator(mode="after")
    def _validate_admin_credentials(self):
        if not self.admin_password_hash:
            if _looks_placeholder(self.admin_password):
                raise ValueError(
                    "ADMIN_PASSWORD veya ADMIN_PASSWORD_HASH ayarlanmalı (placeholder kullanılamaz)"
                )
            if len(self.admin_password) < 10:
                raise ValueError("ADMIN_PASSWORD en az 10 karakter olmalı")
        return self

    @model_validator(mode="after")
    def _validate_cors(self):
        origins = self.cors_origins_list
        for o in origins:
            if o == "*" or "*" in o or o.strip().lower() == "null":
                raise ValueError(
                    f"CORS_ORIGINS güvensiz origin içeremez ('{o}') — "
                    "wildcard/null, allow_credentials=True ile birlikte güvensizdir"
                )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return json.loads(self.cors_origins)

    @property
    def worker_count(self) -> int:
        mode_map = {
            "SAFE": self.safe_worker_count,
            "FAST": self.fast_worker_count,
            "TURBO": self.turbo_worker_count,
        }
        return mode_map.get(self.default_farming_mode, self.safe_worker_count)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
