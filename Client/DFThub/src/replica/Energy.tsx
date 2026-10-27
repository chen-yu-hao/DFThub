import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { displayDate, errorMessage, listFiles, listJobs, listRuns, readDirectory, runFields, statusLabel } from "./data";
import type { Job } from "./data";
import { Icon } from "./Icons";

type EnergyProps = { username: string; onNotify: (message: string, kind?: "good" | "bad" | "info") => void };
type Task = { name: string; status: string; result: any | null; log: string; updated?: number };

function taskStatus(task: Task) {
  if (task.result?.complete === true) return "completed";
  return task.status ? task.status.toLowerCase() : "unknown";
}

function energyStatus(task: Task) {
  const status = taskStatus(task);
  const rows = Array.isArray(task.result?.molecularEnergies) ? task.result.molecularEnergies : [];
  if (status === "failed" && rows.some((row: any) => row.status === "failed") && rows.some((row: any) => row.status !== "failed")) return "partial";
  return status;
}

function energyStatusLabel(status: string) {
  return status === "partial" ? "Partial" : statusLabel(status);
}

function energyStatusClass(status: string) {
  return status === "partial" ? "queued" : status;
}

export default function Energy({ username, onNotify }: EnergyProps) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState("");
  const [runs, setRuns] = useState<Job[]>([]);
  const [runId, setRunId] = useState("");
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
  const [error, setError] = useState("");

  const run = runs.find((item) => item.id === runId) || null;
  const selectedTask = tasks.find((task) => task.name === taskName) || null;
  const active = tasks.some((task) => ["queued", "running"].includes(taskStatus(task)));
  const job = jobs.find((item) => item.id === jobId) || null;
  const visibleJobs = jobs.filter((item) => !jobQuery.trim() || item.id.toLowerCase().includes(jobQuery.trim().toLowerCase()));

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

  async function refreshTasks() {
    if (!jobId || !runId) { setTasks([]); return; }
    try {
      const root = `Work/${username}/${jobId}/output/${runId}/energy_input`;
      const folders = await listFiles(root, "folder");
      const values = await Promise.all(folders.map(async (folder: any) => {
        const name = String(folder.name);
        const files = await readDirectory(`${root}/${name}`, ["SinglePointResults.energy.json", "spe_energy.status.json", "spe_energy.log"]);
        let result = null;
        try { result = files["SinglePointResults.energy.json"] ? JSON.parse(files["SinglePointResults.energy.json"]) : null; } catch { result = null; }
        let status = "";
        try { status = files["spe_energy.status.json"] ? JSON.parse(files["spe_energy.status.json"]).status || "" : ""; } catch { status = ""; }
        return { name, result, status, log: files["spe_energy.log"] || "", updated: Number(folder.time_modify) } as Task;
      }));
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
    const timer = setInterval(() => { if (!document.hidden) void refreshTasks(); }, 10000);
    return () => clearInterval(timer);
  }, [active, username, jobId, runId]);

  const nextName = useMemo(() => {
    let index = 1;
    while (tasks.some((task) => task.name === `DFT energy ${index}`)) index += 1;
    return `DFT energy ${index}`;
  }, [tasks]);

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

  async function submit() {
    const cleanName = (newTaskName.trim() || nextName).trim();
    if (!jobId || !runId || !archive || !cleanName || busy) return;
    if (tasks.some((task) => task.name === cleanName)) {
      setNameError(`A task called ${cleanName} already exists for this Run.`);
      return;
    }
    setBusy(true); setError("");
    try {
      const folder = `Work/${username}/${jobId}/output/${runId}/energy_input/${cleanName}`;
      const form = new FormData();
      form.append("folder_dir", folder);
      form.append("files", archive, archive.name);
      const upload = await axios.put("/api_dft/upload", form);
      if (upload.data.result === "error" || upload.data.success === false) throw new Error(upload.data.msg || "Archive upload failed.");
      const response = await axios.post("/api_dft/submit", { mode: "spe", spe_scope: "energy", energy_task: cleanName, work_dir: `Work/${username}/${jobId}`, ...runFields(runId) });
      if (response.data.result === "error" || response.data.success === false) throw new Error(response.data.msg || "DFT energy calculation could not be started.");
      setArchive(null); setFileError(""); setNameError(""); setNewTaskName(""); setTaskName(cleanName); setResultQuery(""); onNotify(`${cleanName} submitted for ${jobId}/${runId}.`); await refreshTasks();
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  function copyEnergies() {
    const rows = selectedTask?.result?.molecularEnergies;
    if (!Array.isArray(rows) || !rows.length) return;
    const text = ["Molecule\tEnergy (Hartree)\tStatus", ...rows.map((row: any) => `${row.name}\t${typeof row.energy_hartree === "number" ? row.energy_hartree.toFixed(10) : "—"}\t${row.status || "unknown"}`)].join("\n");
    if (!navigator.clipboard) { onNotify("Clipboard access is unavailable in this browser.", "bad"); return; }
    navigator.clipboard.writeText(text).then(() => onNotify("Energy table copied."), () => onNotify("Could not copy the energy table.", "bad"));
  }

  function exportEnergies() {
    const rows = selectedTask?.result?.molecularEnergies;
    if (!Array.isArray(rows) || !rows.length) return;
    const csv = ["Molecule,Energy (Hartree),Status", ...rows.map((row: any) => [row.name, typeof row.energy_hartree === "number" ? row.energy_hartree.toFixed(10) : "", row.status || "unknown"].map((value) => `"${String(value).replace(/"/g, '""')}"`).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `${selectedTask.name.replace(/[^a-z0-9_-]+/gi, "-") || "dft-energy"}.csv`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="ws energy-page" id="energy" aria-labelledby="energyTitle">
    <div className="ws-head"><div><h1 id="energyTitle">DFT energy</h1><p>Calculate molecular energies with the optimized functional from a selected Run.</p></div></div>
    {error && <div className="alert" role="alert"><Icon name="alert" /><b>Could not refresh DFT energy</b><div>{error}</div></div>}
    <div className="ws-grid">
      <aside className="sidebar" aria-label="Job and Run selection">
        <div className="side-top"><strong>Jobs</strong><label className="search"><span className="sr">Search jobs</span><Icon name="search" /><input id="jobSearch" type="search" value={jobQuery} onChange={(event) => setJobQuery(event.target.value)} placeholder="Search jobs" autoComplete="off" /><kbd aria-hidden="true">/</kbd></label></div>
        <ul className="job-list" role="listbox" aria-label="Jobs" aria-busy={loading}>
          {visibleJobs.map((item) => <li key={item.id} className="job-item"><button className="job" role="option" aria-selected={item.id === jobId} onClick={() => { setJobId(item.id); setRunId(""); setTaskName(""); setNewTaskName(""); setNameError(""); setArchive(null); setFileError(""); setResultQuery(""); }}><span className="job-name">{item.id}</span><span className="job-date num">{displayDate(item.date)}</span><span className="job-sub"><span className={`dot ${item.status}`} />{statusLabel(item.status)}</span></button></li>)}
          {!loading && !visibleJobs.length && <li className="empty-list">No jobs match.</li>}
        </ul>
        <div className="side-foot">{loading ? "Loading jobs…" : `Showing ${visibleJobs.length} of ${jobs.length} jobs`}</div>
      </aside>
      <article className="detail" id="energyDetail">
        <div className="d-head"><div><div className="d-title"><h2>{jobId || "Choose a Job"}</h2>{job && <span className={`pill ${job.status}`}>{statusLabel(job.status)}</span>}</div><div className="d-meta">{job ? <><span>{displayDate(job.date, true)}</span><span>{runs.length} completed run{runs.length === 1 ? "" : "s"}</span></> : "Select a completed Run before starting a task."}</div></div>{jobId && <a className="btn btn-secondary" href={`/analyze/?job=${encodeURIComponent(jobId)}`}><Icon name="chart" />Analyze runs</a>}</div>
        <div className="energy-run-picker"><label className="field"><span>Run</span><select value={runId} onChange={(event) => { setRunId(event.target.value); setArchive(null); setFileError(""); setNameError(""); setTaskName(""); setNewTaskName(""); setResultQuery(""); }} disabled={!runs.length}><option value="">Choose a completed Run</option>{runs.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label><span className="muted">{runs.length} completed Run{runs.length === 1 ? "" : "s"}</span></div>
        {!run ? <div className="panel"><div className="empty"><Icon name="atom" /><h3>{runs.length ? "Choose a Run" : "No completed runs yet"}</h3><p>{runs.length ? "DFT energy uses the selected Run's optimized parameters and basis." : "Energies can be calculated after a fit completes a Run."}</p>{!runs.length && <a className="btn btn-secondary" href={`/workspace/?job=${encodeURIComponent(jobId)}`}>Open Workspace</a>}</div></div> : <>
          <section className="box energy-task-form"><div className="box-head"><span className="energy-step">1</span><strong>New DFT energy task</strong><span className="sp" /><span className="muted">{run.id}</span></div><p className="energy-task-note">Use the selected Run's optimized functional and stability-aware SCF settings. Each task keeps its own archive, status and results.</p><div className="energy-task-fields"><label className="field"><span>Task name</span><input className="inp" value={newTaskName} aria-invalid={!!nameError} aria-describedby="energyNameHelp" onChange={(event) => { setNewTaskName(event.target.value); setNameError(""); }} placeholder={nextName} autoComplete="off" spellCheck={false} /></label>{nameError && <p className="help err" id="energyNameHelp" role="alert">{nameError}</p>}<div className="field"><span className="flabel">Structures</span><label className={`file-picker energy-drop${archive ? " has" : fileError ? " bad" : ""}`} htmlFor="energyArchive"><input id="energyArchive" type="file" accept=".tgz,.tar.gz,.zip,application/gzip,application/x-gzip,application/zip" onChange={(event) => chooseArchive(event.target.files?.[0] || null)} /><Icon name={archive ? "check" : "archive"} /><span><b>{archive ? archive.name : "Geometry archive (.tgz)"}</b><small className="meta">{archive ? `${Math.ceil(archive.size / 1024)} KB · .xyz structures` : "Drop a .tgz of .xyz files here, or click to choose"}</small></span></label>{fileError && <span className="help err" role="alert">{fileError}</span>}</div></div><div className="energy-task-foot"><span className={`hint${archive && !fileError ? " ok" : ""}`}>{archive && !fileError ? `Ready to calculate ${newTaskName.trim() || nextName}.` : "No .ref file is required."}</span><button className="btn btn-primary" disabled={busy || !archive || !!fileError || !!nameError || !(newTaskName.trim() || nextName).trim()} onClick={() => void submit()}>{busy ? "Submitting…" : "Run DFT energy"}</button></div></section>
          <section className="box"><div className="box-head"><span className="energy-step">2</span><strong>Tasks for {run.id}</strong><span className="sp" /><button className="btn btn-secondary btn-sm" onClick={() => void refreshTasks()} disabled={busy}>Refresh</button></div>{tasks.length ? <div className="energy-task-list">{tasks.map((task) => { const status = energyStatus(task); return <button key={task.name} type="button" className={`energy-task-row ${task.name === taskName ? "selected" : ""}`} aria-pressed={task.name === taskName} onClick={() => { setTaskName(task.name); setResultQuery(""); }}><span><strong>{task.name}</strong><small><span className={`dot ${energyStatusClass(status)}`} aria-hidden="true" />{energyStatusLabel(status)}</small></span><span>{task.result?.molecularEnergies?.length || 0} molecules</span></button>; })}</div> : <p className="muted">No DFT energy tasks yet. Submit the first task above.</p>}</section>
          {selectedTask?.result?.molecularEnergies && <section className="box energy-results">{(() => { const rows = selectedTask.result.molecularEnergies; const status = energyStatus(selectedTask); const done = rows.filter((row: any) => row.status !== "failed" && typeof row.energy_hartree === "number").length; const failed = rows.filter((row: any) => row.status === "failed" || typeof row.energy_hartree !== "number").length; const query = resultQuery.trim().toLowerCase(); const filtered = rows.filter((row: any) => !query || String(row.name).toLowerCase().includes(query)); return <><div className="box-head"><span className="energy-step">3</span><strong>{selectedTask.name} results</strong><span className="sp" /><div className="energy-head-actions"><button className="btn btn-secondary btn-sm" onClick={copyEnergies}>Copy</button><button className="btn btn-secondary btn-sm" onClick={exportEnergies}>Export CSV</button></div><span className={`pill ${energyStatusClass(status)}`}>{energyStatusLabel(status)}</span></div><div className="energy-summary"><div><span>Molecules</span><b>{rows.length}</b></div><div><span>Converged</span><b>{done}</b></div><div className={failed ? "bad" : ""}><span>Failed</span><b>{failed}</b></div></div>{status !== "completed" && <div className="energy-progress"><div className="progress-top">{done} of {rows.length} molecules converged</div><progress max={rows.length} value={done} /></div>}{rows.length > 8 && <div className="energy-results-tools"><label className="search"><Icon name="search" /><span className="sr">Filter molecules</span><input type="search" value={resultQuery} onChange={(event) => setResultQuery(event.target.value)} placeholder="Filter molecules" /></label><span className="muted">Showing {filtered.length} of {rows.length}</span></div>}<div className="tbl-wrap"><table aria-label="DFT energy task results"><thead><tr><th className="idx">#</th><th>Molecule</th><th className="r">Energy (Hartree)</th><th className="st">Status</th></tr></thead><tbody>{filtered.map((row: any, index: number) => <tr key={row.name} className={row.status === "failed" ? "failed" : ""}><td className="idx num">{index + 1}</td><td className="mono mol">{row.name}</td><td className="r num">{typeof row.energy_hartree === "number" ? row.energy_hartree.toFixed(10) : "—"}</td><td className="st">{row.status === "failed" ? <span className="energy-status failed"><span className="dot failed" aria-hidden="true" />Failed</span> : <span className="energy-status"><span className="dot completed" aria-hidden="true" />Converged</span>}</td></tr>)}</tbody></table></div>{selectedTask.log && <details className="energy-log" open={status === "failed" || status === "partial"}><summary><Icon name="chev" />Calculation log</summary><pre>{selectedTask.log}</pre></details>}</>})()}</section>}
        </>}
      </article>
    </div>
  </section>;
}
