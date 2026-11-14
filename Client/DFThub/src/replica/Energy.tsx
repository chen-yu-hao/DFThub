import { Fragment, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { basisOptions } from "./basis";
import { displayDate, errorMessage, listFiles, listJobs, listRuns, readDirectory, readRunInput, runFields, statusLabel } from "./data";
import type { Job } from "./data";
import {
  DEFAULT_COMMON_SOLVENTS,
  HARTREE_TO_KCAL,
  SOLVENT_MODEL_OPTIONS,
  TEMPERATURE_PRESETS,
  VIB_MODEL_OPTIONS,
  formatSolventBadge,
  pressureToPa,
  solutionStandardStateCorrectionKcal,
} from "./energyOptions";
import type { EnergyTaskOptionsPayload, PressureUnit, SolventModelId, SolventPreset, VibModelId } from "./energyOptions";
import { Icon } from "./Icons";

type EnergyProps = { username: string; onNotify: (message: string, kind?: "good" | "bad" | "info") => void };
type Task = { name: string; status: string; result: any | null; config: any | null; log: string; updated?: number };
type DisplayUnit = "hartree" | "kcal_rel";

function taskStatus(task: Task) {
  if (task.result?.complete === true) return "completed";
  return task.status ? task.status.toLowerCase() : "unknown";
}

function energyStatus(task: Task) {
  const status = taskStatus(task);
  const rows = Array.isArray(task.result?.molecularEnergies) ? task.result.molecularEnergies : [];
  if (status === "failed" && rows.some((row: any) => row.status === "failed") && rows.some((row: any) => row.status === "ok")) return "partial";
  return status;
}

function energyStatusLabel(status: string) {
  return status === "partial" ? "Partial" : statusLabel(status);
}

function energyStatusClass(status: string) {
  return status === "partial" ? "queued" : status;
}

function formatNum(value: unknown, digits = 8): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

export default function Energy({ username, onNotify }: EnergyProps) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState("");
  const [runs, setRuns] = useState<Job[]>([]);
  const [runId, setRunId] = useState("");
  const [runBasis, setRunBasis] = useState("def2-qzvp");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [jobQuery, setJobQuery] = useState("");
  const [taskName, setTaskName] = useState("");
  const [newTaskName, setNewTaskName] = useState("");
  const [nameError, setNameError] = useState("");
  const [archive, setArchive] = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [resultQuery, setResultQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");

  // Solvation & Thermochemistry state
  const [solvents, setSolvents] = useState<SolventPreset[]>(DEFAULT_COMMON_SOLVENTS);
  const [solventModel, setSolventModel] = useState<SolventModelId>("none");
  const [solventName, setSolventName] = useState("water");
  const [solventSearch, setSolventSearch] = useState("");
  const [useCustomEps, setUseCustomEps] = useState(false);
  const [customEps, setCustomEps] = useState("78.3553");

  const [calcThermo, setCalcThermo] = useState(false);
  const [optimizeGeometry, setOptimizeGeometry] = useState(false);
  const [temperatureInput, setTemperatureInput] = useState("298.15");
  const [pressureInput, setPressureInput] = useState("1");
  const [pressureUnit, setPressureUnit] = useState<PressureUnit>("atm");
  const [vibModel, setVibModel] = useState<VibModelId>("qrrho-grimme");
  const [qrrhoFreq0, setQrrhoFreq0] = useState("100");
  const [freqScale, setFreqScale] = useState("1.0");
  const [solutionStandardState, setSolutionStandardState] = useState(false);

  // DFT settings override
  const [basisOverride, setBasisOverride] = useState("");
  const [gridLevel, setGridLevel] = useState(6);
  const [withD3, setWithD3] = useState(true);
  const [showAdvancedDft, setShowAdvancedDft] = useState(false);

  // Results display state
  const [displayUnit, setDisplayUnit] = useState<DisplayUnit>("hartree");
  const [expandedMol, setExpandedMol] = useState<string | null>(null);

  const run = runs.find((item) => item.id === runId) || null;
  const selectedTask = tasks.find((task) => task.name === taskName) || null;
  const active = tasks.some((task) => ["queued", "running"].includes(taskStatus(task)));
  const job = jobs.find((item) => item.id === jobId) || null;
  const visibleJobs = jobs.filter((item) => !jobQuery.trim() || item.id.toLowerCase().includes(jobQuery.trim().toLowerCase()));

  useEffect(() => {
    axios.get("/api_dft/energy_presets").then((res) => {
      if (Array.isArray(res.data?.solvents) && res.data.solvents.length) {
        setSolvents(res.data.solvents);
      }
    }).catch(() => {
      // Fallback to built-in DEFAULT_COMMON_SOLVENTS
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    listJobs(`Work/${username}`, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setJobs(items);
      const requested = new URLSearchParams(window.location.search).get("job") || "";
      setJobId(items.find((item) => item.id === requested)?.id || items[0]?.id || "");
    }).catch((failure) => { if (!controller.signal.aborted) setError(errorMessage(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [username]);

  useEffect(() => {
    if (!jobId) { setRuns([]); setRunId(""); return; }
    const controller = new AbortController();
    listRuns(`Work/${username}/${jobId}/output`, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      const completed = items.filter((item) => item.status === "completed");
      setRuns(completed);
      const requested = new URLSearchParams(window.location.search).get("run") || "";
      setRunId(completed.find((item) => item.id === requested)?.id || completed.at(-1)?.id || "");
    }).catch((failure) => { if (!controller.signal.aborted) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [username, jobId]);

  useEffect(() => {
    if (!jobId || !runId) return;
    const controller = new AbortController();
    readRunInput(`Work/${username}/${jobId}`, runId, controller.signal).then((input) => {
      if (controller.signal.aborted) return;
      const detected = String(input["basis.txt"] || "").trim().toLowerCase();
      if (detected) setRunBasis(detected);
    }).catch(() => {});
    return () => controller.abort();
  }, [username, jobId, runId]);

  async function refreshTasks() {
    if (!jobId || !runId) { setTasks([]); return; }
    try {
      const root = `Work/${username}/${jobId}/output/${runId}/energy_input`;
      const folders = await listFiles(root, "folder");
      const values = await Promise.all(folders.map(async (folder: any) => {
        const name = String(folder.name);
        const files = await readDirectory(`${root}/${name}`, [
          "SinglePointResults.energy.json",
          "spe_energy.status.json",
          "spe_energy.log",
          "energy_config.json",
        ]);
        let result = null;
        try { result = files["SinglePointResults.energy.json"] ? JSON.parse(files["SinglePointResults.energy.json"]) : null; } catch { result = null; }
        let config = null;
        try { config = files["energy_config.json"] ? JSON.parse(files["energy_config.json"]) : null; } catch { config = null; }
        let status = "";
        try { status = files["spe_energy.status.json"] ? JSON.parse(files["spe_energy.status.json"]).status || "" : ""; } catch { status = ""; }
        return { name, result, config, status, log: files["spe_energy.log"] || "", updated: Number(folder.time_modify) } as Task;
      }));
      values.sort((a, b) => (b.updated || 0) - (a.updated || 0));
      setTasks(values);
      setTaskName((current) => current && values.some((task) => task.name === current) ? current : values[0]?.name || "");
    } catch (failure: any) {
      if (failure.response?.status === 404) setTasks([]);
      else setError(errorMessage(failure));
    }
  }

  useEffect(() => { void refreshTasks(); }, [username, jobId, runId]);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => { if (!document.hidden) void refreshTasks(); }, 6000);
    return () => clearInterval(timer);
  }, [active, username, jobId, runId]);

  const nextName = useMemo(() => {
    let index = 1;
    while (tasks.some((task) => task.name === `DFT energy ${index}`)) index += 1;
    return `DFT energy ${index}`;
  }, [tasks]);

  const selectedSolventModelInfo = useMemo(
    () => SOLVENT_MODEL_OPTIONS.find((item) => item.id === solventModel) || SOLVENT_MODEL_OPTIONS[0],
    [solventModel],
  );

  const filteredSolvents = useMemo(() => {
    const q = solventSearch.trim().toLowerCase();
    if (!q) return solvents;
    return solvents.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.id.toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q) ||
        String(item.eps).includes(q),
    );
  }, [solvents, solventSearch]);

  const selectedSolventObj = useMemo(
    () => solvents.find((item) => item.id === solventName) || DEFAULT_COMMON_SOLVENTS[0],
    [solvents, solventName],
  );

  const parsedTempK = Number(temperatureInput);
  const parsedPressVal = Number(pressureInput);
  const computedPressurePa = pressureToPa(parsedPressVal, pressureUnit);
  const dgStdKcal = solutionStandardStateCorrectionKcal(parsedTempK, computedPressurePa);

  function handleSolventModelChange(nextModel: SolventModelId) {
    setSolventModel(nextModel);
    if (nextModel === "none") {
      setSolutionStandardState(false);
    } else if (calcThermo) {
      setSolutionStandardState(true);
    }
    if (nextModel === "smd" && useCustomEps) {
      setUseCustomEps(false);
    }
  }

  function handleThermoToggle(enabled: boolean) {
    setCalcThermo(enabled);
    if (enabled && solventModel !== "none") {
      setSolutionStandardState(true);
    }
  }

  function chooseArchive(file: File | null) {
    setFileError("");
    if (!file) { setArchive(null); return; }
    if (!/\.(?:tgz|tar\.gz|zip)$/i.test(file.name)) {
      setArchive(null);
      setFileError("Choose a .tgz, .tar.gz or .zip archive of .xyz structures.");
      return;
    }
    setArchive(file);
  }

  function buildEnergyOptions(): EnergyTaskOptionsPayload | null {
    const epsNum = useCustomEps && solventModel !== "none" ? Number(customEps) : null;
    if (useCustomEps && solventModel !== "none" && (!Number.isFinite(epsNum) || (epsNum ?? 0) <= 1.0)) {
      setError("Custom dielectric constant ε must be a finite number greater than 1.0.");
      return null;
    }
    if (calcThermo) {
      if (!Number.isFinite(parsedTempK) || parsedTempK <= 0 || parsedTempK > 10000) {
        setError("Temperature must be between 0 and 10,000 K.");
        return null;
      }
      if (!Number.isFinite(parsedPressVal) || parsedPressVal <= 0) {
        setError("Pressure must be a positive number.");
        return null;
      }
      const f0 = Number(qrrhoFreq0);
      if (!Number.isFinite(f0) || f0 <= 0 || f0 > 1000) {
        setError("Quasi-RRHO cutoff frequency ω₀ must be between 1 and 1000 cm⁻¹.");
        return null;
      }
      const scale = Number(freqScale);
      if (!Number.isFinite(scale) || scale <= 0.1 || scale > 2.0) {
        setError("Frequency scale factor must be between 0.1 and 2.0.");
        return null;
      }
    }
    return {
      basis: (basisOverride || runBasis || "def2-qzvp").toLowerCase(),
      grid_level: gridLevel,
      with_d3: withD3,
      solvent_model: solventModel,
      solvent_name: solventName,
      solvent_eps: epsNum,
      optimize_geometry: optimizeGeometry,
      calc_thermo: calcThermo,
      temperature_k: Number.isFinite(parsedTempK) && parsedTempK > 0 ? parsedTempK : 298.15,
      pressure_pa: computedPressurePa,
      vib_model: vibModel,
      qrrho_freq0: Number(qrrhoFreq0) || 100.0,
      freq_scale: Number(freqScale) || 1.0,
      solution_standard_state: calcThermo && solutionStandardState,
    };
  }

  async function submit() {
    const cleanName = (newTaskName.trim() || nextName).trim();
    if (!jobId || !runId || !archive || !cleanName || busy) return;
    if (tasks.some((task) => task.name === cleanName)) {
      setNameError(`A task called ${cleanName} already exists for this Run.`);
      return;
    }
    const energyOptions = buildEnergyOptions();
    if (!energyOptions) return;

    setBusy(true); setError("");
    try {
      const folder = `Work/${username}/${jobId}/output/${runId}/energy_input/${cleanName}`;
      const form = new FormData();
      form.append("folder_dir", folder);
      form.append("files", archive, archive.name);
      const upload = await axios.put("/api_dft/upload", form);
      if (upload.data.result === "error" || upload.data.success === false) throw new Error(upload.data.msg || "Archive upload failed.");
      const response = await axios.post("/api_dft/submit", {
        mode: "spe",
        spe_scope: "energy",
        energy_task: cleanName,
        energy_options: energyOptions,
        work_dir: `Work/${username}/${jobId}`,
        ...runFields(runId),
      });
      if (response.data.result === "error" || response.data.success === false) throw new Error(response.data.msg || "DFT energy calculation could not be started.");
      setArchive(null); setFileError(""); setNameError(""); setNewTaskName(""); setTaskName(cleanName); setResultQuery(""); setExpandedMol(null);
      onNotify(`${cleanName} submitted for ${jobId}/${runId}.`);
      await refreshTasks();
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  async function cancelSelectedTask() {
    if (!jobId || !runId || !selectedTask || cancelling) return;
    setCancelling(true);
    try {
      const response = await axios.post("/api_dft/cancel", {
        work_dir: `Work/${username}/${jobId}`,
        ...runFields(runId),
        spe_scope: "energy",
        energy_task: selectedTask.name,
      });
      if (response.data.result === "error") throw new Error(response.data.msg || "Could not stop task.");
      onNotify(`Cancellation requested for ${selectedTask.name}.`, "info");
      await refreshTasks();
    } catch (failure) {
      onNotify(errorMessage(failure), "bad");
    } finally {
      setCancelling(false);
    }
  }

  function downloadOptimizedXyz(molName: string, xyzContent: string) {
    const url = URL.createObjectURL(new Blob([xyzContent], { type: "chemical/x-xyz;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${molName}.opt.xyz`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function copyEnergies() {
    const rows = selectedTask?.result?.molecularEnergies;
    if (!Array.isArray(rows) || !rows.length) return;
    const hasSolv = Boolean(selectedTask?.result?.solvation || rows.some((r: any) => r.e_solvent_hartree != null));
    const hasThermo = Boolean(selectedTask?.result?.calc_thermo || rows.some((r: any) => r.g_tot_hartree != null));
    const headers = [
      "Molecule",
      "E_tot (Hartree)",
      ...(hasSolv ? ["dE_solv (Hartree)", "E_CDS (Hartree)"] : []),
      ...(hasThermo ? ["ZPE (Hartree)", "H_tot (Hartree)", "G_tot (Hartree)", "S_tot (cal/mol/K)", "Lowest_Freq (cm^-1)", "Imag_Count"] : []),
      "Status",
    ];
    const lines = [
      headers.join("\t"),
      ...rows.map((row: any) => [
        row.name,
        formatNum(row.energy_hartree, 10),
        ...(hasSolv ? [formatNum(row.e_solvent_hartree, 8), formatNum(row.e_cds_hartree, 8)] : []),
        ...(hasThermo
          ? [
              formatNum(row.zpe_hartree, 8),
              formatNum(row.h_tot_hartree, 10),
              formatNum(row.g_tot_hartree, 10),
              formatNum(row.s_tot_cal_mol_k, 3),
              formatNum(row.lowest_frequency_cm1, 1),
              row.imaginary_count ?? 0,
            ]
          : []),
        row.status || "unknown",
      ].join("\t")),
    ].join("\n");
    if (!navigator.clipboard) { onNotify("Clipboard access is unavailable in this browser.", "bad"); return; }
    navigator.clipboard.writeText(lines).then(() => onNotify("Energy & thermochemistry table copied."), () => onNotify("Could not copy the table.", "bad"));
  }

  function exportEnergies() {
    const rows = selectedTask?.result?.molecularEnergies;
    if (!Array.isArray(rows) || !rows.length) return;
    const hasSolv = Boolean(selectedTask?.result?.solvation || rows.some((r: any) => r.e_solvent_hartree != null));
    const hasThermo = Boolean(selectedTask?.result?.calc_thermo || rows.some((r: any) => r.g_tot_hartree != null));
    const headers = [
      "Molecule",
      "E_tot (Hartree)",
      "E_D3 (Hartree)",
      ...(hasSolv ? ["Solvent_Model", "Solvent", "Epsilon", "dE_solv (Hartree)", "E_CDS (Hartree)"] : []),
      ...(hasThermo
        ? [
            "ZPE (Hartree)",
            "U_tot (Hartree)",
            "H_tot (Hartree)",
            "G_tot (Hartree)",
            "S_tot (cal/mol/K)",
            "dG_std_1M (Hartree)",
            "Lowest_Freq (cm^-1)",
            "Imaginary_Count",
          ]
        : []),
      "Status",
    ];
    const csvRows = rows.map((row: any) => {
      const cells = [
        row.name,
        typeof row.energy_hartree === "number" ? row.energy_hartree.toFixed(10) : "",
        typeof row.e_d3_hartree === "number" ? row.e_d3_hartree.toFixed(10) : "",
        ...(hasSolv
          ? [
              row.solvent_model || selectedTask?.result?.solvation?.model || "",
              row.solvent_name || selectedTask?.result?.solvation?.solvent || "",
              row.solvent_eps ?? selectedTask?.result?.solvation?.eps ?? "",
              typeof row.e_solvent_hartree === "number" ? row.e_solvent_hartree.toFixed(8) : "",
              typeof row.e_cds_hartree === "number" ? row.e_cds_hartree.toFixed(8) : "",
            ]
          : []),
        ...(hasThermo
          ? [
              typeof row.zpe_hartree === "number" ? row.zpe_hartree.toFixed(8) : "",
              typeof row.u_tot_hartree === "number" ? row.u_tot_hartree.toFixed(10) : "",
              typeof row.h_tot_hartree === "number" ? row.h_tot_hartree.toFixed(10) : "",
              typeof row.g_tot_hartree === "number" ? row.g_tot_hartree.toFixed(10) : "",
              typeof row.s_tot_cal_mol_k === "number" ? row.s_tot_cal_mol_k.toFixed(4) : "",
              typeof row.standard_state_correction_hartree === "number" ? row.standard_state_correction_hartree.toFixed(8) : "",
              typeof row.lowest_frequency_cm1 === "number" ? row.lowest_frequency_cm1.toFixed(2) : "",
              row.imaginary_count ?? "",
            ]
          : []),
        row.status || "unknown",
      ];
      return cells.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(",");
    });
    const csv = [headers.join(","), ...csvRows].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${selectedTask.name.replace(/[^a-z0-9_-]+/gi, "-") || "dft-energy"}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <section className="ws energy-page" id="energy" aria-labelledby="energyTitle">
      <div className="ws-head">
        <div>
          <h1 id="energyTitle">DFT energy &amp; thermochemistry</h1>
          <p>Evaluate molecular electronic energies, implicit solvation (PCM / SMD / COSMO), and harmonic Gibbs free energies with a fitted Run.</p>
        </div>
      </div>
      {error && (
        <div className="alert" role="alert">
          <Icon name="alert" />
          <b>Could not complete DFT energy action</b>
          <div>{error}</div>
        </div>
      )}
      <div className="ws-grid">
        <aside className="sidebar" aria-label="Job and Run selection">
          <div className="side-top">
            <strong>Jobs</strong>
            <label className="search">
              <span className="sr">Search jobs</span>
              <Icon name="search" />
              <input
                id="jobSearch"
                type="search"
                value={jobQuery}
                onChange={(event) => setJobQuery(event.target.value)}
                placeholder="Search jobs"
                autoComplete="off"
              />
              <kbd aria-hidden="true">/</kbd>
            </label>
          </div>
          <ul className="job-list" role="listbox" aria-label="Jobs" aria-busy={loading}>
            {visibleJobs.map((item) => (
              <li key={item.id} className="job-item">
                <button
                  className="job"
                  role="option"
                  aria-selected={item.id === jobId}
                  onClick={() => {
                    setJobId(item.id);
                    setRunId("");
                    setTaskName("");
                    setNewTaskName("");
                    setNameError("");
                    setArchive(null);
                    setFileError("");
                    setResultQuery("");
                    setExpandedMol(null);
                  }}
                >
                  <span className="job-name">{item.id}</span>
                  <span className="job-date num">{displayDate(item.date)}</span>
                  <span className="job-sub">
                    <span className={`dot ${item.status}`} />
                    {statusLabel(item.status)}
                  </span>
                </button>
              </li>
            ))}
            {!loading && !visibleJobs.length && <li className="empty-list">No jobs match.</li>}
          </ul>
          <div className="side-foot">{loading ? "Loading jobs…" : `Showing ${visibleJobs.length} of ${jobs.length} jobs`}</div>
        </aside>

        <article className="detail" id="energyDetail">
          <div className="d-head">
            <div>
              <div className="d-title">
                <h2>{jobId || "Choose a Job"}</h2>
                {job && <span className={`pill ${job.status}`}>{statusLabel(job.status)}</span>}
              </div>
              <div className="d-meta">
                {job ? (
                  <>
                    <span>{displayDate(job.date, true)}</span>
                    <span>{runs.length} completed run{runs.length === 1 ? "" : "s"}</span>
                    <span>Default basis: <b className="mono">{runBasis}</b></span>
                  </>
                ) : (
                  "Select a completed Run before starting a task."
                )}
              </div>
            </div>
            {jobId && (
              <div className="energy-head-actions">
                <a className="btn btn-secondary" href={`/workspace/?job=${encodeURIComponent(jobId)}`}>
                  <Icon name="slider" />Workspace
                </a>
                <a className="btn btn-secondary" href={`/analyze/?job=${encodeURIComponent(jobId)}`}>
                  <Icon name="chart" />Analyze runs
                </a>
              </div>
            )}
          </div>

          <div className="energy-run-picker">
            <label className="field">
              <span>Run</span>
              <select
                value={runId}
                onChange={(event) => {
                  setRunId(event.target.value);
                  setArchive(null);
                  setFileError("");
                  setNameError("");
                  setTaskName("");
                  setNewTaskName("");
                  setResultQuery("");
                  setExpandedMol(null);
                }}
                disabled={!runs.length}
              >
                <option value="">Choose a completed Run</option>
                {runs.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id}{item.mue != null ? ` (MUE ${item.mue.toFixed(2)} kcal/mol)` : ""}
                  </option>
                ))}
              </select>
            </label>
            <span className="muted">
              {runs.length} completed Run{runs.length === 1 ? "" : "s"}
            </span>
          </div>

          {!run ? (
            <div className="panel">
              <div className="empty">
                <Icon name="atom" />
                <h3>{runs.length ? "Choose a Run" : "No completed runs yet"}</h3>
                <p>
                  {runs.length
                    ? "DFT energy uses the selected Run's optimized CF22D parameters and basis."
                    : "Energies can be calculated after a fit completes a Run."}
                </p>
                {!runs.length && (
                  <a className="btn btn-secondary" href={`/workspace/?job=${encodeURIComponent(jobId)}`}>
                    Open Workspace
                  </a>
                )}
              </div>
            </div>
          ) : (
            <>
              {/* STEP 1: New Task Configuration */}
              <section className="box energy-task-form">
                <div className="box-head">
                  <span className="energy-step">1</span>
                  <strong>New DFT energy &amp; free-energy task</strong>
                  <span className="sp" />
                  <span className="muted">{run.id} · {basisOverride || runBasis}</span>
                </div>
                <p className="energy-task-note">
                  Evaluate uploaded <code>.xyz</code> structures with the optimized functional from <b>{run.id}</b>. Combine implicit solvation, BFGS geometry relaxation, and harmonic vibrational thermochemistry in a single reproducible workflow.
                </p>

                <div className="energy-task-fields">
                  <label className="field">
                    <span>Task name</span>
                    <input
                      className="inp"
                      value={newTaskName}
                      aria-invalid={!!nameError}
                      aria-describedby="energyNameHelp"
                      onChange={(event) => {
                        setNewTaskName(event.target.value);
                        setNameError("");
                      }}
                      placeholder={nextName}
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </label>
                  {nameError && (
                    <p className="help err" id="energyNameHelp" role="alert">
                      {nameError}
                    </p>
                  )}

                  <div className="field">
                    <span className="flabel">Structures</span>
                    <label
                      className={`file-picker energy-drop${archive ? " has" : fileError ? " bad" : ""}`}
                      htmlFor="energyArchive"
                    >
                      <input
                        id="energyArchive"
                        type="file"
                        accept=".tgz,.tar.gz,.zip,application/gzip,application/x-gzip,application/zip"
                        onChange={(event) => chooseArchive(event.target.files?.[0] || null)}
                      />
                      <Icon name={archive ? "check" : "archive"} />
                      <span>
                        <b>{archive ? archive.name : "Geometry archive (.tgz / .zip)"}</b>
                        <small className="meta">
                          {archive
                            ? `${Math.ceil(archive.size / 1024)} KB · .xyz structures`
                            : "Drop a .tgz, .tar.gz or .zip archive of .xyz files here, or click to choose"}
                        </small>
                      </span>
                    </label>
                    {fileError && (
                      <span className="help err" role="alert">
                        {fileError}
                      </span>
                    )}
                  </div>
                </div>

                {/* Solvation & Thermochemistry Extension Modules */}
                <div className="energy-ext-grid">
                  {/* Module A: Implicit Solvation Model */}
                  <div className={`energy-ext-card${solventModel !== "none" ? " active" : ""}`}>
                    <div className="energy-ext-head">
                      <div>
                        <span className="energy-ext-kicker">Continuum Reaction Field</span>
                        <h4>Implicit Solvation Model</h4>
                      </div>
                      <span className={`energy-badge${solventModel !== "none" ? " tone-accent" : ""}`}>
                        {selectedSolventModelInfo.badge}
                      </span>
                    </div>

                    <div className="energy-model-pills" role="radiogroup" aria-label="Solvation model">
                      {SOLVENT_MODEL_OPTIONS.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          role="radio"
                          aria-checked={solventModel === item.id}
                          className={`energy-model-pill${solventModel === item.id ? " on" : ""}`}
                          onClick={() => handleSolventModelChange(item.id)}
                        >
                          {item.shortLabel}
                        </button>
                      ))}
                    </div>
                    <p className="energy-ext-desc">{selectedSolventModelInfo.description}</p>

                    {solventModel !== "none" && (
                      <div className="energy-solvent-panel">
                        <div className="energy-solvent-row">
                          <div className="energy-sub-field">
                            <label htmlFor="solventSelect">Solvent ({solvents.length} Minnesota database entries)</label>
                            <div className="energy-solvent-PickGroup">
                              <input
                                type="search"
                                className="inp energy-solvent-filter"
                                placeholder="Filter solvent or ε…"
                                value={solventSearch}
                                onChange={(event) => setSolventSearch(event.target.value)}
                              />
                              <select
                                id="solventSelect"
                                className="energy-select"
                                value={solventName}
                                disabled={useCustomEps && solventModel !== "smd"}
                                onChange={(event) => setSolventName(event.target.value)}
                              >
                                {filteredSolvents.some((s) => s.common) && (
                                  <optgroup label="Common Laboratory Solvents">
                                    {filteredSolvents.filter((s) => s.common).map((s) => (
                                      <option key={s.id} value={s.id}>
                                        {s.name} — ε = {s.eps.toFixed(2)} ({s.category})
                                      </option>
                                    ))}
                                  </optgroup>
                                )}
                                {filteredSolvents.some((s) => !s.common) && (
                                  <optgroup label="Minnesota Solvent Database">
                                    {filteredSolvents.filter((s) => !s.common).map((s) => (
                                      <option key={s.id} value={s.id}>
                                        {s.name} — ε = {s.eps.toFixed(2)}
                                      </option>
                                    ))}
                                  </optgroup>
                                )}
                              </select>
                            </div>
                          </div>
                        </div>

                        <div className="energy-eps-bar">
                          <div className="energy-eps-info">
                            <span>Dielectric constant</span>
                            <b className="num">
                              ε = {useCustomEps ? customEps || "—" : selectedSolventObj?.eps.toFixed(4) || "78.3553"}
                            </b>
                            {solventModel === "smd" && <span className="energy-tag-mini">+ CDS non-electrostatic cavity/dispersion</span>}
                          </div>
                          {selectedSolventModelInfo.supportsCustomEps && solventModel !== "smd" && (
                            <label className="energy-check-inline">
                              <input
                                type="checkbox"
                                checked={useCustomEps}
                                onChange={(event) => {
                                  setUseCustomEps(event.target.checked);
                                  if (event.target.checked && !customEps) {
                                    setCustomEps(String(selectedSolventObj?.eps ?? 78.3553));
                                  }
                                }}
                              />
                              <span>Custom ε</span>
                            </label>
                          )}
                        </div>

                        {useCustomEps && solventModel !== "smd" && (
                          <div className="energy-custom-eps">
                            <label htmlFor="customEpsInput">Custom dielectric constant (ε &gt; 1.0)</label>
                            <input
                              id="customEpsInput"
                              type="number"
                              step="0.01"
                              min="1.01"
                              className="inp num"
                              value={customEps}
                              onChange={(event) => setCustomEps(event.target.value)}
                            />
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Module B: Free Energy, Thermochemistry & Geometry Relaxation */}
                  <div className={`energy-ext-card${calcThermo || optimizeGeometry ? " active" : ""}`}>
                    <div className="energy-ext-head">
                      <div>
                        <span className="energy-ext-kicker">Statistical Mechanics &amp; Relaxation</span>
                        <h4>Free Energy &amp; Thermochemistry</h4>
                      </div>
                      <span className={`energy-badge${calcThermo ? " tone-good" : optimizeGeometry ? " tone-accent" : ""}`}>
                        {calcThermo && optimizeGeometry
                          ? "Opt + Freq (G, H, S, ZPE)"
                          : calcThermo
                            ? "Harmonic Thermo (G, H, S)"
                            : optimizeGeometry
                              ? "BFGS Relaxation Only"
                              : "Single-Point E₀"}
                      </span>
                    </div>

                    <div className="energy-toggle-stack">
                      <label className="energy-switch-row">
                        <input
                          type="checkbox"
                          checked={calcThermo}
                          onChange={(event) => handleThermoToggle(event.target.checked)}
                        />
                        <div>
                          <strong>Compute harmonic frequencies &amp; Gibbs free energy (G, H, U, S, ZPE)</strong>
                          <small>Evaluates the nuclear Hessian, normal-mode vibrational spectrum, imaginary-mode diagnostics, and thermal corrections.</small>
                        </div>
                      </label>

                      <label className="energy-switch-row">
                        <input
                          type="checkbox"
                          checked={optimizeGeometry}
                          onChange={(event) => setOptimizeGeometry(event.target.checked)}
                        />
                        <div>
                          <strong>Pre-optimize molecular geometry (internal-coordinate BFGS)</strong>
                          <small>Relaxes each structure to a local energy minimum before evaluating final energy or vibrational Hessian.</small>
                        </div>
                      </label>
                    </div>

                    {calcThermo && (
                      <div className="energy-thermo-panel">
                        <div className="energy-thermo-grid">
                          <div className="energy-sub-field">
                            <label htmlFor="thermoTemp">Temperature (K)</label>
                            <input
                              id="thermoTemp"
                              type="number"
                              step="0.05"
                              min="1"
                              max="10000"
                              className="inp num"
                              value={temperatureInput}
                              onChange={(event) => setTemperatureInput(event.target.value)}
                            />
                            <div className="energy-chip-row">
                              {TEMPERATURE_PRESETS.map((preset) => (
                                <button
                                  key={preset.value}
                                  type="button"
                                  className={`energy-mini-chip${Math.abs(parsedTempK - preset.value) < 0.01 ? " on" : ""}`}
                                  onClick={() => setTemperatureInput(String(preset.value))}
                                >
                                  {preset.label}
                                </button>
                              ))}
                            </div>
                          </div>

                          <div className="energy-sub-field">
                            <label htmlFor="thermoPress">Pressure</label>
                            <div className="energy-input-unit">
                              <input
                                id="thermoPress"
                                type="number"
                                step="any"
                                min="0.0001"
                                className="inp num"
                                value={pressureInput}
                                onChange={(event) => setPressureInput(event.target.value)}
                              />
                              <select
                                aria-label="Pressure unit"
                                className="energy-unit-select"
                                value={pressureUnit}
                                onChange={(event) => setPressureUnit(event.target.value as PressureUnit)}
                              >
                                <option value="atm">atm</option>
                                <option value="bar">bar</option>
                                <option value="kPa">kPa</option>
                                <option value="Pa">Pa</option>
                              </select>
                            </div>
                            <small className="energy-field-note num">
                              = {computedPressurePa.toLocaleString("en-US", { maximumFractionDigits: 1 })} Pa
                            </small>
                          </div>
                        </div>

                        <div className="energy-thermo-grid">
                          <div className="energy-sub-field">
                            <label htmlFor="vibModelSelect">Low-frequency vibrational model</label>
                            <select
                              id="vibModelSelect"
                              className="energy-select"
                              value={vibModel}
                              onChange={(event) => setVibModel(event.target.value as VibModelId)}
                            >
                              {VIB_MODEL_OPTIONS.map((item) => (
                                <option key={item.id} value={item.id}>
                                  {item.label}
                                </option>
                              ))}
                            </select>
                          </div>

                          <div className="energy-thermo-pair">
                            {vibModel !== "rrho" && (
                              <div className="energy-sub-field">
                                <label htmlFor="qrrhoCutoff">Damping ω₀ (cm⁻¹)</label>
                                <input
                                  id="qrrhoCutoff"
                                  type="number"
                                  step="5"
                                  min="10"
                                  max="500"
                                  className="inp num"
                                  value={qrrhoFreq0}
                                  onChange={(event) => setQrrhoFreq0(event.target.value)}
                                />
                              </div>
                            )}
                            <div className="energy-sub-field">
                              <label htmlFor="freqScaleInput">Freq scale</label>
                              <input
                                id="freqScaleInput"
                                type="number"
                                step="0.001"
                                min="0.5"
                                max="1.5"
                                className="inp num"
                                value={freqScale}
                                onChange={(event) => setFreqScale(event.target.value)}
                              />
                            </div>
                          </div>
                        </div>

                        <label className="energy-stdstate-box">
                          <input
                            type="checkbox"
                            checked={solutionStandardState}
                            onChange={(event) => setSolutionStandardState(event.target.checked)}
                          />
                          <div>
                            <strong>
                              Apply 1 mol/L solution standard-state correction (ΔG°→* ={" "}
                              <span className="num">
                                {dgStdKcal >= 0 ? "+" : ""}
                                {dgStdKcal.toFixed(2)} kcal/mol
                              </span>
                              )
                            </strong>
                            <small>
                              Converts ideal-gas translational entropy at ({parsedTempK || 298.15} K, {pressureInput} {pressureUnit}) to a 1 M solute reference state via RT ln(V_gas / V_1M). Recommended for solution-phase reaction free energies.
                            </small>
                          </div>
                        </label>
                      </div>
                    )}
                  </div>
                </div>

                {/* Collapsible Advanced DFT Settings */}
                <div className="energy-adv-bar">
                  <button
                    type="button"
                    className="energy-adv-toggle"
                    aria-expanded={showAdvancedDft}
                    onClick={() => setShowAdvancedDft((v) => !v)}
                  >
                    <Icon name="chev" className={showAdvancedDft ? "rot90" : ""} />
                    <span>Advanced DFT Settings</span>
                    <span className="energy-adv-summary mono">
                      Basis: {basisOverride || `${runBasis} (Run default)`} · Grid: {gridLevel} · D3(0): {withD3 ? "On" : "Off"}
                    </span>
                  </button>
                  {showAdvancedDft && (
                    <div className="energy-adv-body">
                      <div className="energy-sub-field">
                        <label htmlFor="energyBasisSelect">Basis set preset</label>
                        <select
                          id="energyBasisSelect"
                          className="energy-select"
                          value={basisOverride}
                          onChange={(event) => setBasisOverride(event.target.value)}
                        >
                          <option value="">Use Run basis ({runBasis})</option>
                          {basisOptions.map((b) => (
                            <option key={b.value} value={b.value}>
                              {b.name} ({b.value}) — {b.family}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="energy-sub-field">
                        <label htmlFor="energyGridSelect">XC integration grid level</label>
                        <select
                          id="energyGridSelect"
                          className="energy-select"
                          value={gridLevel}
                          onChange={(event) => setGridLevel(Number(event.target.value))}
                        >
                          <option value={4}>Grid 4 (Fast screening)</option>
                          <option value={5}>Grid 5 (Standard fine)</option>
                          <option value={6}>Grid 6 (DFThub high-accuracy default)</option>
                          <option value={7}>Grid 7 (Ultra-fine benchmark)</option>
                        </select>
                      </div>
                      <div className="energy-sub-field">
                        <label>Dispersion correction</label>
                        <label className="energy-check-inline" style={{ marginTop: 6 }}>
                          <input
                            type="checkbox"
                            checked={withD3}
                            onChange={(event) => setWithD3(event.target.checked)}
                          />
                          <span>Include CF22D D3(0) dispersion</span>
                        </label>
                      </div>
                    </div>
                  )}
                </div>

                <div className="energy-task-foot">
                  <span className={`hint${archive && !fileError ? " ok" : ""}`}>
                    {archive && !fileError
                      ? `Ready to launch ${newTaskName.trim() || nextName} (${solventModel === "none" ? "Gas phase" : `${selectedSolventModelInfo.shortLabel} / ${useCustomEps ? `ε=${customEps}` : solventName}`}${optimizeGeometry ? " · BFGS Opt" : ""}${calcThermo ? ` · Thermo @ ${temperatureInput} K` : ""}).`
                      : "Upload a .tgz or .zip of .xyz molecules. No .ref file is required."}
                  </span>
                  <button
                    className="btn btn-primary"
                    disabled={busy || !archive || !!fileError || !!nameError || !(newTaskName.trim() || nextName).trim()}
                    onClick={() => void submit()}
                  >
                    <Icon name="play" />
                    {busy ? "Submitting…" : calcThermo ? "Run Energy & Free Energy" : "Run DFT Energy"}
                  </button>
                </div>
              </section>

              {/* STEP 2: Tasks for Run */}
              <section className="box">
                <div className="box-head">
                  <span className="energy-step">2</span>
                  <strong>Tasks for {run.id}</strong>
                  <span className="sp" />
                  <button className="btn btn-secondary btn-sm" onClick={() => void refreshTasks()} disabled={busy}>
                    <Icon name="refresh" />Refresh
                  </button>
                </div>
                {tasks.length ? (
                  <div className="energy-task-list">
                    {tasks.map((task) => {
                      const status = energyStatus(task);
                      const opts = task.result?.options || task.config || {};
                      const solvBadge = formatSolventBadge(opts, task.result?.solvation);
                      const isThermo = Boolean(task.result?.calc_thermo || opts?.calc_thermo);
                      const isOpt = Boolean(task.result?.optimize_geometry || opts?.optimize_geometry);
                      const taskBasis = task.result?.basis || opts?.basis || runBasis;
                      return (
                        <button
                          key={task.name}
                          type="button"
                          className={`energy-task-row ${task.name === taskName ? "selected" : ""}`}
                          aria-pressed={task.name === taskName}
                          onClick={() => {
                            setTaskName(task.name);
                            setResultQuery("");
                            setExpandedMol(null);
                          }}
                        >
                          <span>
                            <strong>{task.name}</strong>
                            <small className="energy-task-sub">
                              <span className={`dot ${energyStatusClass(status)}`} aria-hidden="true" />
                              <span>{energyStatusLabel(status)}</span>
                              <span className="energy-task-chip mono">{taskBasis}</span>
                              {solvBadge ? (
                                <span className="energy-task-chip accent">{solvBadge}</span>
                              ) : (
                                <span className="energy-task-chip">Gas phase</span>
                              )}
                              {isOpt && <span className="energy-task-chip">BFGS Opt</span>}
                              {isThermo && (
                                <span className="energy-task-chip good">
                                  Free Energy ({opts.temperature_k ?? 298.15} K)
                                </span>
                              )}
                            </small>
                          </span>
                          <span>{task.result?.molecularEnergies?.length || 0} molecules</span>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="muted">No DFT energy tasks yet. Configure and submit your first task above.</p>
                )}
              </section>

              {/* STEP 3: Selected Task Results */}
              {selectedTask && (
                <section className="box energy-results">
                  {(() => {
                    const rows = Array.isArray(selectedTask.result?.molecularEnergies)
                      ? selectedTask.result.molecularEnergies
                      : [];
                    const status = energyStatus(selectedTask);
                    const isRunning = ["queued", "running"].includes(status);
                    const opts = selectedTask.result?.options || selectedTask.config || {};
                    const hasSolv = Boolean(
                      selectedTask.result?.solvation ||
                        (opts.solvent_model && opts.solvent_model !== "none") ||
                        rows.some((r: any) => r.e_solvent_hartree != null),
                    );
                    const hasThermo = Boolean(
                      selectedTask.result?.calc_thermo ||
                        opts.calc_thermo ||
                        rows.some((r: any) => r.g_tot_hartree != null),
                    );
                    const hasOpt = Boolean(
                      selectedTask.result?.optimize_geometry ||
                        opts.optimize_geometry ||
                        rows.some((r: any) => r.opt_steps != null),
                    );

                    const done = rows.filter((row: any) => row.status === "ok" && typeof row.energy_hartree === "number").length;
                    const failed = rows.filter((row: any) => row.status === "failed").length;
                    const query = resultQuery.trim().toLowerCase();
                    const filtered = rows.filter((row: any) => !query || String(row.name).toLowerCase().includes(query));

                    const validE = rows.map((r: any) => r.energy_hartree).filter((v: any) => typeof v === "number" && Number.isFinite(v));
                    const minE = validE.length ? Math.min(...validE) : null;
                    const validG = rows.map((r: any) => r.g_tot_hartree).filter((v: any) => typeof v === "number" && Number.isFinite(v));
                    const minG = validG.length ? Math.min(...validG) : null;
                    const validH = rows.map((r: any) => r.h_tot_hartree).filter((v: any) => typeof v === "number" && Number.isFinite(v));
                    const minH = validH.length ? Math.min(...validH) : null;

                    const fmtEnergyCol = (val: unknown, minRef: number | null) => {
                      if (typeof val !== "number" || !Number.isFinite(val)) return "—";
                      if (displayUnit === "kcal_rel" && minRef !== null) {
                        const rel = (val - minRef) * HARTREE_TO_KCAL;
                        return `${rel >= 0 ? "+" : ""}${rel.toFixed(2)}`;
                      }
                      return val.toFixed(8);
                    };

                    const solvBadge = formatSolventBadge(opts, selectedTask.result?.solvation);

                    return (
                      <>
                        <div className="box-head">
                          <span className="energy-step">3</span>
                          <strong>{selectedTask.name} results</strong>
                          <span className="sp" />
                          <div className="energy-head-actions">
                            {rows.length > 0 && (
                              <>
                                <div className="seg energy-unit-seg" role="group" aria-label="Energy display unit">
                                  <button
                                    type="button"
                                    aria-pressed={displayUnit === "hartree"}
                                    onClick={() => setDisplayUnit("hartree")}
                                  >
                                    Hartree (Eh)
                                  </button>
                                  <button
                                    type="button"
                                    aria-pressed={displayUnit === "kcal_rel"}
                                    onClick={() => setDisplayUnit("kcal_rel")}
                                  >
                                    Relative (kcal/mol)
                                  </button>
                                </div>
                                <button className="btn btn-secondary btn-sm" onClick={copyEnergies}>
                                  <Icon name="copy" />Copy
                                </button>
                                <button className="btn btn-secondary btn-sm" onClick={exportEnergies}>
                                  <Icon name="down" />Export CSV
                                </button>
                              </>
                            )}
                            {isRunning && (
                              <button
                                className="btn btn-danger btn-sm"
                                disabled={cancelling}
                                onClick={() => void cancelSelectedTask()}
                              >
                                <Icon name="stop" />
                                {cancelling ? "Stopping…" : "Stop"}
                              </button>
                            )}
                          </div>
                          <span className={`pill ${energyStatusClass(status)}`}>{energyStatusLabel(status)}</span>
                        </div>

                        {/* Metadata banner */}
                        <div className="energy-meta-strip">
                          <span>
                            Basis: <b className="mono">{selectedTask.result?.basis || opts.basis || runBasis}</b>
                          </span>
                          <span>
                            Grid: <b className="num">{selectedTask.result?.grid_level ?? opts.grid_level ?? 6}</b>
                          </span>
                          <span>
                            D3(0): <b>{(selectedTask.result?.with_d3 ?? opts.with_d3 ?? true) ? "Enabled" : "Disabled"}</b>
                          </span>
                          <span>
                            Solvation: <b>{solvBadge || "Gas phase (Vacuum)"}</b>
                            {selectedTask.result?.solvation?.eps != null && (
                              <small className="num"> (ε = {Number(selectedTask.result.solvation.eps).toFixed(2)})</small>
                            )}
                          </span>
                          {hasOpt && <span>Geometry: <b>BFGS Pre-optimized</b></span>}
                          {hasThermo && (
                            <span>
                              Thermochemistry:{" "}
                              <b className="num">
                                {opts.temperature_k ?? 298.15} K, {((opts.pressure_pa ?? 101325) / 101325).toFixed(2)} atm
                              </b>{" "}
                              ({opts.vib_model || "qrrho-grimme"}
                              {opts.solution_standard_state ? " · 1 M std state" : ""})
                            </span>
                          )}
                        </div>

                        {rows.length > 0 && (
                          <div className="energy-summary">
                            <div>
                              <span>Molecules</span>
                              <b>{rows.length}</b>
                            </div>
                            <div>
                              <span>Converged</span>
                              <b>{done}</b>
                            </div>
                            <div className={failed ? "bad" : ""}>
                              <span>Failed</span>
                              <b>{failed}</b>
                            </div>
                          </div>
                        )}

                        {status !== "completed" && rows.length > 0 && (
                          <div className="energy-progress">
                            <div className="progress-top">
                              {done} of {rows.length} molecules completed
                            </div>
                            <progress max={rows.length} value={done} />
                          </div>
                        )}

                        {rows.length > 6 && (
                          <div className="energy-results-tools">
                            <label className="search">
                              <Icon name="search" />
                              <span className="sr">Filter molecules</span>
                              <input
                                type="search"
                                value={resultQuery}
                                onChange={(event) => setResultQuery(event.target.value)}
                                placeholder="Filter molecules"
                              />
                            </label>
                            <span className="muted">
                              Showing {filtered.length} of {rows.length} · Click any row for full thermochemical &amp; vibrational breakdown
                            </span>
                          </div>
                        )}

                        {rows.length > 0 ? (
                          <div className="tbl-wrap">
                            <table aria-label="DFT energy task results">
                              <thead>
                                <tr>
                                  <th className="idx">#</th>
                                  <th>Molecule</th>
                                  <th className="r">
                                    {displayUnit === "kcal_rel" ? "ΔE_tot (kcal/mol)" : "E_tot (Hartree)"}
                                  </th>
                                  {hasSolv && <th className="r">ΔE_solv (kcal/mol)</th>}
                                  {hasThermo && (
                                    <>
                                      <th className="r">ZPE (kcal/mol)</th>
                                      <th className="r">
                                        {displayUnit === "kcal_rel" ? "ΔH (kcal/mol)" : "Enthalpy H (Eh)"}
                                      </th>
                                      <th className="r">
                                        {displayUnit === "kcal_rel" ? "ΔG (kcal/mol)" : "Gibbs G (Eh)"}
                                      </th>
                                      <th className="r">Lowest ν̃ (cm⁻¹)</th>
                                    </>
                                  )}
                                  <th className="st">Status</th>
                                </tr>
                              </thead>
                              <tbody>
                                {filtered.map((row: any, index: number) => {
                                  const isExpanded = expandedMol === row.name;
                                  const imagCount = Number(row.imaginary_count || 0);
                                  const solvKcal =
                                    typeof row.e_solvent_hartree === "number"
                                      ? row.e_solvent_hartree * HARTREE_TO_KCAL
                                      : null;
                                  const zpeKcal =
                                    typeof row.zpe_hartree === "number" ? row.zpe_hartree * HARTREE_TO_KCAL : null;
                                  return (
                                    <Fragment key={row.name}>
                                      <tr
                                        className={`${row.status === "failed" ? "failed " : ""}energy-mol-row${isExpanded ? " expanded" : ""}`}
                                        onClick={() => setExpandedMol(isExpanded ? null : row.name)}
                                        title="Click to inspect detailed energy & thermochemistry breakdown"
                                      >
                                        <td className="idx num">{index + 1}</td>
                                        <td className="mono mol">
                                          <span className="energy-mol-name">
                                            <Icon name="chev" className={isExpanded ? "rot90" : ""} />
                                            {row.name}
                                          </span>
                                          {row.opt_steps != null && (
                                            <span className="energy-inline-tag">
                                              Opt: {row.opt_steps} step{row.opt_steps === 1 ? "" : "s"}
                                            </span>
                                          )}
                                        </td>
                                        <td className="r num">{fmtEnergyCol(row.energy_hartree, minE)}</td>
                                        {hasSolv && (
                                          <td className="r num">
                                            {solvKcal !== null ? `${solvKcal >= 0 ? "+" : ""}${solvKcal.toFixed(2)}` : "—"}
                                          </td>
                                        )}
                                        {hasThermo && (
                                          <>
                                            <td className="r num">{zpeKcal !== null ? zpeKcal.toFixed(2) : "—"}</td>
                                            <td className="r num">{fmtEnergyCol(row.h_tot_hartree, minH)}</td>
                                            <td className="r num">
                                              <b>{fmtEnergyCol(row.g_tot_hartree, minG)}</b>
                                            </td>
                                            <td className="r num">
                                              {typeof row.lowest_frequency_cm1 === "number" ? (
                                                <span className={imagCount > 0 ? "energy-freq-imag" : ""}>
                                                  {row.lowest_frequency_cm1.toFixed(1)}
                                                  {imagCount > 0 && ` (${imagCount}i)`}
                                                </span>
                                              ) : (
                                                "—"
                                              )}
                                            </td>
                                          </>
                                        )}
                                        <td className="st">
                                          {row.status === "failed" ? (
                                            <span className="energy-status failed">
                                              <span className="dot failed" aria-hidden="true" />
                                              Failed
                                            </span>
                                          ) : row.status === "pending" ? (
                                            <span className="energy-status">
                                              <span className="dot queued" aria-hidden="true" />
                                              Pending
                                            </span>
                                          ) : (
                                            <span className="energy-status">
                                              <span className="dot completed" aria-hidden="true" />
                                              Converged
                                            </span>
                                          )}
                                        </td>
                                      </tr>
                                      {isExpanded && (
                                        <tr className="energy-detail-row">
                                          <td colSpan={4 + (hasSolv ? 1 : 0) + (hasThermo ? 4 : 0)}>
                                            <div className="energy-mol-drawer">
                                              {row.error && (
                                                <div className="alert" style={{ marginBottom: 12 }}>
                                                  <Icon name="alert" />
                                                  <b>Calculation error for {row.name}</b>
                                                  <div>{row.error}</div>
                                                </div>
                                              )}
                                              <div className="energy-drawer-cols">
                                                <div className="energy-drawer-card">
                                                  <h5>Electronic &amp; Solvation Breakdown</h5>
                                                  <dl className="energy-dl">
                                                    <div>
                                                      <dt>Total SCF Energy (E_tot)</dt>
                                                      <dd className="num">{formatNum(row.energy_hartree, 10)} Eh</dd>
                                                    </div>
                                                    <div>
                                                      <dt>D3(0) Dispersion (E_D3)</dt>
                                                      <dd className="num">
                                                        {typeof row.e_d3_hartree === "number"
                                                          ? `${row.e_d3_hartree.toFixed(8)} Eh (${(row.e_d3_hartree * HARTREE_TO_KCAL).toFixed(2)} kcal/mol)`
                                                          : "Disabled / 0"}
                                                      </dd>
                                                    </div>
                                                    {hasSolv && (
                                                      <>
                                                        <div>
                                                          <dt>Solvent Polarization (ΔE_solv)</dt>
                                                          <dd className="num">
                                                            {typeof row.e_solvent_hartree === "number"
                                                              ? `${row.e_solvent_hartree.toFixed(8)} Eh (${(row.e_solvent_hartree * HARTREE_TO_KCAL).toFixed(2)} kcal/mol)`
                                                              : "—"}
                                                          </dd>
                                                        </div>
                                                        {row.e_cds_hartree != null && (
                                                          <div>
                                                            <dt>SMD Non-electrostatic (E_CDS)</dt>
                                                            <dd className="num">
                                                              {row.e_cds_hartree.toFixed(8)} Eh ({(row.e_cds_hartree * HARTREE_TO_KCAL).toFixed(2)} kcal/mol)
                                                            </dd>
                                                          </div>
                                                        )}
                                                      </>
                                                    )}
                                                    {row.geometry_optimization && (
                                                      <div>
                                                        <dt>BFGS Relaxation</dt>
                                                        <dd className="num">
                                                          {row.geometry_optimization.steps} steps (ΔE ={" "}
                                                          {Number(row.geometry_optimization.energy_change_kcal_mol).toFixed(2)} kcal/mol, max|F| ={" "}
                                                          {Number(row.geometry_optimization.max_grad_hartree_bohr).toFixed(5)} Eh/Bohr)
                                                        </dd>
                                                      </div>
                                                    )}
                                                  </dl>
                                                  {row.optimized_xyz && (
                                                    <div className="energy-drawer-actions">
                                                      <button
                                                        type="button"
                                                        className="btn btn-secondary btn-sm"
                                                        onClick={() => downloadOptimizedXyz(row.name, row.optimized_xyz)}
                                                      >
                                                        <Icon name="down" />Download {row.name}.opt.xyz
                                                      </button>
                                                    </div>
                                                  )}
                                                </div>

                                                {row.thermochemistry && (
                                                  <div className="energy-drawer-card">
                                                    <h5>
                                                      Thermochemistry ({row.thermochemistry.temperature_k} K,{" "}
                                                      {(row.thermochemistry.pressure_pa / 101325).toFixed(2)} atm)
                                                    </h5>
                                                    <dl className="energy-dl">
                                                      <div>
                                                        <dt>Zero-Point Energy (ZPE)</dt>
                                                        <dd className="num">
                                                          {formatNum(row.zpe_hartree, 8)} Eh ({(row.zpe_hartree * HARTREE_TO_KCAL).toFixed(2)} kcal/mol)
                                                        </dd>
                                                      </div>
                                                      <div>
                                                        <dt>0 K Energy (E₀ + ZPE)</dt>
                                                        <dd className="num">{formatNum(row.e_0k_hartree, 10)} Eh</dd>
                                                      </div>
                                                      <div>
                                                        <dt>Thermal Internal Energy (U)</dt>
                                                        <dd className="num">{formatNum(row.u_tot_hartree, 10)} Eh</dd>
                                                      </div>
                                                      <div>
                                                        <dt>Thermal Enthalpy (H)</dt>
                                                        <dd className="num">{formatNum(row.h_tot_hartree, 10)} Eh</dd>
                                                      </div>
                                                      <div>
                                                        <dt>Total Entropy (S / −TS)</dt>
                                                        <dd className="num">
                                                          {formatNum(row.s_tot_cal_mol_k, 2)} cal/(mol·K) (−TS ={" "}
                                                          {(-row.ts_tot_hartree * HARTREE_TO_KCAL).toFixed(2)} kcal/mol)
                                                        </dd>
                                                      </div>
                                                      {row.thermochemistry.solution_standard_state && (
                                                        <div>
                                                          <dt>1 M Standard-State (ΔG°→*)</dt>
                                                          <dd className="num">
                                                            +{Number(row.thermochemistry.standard_state_correction_kcal_mol).toFixed(2)} kcal/mol
                                                          </dd>
                                                        </div>
                                                      )}
                                                      <div>
                                                        <dt>
                                                          <b>Gibbs Free Energy (G_tot)</b>
                                                        </dt>
                                                        <dd className="num">
                                                          <b>{formatNum(row.g_tot_hartree, 10)} Eh</b>
                                                        </dd>
                                                      </div>
                                                    </dl>
                                                  </div>
                                                )}
                                              </div>

                                              {Array.isArray(row.frequencies_cm1) && row.frequencies_cm1.length > 0 && (
                                                <div className="energy-freq-box">
                                                  <div className="energy-freq-head">
                                                    <strong>Harmonic Vibrational Frequencies ({row.frequencies_cm1.length} modes, cm⁻¹)</strong>
                                                    {imagCount > 0 ? (
                                                      <span className="energy-imag-warn">
                                                        {imagCount} imaginary mode{imagCount === 1 ? "" : "s"} detected (saddle point / non-stationary geometry)
                                                      </span>
                                                    ) : (
                                                      <span className="energy-imag-ok">All positive frequencies (local minimum)</span>
                                                    )}
                                                  </div>
                                                  <div className="energy-freq-list num">
                                                    {row.frequencies_cm1.map((freq: number, fIdx: number) => (
                                                      <span
                                                        key={fIdx}
                                                        className={`energy-freq-pill${freq < 0 ? " imag" : freq < 100 ? " low" : ""}`}
                                                      >
                                                        {freq < 0 ? `${Math.abs(freq).toFixed(1)}i` : freq.toFixed(1)}
                                                      </span>
                                                    ))}
                                                  </div>
                                                </div>
                                              )}
                                            </div>
                                          </td>
                                        </tr>
                                      )}
                                    </Fragment>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="muted">
                            {isRunning ? "Calculation is initializing and queued in the worker pool…" : "No molecular results recorded yet."}
                          </p>
                        )}

                        {selectedTask.log && (
                          <details className="energy-log" open={status === "failed" || status === "partial"}>
                            <summary>
                              <Icon name="chev" />Calculation log
                            </summary>
                            <pre>{selectedTask.log}</pre>
                          </details>
                        )}
                      </>
                    );
                  })()}
                </section>
              )}
            </>
          )}
        </article>
      </div>
    </section>
  );
}
