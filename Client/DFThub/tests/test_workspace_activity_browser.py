"""Activity filters, automatic refresh, and deletion of an orphaned job."""
import asyncio
import json
import os
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect
from test_sidebar_browser import Api, BASE, OUT


class ActivityApi(Api):
    def __init__(self):
        super().__init__()
        self.jobs = ['scf', 'optim', 'stale']
        self.runs = {'scf': ['weight_0'], 'optim': ['weight_0'], 'stale': []}
        self.phase = 'Running'

    async def route(self, route):
        path = unquote(urlparse(route.request.url).path)
        if path.endswith('/file_list'):
            body = route.request.post_data_json
            folder = body['file_dir'].rstrip('/')
            if body['file_or_folder'] == 'folder':
                names = self.jobs if folder == 'Work/researcher' else self.runs[folder.split('/')[2]] if folder.endswith('/output') else []
                rows = []
                for index, name in enumerate(names):
                    job = name if folder == 'Work/researcher' else folder.split('/')[2]
                    row = {'name': name, 'time_modify': 1790930000 - index, 'status': 'Interrupted' if job == 'stale' else 'Success'}
                    if job != 'stale' and self.phase != 'Success':
                        row.update(activity_state=self.phase.lower(), activity_status='SCF Input ' + self.phase.lower() if job == 'scf' else 'Optimizing parameters')
                        if job == 'optim':
                            row['status'] = 'Optimizing...'
                    rows.append(row)
                return await route.fulfill(json={'result': rows})
            if '/scf/output/' in folder and not folder.endswith('/input'):
                return await route.fulfill(json={'result': [{'name': name} for name in ['Mue', 'Parameters', 'weight.csv', 'process.log', 'NEW-params.txt', 'SinglePointResults.input.json', 'spe_input.status.json']]})
        if path.endswith('/SinglePointResults.input.json'):
            return await route.fulfill(body=json.dumps({'scope': 'input', 'complete': True, 'targetRows': [], 'targetMue': .2}))
        if path.endswith('/spe_input.status.json'):
            return await route.fulfill(body=json.dumps({'status': self.phase}))
        return await super().route(route)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=os.getenv('CHROMIUM_PATH'))
        for width in (729, 390):
            context = await browser.new_context(viewport={'width': width, 'height': 977}, reduced_motion='reduce', has_touch=width <= 390, is_mobile=width <= 390)
            await context.add_init_script("localStorage.setItem('auth_token','test')")
            api = ActivityApi()
            await context.route('**/api_dft/**', api.route)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(BASE, wait_until='networkidle')
            jobs = page.get_by_role('listbox', name='Jobs', exact=True)
            await expect(jobs.get_by_role('option', name='scf', exact=False)).to_contain_text('SCF Input running')
            await expect(jobs.get_by_role('option', name='optim', exact=False)).to_contain_text('Optimizing parameters')
            await expect(page.get_by_role('button', name='Delete job scf', exact=True)).to_be_disabled()
            await expect(page.get_by_role('button', name='Delete job optim', exact=True)).to_be_disabled()
            await expect(page.locator('.d-title .pill')).to_contain_text('SCF Input running')
            await expect(page.locator('.input-summary .summary-value')).to_contain_text('0.50')
            await expect(page.locator('.d-head').get_by_role('button', name='Stop Input', exact=True)).to_be_enabled()
            filters = page.get_by_role('group', name='Filter jobs by status')
            await filters.get_by_role('button', name='Active', exact=False).click()
            await expect(jobs.get_by_role('option')).to_have_count(2)
            await filters.get_by_role('button', name='All', exact=False).click()
            await jobs.get_by_role('option', name='stale', exact=False).click()
            await expect(page.get_by_role('tabpanel')).to_contain_text('No runs available yet')
            await expect(page.get_by_role('tabpanel')).not_to_contain_text('Refresh after this job starts')
            await page.get_by_role('group', name='Sidebar level').get_by_role('button', name='Jobs', exact=False).click()
            if width > 390:
                await page.get_by_role('button', name='Delete job stale', exact=True).locator('..').hover()
            await page.get_by_role('button', name='Delete job stale', exact=True).click()
            dialog = page.get_by_role('dialog', name='Delete job?', exact=True)
            await dialog.get_by_role('button', name='Delete job', exact=True).click()
            await expect(dialog).not_to_be_visible()
            assert api.deletes == ['/api_dft/delete/Work/researcher/stale']
            # The timer must keep polling even though the original optimization
            # is complete and only the optional SCF calculation was running.
            api.phase = 'Success'
            await expect(jobs.get_by_role('option', name='scf', exact=False)).to_contain_text('Completed', timeout=25000)
            await expect(page.get_by_role('button', name='Delete job scf', exact=True)).to_be_enabled()
            await expect(page.locator('.d-head').get_by_role('button', name='Stop Input', exact=True)).to_have_count(0)
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert not errors, errors
            assert not api.unexpected, api.unexpected
            await page.screenshot(path=str(OUT / f'activity-{width}.png'))
            print('PASS', width, 'SCF/optimization activity, filters, preserved results, orphan deletion, automatic completion refresh', flush=True)
            await context.close()
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
