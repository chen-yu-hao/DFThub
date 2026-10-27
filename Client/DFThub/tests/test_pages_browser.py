"""Independent routes, legacy links and job creation handoff; APIs are mocked."""
import asyncio
import os
from playwright.async_api import async_playwright, expect
from verify_replica import Api

BASE = os.getenv('BASE_URL', 'http://127.0.0.1:18289').rstrip('/')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1366, 'height': 977}, reduced_motion='reduce')
        await context.add_init_script("localStorage.setItem('auth_token','test')")
        api = Api()
        await context.route('**/*', api.route)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(BASE, wait_until='networkidle')
        nav = page.get_by_role('navigation', name='Sections')
        await expect(page.locator('.brand')).to_have_attribute('aria-current', 'page')
        await expect(nav.get_by_role('link', name='Overview', exact=True)).to_have_count(0)
        await expect(page.locator('.hero')).to_be_visible()
        await expect(page.locator('#workspace')).to_have_count(0)
        await nav.get_by_role('link', name='Workspace', exact=True).click()
        await expect(page.locator('.d-title h3')).to_have_text('demo_failed')
        await expect(page.locator('.hero')).to_have_count(0)
        await nav.get_by_role('link', name='Analyze', exact=True).click()
        await expect(page.locator('#anJobTitle')).to_have_text('demo_failed')
        await expect(nav.get_by_role('link', name='Analyze', exact=True)).to_have_attribute('aria-current', 'page')
        await page.reload(wait_until='networkidle')
        await expect(page.locator('#anJobTitle')).to_have_text('demo_failed')
        for width in [729, 390, 320]:
            await page.set_viewport_size({'width': width, 'height': 977})
            for label in ['Workspace', 'Analyze', 'DFT energy', 'Guide']:
                await expect(nav.get_by_role('link', name=label, exact=True)).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        await page.goto(BASE + '/#workspace', wait_until='networkidle')
        await expect(page).to_have_url(BASE + '/workspace/')
        await page.goto(BASE + '/workspace?job=demo_done&run=weight_0&section=energies', wait_until='networkidle')
        await expect(page.get_by_role('tab', name='Self-consistent results', exact=True)).to_have_attribute('aria-selected', 'true')
        await expect(page.locator('.d-title h3')).to_have_text('demo_done')
        await page.goto(BASE, wait_until='networkidle')
        await page.get_by_role('button', name='Start a new job', exact=True).click()
        dialog = page.get_by_role('dialog', name='New job', exact=True)
        await dialog.locator('#fId').fill('pages_new_job')
        await dialog.locator('#fTgz').set_input_files({'name': 'Demo.tgz', 'mimeType': 'application/gzip', 'buffer': b'test'})
        await dialog.locator('#fRef').set_input_files({'name': 'Demo.ref', 'mimeType': 'text/plain', 'buffer': b'0.0'})
        await dialog.get_by_role('button', name='Submit job', exact=True).click()
        await expect(page).to_have_url(BASE + '/workspace/?job=pages_new_job')
        await expect(page.locator('.d-title h3')).to_have_text('pages_new_job')
        assert len(api.submits) == 1 and api.submits[0]['mode'] == 'new'
        assert not errors, errors
        assert not api.unexpected, api.unexpected
        await context.close()
        context = await browser.new_context()
        await context.route('**/*', Api().route)
        page = await context.new_page()
        await page.goto(BASE + '/analyze/', wait_until='networkidle')
        await expect(page.get_by_role('button', name='Sign in', exact=True)).to_be_visible()
        await expect(page.locator('#anDetail')).to_have_count(0)
        await context.close()
        await browser.close()
    print('PASS independent pages, Analyze entry, deep links, mobile navigation, new-job handoff and authentication')

if __name__ == '__main__':
    asyncio.run(main())
