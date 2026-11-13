"""Local single-user mode: no sign-in anywhere, the session starts by itself; APIs are mocked."""
import asyncio

from playwright.async_api import async_playwright, expect
from verify_replica import BASE, Api, wait_for

ROOT = BASE.rsplit("/workspace", 1)[0]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
        # A token left over from an earlier signed-in session is replaced.
        await context.add_init_script("if (!sessionStorage.getItem('seeded')) { localStorage.setItem('auth_token','stale'); sessionStorage.setItem('seeded','1'); }")
        api = Api(mail=False, local=True)
        await context.route("**/*", api.route)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        for path in ("/workspace/", "/analyze/", "/energy/"):
            await page.goto(ROOT + path, wait_until="networkidle")
            await expect(page.get_by_role("button", name="Sign in")).to_have_count(0)
            await expect(page.get_by_text("Sign in to", exact=False)).to_have_count(0)
        await page.goto(BASE + "/", wait_until="networkidle")
        await expect(page.locator(".d-title h3")).to_have_text("demo_failed")
        assert await page.evaluate("localStorage.getItem('auth_token')") == "local-session"
        assert api.local_sessions >= 1 and api.logins == [], (api.local_sessions, api.logins)

        await page.get_by_role("button", name="Open account menu").click()
        menu = page.get_by_role("menu")
        await expect(menu).to_contain_text("Local mode · this computer only")
        await expect(menu.get_by_role("menuitem", name="Sign out")).to_have_count(0)
        await page.keyboard.press("Escape")
        await expect(page.locator('dialog[aria-labelledby="authTitle"]')).to_have_count(0)

        # New job opens directly; with mail off there is no e-mail field.
        await page.keyboard.press("n")
        dialog = page.get_by_role("dialog", name="New job", exact=True)
        await expect(dialog).to_be_visible()
        await expect(dialog.locator("#fEmail")).to_have_count(0)
        await dialog.locator("#fTgz").set_input_files({"name": "Demo.tgz", "mimeType": "application/gzip", "buffer": b"test"})
        await dialog.locator("#fRef").set_input_files({"name": "Demo.ref", "mimeType": "text/plain", "buffer": b"0.0"})
        await dialog.get_by_role("button", name="Submit job", exact=True).click()
        await wait_for(lambda: len(api.submits) == 1)
        assert "email" not in api.submits[0], api.submits[0]

        assert not errors, errors
        # The shared mock has no Analyze fixtures; only sign-in prompts matter there.
        unexpected = [item for item in api.unexpected if not item.endswith("/api_dft/analysis")]
        assert not unexpected, unexpected
        await recovery(browser)
        await browser.close()
    print("PASS local mode")


async def recovery(browser):
    """A failed /features or /local-session read offers Reload, never Sign in."""
    for failing, heading in (("features_fail", "DFThub could not be reached"),
                             ("local_session_fail", "The local session could not start")):
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
        api = Api(mail=False, local=True)
        setattr(api, failing, True)
        await context.route("**/*", api.route)
        page = await context.new_page()
        await page.goto(ROOT + "/workspace/", wait_until="networkidle")
        await expect(page.get_by_role("heading", name=heading)).to_be_visible()
        await expect(page.get_by_role("button", name="Sign in")).to_have_count(0)
        await expect(page.locator('dialog[aria-labelledby="authTitle"]')).to_have_count(0)
        await page.keyboard.press("n")
        await expect(page.get_by_role("dialog", name="New job", exact=True)).to_have_count(0)
        assert api.logins == [], api.logins
        setattr(api, failing, False)  # the server recovers; Reload restores the session
        await page.get_by_role("button", name="Reload").click()
        await expect(page.locator(".d-title h3")).to_have_text("demo_failed")
        await expect(page.get_by_role("button", name="Sign in")).to_have_count(0)
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
