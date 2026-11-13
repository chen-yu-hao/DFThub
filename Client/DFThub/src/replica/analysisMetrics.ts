import type { AnalysisJob, AnalysisRun } from "./analysisData";

export const isValue = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
export const difference = (value: number | null, base: number | null) => isValue(value) && isValue(base) ? value - base : null;
export const average = (values: number[]) => values.length && values.every(isValue) ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
export const mueValue = (job: AnalysisJob, run: AnalysisRun, name: string) => isValue(job.mue[run.id]?.[name]) ? job.mue[run.id][name] : null;
export function baselineValue(job: AnalysisJob, run: AnalysisRun, name: string, baseline: string) {
  if (baseline === "parent" && run.parent) {
    const parent = job.runs.find((item) => item.id === run.parent);
    return parent ? mueValue(job, parent, name) : null;
  }
  return run.originals && Object.prototype.hasOwnProperty.call(run.originals, name)
    ? run.originals[name] : job.datasets.find((dataset) => dataset.name === name)?.original ?? null;
}
export function sharedReferences(job: AnalysisJob, included: string[], baseline: string) {
  const runs = job.runs.filter((run) => included.includes(run.id));
  return runs.length ? job.datasets.filter((dataset) => runs.every((run) => isValue(mueValue(job, run, dataset.name)) && isValue(baselineValue(job, run, dataset.name, baseline)))) : [];
}
export function analysisStats(job: AnalysisJob, run: AnalysisRun, included: string[], baseline: string, names = job.datasets.map((dataset) => dataset.name)) {
  let improved = 0, worse = 0, unchanged = 0, acc = 0, accBase = 0, n = 0;
  for (const name of names) {
    const value = mueValue(job, run, name), base = baselineValue(job, run, name, baseline);
    const delta = difference(value, base);
    if (delta === null) continue;
    n++;
    if (delta < -0.005) improved++;
    else if (delta > 0.005) worse++;
    else unchanged++;
    if (value < 1) acc++;
    if (base < 1) accBase++;
  }
  const shared = sharedReferences(job, included, baseline);
  return { improved, worse, unchanged, acc, accBase, n, missing: names.length - n, meanN: shared.length,
    mean: average(shared.map((dataset) => mueValue(job, run, dataset.name)!)),
    meanBase: average(shared.map((dataset) => baselineValue(job, run, dataset.name, baseline)!)) };
}
