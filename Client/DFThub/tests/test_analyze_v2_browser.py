"""Analyze v2 integration. Every application API request is intercepted."""
import asyncio
import csv
import io
import json
import os
import re
import struct
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

from playwright.async_api import async_playwright, expect

BASE = os.getenv('BASE_URL', 'http://127.0.0.1:18289').rstrip('/')
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.getenv('OUTPUT_DIR', str(Path(__file__).parent / 'qa-analyze-v2')))
NATIVE = json.loads((ROOT / 'src/replica/cf22d-native.json').read_text())
RUNS = ['weight_0', 'weight_1', 'weight_2', 'weight_2/fork-1', 'weight_2/fork-2', 'weight_2/fork-3']
DATASETS = ['BH76RC', 'DBH24', 'AE17', 'S22', 'S66', 'G21EA', 'pAEE5', 'MR-TMD-BE3']
USER = {'id': 1, 'username': 'researcher', 'email': 'researcher@example.test'}


class Api:
    def __init__(self):
        self.submits = []
        self.unexpected = []
        self.states = {'weight_2/fork-3': 'Queued'}
        self.fail_submit = False
        self.fail_mue = False
        self.hold = asyncio.Event()
        self.hold.set()
        self.zero = False
        self.no_baseline = False
        self.omit_overlap = False
        self.requests = []

    def outputs(self, run):
        index = RUNS.index(run) if run in RUNS else 0
        input_mue = 0 if self.zero else [1.86, 1.58, 1.37, 1.3, 1.26, 1.22][index]
        values = {name: 0 if self.zero or name == 'AE17' else round((i + 1) * .2 + index * .03, 4) for i, name in enumerate(DATASETS)}
        # A missing cell must stay unavailable, never be presented as zero.
        if index == 5:
            values.pop('S66')
        mue = '\n'.join([f'input\t{input_mue}'] + [f'{name}\t{value}' for name, value in values.items()]) + '\n------------LOSS-------------\nWeighted MUE sum:\t999\nRegularization:\t3\nTotal loss:\t1002'
        weights = 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nCustom\t\t\tuploaded\t3\t' + str(.02 / (min(index, 2) + 1)) + '\n'
        weights += '\n'.join(f'{name}\tReference\t' + ('BH' if i < 2 else 'NC' if i in (3, 4) else 'TC') + f'\tReference\t{i + 1}\t{.1 + index * .01}' for i, name in enumerate(DATASETS))
        result = {'Mue': mue, 'weight.csv': weights, 'OriginalMue': 'input\t4.22',
                  'OriginalMue.meta.json': json.dumps({'source': 'libxc-native-cf22d', 'parameter_sha256': 'unverified' if self.no_baseline else NATIVE['parameter_sha256']}),
                  'InputDescriptors.json': '{"complete":true,"grid_level":6}', 'basis.txt': 'cc-pvtz', 'process.log': 'SUCCESS!\n'}
        if index >= 3:
            result['run.json'] = json.dumps({'parent': RUNS[index - 1], 'grid_level': 6, 'basis': 'cc-pvtz', 'created_at': 1790930000 + index})
        if index < 4 or self.states.get(run) == 'Success':
            payload = {'scope': 'input', 'complete': True, 'targetMue': 0 if self.zero else input_mue + .2, 'targetRows': [{'system': 'H2', 'reference': 1, 'calculated': 1.2, 'unbiasedError': .2}]}
            if not (self.omit_overlap and run == 'weight_1'):
                payload['wavefunction_overlap'] = {'metric': 'occupied_slater_determinant_overlap', 'reference': 'Initial CF22D density checkpoint', 'available': 1, 'total': 1, 'mean': .96 - index * .01, 'rows': [{'molecule': 'H2', 'status': 'available', 'overlap': .96 - index * .01, 'alpha': .98, 'beta': .98}]}
            result['SinglePointResults.input.json'] = json.dumps(payload)
        if run in self.states:
            result['spe_input.status.json'] = json.dumps({'scope': 'input', 'status': self.states[run]})
        return result

    async def route(self, route):
        request = route.request
        path = unquote(urlparse(request.url).path)
        if not path.startswith('/api_dft/'):
            return await route.continue_()
        self.requests.append((request.method, path))
        if path.endswith('/me'):
            return await route.fulfill(json={'success': True, 'user': USER})
        if path.endswith('/submit_count.txt'):
            return await route.fulfill(content_type='text/plain', body='69')
        if path.endswith('/file_list'):
            body = request.post_data_json
            folder = body['file_dir'].rstrip('/')
            if body['file_or_folder'] == 'folder':
                names = ['alpha', 'single', 'empty'] if folder == 'Work/researcher' else []
                if folder.endswith('/output'):
                    names = [] if '/empty/' in folder else ['weight_0'] if '/single/' in folder else RUNS[:3]
                elif folder.endswith('/alpha/output/weight_2'):
                    names = ['fork-1', 'fork-2', 'fork-3']
                return await route.fulfill(json={'result': [{'name': name, 'status': 'Success', 'time_modify': 1790930000 + i} for i, name in enumerate(names)]})
            if folder.endswith('/input'):
                names = ['basis.txt', 'Custom.tgz', 'Custom.ref']
            elif '/output/' in folder:
                run = folder.split('/output/', 1)[1]
                names = list(self.outputs(run)) + ['NEW-params.txt']
            else:
                names = ['process.log']
            return await route.fulfill(json={'result': [{'name': name} for name in names]})
        if path.endswith('/submit'):
            payload = request.post_data_json
            assert payload['mode'] == 'spe' and payload['spe_scope'] == 'input'
            assert payload['work_dir'] == 'Work/researcher/alpha'
            self.submits.append(payload)
            await self.hold.wait()
            if self.fail_submit:
                return await route.fulfill(status=409, json={'msg': 'SCF is unavailable for this run'})
            run = payload['weightFile'] + ('/' + payload['fork'] if payload.get('fork') else '')
            self.states[run] = 'Queued'
            return await route.fulfill(json={'result': 'work submit success'})
        if '/download/' in path:
            filename = path.rsplit('/', 1)[-1]
            run = path.split('/output/', 1)[-1].rsplit('/', 1)[0] if '/output/' in path else 'weight_0'
            if run.endswith('/input'):
                run = run[:-6]
            if self.fail_mue and filename == 'Mue' and run == RUNS[-1]:
                return await route.fulfill(status=503, json={'msg': 'MUE temporarily unavailable'})
            values = self.outputs(run)
            if filename in values:
                return await route.fulfill(content_type='text/plain', body=values[filename])
        self.unexpected.append(f'{request.method} {path}')
        return await route.fulfill(status=400, json={'msg': 'Unexpected fixture request'})


async def ready(page):
    await expect(page.locator('#analyze')).to_have_attribute('aria-busy', 'false')
    await expect(page.locator('#anJobTitle')).to_have_text('alpha')
    await expect(page.get_by_role('tab', name='Trends', exact=True)).to_be_visible()


async def valid_svg(page):
    invalid = await page.locator('#anPanel svg').evaluate_all("els => els.flatMap(svg => [...svg.querySelectorAll('*')]).flatMap(e => [...e.attributes]).filter(a => /NaN|Infinity/.test(a.value)).map(a => a.name + '=' + a.value)")
    assert not invalid, invalid


async def export_figure(page, figure, chart, *, png=False):
    await figure.get_by_role('button', name='Export', exact=True).click()
    dialog = page.get_by_role('dialog', name='Export figure', exact=True)
    await expect(dialog).to_be_visible()
    await expect(dialog.locator('#anExpImg')).to_have_js_property('complete', True)
    assert await dialog.locator('#anExpImg').evaluate('image => image.naturalWidth > 0')
    await dialog.get_by_label('Panel label', exact=True).fill('a')
    await dialog.get_by_role('button', name='PNG' if png else 'SVG', exact=True).click()
    if png:
        await dialog.get_by_role('button', name='300 dpi', exact=True).click()
    async with page.expect_download() as info:
        await dialog.get_by_role('button', name='Download PNG' if png else 'Download SVG', exact=True).click()
    download = await info.value
    target = OUT / download.suggested_filename
    await download.save_as(target)
    assert target.stat().st_size > 100
    if png:
        data = target.read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        p = data.index(b'pHYs')
        x, y, unit = struct.unpack('>IIB', data[p + 4:p + 13])
        assert unit == 1 and abs(x * .0254 - 300) < .1 and x == y
    else:
        svg = target.read_text()
        ElementTree.fromstring(svg)
        assert 'NaN' not in svg and 'Infinity' not in svg
        assert 'width="89mm"' in svg and '<text' in svg and 'Arial' in svg
        assert '<rect' in svg and 'fill="#ffffff"' in svg
        assert re.search(r'>a</text>', svg)
    print('PASS export', chart, 'png' if png else 'svg', flush=True)
    return target


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1366, 'height': 977}, reduced_motion='reduce')
        await context.add_init_script("localStorage.setItem('auth_token','test');localStorage.setItem('dfthub.theme','\"light\"')")
        api = Api()
        await context.route('**/*', api.route)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        await page.goto(BASE + '/analyze/?job=alpha', wait_until='networkidle')
        await ready(page)
        await expect(page.get_by_role('group', name='Summary for weight_2/fork-3')).to_contain_text('1.22')
        await expect(page.get_by_role('group', name='Summary for weight_2/fork-3')).to_contain_text('Calculating')
        await expect(page.locator('.an-kpi-label', has_text='Test set MUE · non-SCF')).to_have_count(0)
        await expect(page.locator('#anDetail')).not_to_contain_text('Sample data')
        await expect(page.locator('#anList input[type=checkbox]')).to_have_count(6)
        await valid_svg(page)
        await page.screenshot(path=str(OUT / 'trends-desktop.png'), full_page=True)
        trend = page.get_by_role('figure', name='MUE across runs', exact=True)
        trade = page.get_by_role('figure', name='Your data set vs reference databases', exact=True)
        await trend.get_by_role('button', name='Table', exact=True).click()
        await expect(trend.get_by_role('table')).to_contain_text('4.22')
        await expect(trend.get_by_role('table')).to_contain_text('1.86')
        await trend.get_by_role('button', name='Chart', exact=True).click()
        await trend.get_by_role('button', name='Add reference datasets', exact=True).click()
        picker = page.get_by_role('dialog', name='Add reference datasets', exact=True)
        await picker.get_by_role('searchbox', name='Search reference datasets').fill('AE17')
        await picker.locator('label.an-picker-item').filter(has_text='AE17').click()
        await page.keyboard.press('Escape')
        await expect(trend.locator('.an-chip')).to_contain_text('AE17')
        await trend.get_by_role('button', name='Log', exact=True).click()
        await valid_svg(page)
        assert 'scale=log' in page.url and 'ds=AE17' in page.url
        await page.reload(wait_until='networkidle')
        await ready(page)
        await expect(trend.get_by_role('button', name='Log', exact=True)).to_have_attribute('aria-pressed', 'true')
        await trend.get_by_role('button', name='Linear', exact=True).click()
        await export_figure(page, trend, 'trend')
        await export_figure(page, trend, 'trend', png=True)
        await export_figure(page, trade, 'tradeoff')
        # Analysis always uses the published CF22D parameters as its baseline.
        await expect(page.locator('#anBaseline')).to_have_count(0)
        await page.get_by_role('checkbox', name='Include weight_2/fork-2 in analysis', exact=True).uncheck()
        await expect(page.get_by_role('group', name='Summary for weight_2/fork-3')).to_contain_text('CF22D')
        await page.locator('#anList .job[title="weight_0"]').click()
        await expect(page.get_by_role('group', name='Summary for weight_0')).to_contain_text('CF22D')
        await page.get_by_role('checkbox', name='Include weight_2/fork-2 in analysis', exact=True).check()
        await page.get_by_role('tab', name='Input vs SCF', exact=True).click()
        await valid_svg(page)
        scf = page.get_by_role('figure', name='Input MUE: non-SCF vs SCF', exact=True)
        await scf.get_by_role('button', name='Table', exact=True).click()
        await expect(scf.get_by_role('table')).to_contain_text('2.06')
        await expect(scf.get_by_role('table')).to_contain_text('Calculating')
        await export_figure(page, scf, 'scf')
        await page.get_by_role('tab', name='Wavefunction overlap', exact=True).click()
        await expect(page.get_by_role('figure', name='Wavefunction overlap with initial CF22D', exact=True)).to_contain_text('0.9600')
        await valid_svg(page)
        await page.get_by_role('tab', name='All changes', exact=True).click()
        await valid_svg(page)
        heat = page.get_by_role('figure', name='Every MUE change', exact=True)
        counts = page.get_by_role('figure', name='Reference datasets improved vs worse', exact=True)
        await page.get_by_role('searchbox', name='Search datasets', exact=True).fill('BH76RC')
        await expect(heat.locator('[data-ds]')).to_have_count(1)
        await heat.get_by_role('button', name='Table', exact=True).click()
        await expect(heat.get_by_role('table')).to_contain_text('BH76RC')
        await expect(heat.get_by_role('table')).not_to_contain_text('DBH24')
        await export_figure(page, heat, 'heat')
        await export_figure(page, counts, 'counts')
        await heat.get_by_role('button', name='Chart', exact=True).click()
        await heat.locator('.an-cell').last.focus()
        await page.evaluate("window.dispatchEvent(new Event('scroll'))")
        await expect(page.get_by_role('tooltip')).to_be_visible()
        await page.keyboard.press('Enter')
        drill = page.get_by_role('region', name='Dataset BH76RC', exact=True)
        await expect(drill).to_be_visible()
        await export_figure(page, drill, 'drill')
        await drill.get_by_role('button', name='Table', exact=True).click()
        await expect(drill.get_by_role('table')).to_contain_text('weight_2/fork-3')
        await page.get_by_role('searchbox', name='Search datasets', exact=True).fill('')
        await heat.get_by_role('button', name='Table', exact=True).click()
        await expect(heat.get_by_role('table')).to_contain_text('— (—)')
        async with page.expect_download() as info:
            await page.get_by_role('button', name='Export CSV', exact=True).click()
        download = await info.value
        await download.save_as(OUT / 'analysis.csv')
        csv_text = (OUT / 'analysis.csv').read_text()
        assert 'delta_vs_original' in csv_text and 'Weighted MUE' not in csv_text and 'NaN' not in csv_text
        assert len(list(csv.reader(io.StringIO(csv_text)))) > 10
        for width in [1366, 729, 390, 320]:
            await page.set_viewport_size({'width': width, 'height': 977})
            for tab in ['Trends', 'Input vs SCF', 'Wavefunction overlap', 'All changes']:
                await page.get_by_role('tab', name=tab, exact=True).click()
                await valid_svg(page)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (width, tab)
            for theme in ['light', 'dark']:
                await page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                await page.locator('#anDetail').evaluate("el => el.scrollIntoView({block:'start', behavior:'instant'})")
                await page.screenshot(path=str(OUT / f'changes-{width}-{theme}.png'))
            print('PASS views', width, flush=True)
        await page.set_viewport_size({'width': 1366, 'height': 977})
        api.omit_overlap = True
        await page.get_by_role('button', name='Refresh analysis', exact=True).click()
        await ready(page)
        await page.get_by_role('tab', name='Wavefunction overlap', exact=True).click()
        await expect(page.locator('#anCalcScf')).to_contain_text('Calculate SCF Input (1)')
        await expect(page.get_by_role('figure', name='Wavefunction overlap with initial CF22D', exact=True)).to_contain_text('—')
        api.omit_overlap = False
        await page.get_by_role('button', name='Refresh analysis', exact=True).click()
        await ready(page)
        # Failed submission must not invent queued state; a second click submits once.
        api.fail_submit = True
        await page.get_by_role('button', name='Calculate SCF Input (1)', exact=True).click()
        await expect(page.locator('.toast.bad').filter(has_text='SCF is unavailable')).to_be_visible()
        await expect(page.get_by_role('button', name='Calculate SCF Input (1)', exact=True)).to_be_enabled()
        api.fail_submit = False
        before = len(api.submits)
        api.hold.clear()
        await page.get_by_role('button', name='Calculate SCF Input (1)', exact=True).click()
        await expect(page.locator('#anCalcScf')).to_be_disabled()
        api.hold.set()
        await expect(page.locator('#anCalcScf')).to_contain_text('running (2)')
        assert len(api.submits) == before + 1
        assert api.submits[-1]['weightFile'] == 'weight_2' and api.submits[-1]['fork'] == 'fork-2'
        await page.reload(wait_until='networkidle')
        await ready(page)
        await expect(page.locator('#anCalcScf')).to_contain_text('running (2)')
        api.states['weight_2/fork-2'] = 'Success'
        await page.get_by_role('button', name='Refresh analysis', exact=True).click()
        await ready(page)
        await expect(page.locator('#anList .job[title="weight_2/fork-2"]')).to_contain_text('SCF 1.46')
        levels = page.get_by_role('group', name='Sidebar level', exact=True)
        await levels.get_by_role('button', name='Jobs', exact=False).click()
        await page.locator('#anList .job').filter(has=page.locator('.job-name', has_text='single')).click()
        await expect(page.locator('#anJobTitle')).to_have_text('single')
        await expect(page.locator('#anPanel')).to_contain_text('at least two')
        await levels.get_by_role('button', name='Jobs', exact=False).click()
        await page.locator('#anList .job').filter(has=page.locator('.job-name', has_text='alpha')).click()
        await ready(page)
        await expect(page.locator('.an-tip')).to_have_count(1)
        await page.get_by_role('tab', name='Trends', exact=True).focus()
        await page.keyboard.press('End')
        await expect(page.get_by_role('tab', name='All changes', exact=True)).to_be_focused()
        api.fail_mue = True
        await page.get_by_role('button', name='Refresh analysis', exact=True).click()
        await ready(page)
        await expect(page.locator('.an-data-note')).to_contain_text('weight_2/fork-3')
        await valid_svg(page)
        api.fail_mue = False
        api.zero = True
        api.no_baseline = True
        await page.get_by_role('button', name='Refresh analysis', exact=True).click()
        await ready(page)
        await page.get_by_role('tab', name='Trends', exact=True).click()
        await valid_svg(page)
        await trend.get_by_role('button', name='Log', exact=True).click()
        await valid_svg(page)
        await expect(trend).to_contain_text('No positive values')
        await trend.get_by_role('button', name='Linear', exact=True).click()
        await valid_svg(page)
        await expect(trend.locator('.an-viz > svg')).to_have_count(1)
        assert not errors, errors
        assert not api.unexpected, api.unexpected
        await context.close()
        await browser.close()
    (OUT / 'report.json').write_text(json.dumps({'views': 'passed', 'baseline_and_lineage': 'passed', 'filters_and_tables': 'passed', 'exports': 'six SVG charts and PNG with 300 dpi', 'scf': 'mocked submission, failure, duplicate prevention and status refresh passed', 'missing_and_zero': 'passed', 'console_errors': errors}, indent=2))
    print('PASS Analyze v2 integration', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
