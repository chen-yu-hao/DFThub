import asyncio
import os
import sys

from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from verify_replica import Api

BASE = os.getenv("BASE_URL", "http://127.0.0.1:18293").rstrip("/")


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 729, "height": 977})
        await context.add_init_script("localStorage.setItem('auth_token','test-session')")
        api = Api()
        await context.route("**/*", api.route)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(BASE + "/workspace/", wait_until="networkidle")
        await expect(page.locator(".d-title h3")).to_have_text("demo_failed")
        assert not errors, errors
        print("PASS authenticated Workspace hydration")
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
