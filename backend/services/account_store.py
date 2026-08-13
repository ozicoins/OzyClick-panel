"""Hesap deposu — hesaplar redis'te tutulur (manuel ekleme + txt yükleme kalıcı).

gmail.csv[.enc] sadece İLK seed kaynağıdır; sonrası redis'te yönetilir. Böylece
farming yalnızca txt'e bağımlı olmaz; manuel eklenen hesaplar da kullanılır.

GÜVENLİK: hassas alanlar (password/totp/recovery/app_password/phone) redis'e
YAZILMADAN ÖNCE Fernet ile şifrelenir (CREDENTIAL_KEY varsa). Böylece redis
snapshot/AOF sızsa bile parola+2FA düz metin çıkmaz. Okurken çözülür.
"""
import os
import orjson

from services.csv_parser import CSVParserService
from services import crypto

ACCOUNTS_KEY = "accounts:list"
INIT_KEY = "accounts:initialized"   # bir kez seed edildi işareti → silinen hesap geri gelmesin
SENSITIVE_FIELDS = {"password", "totp_secret", "recovery_email", "app_password", "phone_number"}
_ENC_PREFIX = "enc:"
DEVICE_PROMPT_KEY = "accounts:device_prompt"  # cihaz-onaylı 2FA (otomatikleşmez) hesaplar

_parser = CSVParserService()


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%d")


async def get_daily_count(redis, email: str) -> int:
    """Bu hesabın BUGÜN kaç profil ürettiği (aşırı-farmlama koruması)."""
    if redis is None or not email:
        return 0
    try:
        v = await redis.get(f"acct:daily:{_today()}:{email}")
        return int(v) if v else 0
    except Exception:
        return 0


async def incr_daily_count(redis, email: str, n: int = 1) -> int:
    if redis is None or not email:
        return 0
    try:
        k = f"acct:daily:{_today()}:{email}"
        v = await redis.incrby(k, n)
        await redis.expire(k, 172800)  # 2 gün TTL (dünkü sayaç kendiliğinden düşer)
        return int(v)
    except Exception:
        return 0


async def flag_device_prompt(redis, email: str) -> None:
    """Cihaz-onaylı 2FA (telefon 'evet') hesabını işaretle → panelde 'otomatikleşmez' gösterilir."""
    if redis is None or not email:
        return
    try:
        await redis.sadd(DEVICE_PROMPT_KEY, email)
    except Exception:
        pass


async def get_device_prompt_flags(redis) -> list[str]:
    if redis is None:
        return []
    try:
        vals = await redis.smembers(DEVICE_PROMPT_KEY)
        return sorted(v.decode() if isinstance(v, bytes) else v for v in vals)
    except Exception:
        return []


def _blank(email: str) -> dict:
    return {
        "email": email, "password": "", "recovery_email": "", "proxy_ip": "",
        "totp_secret": "", "phone_number": "", "daily_limit": 0, "farming_mode": "",
    }


def _file_seed() -> list[dict]:
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gmail.csv")
    try:
        if os.path.exists(csv_path) or os.path.exists(csv_path + ".enc"):
            return _parser.parse_file(csv_path)
    except Exception:
        pass
    return []


def _enc(v):
    if not v or not isinstance(v, str) or not crypto.is_enabled():
        return v
    if v.startswith(_ENC_PREFIX):
        return v
    try:
        return _ENC_PREFIX + crypto.encrypt_bytes(v.encode()).decode()
    except Exception:
        return v


def _dec(v):
    if isinstance(v, str) and v.startswith(_ENC_PREFIX) and crypto.is_enabled():
        try:
            return crypto.decrypt_bytes(v[len(_ENC_PREFIX):].encode()).decode()
        except Exception:
            return ""
    return v


def _encrypt_for_store(accounts: list[dict]) -> list[dict]:
    out = []
    for a in accounts:
        d = dict(a)
        for f in SENSITIVE_FIELDS:
            if d.get(f):
                d[f] = _enc(d[f])
        out.append(d)
    return out


def _decrypt_from_store(accounts: list[dict]) -> list[dict]:
    out = []
    for a in accounts:
        d = dict(a)
        for f in SENSITIVE_FIELDS:
            if d.get(f):
                d[f] = _dec(d[f])
        out.append(d)
    return out


def _mask_proxy(url: str) -> str:
    """Proxy URL'sindeki user:pass'ı yanıttan çıkar → http://host:port."""
    if isinstance(url, str) and "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://{rest.split('@', 1)[1]}"
    return url


def strip_sensitive(accounts: list[dict]) -> list[dict]:
    out = []
    for a in accounts:
        d = {k: v for k, v in a.items() if k not in SENSITIVE_FIELDS}
        if d.get("proxy_ip"):
            d["proxy_ip"] = _mask_proxy(d["proxy_ip"])  # proxy kimlik bilgisini gizle
        out.append(d)
    return out


async def get_accounts(redis, include_sensitive: bool = False) -> list[dict]:
    stored = None
    read_ok = True
    if redis is not None:
        try:
            raw = await redis.get(ACCOUNTS_KEY)
            stored = orjson.loads(raw) if raw is not None else None
        except Exception:
            # Okuma hatası → veriyi EZME (aksi halde geçici blip hesapları siler).
            read_ok = False
    if stored is None:
        # Daha önce initialize edildiyse (kullanıcı hesap yönetti) dosyadan ASLA
        # yeniden seed etme → silinen hesap geri gelmez. Yalnızca ilk kez seed et.
        initialized = True
        if redis is not None and read_ok:
            try:
                initialized = bool(await redis.get(INIT_KEY))
            except Exception:
                initialized = True  # emin değilsek seed etme (veri kaybı riski)
        if initialized:
            accounts = []
        else:
            accounts = _file_seed()
            if read_ok:
                await save_accounts(redis, accounts)  # INIT_KEY'i de set eder
    else:
        accounts = _decrypt_from_store(stored)
    return accounts if include_sensitive else strip_sensitive(accounts)


async def save_accounts(redis, accounts: list[dict]) -> None:
    if redis is not None:
        await redis.set(ACCOUNTS_KEY, orjson.dumps(_encrypt_for_store(accounts)))
        await redis.set(INIT_KEY, "1")  # hesaplar en az bir kez yönetildi


async def merge_accounts(redis, new_accounts: list[dict]) -> list[dict]:
    """Yeni hesapları mevcut havuza ekler (email'e göre dedup, yeni olan üzerine yazar)."""
    existing = await get_accounts(redis, include_sensitive=True)
    by_email = {a["email"]: a for a in existing if a.get("email")}
    for a in new_accounts:
        em = a.get("email")
        if not em:
            continue
        # Alan-bazlı merge: yeni değer DOLUYSA üzerine yaz, boşsa mevcut korunur
        # (yeniden ekleyince 2FA/proxy silinmesin).
        base = dict(by_email.get(em, {}))
        for k, v in a.items():
            if v not in (None, "", 0) or k not in base:
                base[k] = v
        by_email[em] = base
    merged = list(by_email.values())
    await save_accounts(redis, merged)
    return merged


async def add_account(redis, acc: dict) -> list[dict]:
    return await merge_accounts(redis, [acc])


async def remove_account(redis, email: str) -> list[dict]:
    accounts = [a for a in await get_accounts(redis, include_sensitive=True) if a.get("email") != email]
    await save_accounts(redis, accounts)
    return accounts


async def get_credentials(redis, email: str) -> dict | None:
    for a in await get_accounts(redis, include_sensitive=True):
        if a.get("email") == email:
            return a
    return None


def make_account(email: str, password: str, totp_secret: str = "", proxy_ip: str = "",
                 recovery_email: str = "") -> dict:
    acc = _blank(email)
    acc.update({"password": password, "totp_secret": totp_secret, "proxy_ip": proxy_ip,
                "recovery_email": recovery_email})
    return acc
