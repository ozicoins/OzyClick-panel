import asyncio
import math
import random


class MouseSimulator:
    async def bezier_move(self, page, start_x: int, start_y: int, end_x: int, end_y: int, steps: int = 20):
        cp1_x = start_x + random.randint(-50, 50)
        cp1_y = start_y + random.randint(-50, 50)
        cp2_x = end_x + random.randint(-50, 50)
        cp2_y = end_y + random.randint(-50, 50)

        for i in range(steps + 1):
            t = i / steps
            x = (1-t)**3 * start_x + 3*(1-t)**2*t * cp1_x + 3*(1-t)*t**2 * cp2_x + t**3 * end_x
            y = (1-t)**3 * start_y + 3*(1-t)**2*t * cp1_y + 3*(1-t)*t**2 * cp2_y + t**3 * end_y
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.005, 0.02))

    async def human_click(self, page, x: int, y: int):
        current = await page.evaluate("() => ({x: 0, y: 0})")
        await self.bezier_move(page, current["x"], current["y"], x, y)
        await asyncio.sleep(random.uniform(0.05, 0.15))
        await page.mouse.click(x, y)

    async def human_type(self, page, selector: str, text: str, typo_chance: float = 0.03):
        element = page.locator(selector)
        await element.click()
        await asyncio.sleep(random.uniform(0.2, 0.5))

        for char in text:
            if random.random() < typo_chance:
                wrong = chr(ord(char) + random.choice([-1, 1]))
                await page.keyboard.type(wrong, delay=random.randint(50, 150))
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.05, 0.15))

            delay = random.randint(30, 120)
            await page.keyboard.type(char, delay=delay)

    async def natural_scroll(self, page, scrolls: int = 3):
        for _ in range(scrolls):
            delta = random.randint(100, 400)
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(random.uniform(0.5, 2))
