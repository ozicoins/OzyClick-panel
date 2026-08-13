# Kurulum Kılavuzu — Sıfırdan Adım Adım

Bu proje Docker Compose ile 4 servis çalıştırır: **frontend** (React, :3000), **backend**
(FastAPI, iç ağda :8000), **postgres** ve **redis**. Aşağıdaki adımlar temiz bir Ubuntu
sunucuda (22.04 / 24.04) sıfırdan kurulum içindir.

---

## 1) Gereksinimler

- Ubuntu 22.04 veya 24.04 (root ya da sudo yetkisi)
- ~10 GB boş disk (backend imajı Playwright/Chromium ile ~7-8 GB)
- 2 GB+ RAM
- Docker + Docker Compose plugin

### Docker kurulu değilse
```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
docker --version && docker compose version
```

---

## 2) Projeyi yerleştir

`bot.zip`'i sunucuya kopyalayıp açın:
```bash
unzip bot.zip -d /opt/sadq-proje
cd /opt/sadq-proje/sadq
```
(Dizin adı `sadq` olacak — tüm komutlar bu dizinde çalışır.)

---

## 3) .env oluştur (secret'lar)

`.env` dosyası ZORUNLUDUR ve gerçek secret'lar içermelidir. İki yol var:

### Yol A — Otomatik üretici (önerilir)
```bash
pip install 'passlib[bcrypt]' cryptography   # sadece üretici için
python3 generate_env.py
```
- Güvenli rastgele `JWT_SECRET_KEY`, DB/Redis parolaları, `CREDENTIAL_KEY` üretir.
- **Admin parolasını ekrana BİR KEZ yazar — kaydedin** (diskte yalnızca bcrypt hash tutulur).
- Var olan `.env`'i EZMEZ.

### Yol B — Elle
```bash
cp .env.example .env
nano .env
```
Doldurulması zorunlu alanlar:
| Değişken | Açıklama |
|---|---|
| `JWT_SECRET_KEY` | ≥32 karakter rastgele. Üret: `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Panel girişi (parola ≥10 karakter). Alternatif: `ADMIN_PASSWORD_HASH` (bcrypt) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Postgres kimlik bilgileri |
| `DATABASE_URL` | `postgresql+asyncpg://KULLANICI:PAROLA@postgres:5432/DB` |
| `REDIS_PASSWORD` | Redis parolası |
| `REDIS_URL` | `redis://:PAROLA@redis:6379/0` |
| `CREDENTIAL_KEY` | Fernet anahtarı: `python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
| `CORS_ORIGINS` | Örn: `["http://SUNUCU_IP:3000"]` (kendi IP/domaininizi ekleyin) |
| `ENVIRONMENT` | `production` |
| `TRUSTED_PROXY_COUNT` | Nginx arkasında `1` |
| `COOKIE_SECURE` | TLS **yoksa** `false`, TLS **varsa** `true` |

> Not: `placeholder`/`change-me`/`example` gibi değerler reddedilir; gerçek değer girin.

---

## 4) (Opsiyonel) Hesaplar

Hesap eklemek için **dosya ZORUNLU DEĞİL**. Panel açıldıktan sonra:
- **Üretim** sekmesi → *Multi-Gmail Havuzu* → **manuel ekle** (+kişi), veya
- `.txt`/`.csv` **yükle** (format: `mail:şifre:2fa:proxy:port:kullanıcı:şifre` — 2fa ve sonrası opsiyonel, otomatik algılanır).

İlk seed olarak `gmail.csv.enc` (Fernet ile şifreli) bırakabilirsiniz; sonrası panelden yönetilir.

---

## 5) Kur ve başlat

```bash
docker compose up -d --build
```
veya kısayol:
```bash
make setup
```
İlk build ~5-10 dk sürer (Playwright/Chromium indirir). Durum:
```bash
docker compose ps
```
Dört servis de `Up`/`healthy` olmalı.

---

## 6) Erişim

- Panel: **http://SUNUCU_IP:3000**
- Giriş: `ADMIN_USERNAME` + admin parolası (3. adımda belirlenen).

---

## 7) İlk ayarlar (panel → Ayarlar sekmesi)

- **Çalışma Modu → DRY-RUN**: Açık = sentetik test (tarayıcı/proxy YOK, kredi harcamaz).
  Gerçek üretim için kapatın (önce küçük bir count ile deneyin).
- **Proxy (ScrapingBee)**: API anahtar(lar)ını girin (tek tek veya toplu txt). Birden fazla
  anahtar ekleyip biri tükenince "sonraki anahtara geç" ile failover yapabilirsiniz.
- **Ülke + Kalite**: Classic (1 kredi) / Premium (~10-25) / Stealth (~75). Kredi harcamasına dikkat.

---

## 8) Bakım komutları

```bash
make logs                 # backend loglarını izle
make health               # sağlık kontrolü
make backup               # postgres yedeği (./backups altına)
make stop                 # tüm servisleri durdur
docker compose up -d --build   # kod değişikliğinden sonra yeniden deploy
docker builder prune -f        # deploy sonrası disk şişmesini önle (build cache)
```

---

## 9) Güvenlik önerileri (production)

- **TLS ekleyin** (domain + Caddy/nginx + Let's Encrypt). TLS gelince `.env`'de `COOKIE_SECURE=true` yapın.
- **SSH sertleştir**: root parola girişini kapatın, anahtar tabanlı auth + `fail2ban`.
- Postgres/Redis portları host'a AÇILMAZ (compose bunu zaten sağlar) — dışarı açmayın.
- `.env` ve `*.enc` dosyalarını gizli tutun (git'e koymayın; `.gitignore` hazırdır).

---

## 10) Sık sorunlar

| Belirti | Çözüm |
|---|---|
| Panel açılmıyor | `docker compose ps` → frontend/backend `Up` mı? `make logs` |
| Login çalışmıyor (HTTP'de) | `.env` → `COOKIE_SECURE=false` (TLS yoksa) |
| Disk doluyor | `docker builder prune -f` (build cache birikir) |
| Backend başlamıyor | `.env` eksik/placeholder secret → 3. adımı kontrol edin |
