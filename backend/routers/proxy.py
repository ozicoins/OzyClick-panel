import asyncio
import time

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_validator
from typing import Literal, Optional

from auth import get_current_user
from services.proxy_config import (
    load_proxy_settings, save_proxy_settings, public_view, rotate_key, QUALITIES, mask_proxy,
)
from services.proxy_rotator import build_scrapingbee_proxy

router = APIRouter()

# api64 = dual-stack (IPv4 VE IPv6) → IPv6-only proxy'ler de erişebilir (api.ipify IPv4-only idi).
_TEST_URL = "https://api64.ipify.org?format=json"  # çıkış IP'sini döndürür
_TEST_TIMEOUT = 9.0


async def _check_proxy(proxy_arg) -> dict:
    """Bir proxy üzerinden çıkış IP'si + gecikme ölç (canlı mı?)."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(proxy=proxy_arg, timeout=_TEST_TIMEOUT,
                                     verify=False, follow_redirects=True) as c:
            r = await c.get(_TEST_URL)
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code == 200:
            try:
                ip = r.json().get("ip", "")
            except Exception:
                ip = (r.text or "")[:45]
            return {"alive": True, "latency_ms": ms, "exit_ip": ip, "error": ""}
        return {"alive": False, "latency_ms": ms, "exit_ip": "", "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"alive": False, "latency_ms": 0, "exit_ip": "",
                "error": (type(e).__name__ + ": " + str(e))[:80]}


class ProxySettingsPatch(BaseModel):
    provider: Optional[Literal["csv", "scrapingbee", "list"]] = None
    country: Optional[str] = None
    render_js: Optional[bool] = None
    quality: Optional[Literal["classic", "premium", "stealth"]] = None
    # ScrapingBee çok-anahtar işlemleri (yalnızca yazılır)
    add_api_keys: Optional[list[str]] = None
    set_api_keys: Optional[list[str]] = None
    remove_api_key_index: Optional[int] = None
    active_index: Optional[int] = None
    # Proxy havuzu (IPv6 destekli) işlemleri
    add_proxies: Optional[list[str]] = None
    set_proxies: Optional[list[str]] = None
    remove_proxy_index: Optional[int] = None

    @field_validator("country")
    @classmethod
    def _validate_country(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().lower()
        if not (len(v) == 2 and v.isalpha()):
            raise ValueError("Ülke kodu 2 harfli ISO olmalı (tr, us, gb...)")
        return v

    @field_validator("add_api_keys", "set_api_keys")
    @classmethod
    def _clean_keys(cls, v):
        if v is None:
            return v
        return [k.strip() for k in v if k and k.strip()][:50]  # üst sınır


@router.get("/proxy-settings")
async def get_proxy_settings(request: Request, _user: dict = Depends(get_current_user)):
    return public_view(await load_proxy_settings(request.app.state.redis))


@router.put("/proxy-settings")
async def put_proxy_settings(
    patch: ProxySettingsPatch,
    request: Request,
    _user: dict = Depends(get_current_user),
):
    return await save_proxy_settings(request.app.state.redis, patch.model_dump(exclude_none=True))


@router.post("/proxy-settings/rotate")
async def rotate_proxy_key(request: Request, _user: dict = Depends(get_current_user)):
    """Aktif anahtarı bir sonrakine çevir (biri tükendiğinde failover)."""
    return await rotate_key(request.app.state.redis)


class ProxyTestPatch(BaseModel):
    index: Optional[int] = None  # verilirse SADECE o proxy/anahtar; yoksa hepsi


@router.post("/proxy-settings/test")
async def test_proxies(
    patch: ProxyTestPatch,
    request: Request,
    _user: dict = Depends(get_current_user),
):
    """Aktif sağlayıcının proxy'lerini canlılık için test eder (çıkış IP + gecikme).
    list → havuzdaki her proxy; scrapingbee → her API anahtarı (dikkat: kredi harcar);
    csv → hesap-başı proxy olduğu için test edilmez."""
    cfg = await load_proxy_settings(request.app.state.redis)
    provider = cfg.get("provider", "csv")
    results: list[dict] = []

    if provider == "list":
        proxies = list(cfg.get("proxies") or [])
        idxs = [patch.index] if patch.index is not None else list(range(len(proxies)))
        sem = asyncio.Semaphore(10)

        async def _one(i: int):
            if i < 0 or i >= len(proxies):
                return None
            async with sem:
                res = await _check_proxy(proxies[i])
            res["index"] = i
            res["proxy"] = mask_proxy(proxies[i])
            return res

        results = [r for r in await asyncio.gather(*[_one(i) for i in idxs]) if r]

    elif provider == "scrapingbee":
        keys = list(cfg.get("api_keys") or [])
        idxs = [patch.index] if patch.index is not None else list(range(len(keys)))
        for i in idxs:
            if i < 0 or i >= len(keys):
                continue
            sb = build_scrapingbee_proxy(cfg, keys[i])
            if not sb:
                continue
            proxy_arg = httpx.Proxy(url=sb["server"], auth=(sb.get("username", ""), sb.get("password", "")))
            res = await _check_proxy(proxy_arg)
            res["index"] = i
            res["proxy"] = f"ScrapingBee #{i + 1} ({(keys[i] or '')[:4]}…)"
            results.append(res)

    return {"provider": provider, "results": results}
