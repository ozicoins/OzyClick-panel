"""Hedef site havuzu — Google girişinden SONRA gezilecek ekstra siteler.

Google zaten varsayılan hedef (login + ısıtma her zaman yapılır). Buradaki liste
EKSTRA sitelerdir; her profil üretilirken bu siteler gezilip GERÇEK çerezleri toplanır.
Redis'te tutulur (UI'dan yönetilir).
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import orjson

TARGETS_KEY = "targets:sites"
MAX_TARGETS = 50

# SSRF koruması: sunucu tarayıcısının iç servislere/metadata'ya yönlendirilmesini engelle.
_BLOCKED_HOSTNAMES = {"localhost", "ip6-localhost", "metadata.google.internal", "metadata"}


def _ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


async def _target_is_safe(url: str) -> bool:
    """http(s) şeması + kimlik-bilgisiz + host iç/loopback/metadata DEĞİL (DNS çözümlü)."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if p.username or p.password or "@" in (p.netloc or ""):
        return False
    host = (p.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTNAMES:
        return False
    if _ip_blocked(host):  # literal IP (kanonik)
        return False
    # Obfuscated/non-kanonik IP formlarını reddet (octal 0177.., hex 0x7f.., tamsayı
    # 2130706433) — resolver ile Chromium'un yorumu farklı olabilir (parser-differential SSRF).
    labels = host.split(".")
    if (host.startswith("0x") or ".0x" in host
            or any(lab.isdigit() and len(lab) > 1 and lab[0] == "0" for lab in labels)
            or (":" not in host and host.replace(".", "").isdigit() and len(labels) != 4)):
        return False
    try:  # hostname → çöz; herhangi bir IP iç ise reddet (DNS-rebind/SSRF)
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(
            host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP
        )
    except Exception:
        return False  # çözülemeyen host zaten ziyaret edilemez
    return not any(_ip_blocked(info[4][0]) for info in infos)

# Temel hedefler — her zaman havuzda (kullanıcı silemez). Yüksek trafikli, gerçek
# oturum çerezi bırakan siteler; her profil bu havuzdan RASTGELE bir alt küme gezer.
# NOT: Proxy'ler IPv6-only çıkışlı → hedefin AAAA (IPv6) kaydı OLMALI, yoksa bağlantı
# timeout/ProxyError verir (profil başına ~12sn boşa + çerez yok). Aşağıdakiler IPv6-DOĞRULANMIŞ.
# IPv4-only oldukları için ÇIKARILDI: trendyol, hepsiburada, sahibinden, n11 (2026-08 IPv6 testi).
DEFAULT_TARGETS = [
    "https://www.youtube.com",     # IPv6 ✓ (Google — en değerli çerezler)
    "https://tr.wikipedia.org",    # IPv6 ✓
    "https://www.amazon.com.tr",   # IPv6 ✓
]


async def get_targets(redis) -> list[str]:
    if redis is not None:
        try:
            raw = await redis.get(TARGETS_KEY)
            if raw:
                return orjson.loads(raw)
        except Exception:
            pass
    return []


async def get_effective_targets(redis) -> list[str]:
    """Motorun kullanacağı tam havuz = temel siteler + kullanıcının eklediği ekstralar (dedup)."""
    pool = list(DEFAULT_TARGETS)
    for u in await get_targets(redis):
        if u not in pool:
            pool.append(u)
    return pool


async def set_targets(redis, urls: list[str]) -> list[str]:
    clean = []
    for u in urls or []:
        u = (u or "").strip()
        if not u:
            continue
        if "://" not in u:
            u = "https://" + u
        if u in clean:
            continue
        # SSRF: iç/loopback/metadata hedeflerini sessizce ele (yalnızca güvenli olanı sakla).
        if await _target_is_safe(u):
            clean.append(u)
    clean = clean[:MAX_TARGETS]
    if redis is not None:
        await redis.set(TARGETS_KEY, orjson.dumps(clean))
    return clean
