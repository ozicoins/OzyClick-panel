import csv
import io
import os
import re
from urllib.parse import quote

# TOTP/2FA sırrı: base32 (A-Z, 2-7), noktasız, en az 16 karakter. Proxy host'ları
# nokta içerdiği için ayrışır → 2fa alanı otomatik algılanabilir.
_TOTP_RE = re.compile(r"^[A-Za-z2-7]{16,}$")
# host:port veya host:port:user:pass (tek alan proxy). host harf/rakam/./-; port 2-5 hane.
_PROXY_RE = re.compile(r"^[A-Za-z0-9.\-]+:\d{2,5}(:[^:]+:[^:]+)?$")


def _looks_totp(s: str) -> bool:
    s = s.replace(" ", "")
    return "." not in s and bool(_TOTP_RE.match(s))


def _build_proxy_url(rest: list[str]) -> str:
    """rest = [host, port] veya [host, port, user, pass] → proxy URL."""
    rest = [r for r in rest if r]
    if len(rest) >= 4:
        host, port, user, pw = rest[0], rest[1], rest[2], rest[3]
        # user/pass URL-encode → özel karakterler (/ ? # boşluk) URL'yi bozmaz.
        return f"http://{quote(user, safe='')}:{quote(pw, safe='')}@{host}:{port}"
    if len(rest) >= 2:
        return f"http://{rest[0]}:{rest[1]}"
    return ""


def _blank_account(email: str) -> dict:
    return {
        "email": email,
        "password": "",
        "recovery_email": "",
        "proxy_ip": "",
        "totp_secret": "",
        "phone_number": "",
        "daily_limit": 0,
        "farming_mode": "",
    }


class CSVParserService:
    def parse(self, file_content: bytes) -> list[dict]:
        text = self._decode(file_content)
        # Başlıklı CSV (email,password,... header) → CSV olarak oku.
        if self._is_csv_header(text):
            return self._parse_csv(text)
        # Aksi halde HER SATIRI evrensel parse et — ayraç ne olursa olsun
        # (| , ; TAB : veya boşluk). Alanlar akıllı sınıflandırılır (email/parola/totp/kurtarma/proxy).
        accounts = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            acc = self._parse_one(line)
            if acc and acc.get("email") and acc.get("password"):
                accounts.append(acc)
        return accounts

    @staticmethod
    def _is_csv_header(text: str) -> bool:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            low = line.lower()
            return ("," in line) and ("email" in low) and ("password" in low or "pass" in low)
        return False

    def _parse_one(self, line: str) -> dict | None:
        """Tek satırı ayraçtan bağımsız parse eder. Ayraç önceliği: | , ; TAB → sonra ':' → boşluk.
        proxy ':' içerdiğinden, ':' dışı ayraç varsa proxy tek alan kalır (host:port[:user:pass])."""
        # 1) ':' DIŞI ayraçlar (proxy'nin ':'ına dokunmaz)
        for d in ("|", "\t", ";", ","):
            if d in line and "@" in line.split(d, 1)[0]:
                return self._from_delimited([p.strip() for p in line.split(d)], proxy_single=True)
        # 2) Saf ':' format (proxy host:port:user:pass ':' ile bölünür → sağdan topla)
        if ":" in line and "@" in line.split(":", 1)[0]:
            return self._colon_one(line)
        # 3) Boşlukla ayrılmış
        parts = line.split()
        if parts and "@" in parts[0]:
            return self._from_delimited(parts, proxy_single=True)
        return None

    def _from_delimited(self, fields: list[str], proxy_single: bool) -> dict | None:
        fields = [f.strip() for f in fields]
        if not fields or "@" not in fields[0]:
            return None
        email = fields[0]
        rest = [f for f in fields[1:]]
        password = rest[0] if rest else ""
        extras = rest[1:]
        totp = recovery = proxy = ""
        for f in extras:
            if not f:
                continue
            if "@" in f and not recovery:                      # kurtarma e-postası
                recovery = f
            elif (_PROXY_RE.match(f) or ("." in f and ":" in f)) and not proxy:  # host:port[:user:pass] tek alan
                proxy = _build_proxy_url([x for x in f.split(":") if x])
            elif _looks_totp(f) and not totp:                  # base32 2FA — SADECE base32 kabul
                totp = f.replace(" ", "")
            # NOT: 'bilinmeyen → totp varsay' kör yedeği KALDIRILDI (#19). Telefon/not gibi
            # base32-olmayan alanlar totp_secret'e yazılıyor, hatta SONRAKİ gerçek base32
            # secret'i bloke edip 2FA hesabını sessizce bozuyordu. base32 değilse yok say.
        acc = _blank_account(email)
        acc.update({"password": password, "totp_secret": totp, "recovery_email": recovery, "proxy_ip": proxy})
        return acc

    def _colon_one(self, line: str) -> dict | None:
        parts = [p.strip() for p in line.split(":")]
        if len(parts) < 2 or "@" not in parts[0]:
            return None
        email = parts[0]
        mid = parts[1:]
        proxy_url = ""
        totp = ""
        recovery = ""
        # SAĞDAN proxy: host:port:user:pass (4) veya host:port (2)
        if len(mid) >= 5 and "." in mid[-4] and mid[-3].isdigit():
            proxy_url = _build_proxy_url(mid[-4:]); mid = mid[:-4]
        elif len(mid) >= 3 and "." in mid[-2] and mid[-1].isdigit():
            proxy_url = _build_proxy_url(mid[-2:]); mid = mid[:-2]
        # kurtarma e-postası (mid[1:] içinde '@' varsa) — totp'ten ÖNCE ayır ki totp sona gelsin
        for i, f in enumerate(mid[1:], start=1):
            if "@" in f:
                recovery = f
                mid = mid[:i] + mid[i + 1:]
                break
        # SAĞDAN 2fa (base32)
        if len(mid) >= 2 and _looks_totp(mid[-1]):
            totp = mid[-1]; mid = mid[:-1]
        password = ":".join(mid)  # parola ':' içerebilir → geri birleştir
        acc = _blank_account(email)
        acc.update({"password": password, "totp_secret": totp, "recovery_email": recovery, "proxy_ip": proxy_url})
        return acc

    @staticmethod
    def _has_pipe(text: str) -> bool:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            return "|" in line and "@" in line.split("|")[0]
        return False

    def _parse_pipe(self, text: str) -> list[dict]:
        """NET sabit-kolon format — her satır bir hesap, kolonlar '|' ile ayrılır:
            email|password|totp_secret|recovery_email|proxy
        Son 3 kolon OPSİYONEL (boş bırakılabilir/atlanabilir). proxy = host:port
        veya host:port:user:pass (kendi ':'larını korur). 'akıllı tahmin' YOK — konum sabit."""
        accounts = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            email = parts[0] if parts else ""
            if "@" not in email:
                continue
            password = parts[1] if len(parts) > 1 else ""
            totp = (parts[2] if len(parts) > 2 else "").replace(" ", "")
            recovery = parts[3] if len(parts) > 3 else ""
            proxy_raw = parts[4] if len(parts) > 4 else ""
            proxy_url = ""
            if proxy_raw:
                pp = [x.strip() for x in proxy_raw.split(":") if x.strip()]
                proxy_url = _build_proxy_url(pp) if len(pp) >= 2 else ""
            acc = _blank_account(email)
            acc.update({
                "password": password,
                "totp_secret": totp,
                "recovery_email": recovery,
                "proxy_ip": proxy_url,
            })
            accounts.append(acc)
        return accounts

    @staticmethod
    def _decode(file_content: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "iso-8859-9", "latin-1"):
            try:
                return file_content.decode(encoding)
            except (UnicodeDecodeError, ValueError):
                continue
        return file_content.decode("utf-8", errors="replace")

    @staticmethod
    def _is_colon_format(text: str) -> bool:
        # İlk anlamlı satıra bak: CSV header ise CSV; "email@...:..." ise colon.
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "," in line and "email" in line.lower():
                return False
            at, colon = line.find("@"), line.find(":")
            return at != -1 and colon != -1 and colon > at
        return False

    def _parse_csv(self, text: str) -> list[dict]:
        reader = csv.DictReader(io.StringIO(text))
        accounts = []
        for row in reader:
            email = (row.get("email") or "").strip()
            if not email or "@" not in email:
                continue
            acc = _blank_account(email)
            acc.update({
                "password": (row.get("password") or "").strip(),
                "recovery_email": (row.get("recovery_email") or "").strip(),
                "proxy_ip": (row.get("proxy_ip") or "").strip(),
                "totp_secret": (row.get("totp_secret") or "").strip(),
                "phone_number": (row.get("phone_number") or "").strip(),
                "daily_limit": self._safe_int(row.get("daily_limit")),
                "farming_mode": (row.get("farming_mode") or "").strip(),
            })
            accounts.append(acc)
        return accounts

    def _parse_colon(self, text: str) -> list[dict]:
        """
        Format: email:password[:2fa][:proxy_host:proxy_port[:proxy_user:proxy_pass]]
        2fa ve sonrası İSTEĞE BAĞLI ve OTOMATİK ALGILANIR:
          - email:password
          - email:password:2fa
          - email:password:host:port
          - email:password:host:port:user:pass
          - email:password:2fa:host:port
          - email:password:2fa:host:port:user:pass
        2fa alanı base32 (noktasız, 16+ karakter) ise 2fa; nokta içeriyorsa proxy host'tur.
        """
        accounts = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            parts = [p.strip() for p in line.split(":")]
            if len(parts) < 2 or "@" not in parts[0]:
                continue

            email = parts[0]
            mid = parts[1:]            # password + [2fa] + [proxy...]
            proxy_url = ""
            totp = ""

            # 1) SAĞDAN proxy'yi ayır: host:port:user:pass (4) veya host:port (2).
            #    host nokta içerir, port sayısaldır. (password'ı yemesin diye min uzunluk kontrolü)
            if len(mid) >= 5 and "." in mid[-4] and mid[-3].isdigit():
                proxy_url = _build_proxy_url(mid[-4:])
                mid = mid[:-4]
            elif len(mid) >= 3 and "." in mid[-2] and mid[-1].isdigit():
                proxy_url = _build_proxy_url(mid[-2:])
                mid = mid[:-2]

            # 2) SAĞDAN 2fa'yı ayır (base32, noktasız, 16+).
            if len(mid) >= 2 and _looks_totp(mid[-1]):
                totp = mid[-1]
                mid = mid[:-1]

            # 3) Kalan her şey parola → ':' içerebilir, geri birleştir.
            password = ":".join(mid)

            acc = _blank_account(email)
            acc.update({
                "password": password,
                "totp_secret": totp,
                "proxy_ip": proxy_url,
            })
            accounts.append(acc)
        return accounts

    @staticmethod
    def _safe_int(value: str | None, default: int = 0) -> int:
        if not value:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def parse_file(self, filepath: str) -> list[dict]:
        from services import crypto

        if filepath.endswith(".enc"):
            return self._parse_encrypted(filepath)

        enc_path = filepath + ".enc"
        enc_exists = os.path.exists(enc_path)
        plain_exists = os.path.exists(filepath)

        # .enc'i yalnızca anahtar mevcutsa ya da düz metin yoksa kullan.
        if enc_exists and (crypto.is_enabled() or not plain_exists):
            return self._parse_encrypted(enc_path)
        if plain_exists:
            with open(filepath, "rb") as f:
                return self.parse(f.read())
        raise FileNotFoundError(f"Credential dosyası yok: {filepath} / {enc_path}")

    def _parse_encrypted(self, filepath: str) -> list[dict]:
        from services.crypto import decrypt_bytes
        with open(filepath, "rb") as f:
            return self.parse(decrypt_bytes(f.read()))
