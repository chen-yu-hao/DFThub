import asyncio
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 729, "height": 977}, reduced_motion="reduce")
        await context.add_init_script("localStorage.setItem('auth_token','test');localStorage.setItem('dfthub.theme','light')")
        async def route(route):
            path = unquote(urlparse(route.request.url).path)
            if path.endswith('/me'):
                return await route.fulfill(json={'success': True, 'user': {'id': 1, 'username': 'researcher', 'email': 'researcher@example.test'}})
            if path.endswith('/submit_count.txt'):
                return await route.fulfill(content_type='text/plain', body='1')
            if path.endswith('/file_list'):
                return await route.fulfill(json={'result': []})
            return await route.fulfill(json={'result': []})
        await context.route('**/api_dft/**', route)
        page = await context.new_page()
        await page.goto('http://127.0.0.1:18292/', wait_until='networkidle')
        await page.get_by_role('button', name='New job', exact=True).first.click()
        dialog = page.get_by_role('dialog', name='New job', exact=True)
        await dialog.locator('.advanced-settings > summary').click()
        await expect(dialog.get_by_text('Final basis', exact=True)).to_be_visible()
        await expect(dialog.get_by_text('Optional test set', exact=True)).to_be_visible()
        await dialog.locator('#fZeta [data-v="4"]').click()
        await dialog.locator('#fBasis').click()
        picker = dialog.get_by_role('group', name='Available basis sets')
        assert await picker.locator('[data-basis]').count() == 7
        await dialog.locator('#fEcp [data-v="ecp"]').click()
        await dialog.locator('#fBasis').click()
        picker = dialog.get_by_role('group', name='Available basis sets')
        assert await picker.locator('[data-basis]').count() == 3
        await dialog.locator('#fZeta [data-v="3"]').click()
        await dialog.locator('#fEcp [data-v="ae"]').click()
        await dialog.locator('#fBasis').click()
        picker = dialog.get_by_role('group', name='Available basis sets')
        print('ZETA3', await picker.locator('[data-basis]').all_text_contents(), await picker.locator('[data-basis]').count())
        assert await picker.locator('[data-basis]').count() == 11
        await page.screenshot(path='/tmp/basis-picker-final.png')
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        print('PASS grouped zeta/ECP choices and final basis picker')
        await browser.close()

asyncio.run(main())
