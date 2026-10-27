const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true },
}).outputText, filename);
const root = path.resolve(__dirname, '../src/replica');
const { makeAnalysisJob, inputScf, testScf } = require(path.join(root, 'analysisData.ts'));
const { analysisStats, baselineValue, difference, sharedReferences } = require(path.join(root, 'analysisMetrics.ts'));
const native = require(path.join(root, 'cf22d-native.json'));
const ids = ['weight_0', 'weight_1', 'weight_1/fork-1'];
const listed = ids.map(id => ({ id, date: '2026-10-02T10:00:00Z', status: 'completed' }));
const weights = 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nCustom\t\t\tuploaded\t3\t0.02\nBH76RC\t\tBH\tReference\t1\t999\nDBH24\t\tBH\tReference\t100\t0.0001\nAE17\t\tTC\tReference\t2\t0.1';
const file = (input, bh, db) => ({ Mue: `INPUT_ref\t${input}\nBH76RC\t${bh}\nDBH24\t${db}\nAE17\t0\nWeighted MUE sum:\t999\nTotal loss:\t1001`, 'weight.csv': weights,
  OriginalMue: 'Input\t4.22', 'OriginalMue.meta.json': JSON.stringify({ source: 'libxc-native-cf22d', parameter_sha256: native.parameter_sha256 }),
  _files: ['NEW-params.txt'] });
const files = { weight_0: file(1.86, 1, 4), weight_1: file(1.58, 2, 1), 'weight_1/fork-1': { ...file(1.3, 0.5, 1.5), 'run.json': JSON.stringify({ parent: 'weight_1', created_at: 1790930000 }) } };
const input = { 'basis.txt': 'cc-pvtz', _files: ['Custom.tgz', 'Custom.ref', 'basis.txt'] };
const job = makeAnalysisJob('alpha', listed, files, input);
assert.equal(job.runs[1].parent, null, 'new fits must not acquire a fabricated parent');
assert.equal(job.runs[1].trendParent, 'weight_0');
assert.equal(job.runs[2].parent, 'weight_1');
assert.equal(job.runs[0].input.original, 4.22);
assert.equal(job.runs[0].canScf, true);
assert.equal(job.runs[2].tunedWeights, 0);
const original = analysisStats(job, job.runs[0], ids, 'original');
assert.equal(original.mean, 5 / 3, 'Reference mean is unweighted across datasets');
assert.equal(original.meanN, 3);
const parent = analysisStats(job, job.runs[2], [ids[0], ids[2]], 'parent');
assert.equal(parent.meanBase, 1, 'excluded parent still supplies the baseline');
assert.equal(parent.improved, 1);
assert.equal(parent.worse, 1);
assert.equal(parent.unchanged, 1);
assert.equal(baselineValue(job, job.runs[1], 'BH76RC', 'parent'), native.datasets.BH76RC, 'unrecorded parent uses CF22D');
assert.equal(difference(null, 0), null);
assert.equal(difference(0, 0), 0);
delete job.mue['weight_1/fork-1'].DBH24;
assert.equal(sharedReferences(job, ids, 'original').length, 2);
assert.equal(analysisStats(job, job.runs[2], ids, 'original').missing, 1);
job.runs[2].parent = 'weight_99';
assert.equal(baselineValue(job, job.runs[2], 'BH76RC', 'parent'), null, 'a missing recorded parent cannot be replaced with a fabricated baseline');
const result = { scope: 'input', complete: true, targetMue: 0 };
assert.deepEqual(inputScf({ 'SinglePointResults.input.json': JSON.stringify(result) }), { state: 'done', value: 0 });
assert.deepEqual(inputScf({ 'SinglePointResults.input.json': JSON.stringify(result), 'spe_input.status.json': '{"status":"Queued"}' }), { state: 'running', value: null });
assert.deepEqual(inputScf({ 'SinglePointResults.input.json': JSON.stringify(result), 'spe_input.status.json': '{"status":"Failed"}' }), { state: 'failed', value: null });
assert.deepEqual(inputScf({ 'SinglePointResults.input.json': JSON.stringify({ ...result, complete: false }) }), { state: 'none', value: null });
assert.deepEqual(inputScf({ 'SinglePointResults.json': '{"targetMue":88,"userTargetMue":0.4}' }), { state: 'done', value: .4 });
assert.deepEqual(inputScf({ 'SinglePointResults.json': '{"targetMue":88}' }), { state: 'none', value: null });
assert.throws(() => inputScf({ 'SinglePointResults.input.json': '{"scope":"ame418","targetMue":10}' }), /scope/);
const partialTest = { ...result, trainingComplete: true, testComplete: false, evaluationComplete: false, testTargetMue: .6675, testSetExcludedFromOptimization: true };
const partialFiles = { 'SinglePointResults.input.json': JSON.stringify(partialTest) };
assert.deepEqual(inputScf(partialFiles), { state: 'done', value: 0 });
assert.deepEqual(testScf(partialFiles), { state: 'failed', value: null }, 'partial test MUE must never be plotted as a completed evaluation');
assert.deepEqual(inputScf({ ...partialFiles, 'spe_input.status.json': '{"status":"Failed"}' }), { state: 'done', value: 0 });
for (const status of ['Queued', 'Running']) {
  const retry = { ...partialFiles, 'spe_input.status.json': JSON.stringify({ status }) };
  assert.deepEqual(inputScf(retry), { state: 'running', value: null });
  assert.deepEqual(testScf(retry), { state: 'running', value: null });
}
assert.deepEqual(testScf({ 'SinglePointResults.input.json': JSON.stringify({ ...partialTest, testComplete: true, testTargetMue: 0 }) }), { state: 'done', value: 0 });
assert.deepEqual(inputScf({ 'SinglePointResults.input.json': JSON.stringify({ ...partialTest, trainingComplete: false }) }), { state: 'failed', value: null });
assert.deepEqual(testScf({ 'SinglePointResults.input.json': JSON.stringify({ ...result, complete: false, testTargetMue: .6 }) }), { state: 'failed', value: null }, 'legacy partial results are not still running');
const unaudited = makeAnalysisJob('alpha', listed, { ...files, weight_0: { ...files.weight_0, 'OriginalMue.meta.json': '{}' } }, input);
assert.equal(unaudited.runs[0].input.original, null);
assert.equal(makeAnalysisJob('alpha', listed, files, { _files: [] }).runs[0].canScf, false);
assert.equal(job.datasets.some(d => /loss|weighted/i.test(d.name)), false);
const testFiles = { ...files, weight_0: { ...files.weight_0, TestMue: 'test_input\t0.77\n', TestOriginalMue: 'test_input\t1.11\n', 'SinglePointResults.input.json': JSON.stringify({ scope: 'input', complete: true, testTargetMue: 0.66 }) } };
const withTest = makeAnalysisJob('alpha', listed, testFiles, input);
assert.equal(withTest.runs[0].test.nonScf, 0.77);
assert.equal(withTest.runs[0].test.original, 1.11);
assert.equal(withTest.runs[0].test.scf.value, 0.66);
const testRun = (extra = {}) => makeAnalysisJob('alpha', listed.slice(0, 1), { weight_0: { ...files.weight_0, ...extra } }, input).runs[0];
assert.equal(testRun().test, null, 'a job without a test upload has no test summary');
assert.equal(testRun({ 'SinglePointResults.input.json': JSON.stringify({ ...result, testTargetMue: null, testTargetRows: [] }) }).test, null,
  'an empty SCF test field does not establish that a test set was uploaded');
for (const name of ['TEST_INPUT', 'TEST_INPUT_ref', 'TestDescriptors.json', 'TestMue']) {
  assert.deepEqual(testRun({ _files: ['NEW-params.txt', name] }).test,
    { nonScf: null, original: null, scf: { state: 'none', value: null } },
    'an uploaded test set remains visible before MUE evaluation finishes');
}
assert.equal(testRun({ TestOriginalMue: 'test_input\t1.11\n' }).test.original, 1.11,
  'baseline-only test results establish test presence before optimized MUE is available');
assert.equal(testRun({ 'SinglePointResults.input.json': JSON.stringify({ ...result, testTargetMue: 0 }) }).test.scf.value, 0,
  'zero is a valid test MUE');
assert.equal(testRun({ 'SinglePointResults.input.json': JSON.stringify({ ...result, testTargetMue: null, testSetExcludedFromOptimization: true }) }).test.nonScf, null,
  'explicit test metadata keeps an uploaded test set visible without a result');
console.log('PASS analysis v2: verified baselines, true lineage, unweighted reference means, missing data, SCF states, optional-test presence and scope isolation');
