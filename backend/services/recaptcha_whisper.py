import os
import random
import tempfile
import asyncio
import logging
import httpx
from typing import Optional
from playwright.async_api import Page

logger = logging.getLogger("recaptcha_whisper")
_whisper_model = None

def get_whisper_model():
    """
    Yerel ve çevrimdışı Whisper AI modelini yükler (CPU int8 optimize).
    İlk çağrılışta tiny.en modelini hafızaya alır, sonraki çağrılarda anında kullanır.
    """
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            logger.info("[Whisper AI] Yerel model yükleniyor (Çevrimdışı / %100 Ücretsiz)...")
            _whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
            logger.info("[Whisper AI] Model başarıyla hazırlandı!")
        except Exception as e:
            logger.error(f"[Whisper AI] Model yükleme hatası: {e}")
            _whisper_model = None
    return _whisper_model


class RecaptchaWhisperSolver:
    """
    Playwright için Yerel Whisper AI Destekli Google reCAPTCHA v2 / Audio Çözücüsü.
    Harici API gerektirmez; tarayıcının kendi IP'si üzerinden ses dosyasını çözer.
    """

    @staticmethod
    async def solve(page: Page, max_wait: int = 45, log=None) -> bool:
        """
        Mevcut sayfadaki Google reCAPTCHA bulmacasını tespit eder ve Whisper ile çözer.
        """
        async def _say(msg, level="INFO"):
            if log:
                try:
                    await log(f"🧩 [Whisper Solver] {msg}", level)
                except Exception:
                    pass
            logger.info(f"[Whisper Solver] {msg}")

        await _say("reCAPTCHA tespiti yapılıyor...", "INFO")

        anchor_frame = page.frame_locator("iframe[src*='/anchor'], iframe[name^='a-']").first
        challenge_frame = page.frame_locator("iframe[src*='/bframe'], iframe[name^='c-']").first

        # 1. Checkbox tıkla
        try:
            cb = anchor_frame.locator("#recaptcha-anchor, .recaptcha-checkbox").first
            if await cb.count() > 0:
                await _say("'Ben robot değilim' kutucuğuna tıklanıyor...")
                await cb.click(timeout=5000)
                await asyncio.sleep(2.0)
        except Exception as e:
            logger.debug(f"Checkbox tıklama uyarısı: {e}")

        # Checkbox doğrudan onaylandı mı?
        try:
            checked = await anchor_frame.locator('.recaptcha-checkbox[aria-checked="true"]').count()
            if checked > 0:
                await _say("TEBRİKLER: reCAPTCHA doğrudan onaylandı (Yeşil Tik)!", "INFO")
                return True
        except Exception:
            pass

        # 2. Sesli Doğrulama (Kulaklık) butonuna tıkla
        try:
            audio_btn = challenge_frame.locator("#recaptcha-audio-button").first
            if await audio_btn.count() > 0:
                await _say("Sesli doğrulama (Kulaklık) butonuna tıklanıyor...")
                await audio_btn.click(timeout=4000)
                await asyncio.sleep(2.5)
        except Exception as e:
            logger.debug(f"Audio buton uyarısı: {e}")

        # 3. Whisper ile Sesi Çöz ve Doğrula
        start_time = asyncio.get_event_loop().time()
        last_url = None

        while asyncio.get_event_loop().time() - start_time < max_wait:
            # Checkbox kontrolü
            try:
                checked = await anchor_frame.locator('.recaptcha-checkbox[aria-checked="true"]').count()
                if checked > 0:
                    await _say("BAŞARILI: reCAPTCHA doğrulaması tamamlandı!", "INFO")
                    submit_btn = page.locator("input[type='submit'], button[type='submit']").first
                    if await submit_btn.count() > 0 and "/sorry/" in page.url:
                        await submit_btn.click()
                    await asyncio.sleep(1.5)
                    return True
            except Exception:
                pass

            # Google sesli meydan okumayı kilitledi mi?
            try:
                doscaptcha = challenge_frame.locator(".rc-doscaptcha-header-text, .rc-doscaptcha-body-text, .rc-doscaptcha-body").first
                if await doscaptcha.count() > 0:
                    msg = await doscaptcha.inner_text()
                    await _say(f"Google sesli meydan okumayı kilitledi ({msg.strip()}). IP değişimi gerekebilir.", "ERROR")
                    return False
            except Exception:
                pass

            # Audio MP3 dosyasını bul
            try:
                audio_input = challenge_frame.locator("#audio-response").first
                if await audio_input.count() > 0:
                    audio_src = None
                    try:
                        audio_elem = challenge_frame.locator("#audio-source").first
                        if await audio_elem.count() > 0:
                            audio_src = await audio_elem.get_attribute("src")
                    except Exception:
                        pass

                    if not audio_src:
                        try:
                            dl_link = challenge_frame.locator(".rc-audiochallenge-tdownload-link").first
                            if await dl_link.count() > 0:
                                audio_src = await dl_link.get_attribute("href")
                        except Exception:
                            pass

                    if audio_src and audio_src.startswith("http") and audio_src != last_url:
                        last_url = audio_src
                        await _say(f"Ses dosyası indiriliyor: {audio_src[:45]}...")

                        async with httpx.AsyncClient(timeout=15) as client:
                            resp = await client.get(audio_src)
                            if resp.status_code == 200:
                                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_audio:
                                    tmp_audio.write(resp.content)
                                    tmp_path = tmp_audio.name

                                try:
                                    model = get_whisper_model()
                                    if model:
                                        await _say("Whisper AI sesi metne döküyor...")
                                        t_start = asyncio.get_event_loop().time()
                                        segments, _ = model.transcribe(tmp_path, language="en")
                                        text_result = " ".join([seg.text.strip() for seg in segments]).strip()
                                        t_dur = round(asyncio.get_event_loop().time() - t_start, 2)
                                        await _say(f"Tanımlanan Metin: '{text_result}' ({t_dur}sn)")

                                        await audio_input.click()
                                        await asyncio.sleep(random.uniform(0.25, 0.45))

                                        # İnsansı Tuş Vuruşu
                                        for ch in text_result:
                                            await audio_input.type(ch, delay=random.randint(60, 115))
                                            if ch == " ":
                                                await asyncio.sleep(random.uniform(0.06, 0.14))

                                        await asyncio.sleep(random.uniform(0.5, 0.8))

                                        verify_btn = challenge_frame.locator("#recaptcha-verify-button").first
                                        if await verify_btn.count() > 0:
                                            await _say("'Doğrula' butonuna tıklandı...")
                                            await verify_btn.click()
                                            await asyncio.sleep(3.0)
                                finally:
                                    if os.path.exists(tmp_path):
                                        os.remove(tmp_path)
            except Exception as loop_err:
                logger.debug(f"Audio loop step err: {loop_err}")

            await asyncio.sleep(1.2)

        try:
            checked = await anchor_frame.locator('.recaptcha-checkbox[aria-checked="true"]').count()
            return checked > 0
        except Exception:
            return False
