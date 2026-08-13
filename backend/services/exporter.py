import os
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import aiofiles
import orjson

logger = logging.getLogger("exporter")


class ExporterService:
    async def export_profile(self, output_dir: str, profile: dict) -> str:
        os.makedirs(output_dir, exist_ok=True)
        idx = profile["profile_index"]
        filename = f"profile_{idx:05d}.json"
        filepath = os.path.join(output_dir, filename)

        async with aiofiles.open(filepath, "wb") as f:
            await f.write(orjson.dumps(profile["storage_state"], option=orjson.OPT_INDENT_2))

        return filename

    async def write_batch_manifest(
        self,
        output_dir: str,
        email: str,
        profiles: list[dict],
        sector: str = "",
        keywords: list[str] | None = None,
        lifespan_days: int = 5,
    ):
        manifest = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "accountEmail": email,
            "totalProfiles": len(profiles),
            "sector": sector,
            "warmingKeywords": keywords or [],
            "lifespanDays": lifespan_days,
            "proxyLocation": "TR",
            "profiles": [
                {
                    "file": f"profile_{p['profile_index']:05d}.json",
                    "sessionId": p["session_id"],
                    "proxyIp": p.get("proxy_ip", ""),
                    "createdAt": datetime.fromtimestamp(p["created_at"], tz=timezone.utc).isoformat(),
                    "expiresAt": datetime.fromtimestamp(p["expires_at"], tz=timezone.utc).isoformat(),
                    "status": p["status"],
                    "cookieCount": p["cookie_count"],
                    "userAgent": p.get("user_agent", ""),
                    "device": p.get("device", ""),
                }
                for p in profiles
            ],
        }

        path = os.path.join(output_dir, "batch_manifest.json")
        async with aiofiles.open(path, "wb") as f:
            await f.write(orjson.dumps(manifest, option=orjson.OPT_INDENT_2))

    async def write_proxy_map(self, output_dir: str, profiles: list[dict]):
        mapping = [
            {
                "profileFile": f"profile_{p['profile_index']:05d}.json",
                "assignedProxy": p.get("proxy_ip", ""),
                "proxyType": "IPv6" if ("::" in p.get("proxy_ip", "") or "ipv6" in p.get("proxy_ip", "").lower()) else "IPv4",
                "location": "TR",
                "status": p["status"],
            }
            for p in profiles
        ]

        path = os.path.join(output_dir, "cookie_proxy_map.json")
        async with aiofiles.open(path, "wb") as f:
            await f.write(orjson.dumps(mapping, option=orjson.OPT_INDENT_2))

    def create_streaming_zip(self, directory: str) -> Any:
        import zipstream
        # zipstream-ng: add_path() DOSYAYI diskten okur; add() argümanı içerik sanar.
        # (Eski hata: add(filepath) her girişe dosya yolunu metin olarak yazıyordu.)
        ct = getattr(zipstream, "ZIP_DEFLATED", 8)
        try:
            z = zipstream.ZipStream(compress_type=ct)
        except TypeError:
            z = zipstream.ZipStream()
        for root, _, files in os.walk(directory):
            for filename in sorted(files):
                filepath = os.path.join(root, filename)
                arcname = os.path.relpath(filepath, directory)
                z.add_path(filepath, arcname=arcname)
        return z

    def to_netscape_format(self, cookies: list[dict]) -> str:
        lines = ["# Netscape HTTP Cookie File", ""]
        for c in cookies:
            name = c.get("name")
            if not name:
                continue
            domain = c.get("domain") or ".google.com"
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            # httpOnly çerezler için '#HttpOnly_' önekli domain (curl/tarayıcı standardı) — L3
            dom_field = f"#HttpOnly_{domain}" if c.get("httpOnly") else domain
            secure = "TRUE" if c.get("secure") else "FALSE"
            path = c.get("path", "/")
            exp = c.get("expires")
            # Session çerezi (expires -1/None) → 0 (standart). -1 = 1969 → parser 'süresi dolmuş' sayardı (M4)
            expires = str(int(exp)) if isinstance(exp, (int, float)) and exp > 0 else "0"
            value = c.get("value", "")
            lines.append(f"{dom_field}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
        return "\n".join(lines) + "\n"

    def to_curl_format(self, cookies: list[dict]) -> str:
        parts = [f'{c["name"]}={c["value"]}' for c in cookies]
        cookie_str = "; ".join(parts)
        return f'curl -b "{cookie_str}" https://www.google.com'

    def output_stats(self, base_dir: str) -> dict:
        """Tüm hesaplardaki toplam profil (cookie dosyası) sayısı + hesap kırılımı."""
        total = 0
        breakdown = []
        if os.path.isdir(base_dir):
            for acct in sorted(os.listdir(base_dir)):
                adir = os.path.join(base_dir, acct)
                if not os.path.isdir(adir):
                    continue
                n = len([f for f in os.listdir(adir) if f.startswith("profile_") and f.endswith(".json")])
                if n:
                    breakdown.append({"account": acct, "profiles": n})
                    total += n
        return {"total_profiles": total, "accounts": len(breakdown), "breakdown": breakdown}

    def stream_all_transformed(self, base_dir: str, fmt: str):
        """TÜM hesaplardaki TÜM profilleri seçilen formata çevirip tek ZIP'e akıtır.
        fmt: 'adswhite' | 'gologin' | 'raw'. Her profil ayrı dosya (adswhite 'Cookie Klasörü'ne uygun)."""
        import zipstream
        import orjson
        ct = getattr(zipstream, "ZIP_DEFLATED", 8)
        try:
            z = zipstream.ZipStream(compress_type=ct)
        except TypeError:
            z = zipstream.ZipStream()
        if not os.path.isdir(base_dir):
            return z
        for acct in sorted(os.listdir(base_dir)):
            adir = os.path.join(base_dir, acct)
            if not os.path.isdir(adir):
                continue
            for fn in sorted(os.listdir(adir)):
                if not (fn.startswith("profile_") and fn.endswith(".json")):
                    continue
                try:
                    with open(os.path.join(adir, fn), "rb") as f:
                        profile = orjson.loads(f.read())
                    cookies = (profile.get("storage_state") or {}).get("cookies") or []
                    idx = fn.replace("profile_", "").replace(".json", "")
                    if fmt == "netscape":
                        # cookies.txt (metin) — Netscape formatı, çoğu araç/curl kabul eder.
                        z.add(self.to_netscape_format(cookies).encode("utf-8"), arcname=f"{acct}_p{idx}.txt")
                        continue
                    data = self.build_export(profile, cookies, fmt)
                    # DÜZ isim (alt-klasör yok) → adswhite 'Cookie Klasörü' tek klasörde hepsini görür.
                    arcname = f"{acct}_p{idx}_{fmt}.json"
                    z.add(orjson.dumps(data, option=orjson.OPT_INDENT_2), arcname=arcname)
                except Exception:
                    continue
        return z

    def to_adswhite_cookies(self, cookies: list[dict]) -> list[dict]:
        """adswhite / Playwright `context.add_cookies()` için birebir uyumlu çerez LİSTESİ.
        adswhite `expires` alanını okur ve sameSite'ı Strict/Lax/None bekler.
        KRİTİK: sameSite='None' olan çerez MUTLAKA secure=True olmalı — değilse Playwright
        add_cookies TÜM listeyi reddeder, adswhite hatayı yutar → çerezsiz/oturumsuz kalır."""
        ss_map = {"Strict": "Strict", "Lax": "Lax", "None": "None",
                  "strict": "Strict", "lax": "Lax", "none": "None",
                  "no_restriction": "None", "unspecified": "Lax"}
        out = []
        for c in cookies:
            if not c.get("name") or not c.get("domain"):   # boş isim/domain → add_cookies tüm listeyi reddeder (L2)
                continue
            ss_raw = c.get("sameSite")
            ss = ss_map.get(ss_raw, "Lax") if ss_raw else None
            secure = bool(c.get("secure", False))
            if ss == "None":
                secure = True  # SameSite=None → Secure ZORUNLU (yoksa add_cookies patlar)
            ck = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": secure,
            }
            exp = c.get("expires", c.get("expirationDate"))
            if isinstance(exp, (int, float)) and exp > 0:
                ck["expires"] = float(exp)
            if ss:
                ck["sameSite"] = ss
            out.append(ck)
        return out

    def build_export(self, profile: dict, cookies: list[dict], fmt: str):
        """Profili seçilen formata çevirir — TAM fingerprint dahil.
        gologin/universal → düz Chrome dizisi (GoLogin/AdsPower/Dolphin/Octo/Multilogin paste);
        raw → Playwright storage_state; adswhite → fingerprint+proxy+çerez tek dosyada."""
        fp = profile.get("fingerprint") or {}
        if fmt in ("gologin", "universal"):
            return self.to_gologin_cookies(cookies)
        if fmt == "raw":
            return profile.get("storage_state") or {"cookies": cookies}
        # OzyClick (varsayılan) — çerezi tüketen taraf BİREBİR fingerprint kursun (pasif oturum önlenir)
        return {
            "brand": "Ozy",              # OzyClick markası (çerezin içinde)
            "generator": "OzyClick",
            "user_agent": fp.get("user_agent") or profile.get("user_agent", ""),
            "device": fp.get("device") or profile.get("device", ""),
            "proxy": fp.get("proxy_ip") or profile.get("proxy_ip", ""),
            "fingerprint": fp,
            "cookies": self.to_adswhite_cookies(cookies),
        }

    def to_gologin_cookies(self, cookies: list[dict]) -> list[dict]:
        """Playwright storage_state çerezlerini GoLogin/AdsPower/Multilogin ve Chrome
        uzantısı (EditThisCookie/Cookie-Editor) formatına çevirir:
        expires→expirationDate (sn), sameSite Strict/Lax/None→strict/lax/no_restriction,
        hostOnly/session alanları eklenir. GoLogin 'Cookies' alanına bu dizi yapıştırılır."""
        ss_map = {"Strict": "strict", "Lax": "lax", "None": "no_restriction",
                  "strict": "strict", "lax": "lax", "none": "no_restriction"}
        out = []
        for c in cookies:
            name = c.get("name")
            domain = c.get("domain", "")
            if not name or not domain:      # boş isim/domain → import'ta tüm listeyi reddettirir (L2)
                continue
            exp = c.get("expires", -1)
            same_site = ss_map.get(c.get("sameSite", ""), "unspecified")
            secure = bool(c.get("secure", False))
            if same_site == "no_restriction":
                secure = True               # SameSite=None → Secure ZORUNLU, yoksa Chrome/GoLogin çerezi düşürür (M1)
            gc = {
                "name": name,
                "value": c.get("value", ""),
                "domain": domain,
                "path": c.get("path", "/"),
                "hostOnly": not str(domain).startswith("."),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": secure,
                "sameSite": same_site,
                "session": (exp is None) or (exp in (-1,)) or (isinstance(exp, (int, float)) and exp < 0),
            }
            if isinstance(exp, (int, float)) and exp > 0:
                gc["expirationDate"] = float(exp)  # GoLogin/Chrome: saniye cinsinden
            out.append(gc)
        return out
