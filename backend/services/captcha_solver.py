import asyncio
import logging

import httpx

logger = logging.getLogger("captcha_solver")


# ⚠️ ÖLÜ KOD UYARISI (#20): Bu sınıf app kodunda HİÇBİR yerden çağrılmıyor. farming_engine
# CAPTCHA görürse yalnızca loglar ve False döner (graceful — çöküş yok). Wire edilmesi
# durumunda Google için ÇALIŞMAZ: (a) sitekey'i sadece klasik .g-recaptcha[data-sitekey]'ten
# okur — Google'ın invisible/enterprise reCAPTCHA'sında bu element YOK → site_key='' → False;
# (b) form.submit() reCAPTCHA JS callback'ini atlar, token tüketilmez; (c) _solve_recaptcha
# 2captcha hata kodunu (ZERO_BALANCE/KEY_DOES_NOT_EXIST) loglamaz. Google login'de kullanmadan
# önce: enterprise/invisible akışıyla sitekey al, callback tetikle, hata kodunu logla.
class CaptchaSolver:
    def __init__(self, api_key: str = "", service: str = "2captcha"):
        self._api_key = api_key
        self._service = service

    async def solve(self, page) -> bool:
        if not self._api_key:
            logger.warning("CAPTCHA detected but no API key configured — manual solve required")
            return False

        try:
            site_key = await page.evaluate(
                "() => document.querySelector('.g-recaptcha')?.getAttribute('data-sitekey') || ''"
            )
            if not site_key:
                return False

            token = await self._solve_recaptcha(site_key, page.url)
            if not token:
                return False

            await page.evaluate(
                "(t) => { const el = document.getElementById('g-recaptcha-response');"
                " if (el) el.value = t; }",
                token,
            )
            await page.evaluate("() => { document.querySelector('form')?.submit(); }")
            await asyncio.sleep(3)
            return True

        except Exception as e:
            logger.error(f"CAPTCHA solve failed: {e}")
            return False

    async def _solve_recaptcha(self, site_key: str, page_url: str) -> str | None:
        if self._service != "2captcha":
            return None

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                "https://2captcha.com/in.php",
                data={
                    "key": self._api_key,
                    "method": "userrecaptcha",
                    "googlekey": site_key,
                    "pageurl": page_url,
                    "json": 1,
                },
            )
            data = r.json()
            if data.get("status") != 1:
                return None

            task_id = data["request"]
            for _ in range(60):
                await asyncio.sleep(5)
                r = await client.get(
                    "https://2captcha.com/res.php",
                    params={"key": self._api_key, "action": "get", "id": task_id, "json": 1},
                )
                result = r.json()
                if result.get("status") == 1:
                    return result["request"]
                if result.get("request") == "ERROR_CAPTCHA_UNSOLVABLE":
                    return None

        return None
