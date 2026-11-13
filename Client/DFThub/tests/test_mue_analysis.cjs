const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('typescript');
const Module = require('node:module');
const root = path.resolve(__dirname, '../src/replica');
require.extensions['.ts'] = (module, filename) => {
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, resolveJsonModule: true, esModuleInterop: true } }).outputText;
  module._compile(code, filename);
};
const { compareDatasets, overallByType, overviewStats, reportedTotalMue } = require(path.join(root, 'mueAnalysis.ts'));
const { datasetType } = require(path.join(root, 'datasetMetadata.ts'));
const rows = [{ key: 'input', name: 'Input', value: 0.59 }, { key: 'a', name: 'A', value: 0.5 }, { key: 'b', name: 'B', value: 2 }, { key: 'zero', name: 'Zero', value: 0 }, { key: 'missing', name: 'Missing', value: 2 }];
const original = new Map([['input', 4.25], ['a', 1], ['b', 3], ['zero', 0]]);
const weights = 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nDemo\t\t\tuploaded\t\t0.02\nA\t\tBH\tReference\t100\t999\nB\t\tBH\tReference\t100\t0.001\nZero\t\tEE\tReference\t2\t1\nMissing\t\tTC\tReference\t2\t1\n';
const comparison = compareDatasets(rows, original, weights, { a: 1, b: 3 });
const groups = overallByType(comparison);
assert.equal(groups[0].key, 'Input');
assert.equal(groups[0].points, null);
assert.equal(groups[0].value, 0.59);
const bh = groups.find(row => row.key === 'BH');
assert.equal(bh.value, (0.5 + 2 * 3) / 4);
assert.equal(bh.original, (1 + 3 * 3) / 4);
assert.equal(bh.points, 4);
assert(!groups.some(row => row.key === 'TC'));
const summary = overviewStats(comparison);
assert.equal(summary.references, 3);
assert.equal(summary.totalReferences, 4);
assert.equal(summary.improved.length, 2);
assert.equal(summary.worse.length, 0);
assert.equal(summary.unchanged, 1);
assert.equal(summary.beforeAccurate, 1);
assert.equal(summary.afterAccurate, 2);
assert.equal(reportedTotalMue('new_total_mue:1.90867\nWeighted MUE sum:\t500\nTotal loss:\t542'), 1.90867);
assert.equal(reportedTotalMue('Total loss:\t542'), null);
const unknown = compareDatasets([{ key: 'bad', name: 'Bad', value: 2 }], new Map([['bad', 3]]), '', {});
assert.equal(overallByType(unknown).length, 0);
// Old weight files labelled the three TMB11 sets "built-in" rather than by
// scientific category. Correct the view without rewriting the source weights.
const legacyWeights = 'Database\tDescription\tType\tSource\tNumber\tInverse Weight\nNCCE30\t\tbuilt-in\tTMB11\t\t0.07\nπIE3\t\tbuilt-in\tTMB11\t\t0.83\nπPa10\t\tbuilt-in\tTMB11\t\t0.40';
assert.equal(datasetType(' NCCE30_ref ', 'built-in'), 'NC');
for (const alias of ['πIE3', 'pIE3_ref', 'piIE3', 'PIIE3_REF']) assert.equal(datasetType(alias, 'built-in'), 'IE');
for (const alias of ['πPa10', 'pPa10_ref', 'piPa10', 'PIPA10_REF']) assert.equal(datasetType(alias, 'built-in'), 'TC');
assert.equal(datasetType('Uncatalogued', 'custom'), 'custom');
assert.equal(datasetType('Example', ' bh '), 'BH');
const legacyRows = [
  { key: 'ncce30', name: 'NCCE30', value: 0.2 },
  { key: 'pie3', name: 'pIE3_ref', value: 2 },
  { key: 'πpa10', name: 'πPa10', value: 3 },
];
const legacyComparison = compareDatasets(legacyRows, new Map([['ncce30', 0.3], ['πie3', 4], ['πpa10', 5]]), legacyWeights,
  { ncce30: 23, pie3: 3, 'πpa10': 10 });
assert.deepEqual(legacyComparison.map(row => row.type), ['NC', 'IE', 'TC']);
assert.equal(legacyComparison[1].original, 4);
assert.deepEqual(overallByType(legacyComparison).map(row => [row.key, row.points]), [['TC', 10], ['NC', 23], ['IE', 3]]);
assert.equal(compareDatasets(legacyRows, new Map(), '', {})[0].type, 'NC');
const asciiWeights = legacyWeights.replace('πIE3', 'pIE3_ref').replace('πPa10', 'pPa10_ref');
assert.deepEqual(compareDatasets(legacyRows, new Map(), asciiWeights, {}).map(row => row.type), ['NC', 'IE', 'TC']);
console.log('PASS point-weighted categories, paired coverage, zero/unknown counts, original matching, and overview statistics');
