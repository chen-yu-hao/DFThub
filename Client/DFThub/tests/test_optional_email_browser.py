"""With mail off, nothing asks for an e-mail address; APIs are mocked."""
import asyncio

from playwright.async_api import async_playwright, expect
from verify_replica import BASE, USER, Api, wait_for


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
        await expect(dialog.locator("#dropTgz")).to_have_class("drop has")
        await expect(dialog.locator("#dropRef")).to_have_class("drop has")
        await expect(dialog.locator("#submitHint")).to_have_text("Ready to submit.")
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
        await mail_on_without_account_address(browser)
        await browser.close()
    print("PASS optional email")


async def mail_on_without_account_address(browser):
    """Mail on, account without e-mail: every calculation asks for an address and sends it."""
    context = await browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    await context.add_init_script("localStorage.setItem('auth_token','test-session')")
    api = Api(mail=True, user={**USER, "email": None})
    await context.route("**/*", api.route)
    page = await context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    await page.goto(BASE + "/", wait_until="networkidle")
    await expect(page.locator(".d-title h3")).to_have_text("demo_failed")
    prompt = page.get_by_role("dialog", name="Notification email")

    async def resubmit_weights():
        await page.get_by_role("tab", name="Weights", exact=True).click()
        await page.get_by_role("textbox", name="Inverse weight for Demo", exact=True).fill("0.01")
        await page.get_by_role("button", name="Review & resubmit").click()
        review = page.get_by_role("dialog", name="Resubmit with new weights")
        await review.get_by_role("button", name="Resubmit", exact=False).last.click()
        return review

    # Follow-up (weights resubmission): asked for an address, which is sent.
    review = await resubmit_weights()
    await expect(prompt).to_be_visible()
    await expect(prompt.locator("#notifyEmail")).to_have_value("")
    await prompt.get_by_role("button", name="Continue").click()
    await expect(prompt.get_by_text("Enter a valid email address.")).to_be_visible()
    await prompt.locator("#notifyEmail").fill("me@example.test")
    await prompt.get_by_role("button", name="Continue").click()
    await wait_for(lambda: len(api.submits) == 1)
    assert api.submits[0]["mode"] == "optim" and api.submits[0]["email"] == "me@example.test", api.submits[0]

    # The next calculation offers the same address; cancelling sends nothing.
    review = await resubmit_weights()
    await expect(prompt.locator("#notifyEmail")).to_have_value("me@example.test")
    await prompt.get_by_role("button", name="Cancel").click()
    await expect(prompt).not_to_be_visible()
    await expect(review).to_be_visible()
    await asyncio.sleep(0.3)
    assert len(api.submits) == 1, api.submits
    await review.get_by_role("button", name="Cancel", exact=True).first.click()

    # New job: the form's own field asks for the address; no extra prompt.
    await page.locator(".nav").get_by_role("button", name="New job", exact=True).click()
    dialog = page.get_by_role("dialog", name="New job", exact=True)
    await expect(dialog.locator("#fEmail")).to_have_value("")
    await dialog.locator("#fTgz").set_input_files({"name": "Demo.tgz", "mimeType": "application/gzip", "buffer": b"test"})
    await dialog.locator("#fRef").set_input_files({"name": "Demo.ref", "mimeType": "text/plain", "buffer": b"0.0"})
    await dialog.locator("#fEmail").fill("job@example.test")
    await expect(dialog.locator("#dropTgz")).to_have_class("drop has")
    await expect(dialog.locator("#dropRef")).to_have_class("drop has")
    await expect(dialog.locator("#submitHint")).to_have_text("Ready to submit.")
    await dialog.get_by_role("button", name="Submit job", exact=True).click()
    await wait_for(lambda: len(api.submits) == 2)
    assert api.submits[1]["mode"] == "new" and api.submits[1]["email"] == "job@example.test", api.submits[1]
    await expect(prompt).not_to_be_visible()

    assert not errors, errors
    assert not api.unexpected, api.unexpected
    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
