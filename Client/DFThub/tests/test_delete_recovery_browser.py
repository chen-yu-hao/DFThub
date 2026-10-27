"""A stalled deletion must recover; safe retries handle already-deleted jobs."""
import asyncio
import os
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect, Error
from test_sidebar_browser import Api, BASE, OUT


class DeleteApi(Api):
    def __init__(self):
        super().__init__()
        self.mode = 'hang'
        self.confirming = False
        self.preflight_requests = []
        self.release = asyncio.Event()

    async def route(self, route):
        path = unquote(urlparse(route.request.url).path)
        if self.confirming and path.endswith('/file_list'):
            self.preflight_requests.append(path)
            return await route.fulfill(status=503, json={'message': 'Listing unavailable during deletion'})
        if route.request.method == 'DELETE':
            self.deletes.append(path)
            if self.mode == 'hang':
                await self.release.wait()
                try:
                    await route.abort()
                except Error:
                    pass  # The browser has already timed out this request.
                return
            if self.mode == 'conflict':
                return await route.fulfill(status=409, json={'message': 'This job has a queued or running calculation.'})
            self.confirming = False
            self.jobs.remove(path.rsplit('/', 1)[-1])
            if self.mode == 'missing':
                return await route.fulfill(status=404, json={'message': 'File or folder not found'})
            return await route.fulfill(json={'result': 'file delete success'})
        return await super().route(route)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=os.getenv('CHROMIUM_PATH'))
        context = await browser.new_context(viewport={'width': 729, 'height': 977}, reduced_motion='reduce')
        await context.add_init_script("localStorage.setItem('auth_token','test')")
        api = DeleteApi()
        await context.route('**/api_dft/**', api.route)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(BASE, wait_until='networkidle')
        await expect(page.locator('.input-summary .summary-value')).to_be_visible()
        button = page.get_by_role('button', name='Delete job alpha', exact=True)
        await button.locator('..').hover()
        await button.click()
        dialog = page.get_by_role('dialog', name='Delete job?', exact=True)
        api.confirming = True
        await dialog.get_by_role('button', name='Delete job', exact=True).click()
        await expect(dialog.get_by_role('button', name='Deleting…', exact=True)).to_be_disabled()
        await expect(dialog.get_by_role('alert')).to_contain_text('Deleting took too long', timeout=35000)
        await expect(dialog.get_by_role('button', name='Cancel', exact=True)).to_be_enabled()
        await expect(dialog.get_by_role('button', name='Delete job', exact=True)).to_be_enabled()
        assert len(api.deletes) == 1 and not api.preflight_requests
        await dialog.screenshot(path=str(OUT / 'delete-timeout-recovered.png'))
        print('PASS stalled deletion times out and restores dialog controls without listing requests', flush=True)
        api.release.set()

        api.mode = 'conflict'
        await dialog.get_by_role('button', name='Delete job', exact=True).click()
        await expect(dialog.get_by_role('alert')).to_contain_text('queued or running')
        await expect(dialog.get_by_role('button', name='Cancel', exact=True)).to_be_enabled()
        assert 'alpha' in api.jobs

        api.mode = 'missing'
        await dialog.get_by_role('button', name='Delete job', exact=True).click()
        await expect(dialog).not_to_be_visible()
        await expect(page.get_by_role('button', name='Delete job alpha', exact=True)).to_have_count(0)
        await expect(page.locator('.d-title h3')).to_have_text('beta')

        api.mode = 'success'
        await page.set_viewport_size({'width': 390, 'height': 977})
        button = page.get_by_role('button', name='Delete job beta', exact=True)
        await button.locator('..').hover()
        await button.click()
        api.confirming = True
        await dialog.get_by_role('button', name='Delete job', exact=True).click()
        await expect(dialog).not_to_be_visible()
        api.empty_gate.set()
        await expect(page.get_by_role('button', name='Delete job beta', exact=True)).to_have_count(0)
        assert len(api.deletes) == 4 and not api.preflight_requests
        assert not errors, errors
        print('PASS active-job rejection, already-deleted retry and successful deletion all settle correctly', flush=True)
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
