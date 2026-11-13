import asyncio
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect

BASE = os.getenv('BASE_URL', 'http://127.0.0.1:18289').rstrip('/') + '/workspace/'
OUT = Path(os.getenv('OUTPUT_DIR', str(Path(__file__).parent / 'qa')))
SOURCE_ROOT = Path(__file__).parent if (Path(__file__).parent / 'src').is_dir() else Path(__file__).resolve().parents[1]
NATIVE = json.loads(Path(os.getenv('CF22D_FIXED_JSON', str(SOURCE_ROOT / 'src/replica/cf22d-native.json'))).read_text())
USER = {'id': 100, 'username': 'researcher', 'email': 'researcher@example.test'}
MUE = '------------SUMMARY-------------\nBH76RC\t0.5\nDBH24\t2.5\nBDE99nonMR\t1.0\nAE17\t0.1\ninput\t0.59\nnew_total_mue:0.938\n------------LOSS----------------\nWeighted MUE sum:\t527\nRegularization (0.01*(a+b+c)):\t14\nTotal loss:\t542\n'
WEIGHTS = 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nDemo\tUser data\t\tuploaded\t\t0.02\nBH76RC\tBarriers\tBH\tReference\t999\t0.1\nDBH24\tBarriers\tBH\tReference\t999\t0.3\nBDE99nonMR\tBond energies\tTC\tReference\t999\t0.1\nAE17\tAtomic energies\tTC\tReference\t999\t0.4\n'
RESULTS = {key: {'MUE': value, 'res': [value] * count} for key, value, count in [('INPUT_ref', .59, 3), ('BH76RC_ref', .5, 5), ('DBH24_ref', 2.5, 15), ('BDE99nonMR_ref', 1., 2), ('AE17_ref', .1, 17)]}

class Api:
    def __init__(self):
        self.jobs = ['demo', 'failed', 'active']
        self.deletes = []
        self.unexpected = []
        self.fail_delete = False
        self.active_before_delete = False
        self.active_spe = False
        self.empty_mue = False
        self.delete_release = asyncio.Event()
        self.delete_release.set()

    async def route(self, route):
        req = route.request
        path = unquote(urlparse(req.url).path)
        if not path.startswith('/api_dft/'):
            return await route.continue_()
        if path.endswith('/me'):
            return await route.fulfill(json={'success': True, 'user': USER})
        if path.endswith('/submit_count.txt'):
            return await route.fulfill(content_type='text/plain', body='54')
        if path.endswith('/file_list'):
            body = req.post_data_json
            folder = body['file_dir'].rstrip('/')
            if body['file_or_folder'] == 'folder':
                if folder == 'Work/researcher':
                    names = self.jobs
                elif folder.endswith('/output'):
                    names = ['weight_0']
                else:
                    names = []
                status = lambda name: 'Running' if 'active' in folder + name or (self.active_before_delete and 'failed' in folder + name) else 'Failed' if 'failed' in folder + name else 'Success'
                return await route.fulfill(json={'result': [{'name': name, 'status': status(name), 'total_mue': 'Total loss:\t542.0', 'time_modify': 1790930000 - index} for index, name in enumerate(names)]})
            if folder.endswith('/input'):
                names = ['basis.txt', 'Demo.tgz', 'Demo.ref']
            elif '/output/' in folder:
                names = ['process.log', 'Mue', 'OriginalMue', 'OriginalMue.meta.json', 'results.json', 'weight.csv', 'Parameters', 'NEW-params.txt']
                if self.active_spe: names.append('spe_input.status.json')
            else:
                names = ['process.log']
            return await route.fulfill(json={'result': [{'name': name} for name in names]})
        if req.method == 'DELETE':
            self.deletes.append(path)
            await self.delete_release.wait()
            if self.fail_delete:
                return await route.fulfill(json={'result': 'error', 'msg': 'Deletion failed. Your job is still available.'})
            assert path.startswith('/api_dft/delete/Work/researcher/')
            self.jobs.remove(path.rsplit('/', 1)[1])
            return await route.fulfill(json={'result': 'file delete success'})
        filename = path.rsplit('/', 1)[1]
        values = {'spe_input.status.json': json.dumps({'status': 'Queued'}), 'Mue': MUE, 'OriginalMue': 'INPUT_ref\t4.25\n', 'OriginalMue.meta.json': json.dumps({'source': 'libxc-native-cf22d', 'parameter_sha256': NATIVE['parameter_sha256']}), 'results.json': json.dumps(RESULTS), 'weight.csv': WEIGHTS,
                  'Parameters': 'HF% = 46.2806\n', 'process.log': 'SUCCESS!\n', 'basis.txt': 'cc-pvqz'}
        if filename in values:
            return await route.fulfill(content_type='text/plain', body='' if filename == 'Mue' and self.empty_mue else values[filename])
        self.unexpected.append(f'{req.method} {path}')
        return await route.fulfill(status=400, json={'message': 'Unmatched test request'})

async def wait_for(predicate):
    for _ in range(100):
        if predicate(): return
        await asyncio.sleep(.05)
    raise AssertionError('Expected request was not observed')

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for width in (1366, 729, 390, 320):
            api = Api()
            context = await browser.new_context(viewport={'width': width, 'height': 977}, reduced_motion='reduce')
            await context.add_init_script("localStorage.setItem('auth_token','test');localStorage.setItem('dfthub.theme','\"light\"')")
            await context.route('**/api_dft/**', api.route)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(BASE, wait_until='networkidle')
            await expect(page.locator('.d-title h3')).to_have_text('demo')
            await expect(page.get_by_role('tabpanel')).to_have_attribute('aria-busy', 'false')
            panel = page.get_by_role('region', name='MUE analysis')
            switch = panel.get_by_role('group', name='MUE views')
            await expect(switch.get_by_role('button', name='Overview', exact=True)).to_have_attribute('aria-pressed', 'true')
            summary = panel.get_by_label('MUE overview statistics')
            await expect(summary).to_contain_text('0.59')
            await expect(summary).to_contain_text('86% lower')
            await expect(summary).to_contain_text('3 of 4')
            await expect(summary).to_contain_text('1 got worse')
            await expect(summary).to_contain_text('0 → 2')
            await expect(panel.get_by_role('table', name='Runs')).to_have_count(0)
            levels = page.get_by_role('group', name='Sidebar level')
            await levels.get_by_role('button', name='Runs', exact=False).click()
            await expect(page.get_by_role('listbox', name='Runs for demo')).to_contain_text('MUE 0.94')
            await levels.get_by_role('button', name='Jobs', exact=False).click()
            await expect(panel.get_by_role('region', name='Got worse')).to_contain_text('DBH24')
            await expect(panel.get_by_role('region', name='Biggest improvements')).to_contain_text('AE17')
            await panel.evaluate("e=>e.scrollIntoView({block:'start',behavior:'instant'})")
            await page.screenshot(path=str(OUT / f'overview-{width}.png'))

            await switch.get_by_role('button', name='Overall MUE by type', exact=True).click()
            await expect(panel.locator('.mue-pair')).to_have_count(3)
            await expect(panel.get_by_label('BH Optimized MUE', exact=True)).to_have_text('2.00')
            before_bh = (NATIVE['datasets']['BH76RC'] * 5 + NATIVE['datasets']['DBH24'] * 15) / 20
            await expect(panel.get_by_label('BH Original MUE', exact=True)).to_have_text(f'{before_bh:.2f}')
            await expect(panel.get_by_label('TC Optimized MUE', exact=True)).to_have_text('0.19')
            await expect(panel).to_contain_text('20 data points')
            await expect(panel.locator('[data-dataset="input"]')).to_contain_text('4.25')
            await page.screenshot(path=str(OUT / f'types-{width}.png'))
            await switch.get_by_role('button', name='MUE by dataset', exact=True).click()
            await expect(panel.locator('.mue-pair')).to_have_count(5)
            await expect(panel.locator('.mue-dataset').first).to_have_text('Input')
            assert 'Weighted MUE' not in await panel.inner_text()
            assert 'Regularization' not in await panel.inner_text()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')

            await page.get_by_role('button', name='Delete job failed', exact=True).click()
            dialog = page.get_by_role('dialog', name='Delete job?', exact=True)
            await expect(dialog).to_be_visible()
            await expect(dialog).to_contain_text('failed')
            await expect(dialog).to_contain_text('cannot be undone')
            await page.screenshot(path=str(OUT / f'delete-{width}.png'))
            await dialog.get_by_role('button', name='Cancel', exact=True).click()
            await expect(dialog).not_to_be_visible()
            assert not api.deletes
            await expect(page.get_by_role('button', name='Delete job active', exact=True)).to_be_disabled()

            if width == 1366:
                await page.get_by_role('button', name='Delete job failed', exact=True).click()
                api.active_before_delete = True
                await dialog.get_by_role('button', name='Delete job', exact=True).click()
                await expect(dialog).to_contain_text('queued or running calculation')
                assert not api.deletes
                api.active_before_delete = False
                api.active_spe = True
                await dialog.get_by_role('button', name='Delete job', exact=True).click()
                await expect(dialog).to_contain_text('active self-consistent calculation')
                assert not api.deletes
                api.active_spe = False
                api.fail_delete = True
                await dialog.get_by_role('button', name='Delete job', exact=True).click()
                await expect(dialog).to_contain_text('Deletion failed')
                await expect(page.get_by_role('button', name='Delete job failed', exact=True)).to_be_attached()
                api.fail_delete = False
                api.delete_release.clear()
                await dialog.get_by_role('button', name='Delete job', exact=True).click()
                await wait_for(lambda: len(api.deletes) == 2)
                await expect(dialog.get_by_role('button', name='Deleting…', exact=True)).to_be_disabled()
                await dialog.get_by_role('button', name='Deleting…', exact=True).evaluate('e=>e.click()')
                assert len(api.deletes) == 2
                api.delete_release.set()
                await expect(dialog).not_to_be_visible()
                await expect(page.get_by_role('button', name='Delete job failed', exact=True)).to_have_count(0)
                assert api.deletes[-1] == '/api_dft/delete/Work/researcher/failed'
                await page.get_by_role('button', name='Delete job demo', exact=True).click()
                await dialog.get_by_role('button', name='Delete job', exact=True).click()
                await expect(dialog).not_to_be_visible()
                await expect(page.locator('.d-title h3')).to_have_text('active')
                await expect(page.get_by_role('button', name='Delete job demo', exact=True)).to_have_count(0)
                await page.get_by_role('region', name='MUE analysis').get_by_role('group', name='MUE views').get_by_role('button', name='Overview', exact=True).click()
                api.empty_mue = True
                await page.get_by_role('button', name='Refresh', exact=True).click()
                await expect(page.get_by_text('No MUE results yet', exact=True)).to_be_visible()
                await expect(page.get_by_label('MUE overview statistics')).to_have_count(0)
            await page.get_by_role('button', name='Open account menu').click()
            await page.get_by_role('menuitem', name='Appearance:', exact=False).click()
            await page.keyboard.press('Escape')
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert not errors, errors
            assert not api.unexpected, api.unexpected
            report.append({'width': width, 'summary': 'passed', 'point_weighted_types': 'passed', 'views': 'passed', 'deletion': 'passed', 'errors': errors})
            print('PASS', width, flush=True)
            await context.close()
        await browser.close()
    (OUT / 'report.json').write_text(json.dumps(report, indent=2))

asyncio.run(main())
