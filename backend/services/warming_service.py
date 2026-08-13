import asyncio
import logging
import random

logger = logging.getLogger("warming_service")


class WarmingService:
    async def warm_session(
        self,
        page,
        keywords: list[str],
        mode: str = "SAFE",
    ) -> dict:
        delays = {
            "SAFE": {"search_min": 3, "search_max": 8, "click_min": 5, "click_max": 15, "search_count_min": 3, "search_count_max": 7},
            "FAST": {"search_min": 1, "search_max": 3, "click_min": 2, "click_max": 5, "search_count_min": 2, "search_count_max": 5},
            "TURBO": {"search_min": 0.5, "search_max": 1.5, "click_min": 0, "click_max": 0, "search_count_min": 1, "search_count_max": 1},
        }
        cfg = delays.get(mode, delays["SAFE"])

        try:
            await page.goto("https://www.google.com.tr", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(1, 3))
        except Exception as e:
            logger.warning(f"Google homepage navigation failed: {e}")
            return {"status": "PARTIAL", "searches_done": 0}

        search_count = random.randint(cfg["search_count_min"], cfg["search_count_max"])
        shuffled = keywords.copy()
        random.shuffle(shuffled)
        selected = shuffled[:search_count]
        searches_done = 0

        for kw in selected:
            try:
                search_input = page.locator('textarea[name="q"], input[name="q"]').first
                # .fill() değeri TEK 'input' event'iyle anında yazar (keydown/keyup YOK) —
                # Google Search'ün tam da ısıttığımız yüzeyinde bilinen otomasyon imzası.
                # Login'deki _human_type gibi tuş-tuş yaz (login ile tutarlı, #17).
                await search_input.click()
                await asyncio.sleep(random.uniform(0.15, 0.4))
                try:
                    await search_input.press_sequentially(kw, delay=random.randint(60, 130))
                except Exception:
                    try:
                        await search_input.type(kw, delay=random.randint(60, 130))
                    except Exception:
                        await search_input.fill(kw)   # en son çare
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await search_input.press("Enter")
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                searches_done += 1

                await asyncio.sleep(random.uniform(cfg["search_min"], cfg["search_max"]))

                if cfg["click_max"] > 0 and random.random() < 0.4:
                    results = await page.locator("h3").all()
                    if results:
                        for r in results[:3]:
                            if await r.is_visible():
                                try:
                                    await r.hover()               # tıklamadan önce imleç hedefe gitsin
                                    await asyncio.sleep(random.uniform(0.2, 0.6))
                                except Exception:
                                    pass
                                await r.click()
                                break
                        await asyncio.sleep(random.uniform(cfg["click_min"], cfg["click_max"]))
                        await page.go_back(wait_until="domcontentloaded", timeout=10000)
            except Exception as e:
                logger.debug(f"Search step failed for '{kw}': {e}")
                continue

        if mode != "TURBO":
            try:
                await page.goto("https://accounts.google.com/myaccount", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(random.uniform(2, 4))
            except Exception:
                pass

        return {"status": "COMPLETE", "searches_done": searches_done}
