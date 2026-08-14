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
    """Sayfada GÖRÜNÜR inline resim-captcha var mı (gizli template değil — false-positive önler)."""
    try:
        img = page.locator(_CAPTCHA_IMG)
        if await img.count() == 0:
            return False
        return await img.first.is_visible()
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
            return ("none", "")               # ← captcha elementi hiç yok
        # KRİTİK: DOM'da olması YETMEZ — GÖRÜNÜR olmalı. Google login sayfasında img#captchaimg
        # çoğu zaman GİZLİ template olarak DURUR (aktif captcha DEĞİL). Sadece 'var mı' bakarsak
        # HER login'de 'captcha var' sanıp boşa uğraşır → üretim durur. Görünür değilse = captcha yok.
        if not await img.first.is_visible():
            return ("none", "")
    except Exception:
        return ("none", "")

    if not api_key:
        await _say("🧩 CAPTCHA çıktı ama CapSolver anahtarı yok — çözülemiyor (Ayarlar'dan ekleyin).", "WARNING")
        return ("nokey", "")

    await _say("🧩 CAPTCHA tespit edildi — resim alınıp CapSolver'a gönderiliyor...", "INFO")
    try:
        # 1) CAPTCHA GÖRÜNTÜSÜNÜ AL — screenshot GÜVENİLMEZ (30sn takılıyordu). Öncelik:
        #    (a) img.src bir data:URI ise → doğrudan base64 çöz (fetch/screenshot yok).
        #    (b) img.src bir URL ise → OTURUM ÇEREZLERİYLE fetch et (page.request context'in cookie'sini kullanır).
        #    (c) son çare → element screenshot (kısa timeout).
        b64 = None
        src = None
        try:
            src = await img.first.get_attribute("src")
        except Exception:
            src = None
        try:
            if src and src.startswith("data:"):
                b64 = src.split(",", 1)[1] if "," in src else None
                await _say("🧩 captcha resmi data-URI'den alındı", "INFO")
            elif src:
                from urllib.parse import urljoin
                if src.startswith("//"):
                    src = "https:" + src
                elif not src.startswith(("http://", "https://")):
                    src = urljoin(page.url, src)   # kök-göreli VE düz-göreli src → mutlak URL
                try:
                    resp = await page.request.get(src, timeout=8000)
                    body = await resp.body()
                    if body:
                        b64 = base64.b64encode(body).decode()
                        await _say(f"🧩 captcha resmi fetch edildi ({len(body)} bayt)", "INFO")
                except Exception as e:
                    await _say(f"🧩 fetch olmadı ({str(e)[:40]}) → screenshot deneniyor", "WARNING")
        except Exception:
            pass
        if not b64:   # (c) son çare: screenshot
            try:
                el = img.first
                await el.wait_for(state="visible", timeout=3000)
                png = await el.screenshot(timeout=5000)
                b64 = base64.b64encode(png).decode()
                await _say("🧩 captcha resmi screenshot ile alındı", "INFO")
            except Exception:
                return ("failed", "captcha görüntüsü alınamadı (src+screenshot başarısız)")
        if not b64:
            return ("failed", "captcha görüntüsü boş")

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

        # 4) cevabı girdi alanına yaz (birden fazla olası seçici)
        filled = False
        for sel in (_CAPTCHA_INPUT, "#ca", "input[name='captcha']", "input[type='text']:not([name='identifier'])"):
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0:
                    await inp.click()
                    await inp.fill(answer)
                    filled = True
                    break
            except Exception:
                continue
        if not filled:
            return ("failed", "captcha girdi alanı bulunamadı (input[name=ca]/#ca)")
        await _say(f"🧩 CAPTCHA çözüldü ve girildi: '{answer}' ({len(answer)} karakter) — Next'e basılacak.", "INFO")
        return ("solved", answer)

    except Exception as e:
        await _say(f"🧩 CAPTCHA çözüm hatası (atlandı): {e}", "ERROR")
        return ("failed", str(e))
