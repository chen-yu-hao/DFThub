import axios from "axios";
import { datasetKey } from "./mue";
import type { BaselineMetadata } from "./mue";
import { workspaceTestSet } from "./testSet";
import type { WorkspaceTestSet } from "./testSet";

export type ParameterArtifact = "Parameters" | "NEW-params.txt" | "CF22D_optimized.py";
const parameterArtifacts: ParameterArtifact[] = ["Parameters", "NEW-params.txt", "CF22D_optimized.py"];

export type Job = {
  id: string;
  date: string;
  status: string;
  rawStatus?: string;
  activityStatus?: string;
  activityLabel?: string;
  mue: number | null;
  effectiveWeight?: number | null;
};
export type Run = Job;
export type SpeScope = "input" | "ame418" | "energy";
export type SpeScopeData = { result: any | null; log: string; status: string; updatedAt?: number; legacy?: boolean };
export type InputDescriptors = { id: string; complete: boolean; grid_level: number; basis: string };
export type RunLineage = { parent: string; descriptor_snapshot_id: string; grid_level: number; basis: string };
export type RunFiles = {
  log: string;
  mue: string;
  originalMue: string;
  originalMueMeta: BaselineMetadata | null;
  datasetCounts: Record<string, number>;
  parameters: string;
  parameterExports: ParameterArtifact[];
  testSet: WorkspaceTestSet | null;
  weights: string;
  basis: string;
  jobLog: string;
  spe: any | null;
  speScopes: Record<SpeScope, SpeScopeData>;
  hasOptimizedFunctional: boolean;
  hasInputDataset: boolean;
  inputDescriptors: InputDescriptors | null;
  lineage: RunLineage | null;
};
export type DetailProps = {
  job: Job;
  runs: Run[];
  run: Run | null;
  files: RunFiles;
  loading: boolean;
  error: string;
  user: { username: string; email: string };
  onRefresh: () => void;
  onNew: (initial?: { basis?: string; email?: string; id?: string }) => void;
  onNotify: (message: string, kind?: "good" | "bad" | "info") => void;
  onSubmitted: (runId: string) => void;
  onCancel: (scope?: SpeScope) => Promise<void>;
  onDeleteRun: () => Promise<void>;
};

export const emptyFiles: RunFiles = {
  log: "", mue: "", originalMue: "", originalMueMeta: null, datasetCounts: {}, parameters: "", weights: "", basis: "", jobLog: "", spe: null,
  parameterExports: [], testSet: null,
  speScopes: { input: { result: null, log: "", status: "" }, ame418: { result: null, log: "", status: "" }, energy: { result: null, log: "", status: "" } },
  hasOptimizedFunctional: false,
  hasInputDataset: false,
  inputDescriptors: null, lineage: null,
};

export function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(String(value).trim());
  return Number.isFinite(number) ? number : null;
}

export function normalizeStatus(status = ""): string {
  if (/^(success|completed)$/i.test(status)) return "completed";
  if (/failed|error|interrupted/i.test(status)) return "failed";
  if (/queued/i.test(status)) return "queued";
  if (/running|submitted|file prepared|density|descriptor|optimiz|outputting/i.test(status)) return "running";
  return "unknown";
}

export function statusLabel(status: string): string {
  return ({ completed: "Completed", failed: "Failed", running: "Running", queued: "Queued", unknown: "Status unavailable" })[status] || status;
}

export function displayStatus(job: Job): string {
  return job.activityStatus || job.status;
}

export function displayStatusLabel(job: Job): string {
  return job.activityLabel || (job.rawStatus && !["Success", "Failed", "Queued", "Running"].includes(job.rawStatus)
    ? job.rawStatus : statusLabel(job.status));
}

export function displayDate(date: string, long = false): string {
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return "Date unavailable";
  return parsed.toLocaleDateString("en-GB", { day: "numeric", month: long ? "long" : "short", ...(long ? { year: "numeric" as const } : {}) });
}

export function fileUrl(path: string): string {
  return "/api_dft/download/" + path.split("/").map(encodeURIComponent).join("/");
}

export async function listFiles(path: string, kind: "folder" | "file", signal?: AbortSignal) {
  const response = await axios.post("/api_dft/file_list", {
    file_dir: path, file_filter: "*", file_or_folder: kind,
  }, { signal });
  if (!Array.isArray(response.data.result)) throw new Error("The job list could not be read.");
  return response.data.result;
}

export async function listJobs(path: string, signal?: AbortSignal): Promise<Job[]> {
  const rows = await listFiles(path, "folder", signal);
  rows.sort((a, b) => (a._display_order !== undefined || b._display_order !== undefined)
    ? (a._display_order || 0) - (b._display_order || 0)
    : Number(b.time_modify) - Number(a.time_modify));
  return rows.map((row) => {
    const timestamp = Number(row.time_modify) * 1000;
    const total = String(row.total_mue || "").trim();
    const match = total.match(/(?:Total[^\d-]*|MUE\s*[:=]?\s*)([-+]?\d*\.?\d+(?:e[-+]?\d+)?)\s*$/i);
    return {
      id: String(row.name),
      date: Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : "",
      status: normalizeStatus(row.status), rawStatus: row.status || "",
      activityStatus: row.activity_state || undefined, activityLabel: row.activity_status || undefined,
      mue: /loss|regularization|weighted/i.test(total) ? null : match ? numberOrNull(match[1]) : numberOrNull(total),
    };
  });
}

export async function readDirectory(path: string, names: string[], signal?: AbortSignal): Promise<Record<string, any>> {
  const available = await listFiles(path, "file", signal);
  const values = await Promise.all(names.map(async (name) => {
    if (!available.some((file) => file.name === name)) return [name, ""];
    const response = await axios.get(fileUrl(path + "/" + name), { signal, responseType: "text" });
    return [name, response.data];
  }));
  return { ...Object.fromEntries(values), _files: available.map((file) => file.name) };
}

export function runFields(id: string) {
  const [weightFile, fork] = id.split("/");
  return { weightFile, ...(fork ? { fork } : {}) };
}

export async function listRuns(path: string, signal?: AbortSignal): Promise<Run[]> {
  const weights = await listJobs(path, signal);
  const groups = await Promise.all(weights.map(async (weight) => {
    const forks = (await listJobs(`${path}/${weight.id}`, signal))
      .filter((item) => /^fork-[1-9]\d*$/.test(item.id))
      .map((item) => ({ ...item, id: `${weight.id}/${item.id}` }));
    return [weight, ...forks];
  }));
  const runs = groups.flat();
  return Promise.all(runs.map(async (run) => {
    const output = await readDirectory(`${path}/${run.id}`, ["weight.csv"], signal);
    const lines = String(output["weight.csv"] || "").trim().split(/\r?\n/);
    const uploaded = lines.slice(1).find((line) => /\buploaded\b/i.test(line));
    const value = uploaded ? Number(uploaded.split("\t").at(-1)) : NaN;
    return { ...run, effectiveWeight: Number.isFinite(value) ? value : null };
  }));
}

export async function loadRunFiles(username: string, job: string, run: string, signal?: AbortSignal): Promise<RunFiles> {
  const path = `Work/${username}/${job}`;
  const [output, input, metadata] = await Promise.all([
    readDirectory(`${path}/output/${run}`, ["process.log", "Mue", "OriginalMue", "OriginalMue.meta.json", "results.json", "Parameters", "weight.csv", "SinglePointResults.json",
      "SinglePointResults.input.json", "SinglePointResults.ame418.json", "SinglePointResults.energy.json", "spe_input.log", "spe_ame418.log", "spe_energy.log", "spe_input.status.json", "spe_ame418.status.json", "spe_energy.status.json", "InputDescriptors.json", "run.json",
      "TestMue", "TestMue.json", "TestOriginalMue", "TestOriginalMue.meta.json"], signal),
    readDirectory(run.includes("/") ? `${path}/output/${run}/input` : `${path}/input`, ["basis.txt"], signal),
    readDirectory(path, ["process.log"], signal),
  ]);
  let spe = null;
  const datasetCounts = resultCounts(output["results.json"]);
  let originalMueMeta: BaselineMetadata | null = null;
  if (output["OriginalMue.meta.json"]) {
    try { originalMueMeta = JSON.parse(output["OriginalMue.meta.json"]); }
    catch { /* Invalid provenance must not be presented as native CF22D. */ }
  }
  if (output["SinglePointResults.json"]) {
    try { spe = JSON.parse(output["SinglePointResults.json"]); }
    catch { throw new Error("The single-point results file could not be read. Refresh after the calculation finishes."); }
  }
  const speScopes = {} as Record<SpeScope, SpeScopeData>;
  for (const scope of ["input", "ame418", "energy"] as const) {
    const raw = output[`SinglePointResults.${scope}.json`];
    const status = output[`spe_${scope}.status.json`] ? JSON.parse(output[`spe_${scope}.status.json`]) : null;
    let result = raw ? JSON.parse(raw) : null;
    let legacy = false;
    if (result && result.scope !== scope) throw new Error(`Unexpected ${scope} result scope`);
    if (!result && spe) {
      if (scope === "input" && spe.userTargetRows?.length) {
        result = { scope, targetRows: spe.userTargetRows, targetMue: spe.userTargetMue, summaryRows: [] };
        legacy = true;
      } else if (scope === "ame418" && (spe.targetRows?.length || spe.summaryRows?.length)) {
        const userName = String(spe.userDatasetTitle || "").replace(/\s+Single Point Energy Results.*$/i, "");
        result = { scope, targetRows: spe.targetRows || [], targetMue: spe.targetMue,
          summaryRows: (spe.summaryRows || []).filter((row) => row.name !== userName) };
        legacy = true;
      }
    }
    const complete = result?.complete === true && (scope !== "input" || result?.trainingComplete !== false);
    speScopes[scope] = { result, legacy, log: output[`spe_${scope}.log`] || "", status: status?.status || (complete ? "Success" : ""), updatedAt: status?.updated_at };
  }
  return {
    log: output["process.log"] || "", mue: output.Mue || "", originalMue: output.OriginalMue || "", originalMueMeta, datasetCounts, parameters: output.Parameters || "",
    parameterExports: parameterArtifacts.filter((name) => output._files.includes(name)), testSet: workspaceTestSet(output),
    weights: output["weight.csv"] || "", basis: String(input["basis.txt"] || "").trim(),
    jobLog: metadata["process.log"] || "", spe, speScopes,
    hasOptimizedFunctional: output._files.includes("CF22D_optimized.py") || output._files.includes("NEW-params.txt"),
    hasInputDataset: input._files.some((name: string) => /\.(zip|tgz|tar\.gz)$/.test(name)) && input._files.some((name: string) => /(?:\.ref|_ref)$/.test(name)),
    inputDescriptors: output["InputDescriptors.json"] ? JSON.parse(output["InputDescriptors.json"]) : null,
    lineage: output["run.json"] ? JSON.parse(output["run.json"]) : null,
  };
}

function resultCounts(text: string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const [name, result] of Object.entries(text ? JSON.parse(text) : {})) {
    const value = result as { MUE?: number; res?: number[] };
    if (value && Number.isFinite(value.MUE) && Array.isArray(value.res) && value.res.length &&
        value.res.every((error) => typeof error === "number" && Number.isFinite(error))) {
      counts[datasetKey(name)] = value.res.length;
    }
  }
  return counts;
}

export function errorMessage(error: any): string {
  return error.response?.data?.msg || error.response?.data?.message || error.message || "The request could not be completed. Please try again.";
}

export async function cancelRun(username: string, job: string, run: string, scope?: SpeScope) {
  const fields = runFields(run);
  const response = await axios.post("/api_dft/cancel", {
    work_dir: `Work/${username}/${job}`,
    ...fields,
    ...(scope ? { spe_scope: scope } : {}),
  });
  if (response.data.result === "error") throw new Error(response.data.msg || "The calculation could not be stopped.");
}

export async function deleteRun(username: string, job: string, run: string) {
  const path = `Work/${username}/${job}/output/${run}`.split("/").map(encodeURIComponent).join("/");
  const response = await axios.delete("/api_dft/delete_run/" + path);
  if (response.data.result === "error") throw new Error(response.data.msg || "The run results could not be deleted.");
}

export async function deleteJob(username: string, id: string) {
  if (!id || id === "." || id === ".." || /[\/\\]/.test(id)) throw new Error("Invalid job ID.");
  // The API owns the active-calculation check.  Listing every job and then
  // every weight/fork before deleting made this action fan out into dozens of
  // requests and left the confirmation sheet stuck while a busy worker was
  // still responding.  Send one authenticated, bounded request instead.
  const path = `Work/${username}/${id}`.split("/").map(encodeURIComponent).join("/");
  try {
    const response = await axios.delete("/api_dft/delete/" + path, { timeout: 30_000 });
    if (response.data.result === "error") throw new Error(response.data.msg || "The job could not be deleted.");
  } catch (error: any) {
    // A second tab may have removed the job after it was selected. Treat that
    // race as success so the workspace can refresh instead of trapping the
    // user in a confirmation dialog for an object that is already gone.
    if (error?.response?.status === 404) return;
    if (error?.code === "ECONNABORTED" || error?.code === "ETIMEDOUT") {
      throw new Error("Deleting took too long. Refresh the workspace to check whether the job was removed.");
    }
    throw error;
  }
}

export async function downloadFile(path: string, filename?: string, options: { timeout?: number } = {}) {
  const response = await axios.get(fileUrl(path), { responseType: "blob", ...options });
  const disposition = response.headers["content-disposition"] || "";
  const suggested = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || suggested || path.split("/").pop() || "download";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
