#!/usr/bin/env python3
"""
.env üretici — güvenli rastgele secret'lar oluşturur ve .env dosyasını yazar.

Kullanım:
    python3 generate_env.py

- Var olan .env'i EZMEZ (önce yedekleyin/silin).
- Admin parolasını ekrana bir kez yazar — kaydedin (diskte yalnızca bcrypt hash tutulur).
- Docker service adlarını (postgres/redis) kullanır. Backend'i Docker DIŞINDA
  çalıştıracaksanız DATABASE_URL ve REDIS_URL içindeki 'postgres'/'redis' →
  'localhost' yapın.
"""
import json
import os
import secrets
import sys


def _ask(prompt: str, default: str) -> str:
    """Etkileşimli sor; TTY yoksa/boşsa varsayılanı kullan."""
    try:
        val = input(f"{prompt}\n  [{default}]: ").strip()
        return val or default
    except (EOFError, KeyboardInterrupt):
        return default

try:
    from passlib.hash import bcrypt
except ImportError:
    sys.exit("passlib kurulu değil. Çalıştırın: pip install 'passlib[bcrypt]'")

try:
    from cryptography.fernet import Fernet
except ImportError:
    sys.exit("cryptography kurulu değil. Çalıştırın: pip install cryptography")

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")

if os.path.exists(ENV_PATH):
    sys.exit(f"HATA: {ENV_PATH} zaten var. Üzerine yazmamak için çıkılıyor. "
             "Yeniden üretmek istiyorsanız önce silin/yedekleyin.")

jwt_secret = secrets.token_urlsafe(48)
pg_pw = secrets.token_urlsafe(24)
redis_pw = secrets.token_urlsafe(24)
admin_user = "ozicoin"
admin_pw = "ozicoin"  # kullanıcı tercihi (kısa parola — güçlendirmek istersen buradan değiştir)
admin_hash = bcrypt.using(rounds=12).hash(admin_pw)
cred_key = Fernet.generate_key().decode()  # credential at-rest encryption anahtarı

# ──── Panelin açık adresi (CORS + cookie güvenliği bu değere göre ayarlanır) ────
# Panel tarayıcıdan HANGİ adresle açılıyorsa (ör. http://194.36.88.29:3000 veya
# https://panel.ornek.com) o girilmeli — aksi halde OriginEnforcement login'i 403'ler.
public_origin = _ask(
    "Panelin açık adresi (tarayıcıdan girilen origin) nedir?",
    "http://localhost:3000",
).rstrip("/")
# Şema yoksa ekle — aksi halde tarayıcı 'http://ip:port' Origin gönderir, CORS listesi
# ('ip:port') eşleşmez ve login 403 olur.
if "://" not in public_origin:
    public_origin = "http://" + public_origin
if "localhost" not in public_origin and "127.0.0.1" not in public_origin and public_origin.startswith("http://"):
    print(f"⚠  UYARI: '{public_origin}' düz HTTP — TLS önerilir. COOKIE_SECURE=false yazılacak.")
uses_tls = public_origin.lower().startswith("https")
# TLS yoksa (düz HTTP) Secure cookie tarayıcıda düşerdi → COOKIE_SECURE=false şart.
cookie_secure = "true" if uses_tls else "false"
# CORS listesi: açık origin + (localhost değilse) yerel geliştirme origin'leri.
_cors = [public_origin]
if "localhost" not in public_origin and "127.0.0.1" not in public_origin:
    _cors += ["http://localhost:3000", "http://localhost:5173"]
cors_origins_json = json.dumps(_cors)

env = f"""# OTOMATIK URETILDI — gizli tutun. Izinler: chmod 600
ENVIRONMENT=production

# ──── Database ────
POSTGRES_USER=iu_user
POSTGRES_PASSWORD={pg_pw}
POSTGRES_DB=iu_cookies
DATABASE_URL=postgresql+asyncpg://iu_user:{pg_pw}@postgres:5432/iu_cookies

# ──── Redis ────
REDIS_PASSWORD={redis_pw}
REDIS_URL=redis://:{redis_pw}@redis:6379/0
REDIS_SESSION_TTL=432000

# ──── JWT ────
JWT_SECRET_KEY={jwt_secret}
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440

# ──── Admin (parola diskte HASH olarak; duz parola yok) ────
ADMIN_USERNAME={admin_user}
ADMIN_PASSWORD_HASH={admin_hash}

# ──── Captcha (opsiyonel · CapSolver) ────
# TERCİH EDİLEN: anahtarı PANELDEN gir (⚙️ → Captcha) → redis'te maskeli. .env yalnızca yedek.
CAPTCHA_API_KEY=
CAPTCHA_SERVICE=capsolver

# ──── Credential at-rest encryption ────
CREDENTIAL_KEY={cred_key}

# ──── Farming ────
DEFAULT_FARMING_MODE=SAFE
MAX_CONCURRENT_BATCHES=3
TURBO_WORKER_COUNT=80
FAST_WORKER_COUNT=10
SAFE_WORKER_COUNT=3
MASTER_SESSION_REFRESH_MINUTES=90
CHECKPOINT_INTERVAL=100

# ──── Playwright ────
PLAYWRIGHT_BROWSER=chromium
BROWSER_POOL_SIZE=10
HEADLESS=true
# Gerçek render (bot tespitini düşürür, ekran GÖSTERMEZ). Sunucuda Xvfb kuruluysa
# USE_XVFB=true + uygulamayı `xvfb-run` altında başlatın → tam headful (en gerçekçi).
REAL_RENDER=true
USE_XVFB=false

# ──── Proxy / Anti-detect ────
DEFAULT_PROXY_LOCATION=TR
CURL_CFFI_IMPERSONATE=chrome120
STEALTH_ENABLED=true

# ──── Telegram / SMS (opsiyonel) ────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
SMS_API_KEY=
SMS_SERVICE=5sim

# ──── Disk / Upload ────
DISK_WARNING_PERCENT=80
DISK_CRITICAL_PERCENT=90
MAX_UPLOAD_BYTES=10485760

# ──── Paths ────
COOKIES_OUTPUT_DIR=./cookies_output
LOG_DIR=./logs

# ──── CORS ────
CORS_ORIGINS={cors_origins_json}

# ──── Cookie güvenliği (TLS varsa true) ────
COOKIE_SECURE={cookie_secure}
"""

with open(ENV_PATH, "w") as f:
    f.write(env)
os.chmod(ENV_PATH, 0o600)

# ──── Credential at-rest encryption'ı otomatik etkinleştir ────
# gmail.csv varsa .env'deki anahtarla şifrele ve düz metni sil (secure-by-default).
gmail_csv = os.path.join(ROOT, "gmail.csv")
gmail_enc = gmail_csv + ".enc"
enc_msg = ""
if os.path.exists(gmail_csv):
    with open(gmail_csv, "rb") as f:
        plaintext = f.read()
    with open(gmail_enc, "wb") as f:
        f.write(Fernet(cred_key.encode()).encrypt(plaintext))
    os.chmod(gmail_enc, 0o600)
    os.remove(gmail_csv)
    enc_msg = f"✓ gmail.csv şifrelendi → {gmail_enc} (düz metin silindi)"
else:
    enc_msg = "ℹ gmail.csv yok — şifreleme atlandı. Ekledikten sonra: python3 encrypt_csv.py"

print("✓ .env olusturuldu (chmod 600):", ENV_PATH)
print("=" * 50)
print("  GIRIS BILGILERI:")
print(f"  Kullanici : {admin_user}")
print(f"  Parola    : {admin_pw}")
print("=" * 50)
print("Duz parola diskte TUTULMUYOR; sadece bcrypt hash .env'de.")
print(enc_msg)
print("Credential anahtari .env icinde (CREDENTIAL_KEY). Docker gmail.csv.enc'i mount eder.")
