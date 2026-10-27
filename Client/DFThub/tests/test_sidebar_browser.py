import asyncio
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect

BASE = os.getenv('BASE_URL', 'http://127.0.0.1:18289').rstrip('/') + '/workspace/'
ROOT = Path(__file__).parent if (Path(__file__).parent / 'src').exists() else Path(__file__).resolve().parents[1]
NATIVE = json.loads((ROOT / 'src/replica/cf22d-native.json').read_text())
OUT = Path(os.getenv('OUTPUT_DIR', str(Path(__file__).parent / 'qa-sidebar')))
USER = {'id': 1, 'username': 'researcher', 'email': 'researcher@example.test'}

class Api:
    def __init__(self):
        self.jobs = ['alpha', 'beta', 'empty']
        self.runs = {'alpha': ['weight_0', 'weight_1', 'weight_2', 'weight_2/fork-1'], 'beta': ['weight_0'], 'empty': []}
        self.deletes = []
        self.unexpected = []
        self.empty_gate = asyncio.Event()

    def value(self, path):
        return 7.77 if '/beta/' in path else 1.94 if '/fork-1/' in path else 2.22 if '/weight_2/' in path else 1.11 if '/weight_1/' in path else .50

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
                if folder == 'Work/researcher': names = self.jobs
                elif folder.endswith('/output'):
                    job = folder.split('/')[2]
                    if job == 'empty':
                        await self.empty_gate.wait()
                    names = [name for name in self.runs[job] if '/' not in name]
                elif folder.endswith('/weight_2'):
                    names = ['fork-1']
                else: names = []
                return await route.fulfill(json={'result': [{'name': name, 'status': 'Success', 'time_modify': 1790930000 - i, 'total_mue': 'Total loss:\t542'} for i, name in enumerate(names)]})
            names = ['basis.txt', 'Demo.tgz', 'Demo.ref'] if folder.endswith('/input') else ['Mue', 'OriginalMue', 'OriginalMue.meta.json', 'Parameters', 'weight.csv', 'process.log', 'NEW-params.txt', 'results.json'] if '/output/' in folder else ['process.log']
            return await route.fulfill(json={'result': [{'name': name} for name in names]})
        if req.method == 'DELETE':
            assert path.startswith('/api_dft/delete/Work/researcher/')
            self.deletes.append(path)
            self.jobs.remove(path.rsplit('/', 1)[-1])
            return await route.fulfill(json={'result': 'file delete success'})
        value = self.value(path)
        values = {'Mue': f'input\t{value}\nBH76RC\t0.5\nnew_total_mue:{value}\n', 'OriginalMue': 'INPUT_ref\t4.25\n',
                  'OriginalMue.meta.json': json.dumps({'source': 'libxc-native-cf22d', 'parameter_sha256': NATIVE['parameter_sha256']}),
                  'weight.csv': 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nDemo\tUser data\t\tuploaded\t3\t0.02\nBH76RC\tBarrier\tBH\tReference\t5\t0.1\n',
                  'Parameters': 'HF% = 46.2806\n', 'process.log': 'SUCCESS!\n', 'basis.txt': 'cc-pvqz',
                  'results.json': json.dumps({'INPUT_ref': {'MUE': value, 'res': [value] * 3}, 'BH76RC_ref': {'MUE': .5, 'res': [.5] * 5}})}
        name = path.rsplit('/', 1)[-1]
        if name in values:
            return await route.fulfill(content_type='text/plain', body=values[name])
        self.unexpected.append(f'{req.method} {path}')
        return await route.fulfill(status=400, json={'message': 'Unmatched fixture'})

async def await_value(page, value):
    await expect(page.get_by_role('tabpanel')).to_have_attribute('aria-busy', 'false')
    await expect(page.locator('.input-summary .summary-value')).to_contain_text(f'{value:.2f}')

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for width in [1366, 729, 390, 320]:
            context = await browser.new_context(viewport={'width': width, 'height': 977}, reduced_motion='reduce')
            await context.add_init_script("localStorage.setItem('auth_token','test');localStorage.setItem('dfthub.theme','\"light\"');const key='dfthub-run:Work/researcher/alpha';if(!sessionStorage.getItem(key))sessionStorage.setItem(key,'weight_1')")
            api = Api()
            await context.route('**/api_dft/**', api.route)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(BASE, wait_until='networkidle')
            await expect(page.locator('.d-title h3')).to_have_text('alpha')
            await await_value(page, 1.11)
            levels = page.get_by_role('group', name='Sidebar level')
            await expect(levels.get_by_role('button', name='Jobs', exact=False)).to_have_attribute('aria-pressed', 'true')
            await expect(page.get_by_role('table', name='Runs', exact=True)).to_have_count(0)
            await expect(page.locator('.run-pick')).to_have_count(0)
            sections = page.get_by_role('tablist', name='Job sections')
            for label in ['Overview', 'Log', 'Weights', 'Self-consistent results']:
                section = sections.get_by_role('tab', name=label, exact=True)
                await section.click()
                await expect(section).to_have_attribute('aria-selected', 'true')
                assert await sections.locator('[aria-selected="true"]').count() == 1
                assert await section.evaluate('e => parseFloat(getComputedStyle(e).fontSize)') == (13 if width <= 640 else 15)
            await sections.get_by_role('tab', name='Self-consistent results').press('Home')
            await expect(sections.get_by_role('tab', name='Overview', exact=True)).to_be_focused()
            await sections.get_by_role('tab', name='Overview', exact=True).press('ArrowRight')
            await expect(sections.get_by_role('tab', name='Log', exact=True)).to_have_attribute('aria-selected', 'true')
            await sections.get_by_role('tab', name='Log', exact=True).press('Home')
            for theme in ['light', 'dark']:
                await page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                assert await sections.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                assert await sections.evaluate('e => getComputedStyle(e, "::before").backgroundColor !== getComputedStyle(e).backgroundColor')
                await sections.scroll_into_view_if_needed()
                await sections.screenshot(path=str(OUT / f'tabs-{theme}-{width}.png'))
            await page.evaluate("document.documentElement.dataset.theme = 'light'")
            jobs = page.get_by_role('listbox', name='Jobs', exact=True)
            await page.get_by_role('searchbox', name='Search jobs', exact=True).fill('alpha')
            await jobs.get_by_role('option', name='alpha', exact=False).click()
            await expect(levels.get_by_role('button', name='Runs', exact=False)).to_have_attribute('aria-pressed', 'true')
            runs = page.get_by_role('listbox', name='Runs for alpha', exact=True)
            await expect(runs.get_by_role('option')).to_have_count(4)
            await page.get_by_role('searchbox', name='Search runs', exact=True).fill('fork')
            await expect(runs.get_by_role('option')).to_have_count(1)
            await runs.get_by_role('option').click()
            await await_value(page, 1.94)
            await expect(runs.get_by_role('option')).to_have_attribute('aria-selected', 'true')
            await expect(runs).not_to_contain_text('MUE')
            await page.locator('.sidebar').evaluate("e=>e.scrollIntoView({block:'start',behavior:'instant'})")
            await page.screenshot(path=str(OUT / f'runs-{width}.png'))
            await levels.get_by_role('button', name='Jobs', exact=False).click()
            await expect(page.get_by_role('searchbox', name='Search jobs', exact=True)).to_have_value('alpha')
            await await_value(page, 1.94)
            await levels.get_by_role('button', name='Runs', exact=False).click()
            await expect(page.get_by_role('searchbox', name='Search runs', exact=True)).to_have_value('fork')
            await page.get_by_role('searchbox', name='Search runs', exact=True).fill('')
            await runs.get_by_role('option').last.focus()
            await page.keyboard.press('Home')
            await await_value(page, .50)
            await page.keyboard.press('End')
            await await_value(page, 1.94)
            await page.locator('.sidebar').evaluate("e=>e.scrollIntoView({block:'start',behavior:'instant'})")
            await page.screenshot(path=str(OUT / f'runs-{width}.png'))

            await levels.get_by_role('button', name='Jobs', exact=False).click()
            await page.get_by_role('searchbox', name='Search jobs', exact=True).fill('')
            await jobs.get_by_role('option', name='alpha', exact=False).focus()
            await page.keyboard.press('ArrowDown')
            await expect(page.locator('.d-title h3')).to_have_text('beta')
            await expect(levels.get_by_role('button', name='Jobs', exact=False)).to_have_attribute('aria-pressed', 'true')
            await page.keyboard.press('Enter')
            await expect(levels.get_by_role('button', name='Runs', exact=False)).to_have_attribute('aria-pressed', 'true')
            await await_value(page, 7.77)
            await expect(page.get_by_role('searchbox', name='Search runs', exact=True)).to_have_value('')
            await expect(page.get_by_role('listbox', name='Runs for beta')).to_contain_text('weight_0')

            await levels.get_by_role('button', name='Jobs', exact=False).click()
            await jobs.get_by_role('option', name='empty', exact=False).click()
            await expect(page.get_by_role('listbox', name='Runs for empty')).to_have_attribute('aria-busy', 'true')
            await expect(page.get_by_role('listbox', name='Runs for empty').get_by_role('option')).to_have_count(0)
            await expect(page.get_by_role('listbox', name='Runs for empty')).to_contain_text('Loading runs')
            await levels.get_by_role('button', name='Jobs', exact=False).click()
            await jobs.get_by_role('option', name='beta', exact=False).click()
            await await_value(page, 7.77)
            api.empty_gate.set()
            await asyncio.sleep(.1)
            await expect(page.get_by_role('listbox', name='Runs for beta').get_by_role('option')).to_have_count(1)
            await levels.get_by_role('button', name='Jobs', exact=False).click()
            await jobs.get_by_role('option', name='empty', exact=False).click()
            await expect(page.get_by_role('listbox', name='Runs for empty')).to_have_attribute('aria-busy', 'false')
            await expect(page.get_by_role('listbox', name='Runs for empty')).to_contain_text('No runs yet')
            await expect(page.get_by_role('tabpanel')).to_have_attribute('aria-busy', 'false')

            await levels.get_by_role('button', name='Jobs', exact=False).click()
            await jobs.get_by_role('option', name='alpha', exact=False).click()
            await await_value(page, 1.94)
            await expect(page.get_by_role('listbox', name='Runs for alpha').get_by_role('option', name='weight_2/fork-1', exact=False)).to_have_attribute('aria-selected', 'true')
            await page.reload(wait_until='networkidle')
            await await_value(page, 1.94)
            await expect(levels.get_by_role('button', name='Jobs', exact=False)).to_have_attribute('aria-pressed', 'true')
            await jobs.get_by_role('option', name='alpha', exact=False).click()
            await expect(page.get_by_role('listbox', name='Runs for alpha').get_by_role('option', name='weight_2/fork-1', exact=False)).to_have_attribute('aria-selected', 'true')
            await expect(page.locator('.sidebar .job-delete')).to_have_count(0)

            await levels.get_by_role('button', name='Jobs', exact=False).click()
            await page.screenshot(path=str(OUT / f'jobs-{width}.png'))
            await page.get_by_role('button', name='Delete job alpha', exact=True).click()
            dialog = page.get_by_role('dialog', name='Delete job?', exact=True)
            await dialog.get_by_role('button', name='Cancel', exact=True).click()
            assert not api.deletes
            if width == 1366:
                await page.get_by_role('button', name='Delete job alpha', exact=True).click()
                await dialog.get_by_role('button', name='Delete job', exact=True).click()
                await expect(dialog).not_to_be_visible()
                await expect(levels.get_by_role('button', name='Jobs', exact=False)).to_have_attribute('aria-pressed', 'true')
                await expect(page.locator('.d-title h3')).to_have_text('beta')
                await expect(page.get_by_role('button', name='Delete job alpha', exact=True)).to_have_count(0)
                assert api.deletes == ['/api_dft/delete/Work/researcher/alpha']
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert not errors, errors
            assert not api.unexpected, api.unexpected
            reports.append({'width': width, 'navigation': 'passed', 'search_state': 'passed', 'fork_selection': 'passed', 'empty_and_race': 'passed', 'session_restore': 'passed', 'delete': 'passed', 'errors': errors})
            print('PASS', width, flush=True)
            await context.close()
        await browser.close()
    (OUT / 'report.json').write_text(json.dumps(reports, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
