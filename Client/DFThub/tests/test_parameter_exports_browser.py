"""Exports preserve selected-run bytes; optional test MUE stays out of reference statistics."""
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect
from test_sidebar_browser import NATIVE, USER, BASE

OUT = Path(os.getenv('OUTPUT_DIR', '/tmp/dfthub-parameter-exports-qa'))


class Api:
    with_test = True
    with_parameters = True
    partial_test = False

    def output(self, fork):
        number = '6.8030840332869869e-01' if fork else '9.1000000000000003e-01'
        files = {
            'process.log': 'SUCCESS!\n', 'Parameters': 'Parameters\nCx(0,0,0) = ' + number + '\n',
            'NEW-params.txt': number + '\n-4.7080250312665506e-01\n',
            'CF22D_optimized.py': '# Selected functional\nCX = ' + number + '\n',
            'Mue': 'input\t0.31\nNCCE30\t0.28\nπIE3\t3.19\nπPa10\t2.80\n',
            'OriginalMue': 'Input\t6.34\n',
            'OriginalMue.meta.json': json.dumps({'source': 'libxc-native-cf22d', 'parameter_sha256': NATIVE['parameter_sha256']}),
            'weight.csv': 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nTrain\t\t\tuploaded\t8\t0.04\nNCCE30\t\tbuilt-in\tTMB11\t\t0.06937893786996\nπIE3\t\tbuilt-in\tTMB11\t\t0.83368920833887\nπPa10\t\tbuilt-in\tTMB11\t\t0.396789968023809\n',
            'results.json': json.dumps({name: {'MUE': value, 'res': [value] * count} for name, value, count in [('INPUT_ref', .31, 8), ('NCCE30_ref', .28, 23), ('πIE3_ref', 3.19, 3), ('πPa10_ref', 2.8, 10)]}),
            'TestMue': 'test_input\t1.067462\n', 'TestOriginalMue': 'test_input\t1.176663\n',
            'TestMue.json': json.dumps({'scope': 'test', 'complete': not self.partial_test, 'targetMue': 1.067462, 'count': 9}),
            'TestOriginalMue.meta.json': json.dumps({'source': 'libxc-native-cf22d', 'parameter_sha256': NATIVE['parameter_sha256']}),
        }
        if not self.with_test:
            files = {name: value for name, value in files.items() if not name.startswith('Test')}
        if not self.with_parameters:
            for name in ['Parameters', 'NEW-params.txt', 'CF22D_optimized.py']:
                files.pop(name)
        return files

    async def route(self, route):
        path = unquote(urlparse(route.request.url).path)
        if path.endswith('/me'):
            return await route.fulfill(json={'success': True, 'user': USER})
        if path.endswith('/submit_count.txt'):
            return await route.fulfill(body='1')
        if path.endswith('/file_list'):
            body = route.request.post_data_json
            folder = body['file_dir'].rstrip('/')
            if body['file_or_folder'] == 'folder':
                names = ['demo'] if folder == 'Work/researcher' else ['weight_0'] if folder.endswith('/output') else ['fork-1'] if folder.endswith('/weight_0') else []
            elif folder.endswith('/input'):
                names = ['basis.txt', 'train.tgz', 'train.ref']
            else:
                names = list(self.output('/fork-1' in folder)) if '/output/' in folder else ['process.log']
            return await route.fulfill(json={'result': [{'name': name, 'status': 'Success', 'time_modify': 1790930000} for name in names]})
        if '/download/' in path:
            filename = path.rsplit('/', 1)[-1]
            content = 'aug-cc-pvtz\n' if filename == 'basis.txt' else self.output('/fork-1/' in path).get(filename)
            assert content is not None, path
            return await route.fulfill(content_type='text/plain', body=content)
        raise AssertionError('Unexpected request: ' + path)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=os.getenv('CHROMIUM_PATH'))
        context = await browser.new_context(viewport={'width': 882, 'height': 956}, reduced_motion='reduce')
        await context.add_init_script("localStorage.setItem('auth_token','test');localStorage.setItem('dfthub.theme','\"dark\"')")
        api = Api()
        await context.route('**/api_dft/**', api.route)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(BASE + '?job=demo&run=weight_0%2Ffork-1', wait_until='networkidle')
        await expect(page.locator('.test-summary .summary-value')).to_contain_text('1.07')
        await expect(page.locator('.test-summary')).to_contain_text('1.18')
        await expect(page.locator('.mue-summary')).to_contain_text('of 3')

        async def export(button, source, fork=True):
            async with page.expect_download() as pending:
                await button.click()
            download = await pending.value
            suffix = 'parameters.txt' if source == 'Parameters' else source
            assert download.suggested_filename == 'demo-weight_0' + ('-fork-1' if fork else '') + '-' + suffix
            target = OUT / download.suggested_filename
            await download.save_as(target)
            assert target.read_text() == api.output(fork)[source], source

        await export(page.locator('.d-head').get_by_role('button', name='Export parameters', exact=True), 'Parameters')
        await page.locator('.parameters-summary').click()
        actions = page.get_by_role('group', name='Export functional parameters', exact=True)
        for label, source in [('Export parameters', 'Parameters'), ('Raw parameters (.txt)', 'NEW-params.txt'), ('PySCF functional (.py)', 'CF22D_optimized.py')]:
            await export(actions.get_by_role('button', name=label, exact=True), source)
        await page.locator('.parameters-panel').screenshot(path=str(OUT / 'parameters-dark.png'))

        views = page.get_by_role('group', name='MUE views')
        for label in ['Overall MUE by type', 'MUE by dataset']:
            await views.get_by_role('button', name=label, exact=True).click()
            test = page.locator('.mue-pair[data-dataset="test_input"]')
            await expect(test.get_by_label('Test Optimized MUE', exact=True)).to_have_text('1.07')
            await expect(test.get_by_label('Test Original MUE', exact=True)).to_have_text('1.18')
            await expect(test).to_contain_text('9 data points')
        await views.get_by_role('button', name='Overall MUE by type', exact=True).click()
        await page.locator('.mue-comparison').screenshot(path=str(OUT / 'test-mue-dark.png'))

        await page.get_by_role('tab', name='Weights', exact=True).click()
        filters = page.get_by_role('group', name='Filter by type')
        await expect(filters.get_by_role('button', name=re.compile('built-in'))).to_have_count(0)
        for category, name in [('NC', 'NCCE30'), ('IE', 'πIE3'), ('TC', 'πPa10')]:
            await filters.get_by_role('button', name=re.compile('^' + category)).click()
            await expect(page.locator('.wt tbody tr')).to_have_count(1)
            await expect(page.locator('.wt tbody tr')).to_contain_text(name)

        await page.get_by_role('group', name='Sidebar level').get_by_role('button', name=re.compile('^Runs')).click()
        await page.get_by_role('option', name=re.compile('^weight_0 ')).click()
        await export(page.locator('.d-head').get_by_role('button', name='Export parameters', exact=True), 'Parameters', fork=False)
        await page.get_by_role('tab', name='Overview', exact=True).click()
        await page.set_viewport_size({'width': 390, 'height': 956})
        await page.evaluate("document.documentElement.dataset.theme='light'")
        await views.get_by_role('button', name='Overview', exact=True).click()
        await expect(page.locator('.test-summary')).to_be_visible()
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        await page.locator('.mue-summary').screenshot(path=str(OUT / 'test-summary-mobile.png'))

        api.partial_test = True
        await page.get_by_role('button', name='Refresh', exact=True).click()
        await expect(page.locator('.test-summary .summary-value')).to_contain_text('—')
        await views.get_by_role('button', name='Overall MUE by type', exact=True).click()
        await expect(page.get_by_label('Test Optimized MUE', exact=True)).to_have_text('—')
        api.with_test = False
        await page.get_by_role('button', name='Refresh', exact=True).click()
        await expect(page.locator('.mue-pair[data-dataset="test_input"]')).to_have_count(0)
        await views.get_by_role('button', name='Overview', exact=True).click()
        await expect(page.locator('.test-summary')).to_have_count(0)
        api.with_parameters = False
        await page.get_by_role('button', name='Refresh', exact=True).click()
        await expect(page.get_by_role('button', name='Export parameters', exact=True)).to_have_count(0)
        assert not errors, errors
        print('PASS exact parameter exports and selected-run switching; Test MUE in all views; no-test/partial states; NC/IE/TC filters; mobile layout', flush=True)
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
