"""With mail off, nothing asks for an e-mail address; APIs are mocked."""
import asyncio

from playwright.async_api import async_playwright, expect
from verify_replica import BASE, Api, wait_for


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
        await context.add_init_script("localStorage.setItem('auth_token','test-session')")
        api = Api(mail=False)
        await context.route("**/*", api.route)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(BASE + "/", wait_until="networkidle")
        await expect(page.locator(".d-title h3")).to_have_text("demo_failed")

        # New job: no e-mail field, and the submission carries no address.
        await page.locator(".nav").get_by_role("button", name="New job", exact=True).click()
        dialog = page.get_by_role("dialog", name="New job", exact=True)
        await expect(dialog).to_be_visible()
        await expect(dialog.locator("#fEmail")).to_have_count(0)
        await expect(dialog).not_to_contain_text("email you")
        await dialog.locator("#fTgz").set_input_files({"name": "Demo.tgz", "mimeType": "application/gzip", "buffer": b"test"})
        await dialog.locator("#fRef").set_input_files({"name": "Demo.ref", "mimeType": "text/plain", "buffer": b"0.0"})
        await dialog.get_by_role("button", name="Submit job", exact=True).click()
        await wait_for(lambda: len(api.submits) == 1)
        await expect(dialog).not_to_be_visible()
        assert api.submits[0]["mode"] == "new" and "email" not in api.submits[0], api.submits[0]

        # Account: sign out, then create an account without an address.
        await page.get_by_role("button", name="Open account menu").click()
        await page.get_by_role("menuitem", name="Sign out").click()
        await page.get_by_role("button", name="Sign in", exact=True).first.click()
        auth = page.locator('dialog[aria-labelledby="authTitle"]')
        await expect(auth).to_have_accessible_name("Sign in to DFThub")
        await expect(auth.get_by_label("Username or email")).to_be_visible()
        await auth.get_by_role("button", name="Create account").click()
        await expect(auth.get_by_text("Email (optional)")).to_be_visible()
        await expect(auth.get_by_text("This server does not send e-mail.")).to_be_visible()
        await auth.locator("#authUsername").fill("researcher")
        await auth.locator("#authPassword").fill("test-password")
        await auth.locator("#authConfirm").fill("test-password")
        await auth.locator("#authConfirm").press("Enter")
        await expect(auth).not_to_be_visible()
        assert api.logins == [{"username": "researcher", "password": "test-password"}], api.logins

        assert not errors, errors
        assert not api.unexpected, api.unexpected
        await browser.close()
    print("PASS optional email")


if __name__ == "__main__":
    asyncio.run(main())
