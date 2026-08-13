import asyncio
import logging
import time

logger = logging.getLogger("totp_handler")

# TOTP replay-kapısı: aynı hesaba (secret) aynı 30sn penceresinde iki login AYNI kodu
# kullanırsa Google 2.'yi "kod zaten kullanıldı" diye reddeder. Her secret için pencereyi
# rezerve edip, aynı pencere ikinci kez istenirse bir sonraki pencereye kadar bekletiriz.
_totp_locks: dict[str, asyncio.Lock] = {}
_totp_last_window: dict[str, int] = {}


async def _reserve_totp_code(secret_clean: str):
    """Bu secret için TAZE bir 30sn penceresinin kodunu rezerve eder (replay önlenir).
    Gerekirse bir sonraki pencereye kadar bekler → aynı hesaptan çok login mümkün."""
    import pyotp
    lock = _totp_locks.setdefault(secret_clean, asyncio.Lock())
    async with lock:
        win = int(time.time() // 30)
        last = _totp_last_window.get(secret_clean, -1)
        if win <= last:
            wait = (last + 1) * 30 - time.time() + 0.4
            if wait > 0:
                await asyncio.sleep(wait)
            win = int(time.time() // 30)
        _totp_last_window[secret_clean] = win
        return pyotp.TOTP(secret_clean).at(win * 30)


class TOTPHandler:
    async def handle_2fa(self, page, totp_secret: str = "") -> tuple[bool, str]:
        """Döner: (başarılı, sebep). Sebep panelde gösterilir → gerçek 2FA durumu görünür."""
        if not totp_secret:
            return False, f"TOTP secret girilmemiş (URL={page.url.split('?')[0]})"
        return await self._enter_totp(page, totp_secret)

    async def _visible(self, locator, timeout_ms: int) -> bool:
        try:
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    async def _click_first(self, page, selectors: list[str]) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=4000)
                    return True
            except Exception:
                continue
        return False

    async def _enter_totp(self, page, secret: str) -> tuple[bool, str]:
        import pyotp
        clean = secret.replace(" ", "").strip().upper()
        try:
            pyotp.TOTP(clean).now()
        except Exception as e:
            return False, f"TOTP secret GEÇERSİZ (base32 değil): {str(e)[:50]}"

        # TOTP kutusu doğrudan var mı?
        inp = page.locator('input[name="totpPin"], input[type="tel"]').first
        if not await self._visible(inp, 4000):
            # 'Başka bir yol dene' → Authenticator seçeneğine git.
            await self._click_first(page, ["text=/try another way|başka bir yol|başka yol dene/i"])
            await asyncio.sleep(1.5)
            await self._click_first(page, [
                "text=/google authenticator/i",
                "text=/authenticator/i",
                "text=/kimlik doğrulama uygulaması/i",
                "text=/doğrulama kodu (al|gir|iste)/i",
                "text=/get a (verification )?code/i",
            ])
            await asyncio.sleep(2)
            inp = page.locator('input[name="totpPin"], input[type="tel"]').first

        if not await self._visible(inp, 5000):
            return False, (f"TOTP kutusu YOK → hesap muhtemelen CİHAZ-ONAYLI 2FA (telefon 'evet'i) "
                           f"veya farklı doğrulama istiyor; otomatikleşmez (URL={page.url.split('?')[0]})")

        # TAZE + REZERVE edilmiş kod al (aynı hesaba paralel login'lerde replay olmaz).
        try:
            code = await _reserve_totp_code(clean)
            await inp.click()
            try:
                await inp.press_sequentially(code, delay=90)
            except Exception:
                await inp.fill(code)
            await asyncio.sleep(0.5)
            # 'Sonraki' (Türkçe) DAHİL submit butonları — locale tr-TR olduğu için kritik.
            if not await self._click_first(page, [
                "#totpNext button", "#totpNext",
                'button:has-text("Sonraki")', 'button:has-text("Next")',
                'button:has-text("İleri")', 'button:has-text("Doğrula")', 'button:has-text("Verify")',
            ]):
                await inp.press("Enter")
        except Exception as e:
            return False, f"TOTP kodu girilemedi: {str(e)[:60]}"

        # Yönlendirme birkaç sn sürebilir → poll et; ama YANLIŞ KOD hatası çıkarsa HIZLI fail
        # (12sn boşuna bekleme), FARKLI challenge'a geçerse "ek adım" de.
        for _ in range(12):
            await asyncio.sleep(0.8)
            u = page.url.lower()
            if ("challenge" not in u) and ("totp" not in u):
                return True, ""  # BAŞARILI
            # Farklı bir doğrulama adımına geçtiyse (totp değil) → secret DOĞRU ama ek adım var
            if ("challenge" in u) and ("totp" not in u):
                return False, (f"TOTP GEÇTİ ama Google EK DOĞRULAMA istedi (kurtarma/onay) → bu hesap "
                               f"otomatik tamamlanamaz (URL={page.url.split('?')[0]})")
            # Yanlış-kod hata mesajı çıktı mı → secret yanlış, hemen bitir
            try:
                if await page.locator(
                    "text=/yanlış kod|kod hatalı|geçersiz kod|wrong code|incorrect code|tekrar deneyin|try again/i"
                ).count() > 0:
                    return False, (f"TOTP KODU REDDEDİLDİ → bu hesabın secret'ı YANLIŞ "
                                   f"(authenticator'daki kodla aynı olmalı; yeniden gir)")
            except Exception:
                pass
        u = page.url.lower()
        if "rejected" in u or "disabled" in u:
            return False, f"TOTP sonrası Google oturumu REDDETTİ (aşırı deneme?) (URL={page.url.split('?')[0]})"
        return False, (f"TOTP kodu girildi ama challenge'dan çıkılmadı → secret yanlış olabilir "
                       f"(URL={page.url.split('?')[0]})")
