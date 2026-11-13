import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { Header, Hero, Citation, Footer } from "./replica/Chrome";
import type { Page } from "./replica/Chrome";
import Analyze from "./replica/Analyze";
import Energy from "./replica/Energy";
import Guide from "./replica/Guide";
import { Icon, SymbolDefs } from "./replica/Icons";
import NewJobSheet from "./replica/NewJobSheet";
import AuthSheet from "./replica/AuthSheet";
import JobDetail from "./replica/JobDetail";
import { cancelRun, deleteJob, deleteRun, displayDate, displayStatus, displayStatusLabel, emptyFiles, errorMessage, listJobs, listRuns, loadRunFiles } from "./replica/data";
import type { Job, RunFiles } from "./replica/data";

type JobSettings = { basis?: string; email?: string; id?: string };
type Notice = { id: number; text: string; kind: "good" | "bad" | "info" };
type Notify = (text: string, kind?: Notice["kind"]) => void;

export default function App({ page }: { page: Page }) {
  return <AuthProvider><Application page={page} /></AuthProvider>;
}

function Application({ page }: { page: Page }) {
  const { user, loading, logout, showAuthModal, setShowAuthModal } = useAuth();
  const [count, setCount] = useState<number | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [initial, setInitial] = useState<JobSettings | undefined>();
  const [pendingNew, setPendingNew] = useState(false);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [createdJob, setCreatedJob] = useState("");
  const [jobIds, setJobIds] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const noticeId = useRef(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const notify = useCallback<Notify>((text, kind = "good") => {
    const id = ++noticeId.current;
    setNotices((current) => [...current.slice(-2), { id, text, kind }]);
    timers.current.push(setTimeout(() => setNotices((current) => current.filter((item) => item.id !== id)), 5000));
  }, []);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  useEffect(() => {
    if (page === "overview" && window.location.hash === "#workspace") {
      window.location.replace("/workspace/" + window.location.search);
    }
  }, [page]);

  useEffect(() => {
    if (page !== "overview") return;
    const controller = new AbortController();
    axios.get("/api_dft/download/submit_count.txt", { signal: controller.signal })
      .then((response) => {
        const value = Number(response.data);
        setCount(Number.isFinite(value) ? value : null);
      }).catch(() => { if (!controller.signal.aborted) setCount(-1); });
    return () => controller.abort();
  }, [page, revision]);

  useEffect(() => {
    if (!user || !newOpen || page === "workspace") return;
    const controller = new AbortController();
    listJobs(`Work/${user.username}`, controller.signal).then((items) => {
      if (!controller.signal.aborted) setJobIds(items.map((item) => item.id));
    }).catch((error) => { if (!controller.signal.aborted) notify(errorMessage(error), "bad"); });
    return () => controller.abort();
  }, [user, newOpen, page, notify]);

  useEffect(() => {
    if (user && pendingNew) {
      setPendingNew(false);
      setNewOpen(true);
    }
    if (!user) {
      setNewOpen(false);
      setCreatedJob("");
      setJobIds([]);
    }
  }, [user, pendingNew]);

  const openNew = useCallback((settings?: JobSettings) => {
    setInitial(settings);
    if (!user) {
      setPendingNew(true);
      setShowAuthModal(true);
    } else setNewOpen(true);
  }, [user, setShowAuthModal]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (event.metaKey || event.ctrlKey || event.altKey || target.closest("input, textarea, select, [contenteditable=true]") || document.querySelector("dialog[open]")) return;
      if (event.key.toLowerCase() === "n") { event.preventDefault(); openNew(); }
      if (event.key === "/") {
        const search = document.getElementById("jobSearch");
        if (search) { event.preventDefault(); search.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openNew]);

  return <>
    <SymbolDefs />
    <Header page={page} user={user} onNew={() => openNew()} onLogin={() => setShowAuthModal(true)}
      onLogout={() => { setPendingNew(false); logout(); }} onNotify={notify} />
    <main id="top" className={`page-${page}`}>
      <div className="wrap">
        {page === "overview" ? <><Hero count={count} onNew={() => openNew()} /><Citation onNotify={notify} /></>
          : page === "guide" ? <Guide onNotify={notify} />
          : user ? page === "analyze" ? <Analyze key={user.username} username={user.username} onNew={() => openNew()} onNotify={notify} />
          : page === "energy" ? <Energy key={user.username} username={user.username} onNotify={notify} />
          : <Workspace key={user.username} user={user} onNew={openNew} onNotify={notify}
          createdJob={createdJob} revision={revision} onJobsChanged={setJobIds} />
          : <section className="ws" id={page} aria-labelledby="wsTitle">
            <div className="ws-head"><div><h1 id="wsTitle">{page === "analyze" ? "Analyze" : page === "energy" ? "DFT energy" : "Workspace"}</h1><p>{page === "analyze" ? "Compare MUE across your runs." : page === "energy" ? "Run optimized-parameter energy calculations." : "Your recent jobs."}</p></div></div>
            <div className="detail"><div className="panel">
              <div className="empty" role="status">
                <span className="big">{loading ? <Icon name="clock" /> : <img src="/favicon.svg" alt="" aria-hidden="true" />}</span>
                <h2>{loading ? "Restoring your workspace" : page === "analyze" ? "Sign in to analyze runs" : "Sign in to get started"}</h2>
                <p>{loading ? "Checking your saved session…" : page === "analyze" ? "Choose runs and compare MUE results." : "Upload data, track calculations, and return to your results."}</p>
                {!loading && <button className="btn btn-primary" onClick={() => setShowAuthModal(true)}>Sign in</button>}
              </div>
            </div></div>
          </section>}
      </div>
    </main>
    <Footer onNotify={notify} />
    {user && <NewJobSheet open={newOpen} onClose={() => setNewOpen(false)} username={user.username}
      email={user.email} existingIds={jobIds} initial={initial} onNotify={notify}
      onSubmitted={(id) => {
        if (page !== "workspace") {
          window.location.assign(`/workspace/?job=${encodeURIComponent(id)}`);
          return;
        }
        setCreatedJob(id); setRevision((value) => value + 1);
        setNewOpen(false);
        requestAnimationFrame(() => document.getElementById("workspace")?.scrollIntoView({ block: "start" }));
      }} />}
    <AuthSheet intent={pendingNew ? "new" : undefined} open={showAuthModal} onClose={() => { setShowAuthModal(false); setPendingNew(false); }} />
    <div className="toasts" aria-live="polite">
      {notices.map((notice) => <div className={`toast ${notice.kind}`} key={notice.id}>
        <Icon name={notice.kind === "good" ? "check" : notice.kind === "bad" ? "alert" : "info"} />
        <span>{notice.text}</span>
      </div>)}
    </div>
  </>;
}

const filters = [["all", "All"], ["active", "Active"], ["completed", "Done"], ["failed", "Failed"]];
function matchesFilter(job: Job, filter: string) {
  return filter === "all" || (filter === "active" ? ["queued", "running"].includes(displayStatus(job)) : displayStatus(job) === filter);
}

function Workspace({ user, onNew, onNotify, createdJob, revision, onJobsChanged }: {
  user: { username: string; email: string }; onNew: (initial?: JobSettings) => void;
  onNotify: Notify; createdJob: string; revision: number;
  onJobsChanged: (ids: string[]) => void;
}) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState("");
  const [runs, setRuns] = useState<Job[]>([]);
  const [runId, setRunId] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [sidebarLevel, setSidebarLevel] = useState<"jobs" | "runs">("jobs");
  const [runQuery, setRunQuery] = useState("");
  const [runFilter, setRunFilter] = useState("all");
  const [refresh, setRefresh] = useState(0);
  const [listLoading, setListLoading] = useState(true);
  const [runLoading, setRunLoading] = useState(false);
  const [filesLoading, setFilesLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [runError, setRunError] = useState("");
  const [filesError, setFilesError] = useState("");
  const [files, setFiles] = useState<RunFiles>(emptyFiles);
  const [filesKey, setFilesKey] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Job | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const deleting = useRef(false);
  // Keep navigation data warm while the user moves between Jobs. The
  // requests below still refresh these entries, but returning to a Job can
  // render immediately instead of waiting for its file-list round trips.
  const runsCache = useRef(new Map<string, Job[]>());
  const filesCache = useRef(new Map<string, RunFiles>());
  const runsPrefetch = useRef(new Map<string, AbortController>());
  const root = `Work/${user.username}`;

  function preferredRun(items: Job[], current = "", jobId = selected) {
    const saved = sessionStorage.getItem(`dfthub-run:${root}/${jobId}`) || "";
    const requested = new URLSearchParams(window.location.search);
    const linked = requested.get("job") === jobId ? requested.get("run") || "" : "";
    return [current, linked, saved].find((id) => items.some((item) => item.id === id)) || items[items.length - 1]?.id || "";
  }

  function prefetchJob(id: string) {
    const path = `${root}/${id}/output`;
    if (id === selected || runsCache.current.has(path) || runsPrefetch.current.has(path)) return;
    const controller = new AbortController();
    runsPrefetch.current.set(path, controller);
    listRuns(path, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      items.sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
      runsCache.current.set(path, items);
    }).catch(() => {
      // Hover prefetch is opportunistic; selecting the Job performs the real load.
    }).finally(() => runsPrefetch.current.delete(path));
  }

  useEffect(() => () => {
    for (const controller of runsPrefetch.current.values()) controller.abort();
    runsPrefetch.current.clear();
  }, []);

  useEffect(() => {
    if (deleteTarget) {
      if (!deleteDialog.current?.open) deleteDialog.current?.showModal();
      deleteDialog.current?.querySelector<HTMLButtonElement>(".delete-cancel")?.focus();
    } else deleteDialog.current?.close();
  }, [deleteTarget]);

  function closeDelete() { if (!deleting.current) setDeleteTarget(null); }
  async function confirmDelete() {
    if (!deleteTarget || deleting.current) return;
    const target = deleteTarget;
    deleting.current = true;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await deleteJob(user.username, target.id);
      const remaining = jobs.filter((item) => item.id !== target.id);
      setJobs(remaining);
      onJobsChanged(remaining.map((item) => item.id));
      sessionStorage.removeItem(`dfthub-run:${root}/${target.id}`);
      runsCache.current.delete(`${root}/${target.id}/output`);
      for (const key of filesCache.current.keys()) if (key.startsWith(`${target.id}/`)) filesCache.current.delete(key);
      if (selected === target.id) {
        setSelected(remaining[0]?.id || ""); setRunId(""); setRuns([]); setFiles(emptyFiles); setFilesKey("");
        setRunError(""); setFilesError("");
        setSidebarLevel("jobs"); setRunQuery(""); setRunFilter("all");
      }
      setDeleteTarget(null);
      setRefresh((value) => value + 1);
      onNotify(`${target.id} deleted.`);
      requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(".job[aria-selected=true]")?.focus());
    } catch (error) {
      setDeleteError(errorMessage(error));
    } finally {
      deleting.current = false;
      setDeleteBusy(false);
    }
  }

  async function stopSelectedRun(scope?: import("./replica/data").SpeScope) {
    if (!selected || !runId) throw new Error("No run is selected.");
    await cancelRun(user.username, selected, runId, scope);
    setRefresh((value) => value + 1);
  }

  async function deleteSelectedRun() {
    if (!selected || !runId) throw new Error("No run is selected.");
    const removed = runId;
    await deleteRun(user.username, selected, removed);
    const remaining = runs.filter((item) => item.id !== removed);
    runsCache.current.delete(`${root}/${selected}/output`);
    filesCache.current.delete(`${selected}/${removed}`);
    setRuns(remaining);
    setRunId(remaining[0]?.id || "");
    setFiles(emptyFiles); setFilesKey("");
    setRefresh((value) => value + 1);
  }

  useEffect(() => {
    const controller = new AbortController();
    setListLoading(true);
    setListError("");
    listJobs(root, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      try { sessionStorage.setItem(`dfthub-jobs:${user.username}`, JSON.stringify({ savedAt: Date.now(), items })); } catch { /* Storage may be unavailable in private browsing. */ }
      setJobs(items);
      onJobsChanged(items.map((item) => item.id));
      const requested = new URLSearchParams(window.location.search).get("job");
      setSelected((current) => items.some((item) => item.id === current) ? current : items.find((item) => item.id === requested)?.id || items[0]?.id || "");
    }).catch((error) => {
      if (!controller.signal.aborted) setListError(errorMessage(error));
    }).finally(() => { if (!controller.signal.aborted) setListLoading(false); });
    return () => controller.abort();
  }, [root, refresh, revision, onJobsChanged]);

  useEffect(() => {
    if (createdJob) { setSelected(createdJob); setRunId(""); setFilter("all"); setQuery(""); setRunQuery(""); setRunFilter("all"); setSidebarLevel("runs"); }
  }, [createdJob, revision]);

  useEffect(() => {
    if (!selected) { setRuns([]); setRunId(""); setRunLoading(false); return; }
    const controller = new AbortController();
    const runsPath = `${root}/${selected}/output`;
    const cached = runsCache.current.get(runsPath);
    if (cached) {
      setRuns(cached);
      setRunId((current) => preferredRun(cached, current, selected));
    } else setRuns([]);
    setRunLoading(!cached);
    setRunError("");
    listRuns(runsPath, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      items.sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
      runsCache.current.set(runsPath, items);
      setRuns(items);
      setRunId((current) => preferredRun(items, current, selected));
    }).catch((error) => {
      if (!controller.signal.aborted) { if (!cached) setRuns([]); setRunError(errorMessage(error)); }
    }).finally(() => { if (!controller.signal.aborted) setRunLoading(false); });
    return () => controller.abort();
  }, [root, selected, refresh, revision]);

  useEffect(() => {
    if (selected && runs.some((item) => item.id === runId)) sessionStorage.setItem(`dfthub-run:${root}/${selected}`, runId);
  }, [root, selected, runs, runId]);

  const currentFilesKey = selected + "/" + runId;
  useEffect(() => {
    if (!selected || !runId) { setFilesLoading(false); setFilesError(""); return; }
    const controller = new AbortController();
    const cached = filesCache.current.get(currentFilesKey);
    if (cached) {
      setFiles(cached);
      setFilesKey(currentFilesKey);
    }
    setFilesLoading(!cached);
    setFilesError("");
    loadRunFiles(user.username, selected, runId, controller.signal).then((values) => {
      if (!controller.signal.aborted) {
        filesCache.current.set(currentFilesKey, values);
        setFiles(values); setFilesKey(currentFilesKey);
      }
    }).catch((error) => {
      if (!controller.signal.aborted) setFilesError(errorMessage(error));
    }).finally(() => { if (!controller.signal.aborted) setFilesLoading(false); });
    return () => controller.abort();
  }, [user.username, selected, runId, currentFilesKey, refresh, revision]);

  // Poll only active calculations, and avoid refreshing while a modal is in use.
  const active = [...jobs, ...runs].some((job) => ["running", "queued"].includes(displayStatus(job))) ||
    Object.values(files.speScopes).some((scope) => ["Queued", "Running"].includes(scope.status));
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      if (!document.hidden && !document.querySelector("dialog[open]")) setRefresh((value) => value + 1);
    }, 20000);
    return () => clearInterval(timer);
  }, [active]);

  function selectJob(id: string, enterRuns = true) {
    if (enterRuns) setSidebarLevel("runs");
    if (id === selected) return;
    setSelected(id); setRunId(""); setRunLoading(true); setFilesError(""); setRunError("");
    setRunQuery(""); setRunFilter("all");
  }

  const visible = jobs.filter((job) => matchesFilter(job, filter) && job.id.toLowerCase().includes(query.trim().toLowerCase()));
  const job = jobs.find((item) => item.id === selected);
  const run = runs.find((item) => item.id === runId) || null;
  const jobFiles = filesKey === currentFilesKey ? files : emptyFiles;
  const showingRuns = sidebarLevel === "runs";
  const sidebarItems = showingRuns ? runs : jobs;
  const sidebarQuery = showingRuns ? runQuery : query;
  const sidebarFilter = showingRuns ? runFilter : filter;
  const visibleItems = showingRuns
    ? runs.filter((item) => matchesFilter(item, runFilter) && item.id.toLowerCase().includes(runQuery.trim().toLowerCase()))
    : visible;
  const sidebarLoading = showingRuns ? runLoading : listLoading;
  const counts = {
    active: jobs.filter((item) => ["queued", "running"].includes(displayStatus(item))).length,
    completed: jobs.filter((item) => displayStatus(item) === "completed").length,
    failed: jobs.filter((item) => displayStatus(item) === "failed").length,
  };

  return <section className="ws" id="workspace" aria-labelledby="wsTitle">
    <div className="ws-head">
      <div><h1 id="wsTitle">Workspace</h1><p id="wsSummary">{listLoading && !jobs.length ? "Loading your jobs…" : `${counts.active} active · ${counts.completed} completed · ${counts.failed} need attention`}</p></div>
      <button className="btn btn-primary" onClick={() => onNew()}><Icon name="plus" />New job</button>
    </div>
    {listError && <div className="alert" role="alert" style={{ marginBottom: 20 }}><Icon name="alert" /><b>Could not refresh your jobs</b><div>{listError}</div><div><button className="btn btn-secondary btn-sm" onClick={() => setRefresh((value) => value + 1)}>Try again</button></div></div>}
    <div className="ws-grid">
      <aside className="sidebar" aria-label="Job and run navigation">
        <div className="side-top">
          <div className="seg full sidebar-levels" role="group" aria-label="Sidebar level">
            <button type="button" aria-pressed={!showingRuns} aria-controls="sidebar-list"
              onClick={() => setSidebarLevel("jobs")}>Jobs <span className="count num">{jobs.length}</span></button>
            <button type="button" aria-pressed={showingRuns} aria-controls="sidebar-list" disabled={!job}
              onClick={() => setSidebarLevel("runs")}>Runs <span className="count num">{runs.length}</span></button>
          </div>
          {showingRuns && <div className="sidebar-job-context">
            <span className="muted">Job</span><strong title={job?.id || selected}>{job?.id || selected}</strong>
          </div>}
          <label className="search"><span className="sr">{showingRuns ? "Search runs" : "Search jobs"}</span><Icon name="search" />
            <input id="jobSearch" type="search" placeholder={showingRuns ? "Search runs" : "Search jobs"} autoComplete="off"
              aria-label={showingRuns ? "Search runs" : "Search jobs"} aria-keyshortcuts="/"
              value={sidebarQuery} onChange={(event) => showingRuns ? setRunQuery(event.target.value) : setQuery(event.target.value)} /><kbd aria-hidden="true">/</kbd>
          </label>
          <div className="seg full" role="group" aria-label={showingRuns ? "Filter runs by status" : "Filter jobs by status"}>
            {filters.map(([key, label]) => <button key={key} type="button" aria-pressed={sidebarFilter === key}
              onClick={() => showingRuns ? setRunFilter(key) : setFilter(key)}>{label} <span className="count num">{sidebarItems.filter((item) => matchesFilter(item, key)).length}</span></button>)}
          </div>
        </div>
        <ul className={`job-list ${showingRuns ? "runs-list" : ""}`} id="sidebar-list" role="listbox" aria-label={showingRuns ? `Runs for ${job?.id || selected}` : "Jobs"} aria-busy={sidebarLoading}>
          {visibleItems.length ? visibleItems.map((item, index) => {
            const selectedItem = showingRuns ? item.id === runId : item.id === selected;
            const totalMue = showingRuns ? null : item.mue;
            return <li key={item.id} className="job-item">
              <button className={`job ${showingRuns ? "run-option" : ""}`} role="option" aria-selected={selectedItem}
                data-fork={showingRuns && item.id.includes("/") ? "true" : undefined} title={item.id}
                onMouseEnter={() => { if (!showingRuns) prefetchJob(item.id); }}
                onFocus={() => { if (!showingRuns) prefetchJob(item.id); }}
                onClick={() => showingRuns ? setRunId(item.id) : selectJob(item.id)}
                onKeyDown={(event) => {
                  if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
                  event.preventDefault();
                  const next = event.key === "Home" ? 0 : event.key === "End" ? visibleItems.length - 1 : Math.max(0, Math.min(visibleItems.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
                  if (showingRuns) setRunId(visibleItems[next].id);
                  else selectJob(visibleItems[next].id, false);
                  (event.currentTarget.closest("ul")?.querySelectorAll(".job")[next] as HTMLButtonElement)?.focus();
                }}>
                <span className={`job-name ${showingRuns ? "mono" : ""}`}>{item.id}</span><span className="job-date num">{showingRuns ? (item.id.includes("/") ? "fork" : item.effectiveWeight == null ? "w —" : `w ${Number(item.effectiveWeight.toPrecision(4))}`) : displayDate(item.date)}</span>
                <span className="job-sub"><span className={`dot ${displayStatus(item)}`} aria-hidden="true" />
                  <span>{displayStatusLabel(item)}{totalMue !== null ? ` · MUE ${totalMue.toFixed(2)} kcal/mol` : ""}</span>
                </span>
              </button>
              {!showingRuns && <button type="button" className="icon-btn job-delete" aria-label={`Delete job ${item.id}`}
                title={["queued", "running"].includes(displayStatus(item)) ? "Wait for the calculation to finish before deleting this job." : `Delete ${item.id}`}
                disabled={deleteBusy || ["queued", "running"].includes(displayStatus(item))}
                onClick={() => { setDeleteError(""); setDeleteTarget(item); }}><Icon name="trash" /></button>}
            </li>;
          }) : <li className="empty-list">{sidebarLoading ? `Loading ${showingRuns ? "runs" : "jobs"}…` : showingRuns
            ? runError ? "Could not load runs. Refresh to try again." : runs.length ? "No runs match this search or status." : "No runs yet."
            : jobs.length ? "No jobs match this search or status." : "No jobs yet. Start a new job to upload your data set."}</li>}
        </ul>
        <div className="side-foot"><button type="button" className="link" onClick={() => setRefresh((value) => value + 1)} disabled={sidebarLoading} aria-label={showingRuns ? "Refresh runs" : "Refresh jobs"}><Icon name="refresh" /></button></div>
      </aside>
      <article className="detail" id="detail">
        {job ? <JobDetail job={job} runs={runs} run={run} files={jobFiles}
          user={user} loading={runLoading || filesLoading} error={runError || filesError}
          onRefresh={() => setRefresh((value) => value + 1)} onNew={onNew} onNotify={onNotify}
          onCancel={stopSelectedRun} onDeleteRun={deleteSelectedRun}
          onSubmitted={(id) => { setRunId(id); setRunQuery(""); setRunFilter("all"); setSidebarLevel("runs"); setRefresh((value) => value + 1); }} />
          : <div className="panel"><div className="empty"><span className="big"><Icon name="atom" /></span><h4>{listLoading ? "Loading your workspace" : "Choose a job to get started"}</h4><p>Open a previous job to inspect its runs, or upload a new data set.</p><div className="row"><button className="btn btn-primary" onClick={() => onNew()}><Icon name="plus" />New job</button></div></div></div>}
      </article>
    </div>
    <dialog className="sheet delete-sheet" ref={deleteDialog} aria-labelledby="delete-title"
      onCancel={(event) => { event.preventDefault(); closeDelete(); }}
      onClick={(event) => { if (event.target === event.currentTarget) closeDelete(); }}>
      <div className="sheet-head"><div><h3 id="delete-title">Delete job?</h3><p>{deleteTarget?.id}</p></div></div>
      <div className="sheet-body"><p>This permanently deletes <strong>{deleteTarget?.id}</strong>, including its uploaded files, all runs, and results.</p><p className="muted">This action cannot be undone.</p>{deleteError && <p className="err-pos" role="alert">{deleteError}</p>}</div>
      <div className="sheet-foot">
        <button type="button" className="btn btn-secondary delete-cancel" disabled={deleteBusy} onClick={closeDelete}>Cancel</button>
        <button type="button" className="btn btn-danger" disabled={deleteBusy} onClick={confirmDelete}>{deleteBusy ? "Deleting…" : "Delete job"}</button>
      </div>
    </dialog>
  </section>;
}
