"""Google login IMAGE-captcha çözücü (CapSolver, ImageToTextTask).

Google giriş akışında (identifier/parola adımı) şüpheli trafik görürse INLINE bir RESİM
captcha gösterir: <img id="captchaimg"> + <input name="ca">. Bu reCAPTCHA DEĞİLDİR — okunacak
bir görüntüdür. Çözüm: img elementinin ekran görüntüsünü al → base64 → CapSolver createTask
(ImageToTextTask) → cevabı al → input[name=ca]'ya yaz.

MARKA: CapSolver (tek marka — clicker paneli de CapSolver/reCAPTCHA v2 kullanır). Aynı anahtar,
tek bakiye. CapSolver ImageToTextTask cevabı genelde createTask yanıtında ANINDA döner (reCAPTCHA
gibi poll gerektirmez); yine de taskId dönerse getTaskResult ile beklenir.

TASARIM (bozulmama garantisi):
- solve_image_captcha() captcha YOKSA anında ("none","") döner → normal akış hiç etkilenmez.
- API anahtarı YOKSA ("nokey","") döner → eski davranış (çözemez, login sonra başarısız olur).
- Her hata try/except ile yutulur → ASLA login akışına exception fırlatmaz.
"""
import asyncio
import base64
import logging

import httpx

logger = logging.getLogger("captcha_solver")

_CAPTCHA_IMG = "img#captchaimg"
_CAPTCHA_INPUT = "input[name='ca']"

_CREATE_URL = "https://api.capsolver.com/createTask"
_RESULT_URL = "https://api.capsolver.com/getTaskResult"


async def captcha_present(page) -> bool:
    """Sayfada inline resim-captcha var mı (hızlı kontrol, no-op yol için)."""
    try:
        return await page.locator(_CAPTCHA_IMG).count() > 0
    except Exception:
        return False


async def solve_image_captcha(page, api_key: str, service: str = "capsolver", log=None) -> tuple[str, str]:
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
        await _say("🧩 CAPTCHA çıktı ama CapSolver anahtarı yok — çözülemiyor (Ayarlar'dan ekleyin).", "WARNING")
        return ("nokey", "")

    try:
        # 1) captcha GÖRÜNÜR mü — değilse/yavaşsa HIZLI vazgeç (login worker'ını 30sn kilitleme).
        el = img.first
        try:
            await el.wait_for(state="visible", timeout=3000)
        except Exception:
            return ("failed", "captcha görüntüsü 3sn'de görünmedi")
        png = await el.screenshot(timeout=5000)   # kısa: takılırsa çöz(e)me, worker'ı bloklama
        b64 = base64.b64encode(png).decode()

        async with httpx.AsyncClient(timeout=60) as client:
            # 2) CapSolver'a gönder (ImageToTextTask → normal resim captcha, module=common)
            r = await client.post(_CREATE_URL, json={
                "clientKey": api_key,
                "task": {"type": "ImageToTextTask", "module": "common", "body": b64},
            })
            data = r.json()
            if data.get("errorId"):
                err = data.get("errorDescription") or data.get("errorCode") or "bilinmeyen"
                await _say(f"🧩 CAPTCHA gönderilemedi (CapSolver: {err})", "ERROR")
                return ("failed", str(err))

            # 3a) ImageToTextTask genelde ANINDA çözülür (createTask yanıtında solution var)
            answer = ((data.get("solution") or {}).get("text") or "").strip()

            # 3b) taskId döndüyse getTaskResult ile bekle (max ~60sn)
            if not answer and data.get("taskId"):
                task_id = data["taskId"]
                for _ in range(20):
                    await asyncio.sleep(3)
                    rr = await client.post(_RESULT_URL, json={"clientKey": api_key, "taskId": task_id})
                    res = rr.json()
                    if res.get("errorId"):
                        await _say(f"🧩 CAPTCHA çözülemedi (CapSolver: {res.get('errorDescription')})", "ERROR")
                        return ("failed", str(res.get("errorDescription")))
                    if res.get("status") == "ready":
                        answer = ((res.get("solution") or {}).get("text") or "").strip()
                        break

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
