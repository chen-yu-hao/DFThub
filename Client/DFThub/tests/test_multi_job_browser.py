"""Cross-Job Analyze selection and inverse-weight axis ordering."""
import asyncio
import json
import os
from urllib.parse import unquote, urlparse
from pathlib import Path
from playwright.async_api import async_playwright, expect
from test_analyze_v2_browser import Api, RUNS, DATASETS, USER

BASE = os.getenv('BASE_URL', 'http://127.0.0.1:18289').rstrip('/')
OUT = Path(os.getenv('OUTPUT_DIR', str(Path(__file__).parent / 'qa-multi-job')))


class MultiApi(Api):
    def __init__(self):
        super().__init__()
        self.jobs = ['alpha', 'beta']

    def outputs_for(self, job, run):
        values = super().outputs(run if run in RUNS else 'weight_0')
        if job == 'beta':
            weight = {'weight_0': '0.02', 'weight_1': '0.003'}[run]
            values['weight.csv'] = values['weight.csv'].replace('\t0.02', '\t' + weight, 1)
            values['basis.txt'] = 'cc-pvtz'
            values['Mue'] = values['Mue'].replace('\t1.86', '\t0.91').replace('\t1.58', '\t0.44')
        else:
            values['basis.txt'] = 'def2-svp'
        return values

    async def route(self, route):
        request = route.request
        path = unquote(urlparse(request.url).path)
        if path.endswith('/file_list'):
            body = request.post_data_json
            folder = body['file_dir'].rstrip('/')
            if body['file_or_folder'] == 'folder':
                if folder == 'Work/researcher':
                    return await route.fulfill(json={'result': [{'name': 'alpha', 'status': 'Success', 'time_modify': 1790930000}, {'name': 'beta', 'status': 'Success', 'time_modify': 1790920000}]})
                if folder.endswith('/alpha/output'):
                    return await route.fulfill(json={'result': [{'name': name, 'status': 'Success', 'time_modify': 1790930000 - i} for i, name in enumerate(['weight_0', 'weight_1'])]})
                if folder.endswith('/beta/output'):
                    return await route.fulfill(json={'result': [{'name': name, 'status': 'Success', 'time_modify': 1790930000 - i} for i, name in enumerate(['weight_0', 'weight_1'])]})
            names = ['basis.txt', 'Custom.tgz', 'Custom.ref'] if folder.endswith('/input') else ['Mue', 'weight.csv', 'OriginalMue', 'OriginalMue.meta.json', 'InputDescriptors.json', 'NEW-params.txt'] if '/output/' in folder else ['process.log']
            return await route.fulfill(json={'result': [{'name': name} for name in names]})
        if '/download/' in path:
            if path.endswith('/input/basis.txt'):
                return await route.fulfill(content_type='text/plain', body='def2-svp' if '/alpha/' in path else 'cc-pvtz')
            parts = path.split('/output/')
            if len(parts) == 2:
                job, suffix = parts[0].split('/')[-1], parts[1]
                run, filename = suffix.rsplit('/', 1)
                values = self.outputs_for(job, run)
                if filename in values:
                    return await route.fulfill(content_type='text/plain', body=values[filename])
        return await super().route(route)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1366, 'height': 977}, reduced_motion='reduce')
        await context.add_init_script("localStorage.setItem('auth_token','test');localStorage.setItem('dfthub.theme','\"light\"')")
        api = MultiApi()
        await context.route('**/*', api.route)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(BASE + '/analyze/?jobs=alpha,beta', wait_until='networkidle')
        await expect(page.locator('#analyze')).to_have_attribute('aria-busy', 'false')
        await expect(page.locator('#anJobTitle')).to_have_text('2 Jobs')
        await expect(page.locator('#anMeta')).to_contain_text('Mixed basis sets')
        levels = page.get_by_role('group', name='Sidebar level', exact=True)
        await levels.get_by_role('button', name='Jobs', exact=False).click()
        await expect(page.get_by_role('checkbox', name='Include Job alpha', exact=True)).to_be_checked()
        await expect(page.get_by_role('checkbox', name='Include Job beta', exact=True)).to_be_checked()
        await levels.get_by_role('button', name='Runs', exact=False).click()
        runs = page.locator('#anList .run-option')
        await expect(runs).to_have_count(4)
        labels = await runs.locator('.job-name').all_text_contents()
        assert labels[0].startswith('beta ·'), labels
        assert labels == ['alpha · w0', 'beta · w0', 'alpha · w1', 'beta · w1'], labels
        axis = await page.locator('[data-chart="trend"] svg').text_content()
        assert axis.count('w 0.02') == 1 and axis.index('w 0.02') < axis.index('w 0.01') < axis.index('w 0.003'), axis
        await page.screenshot(path=str(OUT / 'multi-job.png'), full_page=True)
        await levels.get_by_role('button', name='Jobs', exact=False).click()
        await page.get_by_role('checkbox', name='Include Job beta', exact=True).click(force=True)
        await expect(page.locator('#anJobTitle')).to_have_text('alpha')
        await expect(page.locator('#anMeta')).not_to_contain_text('Mixed basis sets')
        await levels.get_by_role('button', name='Runs', exact=False).click()
        await expect(page.locator('#anList .run-option')).to_have_count(2)
        await levels.get_by_role('button', name='Jobs', exact=False).click()
        await page.get_by_role('checkbox', name='Include Job beta', exact=True).click(force=True)
        await expect(page.locator('#anJobTitle')).to_have_text('2 Jobs')
        assert 'jobs=alpha%2Cbeta' in page.url or 'jobs=alpha,beta' in page.url, page.url
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert not errors, errors
        assert not api.unexpected, api.unexpected
        await context.close()
        await browser.close()
    print('PASS cross-Job selection, mixed-basis metadata, namespaced labels, inverse-weight ordering and deselection')


if __name__ == '__main__':
    asyncio.run(main())
