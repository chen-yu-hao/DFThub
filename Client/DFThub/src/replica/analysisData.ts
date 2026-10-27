import axios from "axios";
import { displayDate, listRuns, normalizeStatus, readDirectory } from "./data";
import type { Job } from "./data";
import { datasetKey, originalMueForRun, parseDatasetMue } from "./mue";
import { compareDatasets, typeNames } from "./mueAnalysis";

export type AnalysisRun = {
  id: string; short: string; kind: "weight" | "fork"; parent: string | null; trendParent: string | null;
  jobId: string; runId: string; label: string; effectiveWeight: number | null; inputSet: string;
  inverseWeight: number | null; tunedWeights: number | null; created: string; basis: string; grid: number | null;
  canScf: boolean; scfReason: string; error?: string; weights: Record<string, number>;
  originals: Record<string, number | null>;
  input: { nonScf: number | null; original: number | null; scf: { state: "none" | "running" | "done" | "failed"; value: number | null } };
  test: { nonScf: number | null; original: number | null; scf: { state: "none" | "running" | "done" | "failed"; value: number | null } } | null;
  density: {
    parent: string | null;
    descriptorSnapshotId: string | null;
    targetRows: { index: number; system: string; reference: number | null; calculated: number | null; error: number | null }[];
    parameterChange: number | null;
    optimization: { converged?: boolean; maxParameterChange?: number | null } | null;
  };
  overlap: {
    state: "none" | "partial" | "running" | "done";
    mean: number | null;
    available: number;
    total: number;
    reference: string;
    rows: { molecule: string; overlap: number | null; alpha?: number | null; beta?: number | null; status: string; reason?: string }[];
  };
};
export type AnalysisJob = {
  id: string; basis: string; grid: number | null; inputSet: string; runs: AnalysisRun[]; totalRuns: number;
  primaryJobId?: string; selectedJobIds?: string[];
  datasets: { name: string; type: string; original: number | null }[];
  mue: Record<string, Record<string, number>>; warnings: string[];
};
export type AnalysisSummary = { id: string; runs: number | null; completed: number | null; bestInput: number | null; updated: string };
export type AnalysisPayload = { job: AnalysisJob; jobs: AnalysisSummary[]; selectedJobIds?: string[]; focusJobId?: string; chemicalAccuracy: number; units: string };
type AnalysisSnapshot = { id: string; runs: Job[]; files: Record<string, Record<string, any>>; input: Record<string, any> };
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const mueNumber = (value: unknown) => finite(value) && value >= 0 ? value : null;
const json = (text: string, filename: string) => {
  if (!text) return null;
  try { return JSON.parse(text); }
  catch { throw new Error(`${filename} could not be read. Refresh after the file finishes writing.`); }
};
const numericLines = (text: string) => (text || "").split(/\r?\n/).map((line) => Number(line.trim())).filter(Number.isFinite);
const relativeParameterChange = (current: number[], initial: number[]) => {
  if (!current.length || current.length !== initial.length) return null;
  const norm = Math.sqrt(initial.reduce((sum, value) => sum + value * value, 0));
  if (!norm) return null;
  return Math.sqrt(current.reduce((sum, value, index) => sum + (value - initial[index]) ** 2, 0)) / norm * 100;
};
const overlapInfo = (result: any): AnalysisRun["overlap"] => {
  const source = result?.wavefunction_overlap;
  if (!source || typeof source !== "object") return { state: "none", mean: null, available: 0, total: 0, reference: "Initial CF22D density checkpoint", rows: [] };
  const rows = Array.isArray(source.rows) ? source.rows.map((row: any) => ({
    molecule: String(row.molecule || ""),
    overlap: finite(row.overlap) ? Math.max(0, Math.min(1, row.overlap)) : null,
    alpha: finite(row.alpha) ? row.alpha : null,
    beta: finite(row.beta) ? row.beta : null,
    status: String(row.status || "unavailable"),
    reason: row.reason ? String(row.reason) : undefined,
  })) : [];
  const available = rows.filter((row) => row.status === "available" && row.overlap !== null).length;
  const total = Number.isFinite(source.total) ? Number(source.total) : rows.length;
  const mean = finite(source.mean) ? Math.max(0, Math.min(1, source.mean)) : available ? rows.reduce((sum, row) => sum + (row.overlap || 0), 0) / available : null;
  return { state: available && available === total ? "done" : available ? "partial" : "none", mean, available, total, reference: String(source.reference || "Initial CF22D density checkpoint"), rows };
};

export function weightInfo(text: string) {
  const lines = text.trim().split(/\r?\n/).map((line) => line.split("\t"));
  const headers = (lines.shift() || []).map((cell) => cell.trim().toLowerCase());
  const weights: Record<string, number> = {};
  let inputName = "", inverseWeight: number | null = null;
  for (const cells of lines) {
    const key = datasetKey(cells[0] || "");
    const raw = cells[headers.indexOf("inverse weight")]?.trim();
    const value = raw ? Number(raw) : NaN;
    if (Number.isFinite(value)) weights[key] = value;
    if (cells[headers.indexOf("source")]?.trim().toLowerCase() === "uploaded") {
      inputName = cells[0].trim();
      inverseWeight = Number.isFinite(value) ? value : null;
    }
  }
  return { weights, inputName, inverseWeight };
}

export function inputScf(files: Record<string, any>): AnalysisRun["input"]["scf"] {
  const status = normalizeStatus(json(files["spe_input.status.json"], "Input SCF status")?.status || "");
  if (["queued", "running"].includes(status)) return { state: "running", value: null };
  const current = json(files["SinglePointResults.input.json"], "Input SCF results");
  if (current && current.scope !== "input") throw new Error("Unexpected SCF result scope; Input MUE is unavailable.");
  if (current?.trainingComplete === false || (status === "failed" && current?.trainingComplete !== true)) return { state: "failed", value: null };
  if (current?.complete === true) {
    let value = mueNumber(current.targetMue);
    const rows = current.targetRows;
    if (value === null && Array.isArray(rows) && rows.length && rows.every((row) => finite(row.unbiasedError))) {
      value = rows.reduce((sum, row) => sum + Math.abs(row.unbiasedError), 0) / rows.length;
    }
    return { state: value === null ? "none" : "done", value };
  }
  const legacy = current ? null : json(files["SinglePointResults.json"], "Legacy SCF results");
  if (current && current.scope !== "input") throw new Error("Unexpected SCF result scope; Input MUE is unavailable.");
  const result = current || legacy;
  if (!result || result.complete === false) return { state: "none", value: null };
  let value = mueNumber(current ? current.targetMue : legacy.userTargetMue);
  const rows = current ? current.targetRows : legacy.userTargetRows;
  if (value === null && Array.isArray(rows) && rows.length && rows.every((row) => finite(row.unbiasedError))) {
    value = rows.reduce((sum, row) => sum + Math.abs(row.unbiasedError), 0) / rows.length;
  }
  return { state: value === null ? "none" : "done", value };
}

export function testScf(files: Record<string, any>): AnalysisRun["input"]["scf"] {
  const status = normalizeStatus(json(files["spe_input.status.json"], "Input SCF status")?.status || "");
  if (["queued", "running"].includes(status)) return { state: "running", value: null };
  const result = json(files["SinglePointResults.input.json"], "Input SCF results");
  if (result && result.scope !== "input") throw new Error("Unexpected SCF result scope; Test MUE is unavailable.");
  if (result?.testComplete === false || (result?.testComplete !== true && (result?.complete === false || status === "failed"))) {
    return { state: "failed", value: null };
  }
  const value = mueNumber(result?.testTargetMue);
  return { state: value === null ? "none" : "done", value };
}

export function makeAnalysisJob(id: string, listed: Job[], files: Record<string, Record<string, any>>, inputs: Record<string, any>): AnalysisJob {
  const warnings: string[] = [];
  const datasets = new Map<string, { name: string; type: string; original: number | null }>();
  const mue: AnalysisJob["mue"] = {};
  const runs: AnalysisRun[] = listed.filter((run) => run.status === "completed").map((run) => {
    const output = files[run.id] || {};
    const info = weightInfo(output["weight.csv"] || "");
    const rows = parseDatasetMue(output.Mue || "").map((row) => row.key === datasetKey(info.inputName) && row.key !== "input" ? { ...row, key: "input", name: "Input" } : row);
    let lineage: any = null, descriptors: any = null, meta: any = null;
    let scf: AnalysisRun["input"]["scf"] = { state: "none", value: null };
    let testScfState: AnalysisRun["input"]["scf"] = { state: "none", value: null };
    const testRows = parseDatasetMue(output.TestMue || "");
    const testOriginalRows = parseDatasetMue(output.TestOriginalMue || "");
    const testResult = (() => {
      try { return output["SinglePointResults.input.json"] ? JSON.parse(output["SinglePointResults.input.json"]) : null; }
      catch { return null; }
    })();
    const overlap = overlapInfo(testResult);
    const optimization = (() => {
      try { return json(output["OptimizationStatus.json"], "Optimization status"); }
      catch (error) { warnings.push(`${run.id}: ${(error as Error).message}`); return null; }
    })();
    const targetRows = Array.isArray(testResult?.targetRows) ? testResult.targetRows.map((row) => ({
      index: Number(row.index), system: String(row.system || ""), reference: finite(row.reference) ? row.reference : null,
      calculated: finite(row.calculated) ? row.calculated : null,
      error: finite(row.calculated) && finite(row.reference) ? row.calculated - row.reference : finite(row.unbiasedError) ? row.unbiasedError : null,
    })) : [];
    for (const [name, assign] of [
      ["run.json", (value) => { lineage = value; }],
      ["InputDescriptors.json", (value) => { descriptors = value; }],
      ["OriginalMue.meta.json", (value) => { meta = value; }],
    ] as const) {
      try { assign(json(output[name], name)); }
      catch (error) { warnings.push(`${run.id}: ${(error as Error).message}`); }
    }
    try { scf = inputScf(output); }
    catch (error) { warnings.push(`${run.id}: ${(error as Error).message}`); }
    try { testScfState = testScf(output); }
    catch (error) { warnings.push(`${run.id}: ${(error as Error).message}`); }
    if (output._error) warnings.push(`${run.id}: ${output._error}`);
    else if (!rows.length) warnings.push(`${run.id}: optimized MUE results are not available yet.`);
    const original = originalMueForRun(output.OriginalMue || "", meta);
    const compared = compareDatasets(rows, original, output["weight.csv"] || "", {});
    mue[run.id] = {};
    for (const row of compared.filter((row) => row.key !== "input")) {
      mue[run.id][row.key] = row.value;
      const previous = datasets.get(row.key);
      datasets.set(row.key, { name: row.key, type: previous && previous.type !== (typeNames[row.type] || row.type) ? "Other / unclassified" : typeNames[row.type] || row.type, original: row.original });
    }
    const inputFiles = output._input || inputs;
    const names: string[] = inputFiles._files || [];
    const geometry = names.some((name) => /\.(zip|tgz|tar\.gz)$/.test(name));
    const reference = names.some((name) => /(?:\.ref|_ref)$/.test(name));
    const optimized = ["CF22D_optimized.py", "NEW-params.txt"].some((name) => (output._files || []).includes(name));
    const testScfMue = mueNumber(testResult?.testTargetMue);
    // These files are created only for an uploaded test set, before its MUE
    // evaluation finishes, and are copied when a run inherits that test set.
    const hasTest = testRows.length > 0 || testOriginalRows.length > 0 || testScfMue !== null ||
      ["TEST_INPUT", "TEST_INPUT_ref", "TestDescriptors.json", "TestMue", "TestOriginalMue", "TestMue.json"]
        .some((name) => (output._files || []).includes(name)) ||
      testResult?.testSetExcludedFromOptimization === true ||
      (Array.isArray(testResult?.testTargetRows) && testResult.testTargetRows.length > 0);
    const fork = run.id.includes("/");
    return {
      id: run.id, short: run.id.replace(/^weight_/, "w").replace("/fork-", "/f"), kind: fork ? "fork" : "weight", jobId: id, runId: run.id, label: `${id} · ${run.id}`, effectiveWeight: info.inverseWeight, inputSet: info.inputName || "Input",
      parent: typeof lineage?.parent === "string" ? lineage.parent : null, trendParent: null,
      inverseWeight: info.inverseWeight, tunedWeights: null, weights: info.weights,
      created: finite(lineage?.created_at) ? new Date(lineage.created_at * 1000).toISOString() : run.date,
      basis: String(inputFiles["basis.txt"] || lineage?.basis || "").trim(), grid: finite(lineage?.grid_level) ? lineage.grid_level : finite(descriptors?.grid_level) ? descriptors.grid_level : null,
      input: { nonScf: rows.find((row) => row.key === "input")?.value ?? null, original: original.get("input") ?? null, scf },
      originals: Object.fromEntries(original.entries()),
      test: hasTest ? {
        nonScf: testRows.find((row) => row.key === "test_input")?.value ?? null,
        original: testOriginalRows.find((row) => row.key === "test_input")?.value ?? null,
        scf: testScfState,
      } : null,
      density: {
        parent: typeof lineage?.parent === "string" ? lineage.parent : null,
        descriptorSnapshotId: typeof lineage?.descriptor_snapshot_id === "string" ? lineage.descriptor_snapshot_id : typeof descriptors?.id === "string" ? descriptors.id : null,
        targetRows,
        parameterChange: relativeParameterChange(numericLines(output["NEW-params.txt"]), numericLines(output["initial-params.txt"])),
        optimization: optimization ? { converged: optimization.converged, maxParameterChange: finite(optimization.max_parameter_change) ? optimization.max_parameter_change : null } : null,
      },
      overlap,
      canScf: optimized && geometry && reference && !output._error,
      scfReason: !optimized ? "Optimized parameters are unavailable." : !geometry || !reference ? "Input geometry or reference files are missing." : output._error || "",
      error: output._error,
    };
  });
  runs.sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
  const byId = new Map(runs.map((run) => [run.id, run]));
  let previousFit: string | null = null;
  for (const run of runs) {
    const seen = new Set([run.id]);
    let cursor = run.parent;
    while (cursor) {
      if (seen.has(cursor)) { warnings.push(`${run.id}: circular parent metadata was ignored.`); run.parent = null; break; }
      seen.add(cursor); cursor = byId.get(cursor)?.parent;
    }
    if (run.kind === "weight") { run.trendParent = previousFit; previousFit = run.id; }
    const parent = byId.get(run.parent || "");
    if (parent) {
      const keys = new Set([...Object.keys(parent.weights), ...Object.keys(run.weights)]);
      run.tunedWeights = [...keys].filter((key) => parent.weights[key] !== run.weights[key]).length;
    }
  }
  for (const run of runs) {
    let cursor: AnalysisRun | undefined = run;
    while (cursor && cursor.inverseWeight === null) cursor = byId.get(cursor.parent || "");
    run.effectiveWeight = cursor?.inverseWeight ?? null;
  }
  const displayNames = new Map(Object.values(files).flatMap((output) => parseDatasetMue(output.Mue || "").map((row) => [row.key, row.name.replace(/_ref$/i, "")] as const)));
  // Stable dataset identity is separate from the case-preserving display name.
  const named = [...datasets.values()].map((dataset) => ({ ...dataset, name: displayNames.get(dataset.name) || dataset.name }));
  for (const run of runs) {
    mue[run.id] = Object.fromEntries([...datasets.keys()].filter((key) => mue[run.id][key] !== undefined).map((key) => [displayNames.get(key) || key, mue[run.id][key]]));
    run.originals = Object.fromEntries(Object.entries(run.originals).map(([key, value]) => [displayNames.get(key) || key, value]));
    run.jobId = id; run.runId = run.id; run.label = `${id} · ${run.short}`;
  }
  const basis = [...new Set(runs.map((run) => run.basis).filter(Boolean))];
  const grid = [...new Set(runs.map((run) => run.grid).filter((value) => value !== null))];
  const inputName = Object.values(files).map((output) => weightInfo(output["weight.csv"] || "").inputName).find(Boolean);
  sortAnalysisRuns(runs);
  previousFit = null;
  for (const run of runs) {
    if (run.kind === "weight") { run.trendParent = previousFit; previousFit = run.id; }
  }
  return { id, primaryJobId: id, selectedJobIds: [id], runs, totalRuns: listed.length, datasets: named, mue, warnings, inputSet: inputName || "Input", basis: basis.length === 1 ? basis[0] : basis.length ? "Mixed basis sets" : "Basis not reported", grid: grid.length === 1 ? grid[0] : null };
}

export function sortAnalysisRuns(runs: AnalysisRun[]) {
  return runs.sort((a, b) => (b.effectiveWeight ?? -Infinity) - (a.effectiveWeight ?? -Infinity) ||
    a.jobId.localeCompare(b.jobId, undefined, { numeric: true }) || a.runId.localeCompare(b.runId, undefined, { numeric: true }));
}

export function combineAnalysisJobs(parts: AnalysisJob[], selectedJobIds: string[]): AnalysisJob {
  const runs: AnalysisRun[] = [];
  const mue: AnalysisJob["mue"] = {};
  const datasets = new Map<string, { name: string; type: string; original: number | null }>();
  const warnings = parts.flatMap((part) => part.warnings.map((warning) => `${part.id}: ${warning}`));
  const names = new Map<string, string>();
  for (const part of parts) {
    for (const dataset of part.datasets) {
      const key = datasetKey(dataset.name);
      const existing = datasets.get(key);
      names.set(key, names.get(key) || dataset.name);
      datasets.set(key, existing ? { ...existing,
        type: existing.type === dataset.type ? existing.type : "Other / unclassified",
        original: existing.original === dataset.original ? existing.original : null } : { ...dataset });
    }
    for (const source of part.runs) {
      const id = `${part.id}::${source.runId || source.id}`;
      const parent = source.parent ? `${part.id}::${source.parent}` : null;
      const trendParent = source.trendParent ? `${part.id}::${source.trendParent}` : null;
      const run = { ...source, id, jobId: part.id, runId: source.runId || source.id, label: `${part.id} · ${source.short}`, parent, trendParent,
        originals: Object.fromEntries(part.datasets.map((dataset) => [datasetKey(dataset.name), source.originals && Object.prototype.hasOwnProperty.call(source.originals, dataset.name) ? source.originals[dataset.name] : dataset.original])) };
      runs.push(run);
      mue[id] = Object.fromEntries(Object.entries(part.mue[source.id] || {}).map(([name, value]) => [datasetKey(name), value]));
    }
  }
  for (const run of runs) {
    mue[run.id] = Object.fromEntries(Object.entries(mue[run.id]).map(([name, value]) => [names.get(name) || name, value]));
    run.originals = Object.fromEntries(Object.entries(run.originals).map(([name, value]) => [names.get(name) || name, value]));
  }
  const jobBasis = [...new Set(parts.map((part) => part.basis).filter(Boolean))];
  const jobGrid = [...new Set(parts.map((part) => part.grid).filter((value) => value !== null))];
  sortAnalysisRuns(runs);
  return {
    id: selectedJobIds.length === 1 ? selectedJobIds[0] : "multiple-jobs",
    primaryJobId: selectedJobIds[0], selectedJobIds: [...selectedJobIds], runs, totalRuns: parts.reduce((sum, part) => sum + part.totalRuns, 0),
    datasets: [...datasets.values()], mue, warnings,
    inputSet: selectedJobIds.length === 1 ? parts[0]?.inputSet || "Input" : "Multiple input sets",
    basis: jobBasis.length === 1 ? jobBasis[0] : jobBasis.length ? "Mixed basis sets" : "Basis not reported",
    grid: jobGrid.length === 1 ? jobGrid[0] : null,
  };
}

async function mapLimited<T, R>(items: T[], task: (item: T) => Promise<R>): Promise<R[]> {
  const output: R[] = new Array(items.length);
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(3, items.length) }, async () => {
    while (cursor < items.length) { const index = cursor++; output[index] = await task(items[index]); }
  }));
  return output;
}

export async function loadAnalysisJob(username: string, id: string, signal: AbortSignal): Promise<AnalysisJob> {
  const path = `Work/${username}/${id}`;
  const [listed, input] = await Promise.all([listRuns(path + "/output", signal), readDirectory(path + "/input", ["basis.txt"], signal)]);
  const entries = await mapLimited(listed.filter((run) => run.status === "completed"), async (run) => {
    try {
      const output = await readDirectory(path + "/output/" + run.id, ["Mue", "weight.csv", "OriginalMue", "OriginalMue.meta.json", "TestMue", "TestOriginalMue", "TestOriginalMue.meta.json", "run.json", "InputDescriptors.json", "SinglePointResults.input.json", "spe_input.status.json", "SinglePointResults.json", "OptimizationStatus.json", "initial-params.txt", "NEW-params.txt"], signal);
      if (run.id.includes("/")) output._input = await readDirectory(path + "/output/" + run.id + "/input", ["basis.txt"], signal);
      return [run.id, output] as const;
    } catch (error) {
      if (signal.aborted) throw error;
      return [run.id, { _error: (error as Error).message }] as const;
    }
  });
  return makeAnalysisJob(id, listed, Object.fromEntries(entries), input);
}

/** Read one server-side snapshot instead of listing and downloading every Run file. */
export async function loadAnalysisJobs(username: string, ids: string[], signal: AbortSignal): Promise<{ jobs: AnalysisJob[]; summaries: AnalysisSummary[] }> {
  const response = await axios.get("/api_dft/analysis", {
    params: { jobs: ids.join(",") },
    signal,
  });
  const rows = Array.isArray(response.data?.jobs) ? response.data.jobs as AnalysisSnapshot[] : [];
  if (!rows.length && ids.length) throw new Error("The analysis snapshot did not contain the selected Job.");
  return {
    jobs: rows.map((row) => makeAnalysisJob(row.id, row.runs, row.files, row.input)),
    summaries: Array.isArray(response.data?.summaries) ? response.data.summaries : [],
  };
}

export async function loadAnalysisSummaries(username: string, ids: string[], signal: AbortSignal): Promise<AnalysisSummary[]> {
  if (!ids.length) return [];
  const response = await axios.get("/api_dft/analysis/summary", {
    params: { jobs: ids.join(",") },
    signal,
  });
  return Array.isArray(response.data?.summaries) ? response.data.summaries : [];
}

export function summarizeAnalysis(job: Job, data?: AnalysisJob): AnalysisSummary {
  const values = data?.runs.map((run) => run.input.nonScf).filter((value) => value !== null) || [];
  return { id: job.id, runs: data?.totalRuns ?? null, completed: data?.runs.length ?? null, bestInput: values.length ? Math.min(...values) : null, updated: displayDate(job.date) };
}

export async function loadAnalysisSummary(username: string, job: Job, signal: AbortSignal): Promise<AnalysisSummary> {
  const [summary] = await loadAnalysisSummaries(username, [job.id], signal);
  return summary || summarizeAnalysis(job);
}
