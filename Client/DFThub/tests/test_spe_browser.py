import asyncio
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect

BASE = os.getenv('BASE_URL', 'http://127.0.0.1:18289').rstrip('/') + '/workspace/'
OUT = Path(os.getenv('OUTPUT_DIR', str(Path(__file__).parent / 'qa-spe')))

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for width in (1440, 729, 390, 320):
            context = await browser.new_context(viewport={'width': width, 'height': 977}, reduced_motion='reduce')
            await context.add_init_script("localStorage.setItem('auth_token','test')")
            submitted = []
            states = {'input': '', 'ame418': ''}
            results = {}
            legacy = {'targetRows': [{'system': 'AME-system', 'reference': 1, 'calculated': 1.2}], 'summaryRows': [{'name': 'AE17', 'mue': .2}, {'name': 'Custom', 'mue': .1}], 'userTargetRows': [{'system': 'Input-system', 'reference': 2, 'calculated': 2.1}], 'userDatasetTitle': 'Custom Single Point Energy Results (SRP)', 'userTargetMue': .1}
            unexpected = []
            input_available = True
            async def route_api(route):
                request = route.request
                path = unquote(urlparse(request.url).path)
                if path.endswith('/me'):
                    return await route.fulfill(json={'success': True, 'user': {'id': 1, 'username': 'test', 'email': 'test@example.test'}})
                if path.endswith('/submit_count.txt'):
                    return await route.fulfill(content_type='text/plain', body='54')
                if path.endswith('/file_list'):
                    body = request.post_data_json
                    folder = body['file_dir'].rstrip('/')
                    if body['file_or_folder'] == 'folder':
                        return await route.fulfill(json={'result': [{'name': 'demo' if folder == 'Work/test' else 'weight_0', 'time_modify': 1790860000, 'status': 'Success', 'total_mue': 'Total MUE:1.0'}]})
                    names = ['basis.txt', 'Custom.tgz', 'Custom.ref'] if folder.endswith('/input') else ['process.log'] if '/output/' not in folder else ['CF22D_optimized.py', 'Parameters', 'Mue', 'weight.csv', 'process.log', 'SinglePointResults.json'] + [f'spe_{scope}.status.json' for scope, status in states.items() if status] + [f'spe_{scope}.log' for scope, status in states.items() if status] + [f'SinglePointResults.{scope}.json' for scope in results]
                    if folder.endswith('/input') and not input_available: names = ['basis.txt']
                    if '/output/' in folder and not folder.endswith('/input') and results.get('input', {}).get('descriptor_snapshot_id'):
                        names.append('InputDescriptors.json')
                    return await route.fulfill(json={'result': [{'name': name} for name in names]})
                if path.endswith('/submit'):
                    payload = request.post_data_json
                    submitted.append(payload)
                    assert payload['mode'] == 'spe' and payload['spe_scope'] in states
                    states[payload['spe_scope']] = 'Queued'
                    return await route.fulfill(json={'result': 'work submit success', 'spe_scope': payload['spe_scope']})
                filename = path.split('/')[-1]
                values = {'process.log': 'SUCCESS!', 'basis.txt': 'cc-pvqz', 'Parameters': 'Cx = 1', 'Mue': 'Dataset\tMUE\ninput\t1.0', 'weight.csv': 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nCustom\t\t\tuploaded\t1\t0.02\n', 'SinglePointResults.json': json.dumps(legacy)}
                if results.get('input', {}).get('descriptor_snapshot_id'):
                    values['InputDescriptors.json'] = json.dumps({'id': results['input']['descriptor_snapshot_id'], 'complete': True, 'grid_level': 6, 'basis': 'cc-pvqz'})
                for scope in states:
                    values[f'spe_{scope}.status.json'] = json.dumps({'scope': scope, 'status': states[scope], 'updated_at': 1790860000})
                    values[f'spe_{scope}.log'] = f'QUEUED\n{scope} calculation log\n'
                    if scope in results: values[f'SinglePointResults.{scope}.json'] = json.dumps(results[scope])
                if filename in values:
                    return await route.fulfill(content_type='text/plain', body=values[filename])
                unexpected.append(path)
                await route.fulfill(status=400, json={'message': 'Blocked test request'})
            await context.route('**/api_dft/**', route_api)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            await page.goto(BASE, wait_until='networkidle')
            await expect(page.get_by_role('button', name='Calculate Input', exact=True)).to_be_enabled()
            await expect(page.locator('.d-head').get_by_role('button', name='Calculate AME418', exact=True)).to_have_count(0)
            await page.get_by_role('tab', name='Self-consistent results', exact=True).click()
            choices = page.get_by_role('group', name='Calculation dataset')
            panel = page.get_by_role('tabpanel')
            table = page.get_by_role('table', name='Single-point energies', exact=True)
            await expect(table).to_contain_text('Input-system')
            await expect(table).not_to_contain_text('AME-system')
            await choices.get_by_role('button', name='AME418', exact=True).click()
            await expect(panel.get_by_role('button', name='Calculate AME418', exact=True)).to_be_enabled()
            await expect(table).to_contain_text('AME-system')
            await expect(table).not_to_contain_text('Input-system')
            await expect(page.get_by_role('table', name='Single-point database summary')).not_to_contain_text('Custom')
            await page.locator('.d-head').get_by_role('button', name='Calculate Input', exact=True).click()
            await expect(choices.get_by_role('button', name='Input', exact=True)).to_have_attribute('aria-pressed', 'true')
            await expect(page.locator('.d-head').get_by_role('button', name='Stop Input', exact=True)).to_be_enabled()
            await expect(page.locator('.d-head').get_by_role('button', name='Calculate AME418', exact=True)).to_have_count(0)
            assert len(submitted) == 1 and submitted[0]['spe_scope'] == 'input'
            await page.reload(wait_until='networkidle')
            await expect(page.get_by_role('button', name='Stop Input', exact=True)).to_be_enabled()
            await page.get_by_role('tab', name='Self-consistent results', exact=True).click()
            await choices.get_by_role('button', name='AME418', exact=True).click()
            await panel.get_by_role('button', name='Calculate AME418', exact=True).click()
            await expect(choices.get_by_role('button', name='AME418', exact=True)).to_have_attribute('aria-pressed', 'true')
            assert len(submitted) == 2 and submitted[1]['spe_scope'] == 'ame418'
            await expect(panel.get_by_role('button', name='Stop AME418', exact=True)).to_be_enabled()
            await expect(page.locator('.d-head').get_by_role('button', name='Stop AME418', exact=True)).to_be_enabled()
            states['input'] = 'Success'
            results['input'] = {'scope': 'input', 'complete': True, 'targetRows': [{'system': 'Fresh-Input', 'reference': 1, 'calculated': 1}], 'summaryRows': []}
            await page.get_by_role('button', name='Refresh', exact=True).click()
            await choices.get_by_role('button', name='Input', exact=True).click()
            await expect(table).to_contain_text('Fresh-Input')
            await expect(page.locator('.d-head').get_by_role('button', name='Calculate Input', exact=True)).to_be_enabled()
            await expect(page.locator('.d-head').get_by_role('button', name='Stop AME418', exact=True)).to_be_enabled()
            results['input'].update(trainingComplete=True, testComplete=False, evaluationComplete=False,
                                    descriptor_snapshot_id='a' * 32, testTargetMue=.6675,
                                    testCoverage={'completedMolecules': 9, 'totalMolecules': 10,
                                                  'completedReactions': 8, 'totalReactions': 9,
                                                  'failedMolecules': ['Li4_IRC_0043']})
            await page.get_by_role('button', name='Refresh', exact=True).click()
            refine = panel.get_by_role('button', name='Re-optimize with SCF descriptors', exact=True)
            await expect(refine).to_be_enabled()
            await expect(panel).to_contain_text('Training SCF complete · Test set incomplete')
            await expect(panel).to_contain_text('Li4_IRC_0043')
            for state in ('Queued', 'Running', 'Failed'):
                states['input'] = state
                await page.get_by_role('button', name='Refresh', exact=True).click()
                await expect(refine).to_be_disabled()
            states['input'] = 'Success'
            results['input']['trainingComplete'] = False
            await page.get_by_role('button', name='Refresh', exact=True).click()
            await expect(refine).to_be_disabled()
            results['input']['trainingComplete'] = True
            await page.get_by_role('button', name='Refresh', exact=True).click()
            await expect(refine).to_be_enabled()
            await choices.get_by_role('button', name='AME418', exact=True).click()
            await expect(panel.get_by_role('button', name='Stop AME418', exact=True)).to_be_enabled()
            await expect(table).to_contain_text('AME-system')
            await expect(table).not_to_contain_text('Fresh-Input')
            await page.locator('#detail').evaluate("e=>e.scrollIntoView({block:'start',behavior:'instant'})")
            await page.screenshot(path=str(OUT / f'spe-{width}.png'))
            if width == 1440:
                input_available = False
                states['ame418'] = 'Success'
                await page.get_by_role('button', name='Refresh', exact=True).click()
                await expect(page.locator('.d-head').get_by_role('button', name='Calculate Input', exact=True)).to_be_disabled()
                await expect(page.locator('.d-head').get_by_role('button', name='Calculate AME418', exact=True)).to_have_count(0)
                await expect(panel.get_by_role('button', name='Calculate AME418', exact=True)).to_be_enabled()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert not errors, errors
            assert not unexpected, unexpected
            print('PASS', width, 'independent scopes, legacy/results isolation, persistent status', flush=True)
            await context.close()
        await browser.close()

asyncio.run(main())
