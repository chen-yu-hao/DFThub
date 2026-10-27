import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import axios from "axios";
import type { DetailProps, SpeScope, ParameterArtifact } from "./data";
import { displayDate, statusLabel, runFields, downloadFile, errorMessage } from "./data";
import { Icon } from "./Icons";
import { originalMueForRun, parseDatasetMue } from "./mue";
import MueViews from "./MueViews";
import { datasetType } from "./datasetMetadata";

const tabs = [
  ["overview", "Overview"],
  ["log", "Log"],
  ["weights", "Weights"],
  ["energies", "Self-consistent results"],
] as const;
type Tab = (typeof tabs)[number][0];
type WeightRow = {
  cells: string[];
  index: number;
  database: string;
  description: string;
  type: string;
  source: string;
  count: string;
  original: string;
};
type EnergyRow = {
  system: string;
  reference: number;
  calculated: number;
  error: number;
};

function positiveNumber(value: string) {
  if (!/^\s*(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?\s*$/i.test(value)) return NaN;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : NaN;
}

function parseWeights(text: string) {
  const lines = text.replace(/\r/g, "").trimEnd().split("\n");
  const header = (lines.shift() || "").split("\t");
  const weightIndex = header.findIndex((value) =>
    /inverse\s*weight/i.test(value),
  );
  if (header.length < 6 || weightIndex < 0)
    return { header, weightIndex, rows: [] as WeightRow[] };
  const rows = lines
    .filter((line) => line.trim())
    .map((line, index) => {
      const cells = line.split("\t");
      return {
        cells,
        index,
        database: cells[0]?.trim() || "",
        description: cells[1]?.trim() || "",
        type: datasetType(cells[0] || "", cells[2] || ""),
        source: cells[3]?.trim() || "",
        count: cells[4]?.trim() || "",
        original: cells[weightIndex]?.trim() || "",
      };
    });
  return { header, weightIndex, rows };
}


function energyRows(rows: unknown): EnergyRow[] {
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((row) => {
    if (
      !row ||
      typeof row !== "object" ||
      typeof row.reference !== "number" ||
      typeof row.calculated !== "number"
    )
      return [];
    if (!Number.isFinite(row.reference) || !Number.isFinite(row.calculated))
      return [];
    return [
      {
        system: String(row.system || row.index || "Reaction"),
        reference: row.reference,
        calculated: row.calculated,
        error: row.calculated - row.reference,
      },
    ];
  });
}

function Pill({ status, label = statusLabel(status) }: { status: string; label?: string }) {
  return (
    <span className={"pill " + status}>
      <span className={"dot " + status} aria-hidden="true" />
      {label}
    </span>
  );
}

function Empty({
  icon = "clock",
  title,
  children,
}: {
  icon?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="big">
        <Icon name={icon} />
      </span>
      <h4>{title}</h4>
      {children}
    </div>
  );
}

export default function JobDetail(props: DetailProps) {
  const {
    job,
    runs,
    run,
    files,
    loading,
    error,
    user,
    onRefresh,
    onNew,
    onNotify,
    onSubmitted,
    onCancel,
    onDeleteRun,
  } = props;
  const [tab, setTab] = useState<Tab>("overview");
  const [logView, setLogView] = useState("summary");
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [editedOnly, setEditedOnly] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, Record<number, string>>>(
    {},
  );
  const [submitting, setSubmitting] = useState(false);
  const [parameterExportBusy, setParameterExportBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [spePending, setSpePending] = useState<Record<string, boolean>>({});
  const [runActionBusy, setRunActionBusy] = useState(false);
  const [speScope, setSpeScope] = useState<SpeScope>("input");
  const [energyFile, setEnergyFile] = useState<File | null>(null);
  const [energyUploadError, setEnergyUploadError] = useState("");
  const [jumpToError, setJumpToError] = useState(false);
  const review = useRef<HTMLDialogElement>(null);
  const logBox = useRef<HTMLDivElement>(null);
  const requestPending = useRef(false);
  const uid = useId();
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("section");
    if (requested === "energies" || requested === "log") setTab(requested);
  }, []);
  useEffect(() => {
    const active = document.getElementById(uid + "-tab-" + tab);
    const group = active?.parentElement;
    if (!active || !group) return;
    const item = active.getBoundingClientRect();
    const bounds = group.getBoundingClientRect();
    if (item.right > bounds.right) group.scrollLeft += item.right - bounds.right;
    if (item.left < bounds.left) group.scrollLeft += item.left - bounds.left;
  }, [tab, uid]);
  const key = user.username + "/" + job.id + "/" + (run?.id || "");
  const currentSpe = files.speScopes[speScope];
  const spePayload = currentSpe.result;
  const scopeName = speScope === "input" ? "Input" : speScope === "ame418" ? "AME418" : "DFT energy";
  const canSpe = files.hasOptimizedFunctional;
  const parameterExports = files.parameterExports || [];
  const primaryParameterExport = parameterExports.find((name) => name !== "CF22D_optimized.py");
  async function exportParameters(artifact: ParameterArtifact) {
    if (!run || parameterExportBusy || loading || !parameterExports.includes(artifact)) return;
    const filename = artifact === "Parameters" ? "parameters.txt" : artifact;
    const downloadName = `${job.id}-${run.id.replaceAll("/", "-")}-${filename}`;
    setParameterExportBusy(true);
    try {
      await downloadFile(`Work/${user.username}/${job.id}/output/${run.id}/${artifact}`, downloadName, { timeout: 30_000 });
    } catch (error) {
      onNotify(errorMessage(error), "bad");
    } finally {
      setParameterExportBusy(false);
    }
  }
  function scopeBusy(scope: SpeScope) {
    return Boolean(spePending[key + "/" + scope]) || ["Queued", "Running"].includes(files.speScopes[scope].status);
  }
  const anySpeBusy = scopeBusy("input") || scopeBusy("ame418");
  const mainBusy = Boolean(run && ["queued", "running"].includes(run.status));
  const canRefine = canSpe && run?.status === "completed" && !scopeBusy("input") &&
    files.speScopes.input.status === "Success" && files.speScopes.input.result?.complete === true &&
    files.speScopes.input.result?.trainingComplete !== false &&
    files.inputDescriptors?.complete === true && files.inputDescriptors.grid_level === 6 &&
    files.speScopes.input.result?.descriptor_snapshot_id === files.inputDescriptors.id;
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;
  useEffect(() => {
    setSpePending((previous) => {
      const next = { ...previous };
      for (const scope of ["input", "ame418", "energy"] as const) {
        if (files.speScopes[scope].status) delete next[key + "/" + scope];
      }
      return next;
    });
  }, [files.speScopes, key]);
  useEffect(() => {
    if (!anySpeBusy) return;
    const timer = setInterval(() => { if (!document.hidden) refreshRef.current(); }, 15000);
    return () => clearInterval(timer);
  }, [anySpeBusy]);
  const draft = drafts[key] || {};
  const weights = useMemo(() => parseWeights(files.weights), [files.weights]);
  const edits = Object.keys(draft).length;
  const invalid = weights.rows.filter(
    (row) => !Number.isFinite(positiveNumber(draft[row.index] ?? row.original)),
  ).length;
  const types = [
    "all",
    ...new Set(weights.rows.map((row) => row.type).filter(Boolean)),
  ];
  const filteredRows = weights.rows.filter(
    (row) =>
      (type === "all" || type === row.type) &&
      (!editedOnly || row.index in draft) &&
      (row.database + " " + row.description)
        .toLowerCase()
        .includes(search.trim().toLowerCase()),
  );
  const fullLog = files.log || files.jobLog || "";
  const lines = fullLog.replace(/\r/g, "").split("\n");
  const summary = lines
    .map((line, index) => ({ line, index }))
    .filter(({ line }) =>
      /^(?:\[|engine:|The program|Found |Basis |Initial |DFT-D3|Weight |Parameters |File )|error|failed|finished|completed|converged/i.test(
        line.trim(),
      ),
    );
  const shownLines =
    logView === "summary" && summary.length
      ? summary
      : lines.map((line, index) => ({ line, index }));
  const latestStart = fullLog.lastIndexOf("The program starts running!");
  const latestLog = latestStart >= 0 ? fullLog.slice(latestStart) : fullLog;
  const lastError =
    latestLog
      .split("\n")
      .filter((line) =>
        /\[error\]|traceback|exception|error:|failed|not converged/i.test(line),
      )
      .slice(-1)[0] || "";
  const factLog = latestLog + "\n" + files.jobLog;
  const basis =
    files.basis || factLog.match(/\b(?:preset|basis)=([^|\s]+)/i)?.[1] || "";
  const dataset = factLog.match(
    /Found\s+(\d+)\s+structures\s+in\s+dataset\s+['"]([^'"]+)/i,
  );
  const densityProgress = [
    ...latestLog.matchAll(/\[(\d+)\/(\d+)\].*\bdone\b/g),
  ].slice(-1)[0];
  const densityDone = densityProgress ? Number(densityProgress[1]) : 0;
  const densityTotal = densityProgress
    ? Number(densityProgress[2])
    : dataset
      ? Number(dataset[1])
      : null;
  const mueBy = useMemo(() => parseDatasetMue(files.mue), [files.mue]);
  const originalMue = useMemo(() => originalMueForRun(files.originalMue || "", files.originalMueMeta), [files.originalMue, files.originalMueMeta]);
  const speRows = useMemo(
    () =>
      energyRows(
        spePayload?.userTargetRows?.length
          ? spePayload.userTargetRows
          : spePayload?.targetRows,
      ),
    [spePayload],
  );
  const speSummary = Array.isArray(spePayload?.summaryRows)
    ? spePayload.summaryRows.filter(
        (row) =>
          typeof row.name === "string" &&
          typeof row.mue === "number" &&
          Number.isFinite(row.mue),
      )
    : [];
  const energyResults = Array.isArray(spePayload?.molecularEnergies)
    ? spePayload.molecularEnergies.filter((row: any) => row && typeof row.name === "string")
    : [];
  const hasEnergy = speScope === "energy" && energyResults.length > 0;
  const hasSpe = speRows.length > 0 || speSummary.length > 0 || hasEnergy;
  const completed = run?.status === "completed";
  const nextRun =
    "weight_" +
    (Math.max(
      -1,
      ...runs.map((item) => Number(item.id.match(/^weight_(\d+)$/)?.[1] ?? -1)),
    ) +
      1);
  const newSettings = () => onNew({ basis, email: user.email, id: job.id });

  useEffect(() => {
    setSearch("");
    setType("all");
    setEditedOnly(false);
    setSubmitError("");
    review.current?.close();
  }, [key]);
  useEffect(() => {
    if (!jumpToError || tab !== "log") return;
    const line = logBox.current?.querySelector<HTMLElement>(".ln.err");
    if (line && logBox.current)
      logBox.current.scrollTop = line.offsetTop - logBox.current.offsetTop - 60;
    setJumpToError(false);
  }, [jumpToError, tab, logView]);

  function showError() {
    setLogView("full");
    setTab("log");
    setJumpToError(true);
  }
  function setWeight(row: WeightRow, value: string | null) {
    setDrafts((all) => {
      const next = { ...(all[key] || {}) };
      if (
        value === null ||
        (Number.isFinite(positiveNumber(value)) &&
          positiveNumber(value) === Number(row.original))
      )
        delete next[row.index];
      else next[row.index] = value;
      return { ...all, [key]: next };
    });
  }
  function discard() {
    setDrafts((all) => ({ ...all, [key]: {} }));
  }
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      onNotify("Copied to clipboard.");
    } catch {
      onNotify(
        "Clipboard access is unavailable. Select and copy the text manually.",
        "bad",
      );
    }
  }
  async function submitWeights() {
    if (!run || !edits || invalid || requestPending.current || loading) return;
    requestPending.current = true;
    setSubmitting(true);
    setSubmitError("");
    try {
      const response = await axios.post("/api_dft/file_list", {
        file_dir: "Work/" + user.username + "/" + job.id + "/output/",
        file_filter: "*",
        file_or_folder: "folder",
      });
      if (!Array.isArray(response.data.result))
        throw new Error(response.data.msg || "Could not check existing runs.");
      const availableIds = response.data.result.map((item) =>
        Number(String(item.name).match(/^weight_(\d+)$/)?.[1] ?? -1),
      );
      const newRun =
        "weight_" +
        (Math.max(
          -1,
          ...availableIds,
          ...runs.map((item) =>
            Number(item.id.match(/^weight_(\d+)$/)?.[1] ?? -1),
          ),
        ) +
          1);
      const text =
        [
          weights.header.join("\t"),
          ...weights.rows.map((row) => {
            const cells = [...row.cells];
            if (row.index in draft)
              cells[weights.weightIndex] = String(
                positiveNumber(draft[row.index]),
              );
            return cells.join("\t");
          }),
        ].join("\n") + "\n";
      const workDir = "Work/" + user.username + "/" + job.id;
      const data = new FormData();
      data.append("folder_dir", workDir + "/output/" + newRun);
      data.append(
        "files",
        new File([text], "weight.csv", { type: "text/tab-separated-values" }),
      );
      const upload = await axios.put("/api_dft/upload", data);
      if (upload.data.result === "error" || upload.data.success === false)
        throw new Error(upload.data.msg || "Weight upload failed.");
      const submitted = await axios.post("/api_dft/submit", {
        mode: "optim",
        work_dir: workDir,
        weightFile: newRun,
      });
      if (submitted.data.result === "error" || submitted.data.success === false)
        throw new Error(
          submitted.data.msg || "Optimization could not be started.",
        );
      setDrafts((all) => ({ ...all, [key]: {} }));
      review.current?.close();
      setTab("overview");
      onNotify(newRun + " submitted for " + job.id + ".");
      onSubmitted(newRun);
    } catch (failure: any) {
      setSubmitError(
        failure.response?.data?.msg ||
          failure.message ||
          "Submission failed. Your edits are preserved.",
      );
    } finally {
      requestPending.current = false;
      setSubmitting(false);
    }
  }
  async function startSpe(scope: SpeScope = "input") {
    if (
      !run ||
      !canSpe ||
      (scope === "input" && !files.hasInputDataset) ||
      scope === "energy" ||
      loading ||
      requestPending.current ||
      scopeBusy(scope)
    )
      return;
    if (
      !window.confirm(
        "Calculate " + (scope === "input" ? "Input only" : "AME418 only") + " with " +
          run.id +
          "? This may take 1–48 hours.",
      )
    )
      return;
    requestPending.current = true;
    setSubmitting(true);
    try {
      const response = await axios.post("/api_dft/submit", {
        mode: "spe",
        spe_scope: scope,
        work_dir: "Work/" + user.username + "/" + job.id,
        ...runFields(run.id),
      });
      if (response.data.result === "error" || response.data.success === false)
        throw new Error(
          response.data.msg || "Calculation could not be started.",
        );
      setSpePending((previous) => ({ ...previous, [key + "/" + scope]: true }));
      setSpeScope(scope);
      setTab("energies");
      onNotify(
        (scope === "input" ? "Input" : "AME418") + " calculation submitted for " + job.id + "/" + run.id + ".",
      );
      onRefresh();
    } catch (failure: any) {
      onNotify(
        failure.response?.data?.msg ||
          failure.message ||
          "Could not start the calculation.",
        "bad",
      );
    } finally {
      requestPending.current = false;
      setSubmitting(false);
    }
  }
  async function startEnergy() {
    if (!run || !canSpe || !energyFile || loading || requestPending.current || scopeBusy("energy")) return;
    requestPending.current = true;
    setSubmitting(true);
    setEnergyUploadError("");
    try {
      const data = new FormData();
      data.append("folder_dir", `Work/${user.username}/${job.id}/output/${run.id}/energy_input`);
      data.append("files", energyFile, energyFile.name);
      const upload = await axios.put("/api_dft/upload", data);
      if (upload.data.result === "error" || upload.data.success === false) throw new Error(upload.data.msg || "Energy archive upload failed.");
      const response = await axios.post("/api_dft/submit", { mode: "spe", spe_scope: "energy", work_dir: `Work/${user.username}/${job.id}`, ...runFields(run.id) });
      if (response.data.result === "error" || response.data.success === false) throw new Error(response.data.msg || "DFT energy calculation could not be started.");
      setEnergyFile(null);
      setSpePending((previous) => ({ ...previous, [key + "/energy"]: true }));
      setSpeScope("energy");
      onNotify(`DFT energy calculation submitted for ${job.id}/${run.id}.`);
      onRefresh();
    } catch (failure: any) {
      setEnergyUploadError(failure.response?.data?.msg || failure.message || "Could not start the DFT energy calculation.");
    } finally { requestPending.current = false; setSubmitting(false); }
  }
  function chooseEnergyFile(file: File | null) {
    setEnergyUploadError("");
    if (!file) { setEnergyFile(null); return; }
    if (!/\.(?:tgz|tar\.gz|zip)$/i.test(file.name)) {
      setEnergyFile(null);
      setEnergyUploadError("Choose a .tgz, .tar.gz or .zip archive of .xyz structures.");
      return;
    }
    setEnergyFile(file);
  }
  async function cancelCalculation(scope?: SpeScope) {
    if (runActionBusy || !run) return;
    setRunActionBusy(true);
    try {
      await onCancel(scope);
      onNotify(`${scope ? scope === "input" ? "Input" : "AME418" : "Run"} calculation stop requested.`, "info");
      onRefresh();
    } catch (failure: any) {
      onNotify(failure.message || "The calculation could not be stopped.", "bad");
    } finally { setRunActionBusy(false); }
  }
  async function deleteResults() {
    if (!run || runActionBusy || mainBusy || anySpeBusy) return;
    if (!window.confirm(`Delete results for ${job.id}/${run.id}? The Job and uploaded input will be kept.`)) return;
    setRunActionBusy(true);
    try {
      await onDeleteRun();
      onNotify(`${job.id}/${run.id} results deleted.`, "good");
    } catch (failure: any) {
      onNotify(failure.message || "The run results could not be deleted.", "bad");
    } finally { setRunActionBusy(false); }
  }

  async function refineInput() {
    if (!run || !canRefine || loading || requestPending.current) return;
    requestPending.current = true;
    setSubmitting(true);
    try {
      const response = await axios.post("/api_dft/submit", {
        mode: "refine", work_dir: `Work/${user.username}/${job.id}`,
        ...runFields(run.id), descriptor_snapshot_id: files.inputDescriptors!.id,
      });
      if (!response.data.run_id) throw new Error(response.data.msg || "Refinement could not be started.");
      setTab("overview");
      onNotify(`${response.data.run_id} ${response.data.existing ? "already exists" : "submitted"}.`);
      onSubmitted(response.data.run_id);
    } catch (failure: any) {
      onNotify(failure.response?.data?.msg || failure.message || "Refinement could not be started.", "bad");
    } finally {
      requestPending.current = false;
      setSubmitting(false);
    }
  }

  const densityFinished = densityTotal !== null && densityDone >= densityTotal;
  const tuningStarted = /Weight tuning started|Parameters optimization/i.test(
    latestLog,
  );
  const tuningFinished =
    /Parameters optimization finished/i.test(latestLog) || completed;
  const stages = [
    {
      label: "Data checked",
      state:
        dataset || /Basis preflight completed/i.test(factLog)
          ? "done"
          : "pending",
      sub: dataset ? dataset[1] + " structures" : "Awaiting log details",
    },
    {
      label: "Initial densities",
      state: densityFinished
        ? "done"
        : lastError && /SCF|density|structure/i.test(lastError)
          ? "failed"
          : /Initial density calculation/i.test(latestLog) &&
              run?.status === "running"
            ? "active"
            : "pending",
      sub:
        densityTotal !== null
          ? densityDone + " of " + densityTotal
          : "No progress reported",
    },
    {
      label: "Weight tuning",
      state: tuningFinished
        ? "done"
        : tuningStarted && run?.status === "running"
          ? "active"
          : "pending",
      sub:
        run?.mue != null
          ? "MUE " + run.mue.toFixed(2) + " kcal/mol"
          : tuningStarted
            ? "See calculation log"
            : "No progress reported",
    },
    {
      label: "Single-point energies",
      state: anySpeBusy ? "active" : files.speScopes.input.result ? "done" : "pending",
      sub: anySpeBusy
        ? "Calculation in progress"
        : files.speScopes.input.result
          ? "Input results ready"
          : canSpe
            ? "Ready to start"
            : "Awaiting fitted parameters",
    },
  ];

  return (
    <>
      <div className="d-head">
        <div>
          <div className="d-title">
            <h3>{job.id}</h3>
            <Pill status={run?.activityStatus || run?.status || job.activityStatus || job.status}
              label={run?.activityLabel || (!run ? job.activityLabel : undefined)} />
          </div>
          <div className="d-meta">
            {files.lineage && <span>Parent: {files.lineage.parent} · Grid level: {files.lineage.grid_level}</span>}
            <span>
              <Icon name="clock" />
              Submitted {displayDate(job.date, true)}
            </span>
            {dataset && (
              <span>
                <Icon name="archive" />
                {dataset[2]} · {dataset[1]} structures
              </span>
            )}
            {basis && (
              <span>
                <Icon name="atom" />
                {basis}
              </span>
            )}
          </div>
        </div>
        <div className="d-actions spe-actions">
          <button
            className="icon-btn"
            aria-label="Refresh"
            title="Refresh run data"
            onClick={onRefresh}
            disabled={loading}
          >
            <Icon name="refresh" />
          </button>
          <a className="btn btn-secondary" href={`/analyze/?job=${encodeURIComponent(job.id)}${run ? "&focus=" + encodeURIComponent(run.id) : ""}`}><Icon name="chart" />Analyze runs</a>
          {run && primaryParameterExport && <button type="button" className="btn btn-secondary"
            disabled={loading || parameterExportBusy} onClick={() => void exportParameters(primaryParameterExport)}>
            <Icon name="down" />Export parameters
          </button>}
          {run && (
            <button
              className="btn btn-secondary"
              onClick={() => setTab("weights")}
            >
              <Icon name="slider" />
              Tune weights
            </button>
          )}
          {run && mainBusy && <button className="btn btn-danger" disabled={runActionBusy} onClick={() => void cancelCalculation()}>
            <Icon name="stop" />{runActionBusy ? "Stopping…" : "Stop calculation"}
          </button>}
          {run && !mainBusy && !anySpeBusy && <button className="btn btn-danger" disabled={runActionBusy} onClick={() => void deleteResults()}>
            <Icon name="trash" />{runActionBusy ? "Deleting…" : "Delete run results"}
          </button>}
          {canSpe ? <>
            {scopeBusy("ame418") && <button className="btn btn-danger" disabled={runActionBusy} onClick={() => void cancelCalculation("ame418")}><Icon name="stop" />{runActionBusy ? "Stopping…" : "Stop AME418"}</button>}
            {scopeBusy("input") ? <button className="btn btn-danger" disabled={runActionBusy} onClick={() => void cancelCalculation("input")}><Icon name="stop" />{runActionBusy ? "Stopping…" : "Stop Input"}</button> : <button className="btn btn-primary" disabled={!files.hasInputDataset || submitting || loading} title={!files.hasInputDataset ? "Input geometry and reference files are required" : undefined} onClick={() => startSpe("input")}>
              <Icon name="play" />{scopeBusy("input") ? "Input in progress" : "Calculate Input"}
            </button>}
          </> : run?.status === "failed" ? (
            <button className="btn btn-primary" onClick={newSettings}><Icon name="dup" />New job with these settings</button>
          ) : null}
        </div>
      </div>
      <div className="d-tabs">
        <div className="seg detail-sections" role="tablist" aria-label="Job sections">
          {tabs.map(([value, label], index) => (
            <button
              key={value}
              role="tab"
              id={uid + "-tab-" + value}
              aria-controls={uid + "-panel"}
              aria-selected={tab === value}
              tabIndex={tab === value ? 0 : -1}
              onClick={() => setTab(value)}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % tabs.length
                    : event.key === "ArrowLeft"
                      ? (index + tabs.length - 1) % tabs.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? tabs.length - 1
                          : -1;
                if (next >= 0) {
                  event.preventDefault();
                  setTab(tabs[next][0]);
                  document
                    .getElementById(uid + "-tab-" + tabs[next][0])
                    ?.focus();
                }
              }}
            >
              {label}
              {value === "weights" && edits > 0 && (
                <span className="badge num">{edits}</span>
              )}
              {value === "log" && lastError && <span className="dot failed" />}
            </button>
          ))}
        </div>
      </div>
      <div
        className="panel"
        id={uid + "-panel"}
        role="tabpanel"
        aria-labelledby={uid + "-tab-" + tab}
        aria-busy={loading}
      >
        {error && (
          <div className="alert" role="alert">
            <Icon name="alert" />
            <b>Could not load run data</b>
            <div>{error}</div>
          </div>
        )}
        {!run ? (
          <Empty title={loading ? "Loading runs…" : "No runs available yet"}>
          </Empty>
        ) : (
          <>
            {tab === "overview" && (
              <>
                <ol className="tracker" aria-label="Job progress">
                  {stages.map((stage) => (
                    <li key={stage.label} className={stage.state}>
                      <span className="t-ico" aria-hidden="true">
                        {stage.state !== "pending" && (
                          <Icon
                            name={
                              stage.state === "done"
                                ? "check"
                                : stage.state === "failed"
                                  ? "x"
                                  : "refresh"
                            }
                          />
                        )}
                      </span>
                      <div className="t-label">
                        {stage.label}
                        <span className="sr"> ({stage.state})</span>
                      </div>
                      <div className="t-sub">{stage.sub}</div>
                    </li>
                  ))}
                </ol>
                {run.status === "failed" || lastError ? (
                  <div className="alert" role="alert">
                    <Icon name="alert" />
                    <b>
                      {run.status === "failed"
                        ? "This run stopped with an error"
                        : "The log reports an error"}
                    </b>
                    <div style={{ overflowWrap: "anywhere" }}>
                      {lastError || "Open the process log for details."}
                    </div>
                    <div>
                      <div className="row">
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={newSettings}
                        >
                          <Icon name="dup" />
                          New job with these settings
                        </button>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={showError}
                        >
                          View in log
                        </button>
                      </div>
                    </div>
                  </div>
                ) : run.status === "queued" ? (
                  <div className="alert warn">
                    <Icon name="clock" />
                    <b>Waiting to run</b>
                    <div>
                      The server has queued this run. Refresh to check its
                      latest status.
                    </div>
                  </div>
                ) : null}
                <details className="box parameters-panel">
                  <summary className="box-head parameters-summary"><span className="parameters-title">Optimized parameters</span><Icon name="chev" className="parameters-chevron" /></summary>
                  {parameterExports.length > 0 && <div className="parameters-actions" role="group" aria-label="Export functional parameters">
                    {parameterExports.map((artifact) => <button key={artifact} type="button" className="btn btn-secondary btn-sm"
                      disabled={loading || parameterExportBusy} onClick={() => void exportParameters(artifact)}>
                      <Icon name="down" />{artifact === "Parameters" ? "Export parameters" : artifact === "NEW-params.txt" ? "Raw parameters (.txt)" : "PySCF functional (.py)"}
                    </button>)}
                  </div>}
                  <pre className="console parameters-output">{files.parameters || "Parameters are not available for this run yet."}</pre>
                </details>
                <MueViews rows={mueBy} original={originalMue} weights={files.weights}
                  counts={files.datasetCounts || {}} testSet={files.testSet} />
                {files.mue && !mueBy.length && (
                  <details className="box">
                    <summary className="box-head" style={{ cursor: "pointer" }}>
                      MUE output
                    </summary>
                    <pre
                      className="console"
                      style={{ margin: 0, padding: 16, whiteSpace: "pre-wrap" }}
                    >
                      {files.mue}
                    </pre>
                  </details>
                )}
              </>
            )}
            {tab === "log" && (
              <>
                {densityTotal !== null && (
                  <div className="progress">
                    <div className="progress-top">
                      <span>
                        <b>Initial densities</b> ·{" "}
                        <span className="num">
                          {densityDone} of {densityTotal}
                        </span>{" "}
                        structures
                      </span>
                      <span
                        className={
                          run.status === "failed" ? "err-pos" : "muted"
                        }
                      >
                        {run.status === "failed"
                          ? "Stopped with an error"
                          : densityFinished
                            ? "Finished"
                            : "Last reported progress"}
                      </span>
                    </div>
                    <div
                      className={"meter " + run.status}
                      role="progressbar"
                      aria-label="Initial densities"
                      aria-valuemin={0}
                      aria-valuemax={densityTotal}
                      aria-valuenow={densityDone}
                    >
                      <i
                        style={{
                          width:
                            Math.min(
                              100,
                              densityTotal
                                ? (densityDone / densityTotal) * 100
                                : 0,
                            ) + "%",
                        }}
                      />
                    </div>
                  </div>
                )}
                <div className="log-tools">
                  <div className="seg" role="group" aria-label="Log detail">
                    <button
                      aria-pressed={logView === "summary"}
                      onClick={() => setLogView("summary")}
                    >
                      Summary
                    </button>
                    <button
                      aria-pressed={logView === "full"}
                      onClick={() => setLogView("full")}
                    >
                      Full output
                    </button>
                  </div>
                  <span className="sp" />
                  {lastError && (
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={showError}
                    >
                      <Icon name="alert" />
                      Jump to error
                    </button>
                  )}
                  <button
                    className="btn btn-secondary btn-sm"
                    disabled={!fullLog}
                    onClick={() => copy(fullLog)}
                  >
                    <Icon name="copy" />
                    Copy log
                  </button>
                </div>
                <div
                  className="console"
                  ref={logBox}
                  tabIndex={0}
                  aria-label="Process log"
                  style={{ height: 460, position: "relative" }}
                >
                  {fullLog ? (
                    shownLines.map(({ line, index }) => (
                      <div
                        key={index}
                        className={
                          "ln " +
                          (/\[error\]|traceback|exception|error:|not converged/i.test(
                            line,
                          )
                            ? "err"
                            : /^\[\d+\/\d+\].*done/.test(line)
                              ? "ok"
                              : /^The program starts|^engine:/.test(line)
                                ? "hdr"
                                : "")
                        }
                      >
                        <span>{index + 1}</span>
                        <span>{line || " "}</span>
                      </div>
                    ))
                  ) : (
                    <div className="ln">
                      <span>1</span>
                      <span>No output yet. Refresh after this run starts.</span>
                    </div>
                  )}
                </div>
              </>
            )}
            {tab === "weights" && (
              <>
                <div className="w-intro">
                  <p>
                    Inverse weight sets how much each database counts in the
                    fit. <b>Lower values give it more influence.</b> Edit any
                    value, then resubmit to start a new run.
                  </p>
                  <span className="file-chip">
                    <Icon name="doc" />
                    {user.username}.{job.id}.{run.id}.csv
                  </span>
                </div>
                {!weights.rows.length ? (
                  <Empty icon="doc" title="Weights are not available yet">
                    <p>
                      Refresh once the server has created this run’s weight
                      file.
                    </p>
                  </Empty>
                ) : (
                  <>
                    <div className="w-tools">
                      <label className="search">
                        <span className="sr">Search databases</span>
                        <Icon name="search" />
                        <input
                          type="search"
                          placeholder="Search databases"
                          value={search}
                          onChange={(event) => setSearch(event.target.value)}
                          autoComplete="off"
                        />
                      </label>
                      <div
                        className="seg"
                        role="group"
                        aria-label="Filter by type"
                      >
                        {types.map((value) => (
                          <button
                            key={value}
                            aria-pressed={type === value}
                            onClick={() => setType(value)}
                          >
                            {value === "all" ? "All" : value}
                            <span className="count num">
                              {
                                weights.rows.filter(
                                  (row) =>
                                    value === "all" || row.type === value,
                                ).length
                              }
                            </span>
                          </button>
                        ))}
                      </div>
                      <button
                        className="toggle-chip"
                        aria-pressed={editedOnly}
                        onClick={() => setEditedOnly(!editedOnly)}
                      >
                        <Icon name="undo" />
                        Edited only
                      </button>
                    </div>
                    <div className="tbl-wrap wt">
                      <table aria-label="Inverse weights">
                        <thead>
                          <tr>
                            <th>#</th>
                            <th className="r col-inverse">Adjust inverse weight</th>
                            <th>Database</th>
                            <th>Type</th>
                            <th className="col-src">Source</th>
                            <th className="r col-n">Data points</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredRows.length ? (
                            filteredRows.map((row) => {
                              const value = draft[row.index] ?? row.original;
                              const changed = row.index in draft;
                              const bad = !Number.isFinite(
                                positiveNumber(value),
                              );
                              return (
                                <tr
                                  data-i={row.index}
                                  key={row.index}
                                  className={changed ? "edited" : ""}
                                >
                                  <td className="idx num">{row.index}</td>
                                  <td className="r col-inverse">
                                    <div className="wcell">
                                      <button className="qbtn" disabled={submitting || bad} aria-label={"Halve " + row.database + " weight"} title="Halve" onClick={() => setWeight(row, String(positiveNumber(value) / 2))}>÷2</button>
                                      <button className="qbtn" disabled={submitting || bad} aria-label={"Double " + row.database + " weight"} title="Double" onClick={() => setWeight(row, String(positiveNumber(value) * 2))}>×2</button>
                                      <input className={"w-in" + (bad ? " bad" : "")} inputMode="decimal" value={value} disabled={submitting} aria-invalid={bad} aria-label={"Inverse weight for " + row.database} title={"Original: " + row.original} onChange={(event) => setWeight(row, event.target.value)} />
                                      <button className="icon-btn reset-row" disabled={submitting} aria-label={"Reset " + row.database + " weight"} title={"Reset to " + row.original} onClick={() => setWeight(row, null)}><Icon name="undo" /></button>
                                    </div>
                                    <div className="was num">{changed ? "was " + row.original : ""}</div>
                                  </td>
                                  <td>
                                    <div className="db">
                                      {row.database}
                                      {row.source.toLowerCase() ===
                                        "uploaded" && (
                                        <span className="mine-tag">
                                          Your data set
                                        </span>
                                      )}
                                    </div>
                                    {row.description && (
                                      <div className="db-d">
                                        {row.description}
                                      </div>
                                    )}
                                  </td>
                                  <td>
                                    {row.type ? (
                                      <span className="type">{row.type}</span>
                                    ) : (
                                      <span className="muted">—</span>
                                    )}
                                  </td>
                                  <td className="col-src muted">
                                    {row.source || "—"}
                                  </td>
                                  <td className="r num col-n">
                                    {row.count || "—"}
                                  </td>
                                </tr>
                              );
                            })
                          ) : (
                            <tr>
                              <td colSpan={6}>
                                <div className="empty" style={{ border: 0 }}>
                                  <Icon name="search" />
                                  <p>
                                    No databases match. Try another search or
                                    type.
                                  </p>
                                </div>
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    {edits > 0 && (
                      <div
                        className="savebar"
                        role="region"
                        aria-label="Unsaved weight changes"
                      >
                        <span>
                          <b className="num">{edits}</b>{" "}
                          {edits === 1 ? "weight" : "weights"} changed
                          {invalid > 0 && (
                            <>
                              {" "}
                              ·{" "}
                              <span className="err-pos">
                                {invalid} values need to be finite numbers above
                                0
                              </span>
                            </>
                          )}
                        </span>
                        <span className="sp" />
                        <button
                          className="btn btn-secondary btn-sm"
                          disabled={submitting}
                          onClick={discard}
                        >
                          Discard
                        </button>
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={invalid > 0 || submitting || loading}
                          onClick={() => {
                            setSubmitError("");
                            review.current?.showModal();
                          }}
                        >
                          Review &amp; resubmit
                        </button>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
            {tab === "energies" && (
              <>
                <div className="seg" role="group" aria-label="Calculation dataset">
                  <button aria-pressed={speScope === "input"} onClick={() => setSpeScope("input")}>Input</button>
                  <button aria-pressed={speScope === "ame418"} onClick={() => setSpeScope("ame418")}>AME418</button>
                  <button aria-pressed={speScope === "energy"} onClick={() => setSpeScope("energy")}>DFT energy</button>
                </div>
                <p className="muted">{speScope === "input" ? "Calculate your training data and optional test set with the fitted functional. Only training descriptors are used for the next iteration." : speScope === "ame418" ? "Calculate only the AME418 benchmark datasets. Your uploaded Input is not included." : "Upload a .tgz archive of XYZ structures. No .ref file is required; the selected Run's optimized functional and basis are used."}</p>
                <p className="muted">{spePayload?.grid_level != null ? `Result grid level: ${spePayload.grid_level}. ` : hasSpe ? "Result grid level: not recorded. " : ""}Next calculation grid level: {speScope === "ame418" ? 5 : 6}.</p>
                {speScope === "energy" && <div className="energy-upload box">
                  <label className="file-picker">
                    <span className="btn btn-secondary">Choose .tgz archive</span>
                    <input type="file" accept=".tgz,.tar.gz,.zip,application/gzip,application/x-gzip,application/zip" onChange={(event) => chooseEnergyFile(event.target.files?.[0] || null)} />
                    <span className="file-name">{energyFile?.name || "No archive selected"}</span>
                  </label>
                  <p className="muted">The archive is evaluated molecule by molecule with the optimized parameters from {run.id}. Reference energies are not needed.</p>
                  {energyUploadError && <p className="err-pos" role="alert">{energyUploadError}</p>}
                </div>}
                <div className="d-actions" style={{ justifyContent: "flex-start" }}>
                  {scopeBusy(speScope) ? <button className="btn btn-danger" disabled={runActionBusy} onClick={() => void cancelCalculation(speScope)}><Icon name="stop" />{runActionBusy ? "Stopping…" : "Stop " + scopeName}</button> : <button className="btn btn-primary" disabled={!canSpe || (speScope === "input" && !files.hasInputDataset) || (speScope === "energy" && !energyFile) || submitting || loading} onClick={() => speScope === "energy" ? void startEnergy() : void startSpe(speScope)}>
                    <Icon name="play" />{"Calculate " + scopeName}
                  </button>}
                  <button className="btn btn-secondary" onClick={onRefresh} disabled={loading}><Icon name="refresh" />Refresh results</button>
                  {currentSpe.status && <span className="pill" role="status">{scopeName}: {currentSpe.status}</span>}
                </div>
                {speScope === "input" && <div className="refine-action">
                  <button className="btn btn-primary" disabled={!canRefine || submitting || loading} onClick={refineInput}>
                    <Icon name="refresh" />Re-optimize with SCF descriptors
                  </button>
                  <p className="muted">{canRefine
                    ? "Creates a new fork using self-consistent Input descriptors. All other settings are inherited."
                    : scopeBusy("input") ? "Waiting for Input calculation and descriptor validation."
                    : "Complete Calculate Input at grid level 6 to prepare descriptors for a new fork."}</p>
                </div>}
                {(scopeBusy(speScope) || currentSpe.status === "Failed") && <div className={"alert " + (currentSpe.status === "Failed" ? "" : "info")} role="status">
                  <Icon name={currentSpe.status === "Failed" ? "alert" : "clock"} />
                  <b>{scopeName} {currentSpe.status === "Failed" ? "calculation failed" : "calculation is queued or running"}</b>
                  <div>{hasSpe ? "Existing results are shown below. Check the calculation log for the latest attempt." : "See the calculation log below for progress and errors."}</div>
                </div>}
                {spePayload?.complete === false && <p className="err-pos" role="status">Partial results: some molecules did not converge.</p>}
                {speScope === "input" && spePayload?.testComplete === false && <div className="alert info" role="status">
                  <Icon name="alert" />
                  <b>{spePayload.trainingComplete ? "Training SCF complete · Test set incomplete" : "Test set incomplete"}</b>
                  <div>
                    {canRefine ? "You can continue to the next iteration using the verified training descriptors. " : ""}
                    {spePayload.testCoverage && `${spePayload.testCoverage.completedMolecules}/${spePayload.testCoverage.totalMolecules} test molecules and ${spePayload.testCoverage.completedReactions}/${spePayload.testCoverage.totalReactions} reactions completed. `}
                    {spePayload.testCoverage?.failedMolecules?.length > 0 && `Unfinished: ${spePayload.testCoverage.failedMolecules.join(", ")}. `}
                    {"Partial test MUE is excluded from Analyze. Calculate Input again to retry unfinished molecules and reuse completed results."}
                  </div>
                </div>}
                {speScope === "input" && !files.hasInputDataset && <p className="muted">Input geometry and reference files are missing. Create a new job with both files to calculate Input.</p>}
                {currentSpe.legacy && <p className="muted">Results from a previous combined calculation.</p>}
                {hasSpe ? (
                  <>
                    {hasEnergy && <div className="box">
                      <div className="box-head">DFT energy results <span className="muted">Hartree · {run.id}</span></div>
                      <div className="tbl-wrap"><table aria-label="DFT energy results"><thead><tr><th>Molecule</th><th className="r">Energy (Hartree)</th><th>Status</th></tr></thead><tbody>{energyResults.map((row: any) => <tr key={row.name}><td className="mono">{row.name}</td><td className="r num">{typeof row.energy_hartree === "number" ? row.energy_hartree.toFixed(10) : "—"}</td><td>{row.status === "ok" ? <span className="pill completed">Completed</span> : <span className="pill failed">Failed</span>}</td></tr>)}</tbody></table></div>
                    </div>}
                    {speRows.length > 0 && (
                      <div className="stats">
                        <div className="stat">
                          <span>Mean unsigned error</span>
                          <b className="num">
                            {(
                              speRows.reduce(
                                (total, row) => total + Math.abs(row.error),
                                0,
                              ) / speRows.length
                            ).toFixed(2)}
                            <small>kcal/mol</small>
                          </b>
                        </div>
                        <div className="stat">
                          <span>Largest error</span>
                          <b className="num">
                            {Math.max(
                              ...speRows.map((row) => Math.abs(row.error)),
                            ).toFixed(2)}
                            <small>kcal/mol</small>
                          </b>
                        </div>
                        <div className="stat">
                          <span>Reactions</span>
                          <b className="num">{speRows.length}</b>
                        </div>
                      </div>
                    )}
                    {speRows.length > 0 && (
                      <div className="box">
                        <div className="box-head">
                          Converged single-point energies{" "}
                          <span className="muted">kcal/mol · {run.id}</span>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() =>
                              copy(
                                "Reaction,Reference,Calculated,Error\n" +
                                  speRows
                                    .map((row) =>
                                      [
                                        JSON.stringify(row.system),
                                        row.reference,
                                        row.calculated,
                                        row.error,
                                      ].join(","),
                                    )
                                    .join("\n"),
                              )
                            }
                          >
                            <Icon name="copy" />
                            Copy CSV
                          </button>
                        </div>
                        <div className="tbl-wrap">
                          <table aria-label="Single-point energies">
                            <thead>
                              <tr>
                                <th>Reaction</th>
                                <th className="r">Reference</th>
                                <th className="r">DFThub</th>
                                <th className="r">Error</th>
                              </tr>
                            </thead>
                            <tbody>
                              {speRows.map((row, index) => (
                                <tr key={index}>
                                  <td
                                    className="mono"
                                    style={{ fontSize: "var(--font-size-sm)" }}
                                  >
                                    {row.system}
                                  </td>
                                  <td className="r num">
                                    {row.reference.toFixed(2)}
                                  </td>
                                  <td className="r num">
                                    {row.calculated.toFixed(2)}
                                  </td>
                                  <td
                                    className="r num"
                                    style={{
                                      fontWeight: 600,
                                      color:
                                        Math.abs(row.error) > 2
                                          ? "var(--bad)"
                                          : undefined,
                                    }}
                                  >
                                    {row.error > 0 ? "+" : ""}
                                    {row.error.toFixed(2)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                    {speSummary.length > 0 && (
                      <div className="box">
                        <div className="box-head">
                          MUE by database{" "}
                          <span className="muted">kcal/mol</span>
                        </div>
                        <div className="tbl-wrap">
                          <table aria-label="Single-point database summary">
                            <thead>
                              <tr>
                                <th>Database</th>
                                <th className="r">MUE</th>
                              </tr>
                            </thead>
                            <tbody>
                              {speSummary.map((row, index) => (
                                <tr key={index}>
                                  <td>{row.name}</td>
                                  <td className="r num">
                                    {row.mue.toFixed(2)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </>
                ) : scopeBusy(speScope) ? (
                  <p className="muted">Results will appear here when the selected calculation finishes.</p>
                ) : !canSpe ? (
                  <Empty
                    icon={run.status === "failed" ? "bolt" : "clock"}
                    title={
                      run.status === "failed"
                        ? "Not available for this run"
                        : "Available after weight tuning"
                    }
                  >
                    <p>
                      Single-point energies require a run that finished weight
                      tuning. Review this run’s log and status first.
                    </p>
                    <div className="row">
                      <button
                        className="btn btn-secondary"
                        onClick={() => setTab("overview")}
                      >
                        Review run
                      </button>
                    </div>
                  </Empty>
                ) : (
                  <Empty
                    icon="bolt"
                    title={"Calculate " + scopeName + " self-consistent energies"}
                  >
                    <p>
                      Uses the functional fitted in {run.id}
                      {run.mue != null
                        ? " (total MUE " + run.mue.toFixed(2) + " kcal/mol)"
                        : ""}
                      . This usually takes 1–48 hours, depending on your
                      systems.
                    </p>
                    <div className="row">
                      <button
                        className="btn btn-primary"
                        disabled={!canSpe || (speScope === "input" && !files.hasInputDataset) || submitting || loading}
                        onClick={() => startSpe(speScope)}
                      >
                        <Icon name="play" />
                        {submitting ? "Submitting…" : "Start " + scopeName + " calculation"}
                      </button>
                      <button
                        className="btn btn-secondary"
                        onClick={() => setTab("weights")}
                      >
                        Tune weights first
                      </button>
                    </div>
                  </Empty>
                )}
                {currentSpe.log && <details className="box">
                  <summary className="box-head" style={{ cursor: "pointer" }}>{scopeName} calculation log</summary>
                  <pre className="console" style={{ margin: 0, padding: 16, whiteSpace: "pre-wrap" }}>{currentSpe.log}</pre>
                </details>}
              </>
            )}
          </>
        )}
      </div>
      <dialog
        className="sheet"
        ref={review}
        aria-labelledby={uid + "-review-title"}
        style={{ width: "min(560px,calc(100vw - 24px))" }}
        onCancel={(event) => {
          if (submitting) event.preventDefault();
        }}
        onClick={(event) => {
          if (event.target === event.currentTarget && !submitting)
            review.current?.close();
        }}
      >
        <div className="sheet-head">
          <div>
            <h3 id={uid + "-review-title"}>Resubmit with new weights</h3>
            <p>
              {job.id} · creates {nextRun} from {run?.id}
            </p>
          </div>
          <button
            className="icon-btn"
            aria-label="Close review"
            disabled={submitting}
            onClick={() => review.current?.close()}
          >
            <Icon name="x" />
          </button>
        </div>
        <div className="sheet-body">
          <div className="diff">
            {weights.rows
              .filter((row) => row.index in draft)
              .map((row) => {
                const next = positiveNumber(draft[row.index]);
                const delta = (next / Number(row.original) - 1) * 100;
                return (
                  <div key={row.index}>
                    <span>
                      <b>{row.database}</b>
                      {row.type && (
                        <>
                          {" "}
                          <span className="type">{row.type}</span>
                        </>
                      )}
                    </span>
                    <span className="chg num">
                      {row.original} → <b>{String(next)}</b>
                    </span>
                    <span className="delta num">
                      {Number.isFinite(delta)
                        ? (delta > 0 ? "+" : "") + delta.toFixed(0) + "%"
                        : "—"}
                    </span>
                  </div>
                );
              })}
          </div>
          <p className="sum-line">
            Lower inverse weights make a database count <b>more</b> in the fit.
            Your current run stays available for comparison.
          </p>
          {submitError && (
            <p className="err-pos" role="alert">
              {submitError}
            </p>
          )}
        </div>
        <div className="sheet-foot">
          <span className="hint">
            {edits} {edits === 1 ? "weight" : "weights"} changed
          </span>
          <button
            className="btn btn-secondary"
            disabled={submitting}
            onClick={() => review.current?.close()}
          >
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={submitting || invalid > 0 || edits === 0}
            onClick={submitWeights}
          >
            {submitting ? "Submitting…" : "Resubmit as " + nextRun}
          </button>
        </div>
      </dialog>
    </>
  );
}
