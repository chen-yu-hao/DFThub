const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('typescript');
const axios = require('axios');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true },
}).outputText, filename);
const root = path.resolve(__dirname, '../src/replica');
const { workspaceTestSet } = require(path.join(root, 'testSet.ts'));
const { loadRunFiles } = require(path.join(root, 'data.ts'));
const native = require(path.join(root, 'cf22d-native.json'));
const testFiles = {
  TestMue: 'test_input\t1.067462\n', TestOriginalMue: 'test_input\t1.176663\n',
  'TestMue.json': JSON.stringify({ scope: 'test', complete: true, count: 9, targetMue: 1.067462 }),
  'TestOriginalMue.meta.json': JSON.stringify({ source: 'libxc-native-cf22d', parameter_sha256: native.parameter_sha256 }),
};
assert.deepEqual(workspaceTestSet({}), null);
assert.deepEqual(workspaceTestSet({ _files: ['TEST_INPUT'] }), { value: null, original: null, points: null, complete: false });
assert.deepEqual(workspaceTestSet(testFiles), { value: 1.067462, original: 1.176663, points: 9, complete: true });
assert.equal(workspaceTestSet({ ...testFiles, TestMue: 'test_input\t0\n' }).value, 0);
assert.equal(workspaceTestSet({ ...testFiles, 'TestOriginalMue.meta.json': '{}' }).original, null, 'unverified baseline must not be shown as native CF22D');
assert.equal(workspaceTestSet({ ...testFiles, 'TestMue.json': '{"complete":false,"count":9}' }).value, null, 'partial evaluation must not be plotted as complete');
assert.equal(workspaceTestSet({ ...testFiles, 'SinglePointResults.input.json': '{"testComplete":false,"testTargetMue":0.3}' }).value, 1.067462,
  'SCF completeness and values must not replace the separate non-SCF test evaluation');

async function main() {
  const base = 'Work/researcher/demo/output/weight_1/fork-4';
  const outputs = { ...testFiles, Parameters: 'Cx(0,0,0) = 6.8030840332869869e-01\n',
    'NEW-params.txt': '0.68030840332869869\n', 'CF22D_optimized.py': '# functional\n', Mue: 'input\t0.31\n' };
  const requests = [];
  let withTest = true;
  axios.defaults.adapter = async (config) => {
    requests.push(config.url);
    const files = Object.fromEntries(Object.entries(outputs).filter(([name]) => withTest || !name.startsWith('Test')));
    let data;
    if (config.url.endsWith('/file_list')) {
      const body = JSON.parse(config.data);
      const names = body.file_dir === base ? Object.keys(files) : body.file_dir.endsWith('/input') ? ['basis.txt', 'train.tgz', 'train.ref'] : [];
      data = { result: names.map(name => ({ name })) };
    } else {
      const file = decodeURIComponent(config.url.split('/').at(-1));
      data = file === 'basis.txt' ? 'aug-cc-pvtz' : files[file];
      assert.notEqual(data, undefined, config.url);
    }
    return { config, data, status: 200, statusText: 'OK', headers: {} };
  };
  const run = await loadRunFiles('researcher', 'demo', 'weight_1/fork-4');
  assert.deepEqual(run.parameterExports, ['Parameters', 'NEW-params.txt', 'CF22D_optimized.py']);
  assert.equal(run.parameters, outputs.Parameters);
  assert.deepEqual(run.testSet, { value: 1.067462, original: 1.176663, points: 9, complete: true });
  assert(requests.includes('/api_dft/download/' + base + '/TestMue'));
  assert(!requests.some(url => url.endsWith('/NEW-params.txt') || url.endsWith('/CF22D_optimized.py')),
    'export-only artifacts should be downloaded on demand');
  withTest = false;
  assert.equal((await loadRunFiles('researcher', 'demo', 'weight_1/fork-4')).testSet, null);
  console.log('PASS workspace test results: optional presence, partial results, zero MUE, baseline provenance, scope isolation and export availability');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
