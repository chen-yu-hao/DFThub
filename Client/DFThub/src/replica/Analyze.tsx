import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { errorMessage, listJobs, runFields } from "./data";
import type { Job } from "./data";
import { combineAnalysisJobs, loadAnalysisJobs, loadAnalysisSummaries, summarizeAnalysis } from "./analysisData";
import type { AnalysisJob, AnalysisPayload, AnalysisSummary } from "./analysisData";
import { mountAnalysis } from "./analyzeView.js";
import shell from "./analyzeShell.html?raw";

export default function Analyze({ username, onNew, onNotify }: {
  username: string; onNew: () => void; onNotify: (message: string, kind?: "good" | "bad" | "info") => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<ReturnType<typeof mountAnalysis> | null>(null);
  const cache = useRef(new Map<string, AnalysisJob>());
  const queueing = useRef(false);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [summaries, setSummaries] = useState<AnalysisSummary[]>([]);
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([]);
  const [focusJobId, setFocusJobId] = useState("");
  const [payload, setPayload] = useState<AnalysisPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const selectionTouched = useRef(false);
  const actions = useRef({ onNew, onNotify });
  actions.current = { onNew, onNotify };
  const selectedRef = useRef(selectedJobIds);
  selectedRef.current = selectedJobIds;

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams(window.location.search);
    const applyJobs = (items: Job[]) => {
      setJobs(items);
      setSummaries(items.map((job) => summarizeAnalysis(job)));
      if (selectionTouched.current) {
        setSelectedJobIds((current) => current.filter((id) => items.some((item) => item.id === id)));
        setFocusJobId((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id || "");
        return;
      }
      const requested = [...new Set((query.get("jobs") || query.get("job") || "").split(","))].filter((id) => items.some((item) => item.id === id));
      const initial = requested.length ? requested : items[0]?.id ? [items[0].id] : [];
      setSelectedJobIds(initial);
      setFocusJobId(initial.includes(query.get("focusJob") || "") ? query.get("focusJob")! : initial[0] || "");
      if (!items.length) setLoading(false);
    };
    try {
      const raw = sessionStorage.getItem(`dfthub-jobs:${username}`);
      const cached = raw ? JSON.parse(raw) : null;
      if (cached && Date.now() - Number(cached.savedAt) < 60_000 && Array.isArray(cached.items)) applyJobs(cached.items);
    } catch { /* Ignore malformed or unavailable session storage. */ }
    listJobs(`Work/${username}`, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      try { sessionStorage.setItem(`dfthub-jobs:${username}`, JSON.stringify({ savedAt: Date.now(), items })); } catch { /* Storage may be unavailable in private browsing. */ }
      applyJobs(items);
    }).catch((failure) => { if (!controller.signal.aborted) { setError(errorMessage(failure)); setLoading(false); } });
    return () => controller.abort();
  }, [username]);

  useEffect(() => {
    if (!jobs?.length || !selectedJobIds.length) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    const pending = selectedJobIds.filter((id) => !cache.current.has(id));
    const renderReady = () => {
      const parts = selectedJobIds.map((id) => cache.current.get(id)).filter(Boolean) as AnalysisJob[];
      if (!parts.length || controller.signal.aborted) return;
      const readyIds = parts.map((part) => part.id);
      const combined = readyIds.length === 1 ? { ...parts[0], primaryJobId: readyIds[0], selectedJobIds: [...readyIds] } : combineAnalysisJobs(parts, readyIds);
      setPayload({ job: combined, jobs: summaries, selectedJobIds: readyIds, focusJobId: focusJobId && readyIds.includes(focusJobId) ? focusJobId : readyIds[0], chemicalAccuracy: 1, units: "kcal/mol" });
      setLoading(readyIds.length < selectedJobIds.length);
    };
    renderReady();
    Promise.all(pending.map(async (id) => {
      const response = await loadAnalysisJobs(username, [id], controller.signal);
      if (controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
      const data = response.jobs[0];
      if (data) cache.current.set(id, data);
      if (response.summaries.length) setSummaries((current) => current.map((summary) => response.summaries.find((next) => next.id === summary.id) || summary));
      renderReady();
    })).then(() => {
      if (!controller.signal.aborted) { renderReady(); setLoading(false); }
    }).catch((failure) => { if (!controller.signal.aborted) { setError(errorMessage(failure)); setLoading(false); } });
    return () => controller.abort();
  }, [username, jobs, selectedJobIds, revision]);

  useEffect(() => {
    if (!jobs?.length || !payload || loading) return;
    const controller = new AbortController();
    loadAnalysisSummaries(username, jobs.map((job) => job.id), controller.signal)
      .then((next) => {
        if (controller.signal.aborted || !next.length) return;
        setSummaries((current) => current.map((item) => next.find((summary) => summary.id === item.id) || item));
      })
      .catch(() => { /* Keep selectable Job rows if a summary refresh is temporarily unavailable. */ });
    return () => controller.abort();
  }, [username, jobs, revision]);

  // Warm a few nearby Jobs after the first view is usable. This keeps the
  // common sidebar switch local while avoiding a burst of analysis requests
  // during the initial render.
  useEffect(() => {
    if (!jobs?.length) return;
    const pending = jobs.map((job) => job.id).filter((id) => !selectedJobIds.includes(id) && !cache.current.has(id)).slice(0, 3);
    if (!pending.length) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void Promise.all(pending.map(async (id) => {
        try {
          const response = await loadAnalysisJobs(username, [id], controller.signal);
          if (!controller.signal.aborted && response.jobs[0]) cache.current.set(id, response.jobs[0]);
        } catch {
          // Prefetch is opportunistic; the selected Job will retry normally.
        }
      }));
    }, 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [username, jobs, selectedJobIds, payload, loading]);

  function refresh() {
    selectedRef.current.forEach((id) => cache.current.delete(id));
    setRevision((value) => value + 1);
  }

  function changeJobs(ids: string[], focus: string) {
    selectionTouched.current = true;
    const next = [...new Set(ids)].filter((id) => jobs?.some((job) => job.id === id));
    if (!next.length) return;
    setSelectedJobIds(next);
    setFocusJobId(next.includes(focus) ? focus : next[0]);
  }

  useEffect(() => {
    if (!payload || !host.current) return;
    const data = { ...payload, jobs: summaries };
    if (view.current) { view.current.update(data); return; }
    host.current.innerHTML = shell;
    view.current = mountAnalysis(host.current.querySelector("#analyze"), data, {
      onJobsChange: changeJobs,
      onNew: () => actions.current.onNew(),
      onRefresh: refresh,
      onNotify: (message, kind) => actions.current.onNotify(message, kind),
      queueScf: async (requests: { jobId: string; runId: string; overlapOnly?: boolean }[]) => {
        const jobCount = new Set(requests.map((request) => request.jobId)).size;
        const overlapOnly = requests.every((request) => request.overlapOnly);
        const message = overlapOnly ? `Calculate missing wavefunction overlap for ${requests.length} run${requests.length === 1 ? "" : "s"} across ${jobCount} job${jobCount === 1 ? "" : "s"}?` : `Calculate SCF Input for ${requests.length} run${requests.length === 1 ? "" : "s"} across ${jobCount} job${jobCount === 1 ? "" : "s"}? This may take 1–48 hours.`;
        if (queueing.current || !requests.length || !window.confirm(message)) return { accepted: [], overlapOnly: [], errors: [] };
        queueing.current = true;
        const accepted: string[] = [], overlapAccepted: string[] = [], errors: string[] = [];
        try {
          for (const request of requests) {
            try {
              const response = await axios.post("/api_dft/submit", { mode: "spe", spe_scope: request.overlapOnly ? "overlap" : "input", work_dir: `Work/${username}/${request.jobId}`, ...runFields(request.runId) });
              if (response.data.result === "error" || response.data.success === false) throw new Error(response.data.msg || "Calculation submission failed.");
              const key = `${request.jobId}::${request.runId}`;
              accepted.push(key);
              if (request.overlapOnly) overlapAccepted.push(key);
            } catch (failure) { errors.push(`${request.jobId}/${request.runId}: ${errorMessage(failure)}`); }
          }
          accepted.forEach((key) => cache.current.delete(key.split("::")[0]));
          return { accepted, overlapOnly: overlapAccepted, errors };
        } finally { queueing.current = false; }
      },
    });
  }, [payload]);

  useEffect(() => { view.current?.updateJobs(summaries); }, [summaries]);
  useEffect(() => { view.current?.setLoading(loading); }, [loading]);
  useEffect(() => { if (error) view.current?.cancelJobChange(); }, [error]);
  useEffect(() => () => { view.current?.destroy(); view.current = null; }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      const data = payload?.job;
      if (!document.hidden && !document.querySelector("dialog[open]") && !queueing.current && data && (data.runs.some((run) => run.input.scf.state === "running" || run.overlap?.state === "running") || data.totalRuns > data.runs.length)) refresh();
    }, 15000);
    return () => clearInterval(timer);
  }, [payload, selectedJobIds]);

  return <>
    {error && <div className="alert an-load-error" role="alert"><b>Could not refresh analysis</b><div>{error}</div><button type="button" className="btn btn-secondary" onClick={() => jobs ? refresh() : window.location.reload()}>Try again</button></div>}
    {!payload && <section className="ws"><div className="ws-head"><div><h2>Analyze</h2><p>Compare MUE trends across jobs, basis sets and runs.</p></div></div><div className="detail"><div className="panel"><div className="empty" role="status"><h3>{loading ? "Loading your analysis…" : jobs?.length === 0 ? "No jobs yet" : "Choose jobs to analyze"}</h3><p>{loading ? "Reading completed runs and their MUE results." : "Create a job in Workspace to start comparing runs."}</p>{!loading && <button type="button" className="btn btn-primary" onClick={onNew}>New job</button>}</div></div></div></section>}
    <div ref={host} />
  </>;
}
