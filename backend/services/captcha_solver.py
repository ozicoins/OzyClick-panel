"""Google login IMAGE-captcha çözücü (2captcha, method=base64).

Google giriş akışında (identifier/parola adımı) şüpheli trafik görürse INLINE bir RESİM
captcha gösterir: <img id="captchaimg"> + <input name="ca">. Bu reCAPTCHA DEĞİLDİR — okunacak
bir görüntüdür. Çözüm: img elementinin ekran görüntüsünü al → base64 → 2captcha in.php
(method=base64) → cevabı res.php'den al → input[name=ca]'ya yaz.

TASARIM (bozulmama garantisi):
- solve_image_captcha() captcha YOKSA anında ("none","") döner → normal akış hiç etkilenmez.
- API anahtarı YOKSA ("nokey","") döner → eski davranış (çözemez, login sonra başarısız olur).
- Her hata try/except ile yutulur → ASLA login akışına exception fırlatmaz.
2captcha en ucuz + normal-captcha'da en yüksek başarı oranlı servis (kullanıcı tercihi).
"""
import asyncio
import base64
import logging

import httpx

logger = logging.getLogger("captcha_solver")

_CAPTCHA_IMG = "img#captchaimg"
_CAPTCHA_INPUT = "input[name='ca']"


async def captcha_present(page) -> bool:
    """Sayfada inline resim-captcha var mı (hızlı kontrol, no-op yol için)."""
    try:
        return await page.locator(_CAPTCHA_IMG).count() > 0
    except Exception:
        return False


async def solve_image_captcha(page, api_key: str, service: str = "2captcha", log=None) -> tuple[str, str]:
    """Sayfadaki resim-captcha'yı çöz + input[name=ca]'ya yaz.
    Dönüş (status, detay):
      "none"    → captcha yok, hiçbir şey yapılmadı (normal akış)
      "solved"  → çözüldü ve dolduruldu
      "nokey"   → captcha var ama API anahtarı yok
      "failed"  → captcha var, anahtar var ama çözülemedi (sebep detayda)
    """
    async def _say(msg, level="INFO"):
        if log:
            try:
                await log(msg, level)
            except Exception:
                pass

    try:
        img = page.locator(_CAPTCHA_IMG)
        if await img.count() == 0:
            return ("none", "")               # ← 99% yol: captcha yok, anında çık
    except Exception:
        return ("none", "")

    if not api_key:
        await _say("🧩 CAPTCHA çıktı ama 2captcha anahtarı yok — çözülemiyor (Ayarlar'dan ekleyin).", "WARNING")
        return ("nokey", "")

    if service != "2captcha":
        return ("failed", f"desteklenmeyen servis: {service}")

    try:
        # 1) captcha görüntüsünün ekran görüntüsü (cookie/URL fetch'e gerek yok)
        png = await img.first.screenshot(timeout=8000)
        b64 = base64.b64encode(png).decode()

        async with httpx.AsyncClient(timeout=60) as client:
            # 2) 2captcha'ya gönder (method=base64 → normal resim captcha)
            r = await client.post(
                "https://2captcha.com/in.php",
                data={"key": api_key, "method": "base64", "body": b64,
                      "regsense": 0, "numeric": 0, "min_len": 4, "max_len": 8, "json": 1},
            )
            data = r.json()
            if data.get("status") != 1:
                err = data.get("request", "bilinmeyen")
                await _say(f"🧩 CAPTCHA gönderilemedi (2captcha: {err})", "ERROR")
                return ("failed", str(err))
            task_id = data["request"]

            # 3) cevabı bekle (max ~60sn)
            answer = None
            for _ in range(20):
                await asyncio.sleep(3)
                rr = await client.get(
                    "https://2captcha.com/res.php",
                    params={"key": api_key, "action": "get", "id": task_id, "json": 1},
                )
                res = rr.json()
                if res.get("status") == 1:
                    answer = (res.get("request") or "").strip()
                    break
                if res.get("request") not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
                    await _say(f"🧩 CAPTCHA çözülemedi (2captcha: {res.get('request')})", "ERROR")
                    return ("failed", str(res.get("request")))

        if not answer:
            return ("failed", "zaman aşımı (cevap gelmedi)")

        # 4) cevabı input[name=ca]'ya yaz
        inp = page.locator(_CAPTCHA_INPUT).first
        if await inp.count() == 0:
            return ("failed", "captcha girdi alanı (input[name=ca]) bulunamadı")
        await inp.click()
        await inp.fill(answer)
        await _say(f"🧩 CAPTCHA çözüldü ve girildi ({len(answer)} karakter).", "INFO")
        return ("solved", answer)

    except Exception as e:
        await _say(f"🧩 CAPTCHA çözüm hatası (atlandı): {e}", "ERROR")
        return ("failed", str(e))
