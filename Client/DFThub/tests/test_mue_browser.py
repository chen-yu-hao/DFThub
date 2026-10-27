import asyncio
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect

BASE = os.getenv('BASE_URL', 'http://127.0.0.1:18289').rstrip('/') + '/workspace/'
OUT = Path(os.getenv('OUTPUT_DIR', '/tmp/dfthub-mue-tNOLeSjd/qa'))
NATIVE = json.loads(Path(os.getenv('CF22D_FIXED_JSON', str(Path(__file__).resolve().parents[1] / 'src/replica/cf22d-native.json'))).read_text())
MUE = '------------SUMMARY-------------\nBH76RC\t1.055\nDBH24\t1.33\ninput\t0.592\nZeroSet\t0\nnew_total_mue:1.908\n\n------------LOSS----------------\nWeighted MUE sum:\t527.95\nRegularization (0.01*(a+b+c)):\t14.29\nTotal loss:\t542.24\n'
ORIGINAL = '------------SUMMARY-------------\nDBH24_ref\t999\nINPUT_ref\t1.4192029804968316\nBH76RC_ref\t999\nZeroSet_ref\t0\nWeighted MUE sum:\t999\nRegularization (0.01*(a+b+c)):\t100\nTotal loss:\t1099\n'

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        results = []
        for width in [1440, 729, 390, 320]:
            context = await browser.new_context(viewport={'width': width, 'height': 977}, reduced_motion='reduce')
            await context.add_init_script("localStorage.setItem('auth_token','test');localStorage.setItem('dfthub.theme','\"light\"')")
            missing = False
            wrong_hash = False
            unexpected = []
            async def route_handler(route):
                path = unquote(urlparse(route.request.url).path)
                if not path.startswith('/api_dft/'):
                    return await route.continue_()
                if path.endswith('/me'):
                    return await route.fulfill(json={'success': True, 'user': {'id': 1, 'username': 'demo', 'email': 'demo@example.test'}})
                if path.endswith('/submit_count.txt'):
                    return await route.fulfill(content_type='text/plain', body='54')
                if path.endswith('/file_list'):
                    body = route.request.post_data_json
                    folder = body['file_dir'].rstrip('/')
                    if body['file_or_folder'] == 'folder':
                        return await route.fulfill(json={'result': [{'name': 'DARC' if folder == 'Work/demo' else 'weight_5', 'time_modify': 1790860000, 'status': 'Success', 'total_mue': 'Total loss:\t542.2438'}]})
                    names = ['basis.txt'] if folder.endswith('/input') else ['process.log'] if '/output/' not in folder else ['Mue', 'Parameters', 'weight.csv', 'process.log', 'OriginalMue', 'OriginalMue.meta.json']
                    if missing: names = [name for name in names if name != 'OriginalMue']
                    return await route.fulfill(json={'result': [{'name': name} for name in names]})
                values = {'OriginalMue': ORIGINAL, 'OriginalMue.meta.json': json.dumps({'source': 'libxc-native-cf22d', 'parameter_sha256': 'old-parameter-hash' if wrong_hash else NATIVE['parameter_sha256']}), 'Mue': MUE, 'Parameters': 'Cx(0,0,0) = 0.342\nHF% = 46.2806\n', 'weight.csv': 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nDemo\tUser data\t\tuploaded\t12\t0.02\n', 'process.log': 'SUCCESS!', 'basis.txt': 'cc-pvqz'}
                if path.split('/')[-1] in values:
                    return await route.fulfill(content_type='text/plain', body=values[path.split('/')[-1]])
                unexpected.append(path)
                await route.fulfill(status=400, json={'message': 'Unmatched mocked request'})
            await context.route('**/api_dft/**', route_handler)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda err: errors.append(str(err)))
            await page.goto(BASE, wait_until='networkidle')
            await expect(page.get_by_role('tabpanel')).to_have_attribute('aria-busy', 'false')
            chart = page.get_by_role('region', name='MUE analysis')
            await chart.get_by_role('group', name='MUE views').get_by_role('button', name='MUE by dataset', exact=True).click()
            await expect(chart.locator('.mue-pair')).to_have_count(4)
            await expect(chart.locator('.mue-dataset').first).to_have_text('Input')
            assert 'Weighted MUE' not in await chart.inner_text()
            assert 'Regularization' not in await chart.inner_text()
            assert 'Total loss' not in await chart.inner_text()
            await expect(chart.get_by_label('Input Original MUE', exact=True)).to_have_text('1.42')
            await expect(chart.get_by_label('BH76RC Original MUE', exact=True)).to_have_text(f"{NATIVE['datasets']['BH76RC']:.2f}")
            await expect(chart.get_by_label('DBH24 Original MUE', exact=True)).to_have_text(f"{NATIVE['datasets']['DBH24']:.2f}")
            await expect(chart).to_contain_text('Original (CF22D)')
            await expect(chart.get_by_label('Input Optimized MUE', exact=True)).to_have_text('0.59')
            assert await chart.locator('.axis span.num').last.inner_text() == '2'
            zero = chart.locator('[data-dataset="zeroset"] .bar.optimized')
            assert (await zero.bounding_box())['width'] == 0
            assert await chart.evaluate('e => getComputedStyle(e).color') == 'rgb(32, 30, 30)'
            await expect(page.get_by_text('Run settings', exact=True)).to_have_count(0)
            await expect(page.get_by_role('tab', name='Self-consistent results', exact=True)).to_be_visible()
            await expect(page.get_by_role('tab', name='Energies', exact=True)).to_have_count(0)
            await expect(page.get_by_role('cell', name='542.24', exact=False)).to_have_count(0)
            params = page.locator('.parameters-panel')
            assert (await params.bounding_box())['y'] < (await chart.bounding_box())['y']
            await params.locator('summary').click()
            await expect(params).to_contain_text('HF% = 46.2806')
            await params.locator('summary').click()
            await params.evaluate("e => e.scrollIntoView({block:'start', behavior:'instant'})")
            await page.screenshot(path=str(OUT / f'mue-{width}.png'))
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            wrong_hash = True
            await page.get_by_role('button', name='Refresh', exact=True).click()
            await expect(chart.get_by_label('Input Original MUE', exact=True)).to_have_text('—')
            await expect(chart.get_by_label('BH76RC Original MUE', exact=True)).to_have_text(f"{NATIVE['datasets']['BH76RC']:.2f}")
            await expect(chart.locator('.bar.original')).to_have_count(2)
            wrong_hash = False
            missing = True
            await page.get_by_role('button', name='Refresh', exact=True).click()
            await expect(chart.get_by_label('Input Original MUE', exact=True)).to_have_text('—')
            await expect(chart.locator('.bar.original')).to_have_count(2)
            await page.get_by_role('button', name='Open account menu').click()
            await page.get_by_role('menuitem', name='Appearance:', exact=False).click()
            await page.keyboard.press('Escape')
            assert await chart.evaluate('e => getComputedStyle(e).color') != 'rgb(32, 30, 30)'
            assert not errors, errors
            assert not unexpected, unexpected
            results.append({'width': width, 'datasets': 4, 'max_axis': 2, 'native_fixed_values': True, 'input_provenance_checked': True, 'missing_not_zero': True, 'errors': errors})
            print('PASS', width, flush=True)
            await context.close()
        await browser.close()
    (OUT / 'report.json').write_text(json.dumps(results, indent=2))

asyncio.run(main())
