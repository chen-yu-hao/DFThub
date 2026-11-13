const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('typescript');
const axios = require('axios');

require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true },
}).outputText, filename);
const { deleteJob } = require(path.resolve(__dirname, '../src/replica/data.ts'));

async function main() {
  const requests = [];
  let reply = { status: 200, data: { result: 'file delete success' } };
  axios.defaults.adapter = async (config) => {
    requests.push(config);
    if (reply instanceof Error) throw reply;
    return { config, statusText: '', headers: {}, ...reply };
  };
  await deleteJob('researcher', 'job with space');
  assert.equal(requests.length, 1, 'deleting must not enumerate jobs, runs, or files first');
  assert.equal(requests[0].method, 'delete');
  assert.equal(requests[0].url, '/api_dft/delete/Work/researcher/job%20with%20space');
  assert.equal(requests[0].timeout, 30_000, 'the confirmation must not wait indefinitely');
  for (const invalid of ['', '.', '..', 'job/run', 'job\\run']) {
    await assert.rejects(() => deleteJob('researcher', invalid), /Invalid job ID/);
  }
  assert.equal(requests.length, 1, 'invalid targets must not send requests');

  for (const status of [401, 403, 409, 500]) {
    reply = Object.assign(new Error('API rejected deletion'), { response: { status, data: { message: 'Rejected' } } });
    await assert.rejects(() => deleteJob('researcher', 'job'), (error) => error === reply,
      'authentication, authorization, active jobs, and server errors must not become success');
  }
  reply = Object.assign(new Error('File or folder not found'), { response: { status: 404 } });
  await deleteJob('researcher', 'already-deleted');
  for (const code of ['ECONNABORTED', 'ETIMEDOUT']) {
    reply = Object.assign(new Error('Timed out'), { code });
    await assert.rejects(() => deleteJob('researcher', 'job'), /Refresh the workspace to check whether the job was removed/);
  }
  reply = { status: 200, data: { result: 'error', msg: 'Deletion failed' } };
  await assert.rejects(() => deleteJob('researcher', 'job'), /Deletion failed/);
  console.log('PASS deletion request: one bounded call, encoded target, invalid paths, active-job rejection, missing target and timeout recovery');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
