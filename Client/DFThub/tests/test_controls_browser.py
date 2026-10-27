"""Exercise the flat controls against mocked application APIs."""
import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright, expect
from verify_replica import Api, BASE

OUT = Path(os.getenv("OUTPUT_DIR", str(Path(__file__).parent / "qa-controls")))


async def aligned(page):
    await page.wait_for_function("""() => [...document.querySelectorAll('.seg')].every(seg => {
      if (!seg.offsetWidth) return true;
      const selected = [...seg.children].find(e => e.matches('button[aria-pressed="true"], button[aria-selected="true"]'));
      if (!selected) return true;
      const pill = getComputedStyle(seg, '::before');
      return seg.hasAttribute('data-seg-ready') && pill.opacity === '1' &&
        Math.abs(parseFloat(pill.left) - selected.offsetLeft) < 1 &&
        Math.abs(parseFloat(pill.top) - selected.offsetTop) < 1 &&
        Math.abs(parseFloat(pill.width) - selected.offsetWidth) < 1 &&
        Math.abs(parseFloat(pill.height) - selected.offsetHeight) < 1;
    })""")


async def context_for(browser, *, width=1366, motion="no-preference", fallback=False, signed_in=True):
    context = await browser.new_context(viewport={"width": width, "height": 977}, reduced_motion=motion)
    await context.add_init_script("localStorage.setItem('dfthub.theme','\"light\"')" +
                                  (";localStorage.setItem('auth_token','test')" if signed_in else ""))
    api = Api()
    async def route(request):
        if fallback and "seg-indicator" in request.request.url:
            await request.fulfill(content_type="text/javascript", body="/* Script unavailable */")
        else:
            await api.route(request)
    await context.route("**/*", route)
    page = await context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    await page.goto(BASE, wait_until="networkidle")
    if signed_in:
        await expect(page.get_by_role("button", name="Open account menu", exact=True)).to_be_visible()
    return context, page, errors, api


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context, page, errors, api = await context_for(browser)
        await expect(page.locator(".d-title h3")).to_have_text("demo_failed")
        await aligned(page)
        sections = page.get_by_role("tablist", name="Job sections")
        await sections.scroll_into_view_if_needed()
        # Sample a real transition before it reaches the new selection.
        motion = await sections.evaluate("""async seg => {
          const box = () => {const s = getComputedStyle(seg, '::before'); return [parseFloat(s.left), parseFloat(s.width)];};
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
          const start = box();
          seg.lastElementChild.click();
          await new Promise(r => setTimeout(r, 110));
          return {start, middle: box(), end: [seg.lastElementChild.offsetLeft, seg.lastElementChild.offsetWidth],
                  duration: getComputedStyle(seg, '::before').transitionDuration,
                  fade: getComputedStyle(seg.lastElementChild).transitionDuration};
        }""")
        assert motion["start"][0] < motion["middle"][0] < motion["end"][0], motion
        assert motion["start"][1] < motion["middle"][1] < motion["end"][1], motion
        assert motion["duration"].startswith("0.32s") and motion["fade"] == "0.16s", motion
        # A second input redirects the capsule while the first move is unfinished.
        await sections.get_by_role("tab", name="Log", exact=True).evaluate("e => e.click()")
        await aligned(page)
        log = page.get_by_role("group", name="Log detail")
        await log.get_by_role("button", name="Full output", exact=True).click()
        await aligned(page)
        await sections.get_by_role("tab", name="Weights", exact=True).click()
        await page.get_by_role("group", name="Filter by type").get_by_role("button", name="BH", exact=False).click()
        await aligned(page)
        await page.get_by_role("button", name="Edited only", exact=True).click()
        await expect(page.locator('.toggle-chip[aria-pressed="true"]')).to_have_css("background-color", "rgb(29, 29, 31)")
        await sections.get_by_role("tab", name="Weights", exact=True).press("Home")
        overview = sections.get_by_role("tab", name="Overview", exact=True)
        await expect(overview).to_be_focused()
        assert await overview.evaluate("e => [getComputedStyle(e).outlineWidth, getComputedStyle(e).outlineOffset, getComputedStyle(e).outlineColor]") == ["2px", "2px", "rgb(0, 113, 227)"]
        await aligned(page)
        views = page.get_by_role("group", name="MUE views")
        for label in ["Overall MUE by type", "MUE by dataset", "Overview"]:
            await views.get_by_role("button", name=label, exact=True).click()
            await aligned(page)
        levels = page.get_by_role("group", name="Sidebar level")
        for label in ["Runs", "Jobs"]:
            await levels.get_by_role("button", name=label, exact=False).click()
            await aligned(page)
        filters = page.get_by_role("group", name="Filter jobs by status")
        for label in ["Failed", "All"]:
            await filters.get_by_role("button", name=label, exact=False).click()
            await aligned(page)
        for width in [1366, 729, 390, 320]:
            await page.set_viewport_size({"width": width, "height": 977})
            for theme, track, pill in [("light", "rgb(232, 232, 237)", "rgb(29, 29, 31)"), ("dark", "rgb(51, 51, 54)", "rgb(99, 99, 102)")]:
                await page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                await aligned(page)
                await expect(sections.locator('button[aria-selected="true"]')).to_have_css("color", "rgb(255, 255, 255)")
                assert await sections.evaluate("e => [getComputedStyle(e).backgroundColor, getComputedStyle(e, '::before').backgroundColor]") == [track, pill]
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                await sections.screenshot(path=str(OUT / f"tabs-{width}-{theme}.png"))
            await page.locator(".nav").get_by_role("button", name="New job", exact=True).click()
            dialog = page.get_by_role("dialog", name="New job", exact=True)
            await dialog.locator(".advanced-settings > summary").click()
            await expect(dialog).to_be_visible()
            await dialog.locator('#fZeta [data-v="3"]').click()
            await dialog.locator('#fEcp [data-v="ecp"]').click()
            await aligned(page)
            await dialog.locator('#fZeta [data-v="1"]').click()
            await expect(dialog.locator('#fEcp [data-v="ae"]')).to_have_attribute("aria-pressed", "true")
            await expect(dialog.locator('#fEcp [data-v="ecp"]')).to_be_disabled()
            await aligned(page)
            await dialog.screenshot(path=str(OUT / f"dialog-{width}.png"))
            await page.keyboard.press("Escape")
            await expect(dialog).not_to_be_visible()
            print("PASS layout", width, flush=True)
        assert not errors, errors
        assert not api.unexpected, api.unexpected
        await context.close()
        context, page, errors, _ = await context_for(browser, motion="reduce")
        await aligned(page)
        await page.get_by_role("tab", name="Log", exact=True).click()
        await aligned(page)
        assert await page.locator(".detail-sections").evaluate("e => getComputedStyle(e, '::before').transitionDuration") == "0s"
        await context.close()
        context, page, errors, _ = await context_for(browser, fallback=True)
        sections = page.get_by_role("tablist", name="Job sections")
        await sections.get_by_role("tab", name="Log", exact=True).click()
        assert await sections.evaluate("e => !e.hasAttribute('data-seg-ready')")
        assert await sections.get_by_role("tab", name="Log", exact=True).evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(29, 29, 31)"
        assert not errors, errors
        await context.close()
        context, page, errors, _ = await context_for(browser, signed_in=False)
        await page.get_by_role("button", name="Sign in", exact=True).click()
        access = page.get_by_role("group", name="Account access")
        await access.get_by_role("button", name="Create account", exact=True).click()
        await aligned(page)
        await expect(page.get_by_label("Username", exact=True)).to_be_visible()
        await access.get_by_role("button", name="Sign in", exact=True).click()
        await aligned(page)
        assert not errors, errors
        await context.close()
        await browser.close()
        (OUT / "report.json").write_text(json.dumps({"motion": motion, "themes": "passed", "responsive": "passed", "keyboard": "passed", "dialogs": "passed", "reduced_motion": "passed", "script_fallback": "passed"}, indent=2))
        print("PASS motion, keyboard, dialogs, reduced motion and fallback", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
