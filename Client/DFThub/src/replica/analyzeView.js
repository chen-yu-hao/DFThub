/*
 * DFThub · Analyze page
 * ---------------------------------------------------------------------------
 * Adapted from the supplied Analyze v2 prototype. This renderer owns only
 * its mounted subtree; React supplies authenticated data and actions.
 *
 * Views
 *   Trends        KPI tiles · Input MUE across runs · trade-off scatter
 *   Input vs SCF  dumbbell of non-SCF vs SCF Input MUE per run
 *   All changes   improved/worse per run · dataset heatmap · drill-down
 *
 * Toggles set aria-pressed / aria-selected; seg-indicator.js animates them.
 */
import { analysisStats, average, baselineValue, difference, isValue, mueValue, sharedReferences } from "./analysisMetrics";

export function mountAnalysis(root, payload, actions) {
  "use strict";
  let DATA = payload;
  let JOB = DATA.job;
  let RUNS = JOB.runs;
  let DATASETS = JOB.datasets;
  let TYPES = [...new Set(DATASETS.map((d) => d.type))];
  let BY_ID = Object.fromEntries(RUNS.map((r) => [r.id, r]));
  const lifecycle = new AbortController();
  let disposed = false;
  let submitting = false;
  const EPS = 0.005; // below this a change rounds to 0.00 and counts as unchanged
  const DENSITY_THRESHOLDS = Object.freeze({ gapKcalMol: 0.05, parameterPercent: 5 });
  const ACC = DATA.chemicalAccuracy || 1;
  const CLAMP = 1; // heatmap saturates at ±1 kcal/mol

  const state = {
    level: "runs",
    job: DATA.focusJobId || JOB.primaryJobId || JOB.id,
    selectedJobs: new Set(DATA.selectedJobIds || JOB.selectedJobIds || [DATA.focusJobId || JOB.primaryJobId || JOB.id]),
    kind: "all",
    runQuery: "",
    included: new Set(RUNS.map((r) => r.id)),
    focus: RUNS[RUNS.length - 1]?.id || "",
    tab: "trends",
    sort: "type",
    hideUnchanged: false,
    dsQuery: "",
    collapsed: new Set(),
    dataset: null,
    tables: new Set(),
    trendDs: [], // reference datasets added to the MUE line chart: { name, slot }
    hidden: new Set(), // series switched off in the series menu
    seriesMenuOpen: false,
    trendScroll: 0,
    scale: "linear", // MUE line chart y-scale: "linear" | "log"
    pickerOpen: false,
    pickerQuery: "",
    densityQuery: "",
  };

  const stableKey = (run) => `${run.jobId}::${run.runId}`;
  const multiJob = () => (JOB.selectedJobIds || []).length > 1;
  const jobCode = (run) => `J${(JOB.selectedJobIds || [run.jobId]).indexOf(run.jobId) + 1}`;
  // One compact name is used in every chart, table, tooltip and export. The
  // Job prefix is only needed when several Jobs are in the same analysis.
  const displayRunName = (run) => {
    const short = run.short || run.runId || run.id;
    return multiJob() ? `${jobCode(run)}/${short}` : short;
  };
  const runLabel = displayRunName;
  const shortLabel = displayRunName;
  const parentLabel = (run) => BY_ID[run.parent] ? displayRunName(BY_ID[run.parent]) : run.parent?.replace("::", " / ");

  let DS_BY_NAME = Object.fromEntries(DATASETS.map((d) => [d.name, d]));
  const DS_SLOTS = [5, 6, 7, 8]; // slots reserved for added reference datasets; test set uses 3/4
  const MAX_DS = DS_SLOTS.length;

  // Colour follows the dataset: a slot is assigned when it is added and freed when removed.
  function addTrendDataset(name) {
    if (!DS_BY_NAME[name] || state.trendDs.some((d) => d.name === name)) return false;
    if (state.trendDs.length >= MAX_DS) return false;
    const used = new Set(state.trendDs.map((d) => d.slot));
    state.trendDs.push({ name, slot: DS_SLOTS.find((k) => !used.has(k)) });
    return true;
  }

  function removeTrendDataset(name) {
    state.trendDs = state.trendDs.filter((d) => d.name !== name);
    [...state.hidden].filter((key) => key === "ds:" + name || key.startsWith("ds:" + name + ":")).forEach((key) => state.hidden.delete(key));
  }

  // Shareable view: ?job=&focus=&tab=
  (() => {
    const q = new URLSearchParams(location.search);
    const linkedFocus = RUNS.find((r) => r.id === q.get("focus") || stableKey(r) === q.get("focus") ||
      (r.runId === q.get("focus") && r.jobId === (q.get("focusJob") || q.get("job"))));
    if (linkedFocus) state.focus = linkedFocus.id;
    if (q.get("focusJob") && DATA.jobs.some((job) => job.id === q.get("focusJob"))) state.job = q.get("focusJob");
    if (q.get("jobs")) {
      const selectedJobs = q.get("jobs").split(",").filter((id) => DATA.jobs.some((job) => job.id === id));
      if (selectedJobs.length) state.selectedJobs = new Set(selectedJobs);
    }
    if (["trends", "scf", "overlap", "changes", "density"].includes(q.get("tab"))) state.tab = q.get("tab");
    if (q.get("scale") === "log") state.scale = "log";
    (q.get("ds") || "").split(",").filter(Boolean).forEach((name) => addTrendDataset(name));
    if (q.has("runs")) {
      const requested = q.get("runs").split(",");
      const selected = RUNS.filter((run) => requested.includes(run.id) || requested.includes(stableKey(run))).map((run) => run.id);
      if (selected.length >= Math.min(2, RUNS.length)) state.included = new Set(selected);
    }
    if (!state.included.has(state.focus)) state.focus = RUNS.find((run) => state.included.has(run.id))?.id || "";
    if (["all", "weight", "fork"].includes(q.get("kind"))) state.kind = q.get("kind");
    if (["type", "change", "name"].includes(q.get("sort"))) state.sort = q.get("sort");
    state.hideUnchanged = q.get("unchanged") === "hide";
    state.dsQuery = q.get("q") || "";
    state.hidden = new Set((q.get("hidden") || "").split(",").filter(Boolean));
    state.tables = new Set((q.get("tables") || "").split(",").filter((id) => ["trend", "tradeoff", "scf", "overlap", "counts", "heat", "drill"].includes(id)));
    state.collapsed = new Set((q.get("collapsed") || "").split(",").filter((type) => TYPES.includes(type)));
    state.dataset = DS_BY_NAME[q.get("dataset")] ? q.get("dataset") : null;
  })();

  function syncUrl() {
    const q = new URLSearchParams({ job: state.job, focusJob: state.job, focus: state.focus, tab: state.tab });
    if (state.selectedJobs.size) q.set("jobs", [...state.selectedJobs].join(","));
    if (state.trendDs.length) q.set("ds", state.trendDs.map((d) => d.name).join(","));
    if (state.scale === "log") q.set("scale", "log");
    if (state.included.size !== RUNS.length) q.set("runs", [...state.included].join(","));
    if (state.kind !== "all") q.set("kind", state.kind);
    if (state.sort !== "type") q.set("sort", state.sort);
    if (state.hideUnchanged) q.set("unchanged", "hide");
    if (state.dsQuery) q.set("q", state.dsQuery);
    if (state.hidden.size) q.set("hidden", [...state.hidden].join(","));
    if (state.tables.size) q.set("tables", [...state.tables].join(","));
    if (state.collapsed.size) q.set("collapsed", [...state.collapsed].join(","));
    if (state.dataset) q.set("dataset", state.dataset);
    try {
      history.replaceState(null, "", `${location.pathname}?${q}`);
    } catch (e) {
      /* file:// previews may refuse; the view still works */
    }
  }

  /* ------------------------------------------------------------------------
     Small helpers
     ------------------------------------------------------------------------ */
  const $ = (s, r = root) => r.querySelector(s);
  const $$ = (s, r = root) => Array.from(r.querySelectorAll(s));
  const SVGNS = "http://www.w3.org/2000/svg";

  function rememberFocus() {
    const element = document.activeElement;
    if (!root.contains(element)) return null;
    const figure = element.closest("figure[aria-label]");
    return { element, id: element.id, label: element.getAttribute("aria-label"), title: element.getAttribute("title"),
      text: element.tagName === "BUTTON" ? element.textContent : null, figure: figure?.getAttribute("aria-label"),
      selection: element instanceof HTMLInputElement && ["text", "search"].includes(element.type) ? [element.selectionStart, element.selectionEnd] : null };
  }

  function restoreFocus(saved) {
    if (!saved || saved.element.isConnected || disposed) return;
    const scope = saved.figure ? $(`figure[aria-label="${CSS.escape(saved.figure)}"]`) : root;
    if (!scope) return;
    const target = saved.id ? $("#" + CSS.escape(saved.id)) : saved.label ? $(`[aria-label="${CSS.escape(saved.label)}"]`, scope)
      : saved.title ? $(`button[title="${CSS.escape(saved.title)}"]`, scope)
      : saved.text ? $$("button", scope).find((button) => button.textContent === saved.text) : null;
    if (!target) return;
    target.focus({ preventScroll: true });
    if (saved.selection && target instanceof HTMLInputElement) target.setSelectionRange(...saved.selection);
  }

  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "style") el.style.cssText = v;
        else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      el.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  function s(tag, attrs, parent) {
    const el = document.createElementNS(SVGNS, tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === "text") el.textContent = v;
        else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v);
      }
    }
    if (parent) parent.appendChild(el);
    return el;
  }

  function icon(id) {
    const el = s("svg", { class: "i", "aria-hidden": "true" });
    s("use", { href: "#" + id }, el);
    return el;
  }

  const f2 = (v) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(2));
  const weightText = (value) => isValue(value) ? String(Number(value.toPrecision(4))) : "—";
  const signed = (v) => {
    if (!isValue(v)) return "—";
    const r = Math.round(v * 100) / 100;
    if (Math.abs(r) < 0.005) return "±0.00";
    return (r > 0 ? "+" : "−") + Math.abs(r).toFixed(2);
  };
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function niceStep(span, target) {
    const raw = span / Math.max(1, target);
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const m = raw / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }

  function niceDomain(lo, hi, target = 5) {
    if (hi - lo < 1e-9) {
      if (lo === 0) hi = 1;
      else { lo -= 0.5; hi += 0.5; }
    }
    const step = niceStep(hi - lo, target);
    const a = Math.floor(lo / step) * step;
    const b = Math.ceil(hi / step) * step;
    const ticks = [];
    for (let v = a; v <= b + step * 0.001; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
    return { lo: a, hi: b, ticks, step };
  }

  function tickText(value, step) {
    let decimals = Math.max(0, Math.min(6, Math.ceil(-Math.log10(step))));
    while (decimals < 6 && Math.abs(Number(step.toFixed(decimals)) - step) > 1e-9) decimals++;
    return String(Number(value.toFixed(decimals)));
  }

  /* ------------------------------------------------------------------------
     Data access
     ------------------------------------------------------------------------ */
  const runsIn = () => RUNS.filter((r) => state.included.has(r.id));
  const focusRun = () => BY_ID[state.focus];
  const canCompare = () => RUNS.length >= 2;
  const workspaceUrl = (run, section) => `/workspace/?job=${encodeURIComponent(run?.jobId || state.job)}${run ? "&run=" + encodeURIComponent(run.runId || run.id.split("::").pop()) : ""}${section ? "&section=" + section : ""}`;

  function densityChainModel() {
    if ((JOB.selectedJobIds || []).length !== 1) return null;
    const selected = runsIn().filter((run) => run.jobId === JOB.selectedJobIds[0]);
    const forks = selected.filter((run) => run.kind === "fork");
    if (forks.length < 1) return null;
    const bases = selected.filter((run) => run.kind === "weight" && forks.every((fork) => {
      let cursor = fork;
      const seen = new Set();
      while (cursor && !seen.has(cursor.id)) {
        if (cursor.id === run.id) return true;
        seen.add(cursor.id);
        cursor = BY_ID[cursor.parent || ""];
      }
      return false;
    }));
    if (bases.length !== 1) return null;
    const base = bases[0];
    const chain = [base];
    let parent = base.id;
    const unused = new Set(forks.map((run) => run.id));
    while (unused.size) {
      const next = forks.find((run) => unused.has(run.id) && run.parent === parent);
      if (!next) return null;
      chain.push(next);
      unused.delete(next.id);
      parent = next.id;
    }
    if (chain.length < 2 || chain.some((run) => !run.density?.targetRows?.length)) return null;
    if (chain.slice(1).every((run) => run.density.parameterChange == null)) return null;
    if (new Set(chain.map((run) => run.basis || "")).size > 1 || new Set(chain.map((run) => run.grid ?? "")).size > 1) return null;
    const allRuns = RUNS.filter((run) => run.jobId === base.jobId && (run.kind === "weight" || chain.includes(run)));
    const scanRuns = allRuns.filter((run) => run.kind === "weight");
    return { base, runs: chain, allRuns, scanRuns, rounds: chain.map((run, index) => ({ ...run, round: index, roundLabel: `R${index}` })) };
  }

  function densityReferenceMean(run) {
    const values = DATASETS.map((dataset) => {
      const value = mue(run, dataset);
      const original = dataset.original;
      return isValue(value) && isValue(original) ? value : null;
    }).filter(isValue);
    return average(values);
  }

  function densityReactionName(system) {
    let value = String(system || "").split(":").slice(1).join(":").trim() || String(system || "");
    value = value.replace(/\b\d+\*/g, "").replace(/\+-(?:1\*)?/, " vs ");
    const stateMatch = value.match(/_(singlet|doublet|triplet|quartet)$/i);
    const stateName = stateMatch ? stateMatch[1].toLowerCase() : "";
    if (stateMatch) value = value.slice(0, stateMatch.index);
    value = value.replace(/_([a-z])/g, (_, letter) => ` ${letter}`).replace(/\b(sym) linear\b/gi, "$1-linear").replace(/\blinear\b/gi, "linear").replace(/\s+/g, " ").trim();
    return { name: value, state: stateName };
  }

  function densityReactionRows(chain) {
    const first = chain.runs[0].density.targetRows;
    return first.map((row) => {
      const key = row.system;
      const values = chain.runs.map((run) => run.density.targetRows.find((item) => item.system === key)?.error ?? null);
      const last = values.at(-1);
      const previous = values.at(-2);
      const info = densityReactionName(key);
      return { ...info, reference: row.reference, values, last, change: isValue(last) && isValue(previous) ? Math.abs(last) - Math.abs(previous) : null };
    });
  }

  function densityPattern(values) {
    const deltas = values.slice(1).map((value, index) => isValue(value) && isValue(values[index]) ? value - values[index] : null).filter(isValue);
    if (deltas.length < 2) return "Mixed";
    const signs = deltas.map((value) => Math.abs(value) <= EPS ? 0 : value > 0 ? 1 : -1).filter(Boolean);
    if (!signs.length) return "Mixed";
    const changes = signs.slice(1).filter((value, index) => value !== signs[index]).length;
    if (changes >= 2 || (signs.length >= 3 && changes >= 1)) return "Oscillating";
    if (signs.every((value) => value < 0)) return "Improving";
    if (signs.every((value) => value > 0)) return "Drifting up";
    return "Mixed";
  }

  function densityReferenceRows(chain) {
    const rounds = chain.runs;
    return DATASETS.filter((dataset) => dataset.name !== "Input").map((dataset) => {
      const values = rounds.map((run) => mue(run, dataset));
      const last = values.at(-1);
      const previous = values.at(-2);
      const vsOriginal = isValue(last) && isValue(dataset.original) ? last - dataset.original : null;
      const change = isValue(last) && isValue(previous) ? last - previous : null;
      return { dataset, values, last, previous, vsOriginal, change, pattern: densityPattern(values) };
    }).filter((row) => isValue(row.last));
  }

  function includedAncestor(run) {
    let p = BY_ID[run.parent || run.trendParent];
    const seen = new Set([run.id]);
    while (p && !state.included.has(p.id) && !seen.has(p.id)) { seen.add(p.id); p = BY_ID[p.parent || p.trendParent]; }
    if (p && seen.has(p.id)) return null;
    return p || null;
  }

  const mue = (run, ds) => mueValue(JOB, run, ds.name);
  const scf = (run) => (run.input.scf.state === "done" ? run.input.scf.value : null);
  const testScf = (run) => (run.test?.scf.state === "done" ? run.test.scf.value : null);

  function baseName(run) {
    return "CF22D";
  }

  const baseMue = (run, ds) => {
    return baselineValue(JOB, run, ds.name, "original");
  };

  const delta = (run, ds) => difference(mue(run, ds), baseMue(run, ds));

  function inputBase(run) {
    return run.input.original;
  }

  function scfBase(run) {
    return run.input.original;
  }

  const statCache = new Map();
  function stats(run, datasets = DATASETS) {
    const key = run.id + "|" + datasets.map((d) => d.name).join(",");
    if (statCache.has(key)) return statCache.get(key);
    const out = analysisStats(JOB, run, [...state.included], "original", datasets.map((d) => d.name));
    statCache.set(key, out);
    return out;
  }

  let originalMean = null;

  // "w2" for new fits, "f3" for forks: used where full ids don't fit
  const tiny = shortLabel;

  function emptyReason(job) {
    if (!job) return "Pick a job to compare its runs.";
    if (job.completed === 0) return "No completed runs yet. Results appear here once the first run finishes.";
    if (job.completed < 2) return `This job has ${plural(job.completed, "completed run", "completed runs")}. Analysis needs at least two.`;
    return "Completed MUE results are not available yet. Refresh after optimization finishes.";
  }

  function runSubtitle(run) {
    const details = `${run.basis || "Basis not reported"} · inverse weight ${weightText(run.effectiveWeight)}`;
    if (run.kind === "weight") return `New fit · ${details}`;
    return `Fork${run.parent ? " of " + parentLabel(run) : " · parent not reported"} · ${details}${run.tunedWeights === null ? "" : " · " + plural(run.tunedWeights, "weight", "weights") + " changed"}`;
  }

  function scfStateText(run) {
    const st = run.input.scf.state;
    if (st === "done") return f2(run.input.scf.value);
    if (st === "running") return "Calculating…";
    if (st === "failed") return "Failed";
    return "Not calculated";
  }

  /* ------------------------------------------------------------------------
     Tooltip
     ------------------------------------------------------------------------ */
  const tip = h("div", { class: "tip an-tip", role: "tooltip", hidden: true });
  root.append(tip);
  let focusedTip = null;

  function tipRow(key, value, label) {
    return h("div", { class: "an-tip-row" }, h("span", { class: "an-key-line " + key }), h("b", { text: value }), h("span", { text: label }));
  }

  function showTip(evt, nodes) {
    tip.replaceChildren(...nodes);
    tip.hidden = false;
    focusedTip = evt?.type === "focus" ? evt.currentTarget || evt.target : null;
    positionTip(evt);
  }

  function positionTip(evt) {
    let x, y;
    if (evt && evt.clientX != null && evt.type !== "focus") {
      x = evt.clientX;
      y = evt.clientY;
    } else {
      const r = (evt.currentTarget || evt.target).getBoundingClientRect();
      x = r.left + r.width / 2;
      y = r.top + r.height / 2;
    }
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    let left = x + 16;
    let top = y + 16;
    if (left + tw > window.innerWidth - 8) left = x - tw - 16;
    if (top + th > window.innerHeight - 8) top = y - th - 16;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }

  const hideTip = () => {
    tip.hidden = true;
    focusedTip = null;
  };

  /* ------------------------------------------------------------------------
     Toasts
     ------------------------------------------------------------------------ */
  function toast(text, kind = "info") {
    actions.onNotify(text, kind);
  }

  /* ------------------------------------------------------------------------
     Toggle helpers (seg controls)
     ------------------------------------------------------------------------ */
  function setPressed(group, attr, value) {
    $$("button", group).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset[attr] === value)));
  }

  /* ------------------------------------------------------------------------
     Sidebar
     ------------------------------------------------------------------------ */
  const list = $("#anList");

  function renderSidebar() {
    const savedFocus = rememberFocus();
    const sideFoot = $("#anSideFoot");
    sideFoot.replaceChildren();
    sideFoot.hidden = true;
    $('#anLevel [data-level="jobs"] .count').textContent = DATA.jobs.length;
    setPressed($("#anLevel"), "level", state.level);
    const runsMode = state.level === "runs";
    $("#anJobCtx").hidden = !runsMode;
    $("#anKind").hidden = !runsMode;
    $("#anRunSearch").placeholder = runsMode ? "Search runs" : "Search jobs";
    $("#anRunSearch").setAttribute("aria-label", runsMode ? "Search runs" : "Search jobs");
    $("#anJobCtx strong").textContent = state.selectedJobs.size > 1 ? `${state.selectedJobs.size} jobs` : state.job;
    const q = state.runQuery.trim().toLowerCase();

    if (!runsMode) {
      const jobs = DATA.jobs.filter((j) => !q || j.id.toLowerCase().includes(q));
      list.setAttribute("aria-label", "Jobs");
      list.replaceChildren(...jobs.map((j) => {
        const selected = state.selectedJobs.has(j.id);
        return h("li", { class: "job-item an-job-item" },
          h("label", { class: "an-incl an-job-incl", title: selected ? "Included in analysis" : "Include this job" },
            h("input", { type: "checkbox", checked: selected, disabled: selected && state.selectedJobs.size <= 1, "aria-label": `Include job ${j.id}`, onchange: (event) => toggleJob(j.id, event.target.checked) }),
            h("span", { class: "an-box" }, icon("i-check"))),
          h("button", { type: "button", class: "job", "aria-pressed": String(j.id === state.job), onclick: () => focusJob(j.id) },
            h("span", { class: "job-name mono", text: j.id }),
            h("span", { class: "job-date num", text: j.updated }),
            h("span", { class: "job-sub" }, h("span", { class: "dot " + (j.completed ? "completed" : "queued"), "aria-hidden": "true" }),
              h("span", { text: `${j.runs === null ? "Loading run summary…" : plural(j.runs, "run", "runs")}${j.bestInput != null ? ` · best Input MUE ${f2(j.bestInput)}` : ""}` }))));
      }));
      restoreFocus(savedFocus);
      return;
    }

    const job = DATA.jobs.find((j) => j.id === state.job);
    $('#anLevel [data-level="runs"] .count').textContent = RUNS.length;
    if (!RUNS.length) {
      $("#anKind").hidden = true;
      list.replaceChildren(h("li", { class: "empty-list", text: emptyReason(job) }));
      return;
    }

    const kinds = { all: RUNS.length, weight: 0, fork: 0 };
    RUNS.forEach((r) => kinds[r.kind]++);
    $$("#anKind button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.kind === state.kind));
      $(".count", b).textContent = kinds[b.dataset.kind];
    });

    const visible = RUNS.filter((r) => (state.kind === "all" || r.kind === state.kind) && (!q || `${runLabel(r)} ${r.basis}`.toLowerCase().includes(q)));
    list.setAttribute("aria-label", "Runs in analysis");
    list.replaceChildren(
      ...visible.map((r) => {
        const inc = state.included.has(r.id);
        const sc = r.input.scf.state;
        return h(
          "li",
          { class: "an-run-item" + (inc ? "" : " excluded") },
          h(
            "label",
            { class: "an-incl", title: inc ? "Included in analysis" : "Excluded from analysis" },
            h("input", {
              type: "checkbox",
              checked: inc,
              disabled: inc && state.included.size <= 2,
              "aria-label": `Include ${runLabel(r)} in analysis`,
              onchange: (e) => toggleInclude(r.id, e.target.checked),
            }),
            h("span", { class: "an-box" }, icon("i-check"))
          ),
          h(
            "button",
            {
              type: "button",
              class: "job run-option",
              "data-fork": r.kind === "fork" ? "true" : null,
              "aria-pressed": String(r.id === state.focus),
              title: runLabel(r),
              "data-run-key": stableKey(r),
              "data-weight": r.effectiveWeight,
              onclick: () => setFocus(r.id, true),
            },
              h("span", { class: "job-name mono", text: displayRunName(r) }),
            h("span", { class: "job-date num", text: `w ${weightText(r.effectiveWeight)}` }),
            h(
              "span",
              { class: "job-sub" },
              h("span", { class: "dot " + (sc === "running" ? "running" : "completed"), "aria-hidden": "true" }),
              h("span", { text: `${r.basis || r.jobId} · Input ${f2(r.input.nonScf)} · SCF ${sc === "done" ? f2(r.input.scf.value) : sc === "running" ? "running" : sc === "failed" ? "failed" : "—"}` })
            )
          )
        );
      })
    );
    if (!visible.length) list.replaceChildren(h("li", { class: "empty-list", text: "No runs match." }));

    if (state.included.size < RUNS.length) {
      sideFoot.hidden = false;
      sideFoot.append(h("button", { type: "button", class: "link", onclick: () => { RUNS.forEach((r) => state.included.add(r.id)); render(); } }, "Include all"));
    }
    restoreFocus(savedFocus);
  }

  function toggleInclude(id, on) {
    if (!on && state.included.size <= 2) {
      toast("Keep at least two runs to compare");
      render();
      return;
    }
    if (on) state.included.add(id);
    else state.included.delete(id);
    if (!state.included.has(state.focus)) {
      const inc = runsIn();
      state.focus = inc[inc.length - 1].id;
    }
    render();
  }

  function focusJob(id) {
    if (!state.selectedJobs.has(id)) {
      const next = state.selectedJobs.size > 1 ? [...state.selectedJobs, id] : [id];
      actions.onJobsChange(next, id);
    }
    state.job = id;
    state.level = "runs";
    const run = runsIn().find((item) => item.jobId === id);
    if (run) state.focus = run.id;
    renderSidebar();
    renderHeader();
    if (run) renderPanel();
  }

  function toggleJob(id, on) {
    const next = new Set(state.selectedJobs);
    if (on) next.add(id);
    else if (next.size > 1) next.delete(id);
    else return;
    state.selectedJobs = next;
    actions.onJobsChange([...next], next.has(state.job) ? state.job : [...next][0]);
    renderSidebar();
  }

  function setFocus(id, include) {
    if (include && !state.included.has(id)) state.included.add(id);
    if (!state.included.has(id)) return;
    state.focus = id;
    state.job = BY_ID[id].jobId;
    render();
  }

  /* ------------------------------------------------------------------------
     Header
     ------------------------------------------------------------------------ */
  function renderHeader() {
    const density = densityChainModel();
    const densityActive = Boolean(density && state.tab === "density");
    root.classList.toggle("an-density-mode", densityActive);
    $("#anJobTitle").textContent = densityActive ? `${density.base.short} density rounds` : state.selectedJobs.size > 1 ? `${state.selectedJobs.size} jobs` : state.job;
    $("#anActions a").href = workspaceUrl(focusRun());
    $("#anExport").disabled = !canCompare();
    $(".d-tabs", root).hidden = !canCompare();
    const densityTab = $("#anTab-density");
    if (densityTab) densityTab.hidden = !density;
    const bases = [...new Set(RUNS.map((run) => run.basis).filter(Boolean))];
    const meta = $("#anMeta");
    meta.replaceChildren(
      ...(densityActive ? [h("span", { text: `${density.runs.length} rounds · ${density.base.inputSet}` })] : []),
      h("span", null, icon("i-atom"), h("strong", { text: bases.length === 1 ? bases[0] : bases.length ? "Mixed basis sets" : JOB.basis }), JOB.grid === null ? "" : " · grid level " + JOB.grid),
      h("span", null, icon("i-info"), densityActive ? `inverse weight ${weightText(density.base.effectiveWeight)} · x-axis R0–R${density.runs.length - 1}` : "kcal/mol")
    );

    const missing = runsIn().filter((r) => r.canScf && (
      ["none", "failed"].includes(r.input.scf.state) ||
      (r.input.scf.state === "done" && ["none", "partial"].includes(r.overlap?.state))
    ));
    const overlapRunning = runsIn().filter((r) => r.overlap?.state === "running").length;
    const running = runsIn().filter((r) => r.input.scf.state === "running").length;
    const btn = $("#anCalcScf");
    btn.disabled = submitting || missing.length === 0;
    btn.lastChild.textContent = submitting ? "Submitting…" : missing.length ? (missing.every((r) => r.input.scf.state === "done") ? `Calculate overlap (${missing.length})` : `Calculate SCF Input (${missing.length})`) : overlapRunning ? `Overlap running (${overlapRunning})` : running ? `SCF Input running (${running})` : runsIn().every((r) => scf(r) !== null) && RUNS.length ? "SCF Input up to date" : "SCF Input unavailable";
    btn.onclick = () => queueScf(missing);
  }

  async function queueScf(runs) {
    const eligible = runs.filter((r) => r.canScf && (
      ["none", "failed"].includes(r.input.scf.state) ||
      (r.input.scf.state === "done" && ["none", "partial"].includes(r.overlap?.state))
    ));
    if (submitting || !eligible.length) return;
    submitting = true; renderHeader();
    try {
      const result = await actions.queueScf(eligible.map((run) => ({ jobId: run.jobId, runId: run.runId || run.id.split("::").pop(), overlapOnly: run.input.scf.state === "done" })));
      if (disposed) return;
      const overlapAccepted = new Set(result.overlapOnly || []);
      result.accepted.forEach((key) => {
        const run = RUNS.find((item) => stableKey(item) === key);
        if (!run) return;
        if (overlapAccepted.has(key)) run.overlap = { ...run.overlap, state: "running" };
        else run.input.scf = { state: "running", value: null };
      });
      if (result.accepted.length) toast(`SCF Input queued for ${plural(result.accepted.length, "run", "runs")}.`, "good");
      if (result.errors.length) toast(result.errors.join("\n"), "bad");
      if (result.accepted.length) actions.onRefresh();
    } catch (error) { if (!disposed) toast(error.message || "SCF submission failed.", "bad"); }
    finally { submitting = false; if (!disposed) render(); }
  }

  /* ------------------------------------------------------------------------
     Card scaffold with a table-view twin
     ------------------------------------------------------------------------ */
  function card({ id, title, sub, legend, caption, draw, table, extraClass, tools: extraTools, below }) {
    const showTable = state.tables.has(id);
    const body = h("div", { class: "an-card-body" });
    const tools = h(
      "div",
      { class: "an-card-tools" },
      legend ? h("div", { class: "an-legend" }, legend) : null,
      extraTools || null,
      exportButton(id, title),
      h(
        "button",
        {
          type: "button",
          class: "link",
          "aria-pressed": String(showTable),
          onclick: () => {
            if (state.tables.has(id)) state.tables.delete(id);
            else state.tables.add(id);
            renderPanel();
          },
        },
        icon(showTable ? "i-chart" : "i-table"),
        showTable ? "Chart" : "Table"
      )
    );
    const fig = h(
      "figure",
      { class: "an-card " + (extraClass || ""), "aria-label": title },
      h("div", { class: "an-card-head" }, h("div", { class: "an-card-title" }, h("h3", { text: title }), sub ? h("p", { text: sub }) : null), tools),
      below || null,
      body,
      caption && !showTable ? h("figcaption", { class: "an-caption", text: caption }) : null
    );
    if (showTable) {
      body.append(table());
    } else {
      const viz = h("div", { class: "an-viz", "data-chart": id });
      body.append(viz);
      charts.push({ el: viz, draw });
    }
    return fig;
  }

  function simpleTable(head, rows) {
    return h(
      "div",
      { class: "an-table-wrap" },
      h(
        "table",
        null,
        h("thead", null, h("tr", null, head.map((c, i) => h("th", { class: i ? "r" : null, text: c })))),
        h("tbody", null, rows.map((r) => h("tr", null, r.map((c, i) => h("td", { class: i ? "r" : "mono", text: c })))))
      )
    );
  }

  const legendItem = (cls, kind, text) => h("span", null, h("span", { class: `an-key-${kind} ${cls}` }), text);

  function exportButton(id, title) {
    return h(
      "button",
      { type: "button", class: "link", "aria-haspopup": "dialog", title: "Export as SVG or PNG", onclick: () => openExport(id, title) },
      icon("i-image"),
      "Export"
    );
  }

  /* ------------------------------------------------------------------------
     Panel / tabs
     ------------------------------------------------------------------------ */
  const panel = $("#anPanel");
  let charts = [];

  function renderPanel() {
    const savedFocus = rememberFocus();
    charts = [];
    statCache.clear();
    originalMean = average(sharedReferences(JOB, [...state.included], "original").map((dataset) => dataset.original));
    hideTip();
    syncUrl();
    $$('[role="tab"]', root).forEach((t) => {
      const on = t.dataset.tab === state.tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    });
    panel.setAttribute("aria-labelledby", "anTab-" + state.tab);
    const density = densityChainModel();
    if (!density && state.tab === "density") state.tab = "trends";
    if (density && state.tab === "density") {
      panel.setAttribute("aria-label", "Density chain analysis");
      panel.replaceChildren(renderDensityChain(density));
      drawCharts();
      restoreFocus(savedFocus);
      return;
    }
    panel.removeAttribute("aria-label");

    if (!canCompare()) {
      panel.replaceChildren(
        h(
          "div",
          { class: "empty" },
          h("div", { class: "big" }, icon("i-chart")),
          h("h3", { text: "Nothing to compare yet" }),
          h("p", { text: `${emptyReason({ completed: RUNS.length })} Tune weights or resubmit in Workspace to create more runs.` }),
          h("div", { class: "row" }, h("a", { class: "btn btn-secondary", href: workspaceUrl(focusRun()) }, "Open in Workspace"))
        )
      );
      return;
    }

    const views = { trends: viewTrends, scf: viewScf, overlap: viewOverlap, changes: viewChanges };
    panel.replaceChildren(...(JOB.warnings.length ? [h("div", { class: "an-data-note", role: "status" }, JOB.warnings.map((message) => h("p", { text: message })))] : []), ...views[state.tab]());
    drawCharts();
    restoreFocus(savedFocus);
  }

  function drawCharts() {
    for (const c of charts) {
      c.el.replaceChildren();
      c.draw(c.el);
    }
  }

  function densityCard(title, sub, badge, draw, extraClass = "") {
    const body = h("div", { class: "density-card-body" });
    const viz = h("div", { class: "density-viz", "data-chart": `density-${title.toLowerCase().replace(/[^a-z]+/g, "-")}` });
    body.append(viz);
    charts.push({ el: viz, draw });
    return h("article", { class: `density-card ${extraClass}` },
      h("div", { class: "density-card-head" }, h("h3", { text: title }), badge ? h("span", { class: "density-badge", text: badge }) : null),
      sub ? h("p", { class: "density-card-sub", text: sub }) : null,
      body
    );
  }

  function densityLineChart(el, { rounds, series, threshold = null, thresholdLabel = "" }) {
    const W = Math.max(260, el.clientWidth);
    const H = 190;
    const m = { l: 38, r: 12, t: 12, b: 30 };
    const values = series.flatMap((item) => item.values).filter(isValue).concat(threshold == null ? [] : [threshold]);
    if (!values.length) { el.append(h("p", { class: "an-empty-note", text: "No round values are available." })); return; }
    const lo = Math.min(...values), hi = Math.max(...values);
    const dom = niceDomain(Math.max(0, lo - (hi - lo || 1) * 0.12), hi + (hi - lo || 1) * 0.12, 4);
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const x = (index) => m.l + (rounds.length === 1 ? iw / 2 : iw * index / (rounds.length - 1));
    const y = (value) => m.t + ih * (1 - (value - dom.lo) / (dom.hi - dom.lo || 1));
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": `${series.map((item) => item.label).join(" and ")} by round` }, el);
    dom.ticks.forEach((tick, index) => {
      s("line", { class: index ? "v-grid" : "v-axis", x1: m.l, x2: W - m.r, y1: y(tick), y2: y(tick) }, svg);
      s("text", { class: "v-tick", x: m.l - 6, y: y(tick) + 4, "text-anchor": "end", text: tickText(tick, dom.step) }, svg);
    });
    if (threshold != null) {
      s("line", { class: "density-threshold", x1: m.l, x2: W - m.r, y1: y(threshold), y2: y(threshold) }, svg);
      s("text", { class: "density-threshold-label", x: W - m.r, y: y(threshold) - 5, "text-anchor": "end", text: thresholdLabel }, svg);
    }
    series.forEach((item, seriesIndex) => {
      const points = item.values.map((value, index) => isValue(value) ? `${x(index)},${y(value)}` : null).filter(Boolean).join(" ");
      if (points) s("polyline", { class: `density-line density-line-${seriesIndex + 1}`, points }, svg);
      item.values.forEach((value, index) => {
        if (!isValue(value)) return;
        s("circle", { class: `density-dot density-dot-${seriesIndex + 1}`, cx: x(index), cy: y(value), r: 3.5 }, svg);
      });
    });
    rounds.forEach((round, index) => s("text", { class: "v-tick mono", x: x(index), y: H - 8, "text-anchor": "middle", text: round.roundLabel }, svg));
  }

  function densityScatterChart(el, chain) {
    const W = Math.max(420, el.clientWidth), H = 300;
    const m = { l: 54, r: 18, t: 16, b: 48 };
    const points = chain.allRuns.map((run) => ({ run, x: run.input.nonScf, y: scf(run) })).filter((point) => isValue(point.x) && isValue(point.y));
    if (!points.length) { el.append(h("p", { class: "an-empty-note", text: "SCF Input MUE and reference means are needed for this comparison." })); return; }
    const xs = points.map((point) => point.x), ys = points.map((point) => point.y);
    const xd = niceDomain(Math.max(0, Math.min(...xs) * 0.88), Math.max(...xs) * 1.08, 5);
    const yd = niceDomain(Math.max(0, Math.min(...ys) * 0.88), Math.max(...ys) * 1.08, 5);
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const X = (value) => m.l + iw * (value - xd.lo) / (xd.hi - xd.lo || 1);
    const Y = (value) => m.t + ih * (1 - (value - yd.lo) / (yd.hi - yd.lo || 1));
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "Fit versus transferability scatter" }, el);
    xd.ticks.forEach((tick, index) => {
      s("line", { class: index ? "v-grid" : "v-axis", x1: X(tick), x2: X(tick), y1: m.t, y2: m.t + ih }, svg);
      s("text", { class: "v-tick", x: X(tick), y: H - m.b + 16, "text-anchor": "middle", text: tickText(tick, xd.step) }, svg);
    });
    yd.ticks.forEach((tick, index) => {
      s("line", { class: index ? "v-grid" : "v-axis", x1: m.l, x2: W - m.r, y1: Y(tick), y2: Y(tick) }, svg);
      s("text", { class: "v-tick", x: m.l - 6, y: Y(tick) + 4, "text-anchor": "end", text: tickText(tick, yd.step) }, svg);
    });
    const chainIds = new Set(chain.runs.map((run) => run.id));
    const chainPoints = points.filter((point) => chainIds.has(point.run.id));
    const ordered = chainPoints.map((point) => `${X(point.x)},${Y(point.y)}`).join(" ");
    if (ordered) s("polyline", { class: "density-scatter-chain", points: ordered }, svg);
    points.forEach((point) => {
      const inChain = chainIds.has(point.run.id);
      s("circle", { class: inChain ? "density-scatter-dot chain" : "density-scatter-dot scan", cx: X(point.x), cy: Y(point.y), r: inChain ? 5 : 4 }, svg);
      s("text", { class: "density-scatter-label", x: X(point.x) + (inChain ? 8 : 6), y: Y(point.y) - 6, text: inChain ? (point.run.roundLabel || displayRunName(point.run)) : displayRunName(point.run) }, svg);
    });
    s("text", { class: "density-axis-title", x: m.l + iw / 2, y: H - 6, "text-anchor": "middle", text: "Input MUE · non-SCF (kcal/mol)" }, svg);
    s("text", { class: "density-axis-title", x: 12, y: m.t + ih / 2, "text-anchor": "middle", transform: `rotate(-90 12 ${m.t + ih / 2})`, text: "Input MUE · SCF (kcal/mol)" }, svg);
  }

  function densityReactionChart(el, values) {
    const W = Math.max(170, el.clientWidth), H = 28;
    const m = { l: 4, r: 4 };
    const x = (value) => m.l + (Math.max(-4, Math.min(4, value)) + 4) / 8 * (W - m.l - m.r);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": `SCF error by round: ${values.map((value, index) => `R${index} ${signed(value)}`).join(", ")}` }, el);
    s("line", { class: "density-reaction-axis", x1: x(-4), x2: x(4), y1: 14, y2: 14 }, svg);
    s("line", { class: "density-reaction-zero", x1: x(0), x2: x(0), y1: 4, y2: 24 }, svg);
    const points = values.map((value) => isValue(value) ? `${x(value)},14` : null).filter(Boolean).join(" ");
    if (points) s("polyline", { class: "density-reaction-line", points }, svg);
    values.forEach((value, index) => { if (isValue(value)) s("circle", { class: `density-reaction-dot r${index}`, cx: x(value), cy: 14, r: index === values.length - 1 ? 3.5 : 3 }, svg); });
  }

  function densitySparkline(el, values) {
    const W = 78, H = 28;
    const finiteValues = values.filter(isValue);
    if (!finiteValues.length) return;
    const lo = Math.min(...finiteValues), hi = Math.max(...finiteValues);
    const x = (index) => values.length === 1 ? W / 2 : index / (values.length - 1) * (W - 4) + 2;
    const y = (value) => 4 + (H - 8) * (1 - (value - lo) / (hi - lo || 1));
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": `MUE by round: ${values.map((value) => isValue(value) ? f2(value) : "—").join(", ")}` }, el);
    s("polyline", { class: "density-sparkline", points: values.map((value, index) => isValue(value) ? `${x(index)},${y(value)}` : null).filter(Boolean).join(" ") }, svg);
    values.forEach((value, index) => { if (isValue(value)) s("circle", { class: "density-spark-dot", cx: x(index), cy: y(value), r: index === values.length - 1 ? 2.5 : 1.8 }, svg); });
  }

  const densityXml = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&apos;" }[char]));

  function densityNatureSvg(chain, widthMm = 180) {
    const W = 960, H = 620;
    const heightMm = widthMm * H / W;
    const rounds = chain.rounds;
    const gapValues = rounds.map((run) => scf(run) != null && run.input.nonScf != null ? Math.abs(scf(run) - run.input.nonScf) : null);
    const parameterValues = rounds.map((run) => run.density.parameterChange);
    const referenceValues = rounds.map((run) => densityReferenceMean(run));
    const charts = [
      { title: "Data-set MUE", unit: "kcal/mol", series: [{ label: "Non-SCF", values: rounds.map((run) => run.input.nonScf), color: "#246fbd" }, { label: "SCF", values: rounds.map((run) => scf(run)), color: "#b64e36" }] },
      { title: "SCF − non-SCF gap", unit: "kcal/mol", series: [{ label: "Gap", values: gapValues, color: "#246fbd" }], threshold: DENSITY_THRESHOLDS.gapKcalMol, thresholdLabel: "threshold" },
      { title: "Parameter change", unit: "%", series: [{ label: "Relative L2", values: parameterValues, color: "#246fbd" }], threshold: DENSITY_THRESHOLDS.parameterPercent, thresholdLabel: "threshold" },
      { title: "Reference mean", unit: "kcal/mol", series: [{ label: "Reference", values: referenceValues, color: "#246fbd" }], threshold: average(DATASETS.map((dataset) => dataset.original).filter(isValue)), thresholdLabel: "CF22D" },
    ];
    const chartSvg = (chart, x0, y0, width, height) => {
      const left = 48, right = 14, top = 34, bottom = 34;
      const all = chart.series.flatMap((item) => item.values).filter(isValue).concat(chart.threshold == null ? [] : [chart.threshold]);
      if (!all.length) return `<text x="${x0 + 12}" y="${y0 + 20}" fill="#666" font-size="12">No values</text>`;
      const hi = Math.max(...all), lo = Math.min(...all), span = hi - lo || 1;
      const domain = niceDomain(Math.max(0, lo - span * .12), hi + span * .12, 4);
      const px = (index) => x0 + left + (rounds.length === 1 ? (width - left - right) / 2 : (width - left - right) * index / (rounds.length - 1));
      const py = (value) => y0 + top + (height - top - bottom) * (1 - (value - domain.lo) / (domain.hi - domain.lo || 1));
      let out = `<g><text x="${x0 + 8}" y="${y0 + 17}" font-size="14" font-weight="700">${densityXml(chart.title)} (${densityXml(chart.unit)})</text>`;
      domain.ticks.forEach((tick, index) => {
        const yy = py(tick);
        out += `<line x1="${x0 + left}" y1="${yy}" x2="${x0 + width - right}" y2="${yy}" stroke="${index ? "#d9d9d9" : "#666"}" stroke-width="${index ? 0.6 : 0.8}"/>`;
        out += `<text x="${x0 + left - 7}" y="${yy + 4}" text-anchor="end" font-size="10" fill="#444">${densityXml(tickText(tick, domain.step))}</text>`;
      });
      if (chart.threshold != null) {
        const yy = py(chart.threshold);
        out += `<line x1="${x0 + left}" y1="${yy}" x2="${x0 + width - right}" y2="${yy}" stroke="#777" stroke-width="0.8" stroke-dasharray="4 3"/>`;
        out += `<text x="${x0 + width - right}" y="${yy - 5}" text-anchor="end" font-size="10" fill="#555">${densityXml(chart.thresholdLabel)}</text>`;
      }
      chart.series.forEach((item) => {
        const points = item.values.map((value, index) => isValue(value) ? `${px(index)},${py(value)}` : null).filter(Boolean).join(" ");
        if (!points) return;
        out += `<polyline points="${points}" fill="none" stroke="${item.color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
        item.values.forEach((value, index) => { if (isValue(value)) out += `<circle cx="${px(index)}" cy="${py(value)}" r="3" fill="${item.color}"/>`; });
      });
      rounds.forEach((round, index) => { out += `<text x="${px(index)}" y="${y0 + height - 10}" text-anchor="middle" font-size="10" font-family="Arial, sans-serif" fill="#444">${densityXml(round.roundLabel)}</text>`; });
      return out + "</g>";
    };
    const cells = [[24, 30], [492, 30], [24, 325], [492, 325]];
    let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${widthMm}mm" height="${heightMm}mm" viewBox="0 0 ${W} ${H}" font-family="Arial, Helvetica, sans-serif"><rect width="${W}" height="${H}" fill="#ffffff"/><text x="24" y="20" font-size="16" font-weight="700">Convergence by round</text>`;
    charts.forEach((chart, index) => { svg += chartSvg(chart, cells[index][0], cells[index][1], 444, 270); });
    return { svg: svg + "</svg>", wPt: widthMm * PT_MM, hPt: heightMm * PT_MM };
  }

  function densityExportButtons() {
    return h("button", { type: "button", class: "link", title: "Export as SVG or PNG", onclick: () => openExport("density", "Convergence by round") }, icon("i-image"), "Export");
  }

  function densityVerdict(cls, tag, title, body) {
    return h("div", { class: `density-verdict ${cls}` }, h("span", { class: "density-verdict-tag", text: tag }), h("h4", { text: title }), h("p", { text: body }));
  }

  function renderDensityChain(chain) {
    const rounds = chain.rounds;
    const latest = rounds.at(-1);
    const previous = rounds.at(-2);
    const gaps = rounds.map((round) => {
      const value = scf(round) != null && round.input.nonScf != null ? scf(round) - round.input.nonScf : null;
      return value;
    });
    const latestGap = gaps.at(-1);
    const parameterValues = rounds.map((round) => round.density.parameterChange);
    const latestParameter = parameterValues.at(-1);
    const referenceValues = rounds.map((round) => densityReferenceMean(round));
    const gapConverged = isValue(latestGap) && Math.abs(latestGap) <= DENSITY_THRESHOLDS.gapKcalMol;
    const parameterConverged = isValue(latestParameter) && latestParameter <= DENSITY_THRESHOLDS.parameterPercent;
    const reactionRows = densityReactionRows(chain);
    const referenceRows = densityReferenceRows(chain);
    const worsening = referenceRows.filter((row) => row.values.slice(1).filter((value, index) => isValue(value) && isValue(row.values[index])).every((value, index) => value > row.values[index] + EPS));
    const originalBetter = referenceRows.filter((row) => row.vsOriginal !== null && row.vsOriginal < -EPS).length;
    const originalUnchanged = referenceRows.filter((row) => row.vsOriginal !== null && Math.abs(row.vsOriginal) <= EPS).length;
    const originalWorse = referenceRows.filter((row) => row.vsOriginal !== null && row.vsOriginal > EPS).length;
    const previousBetter = referenceRows.filter((row) => row.change !== null && row.change < -EPS).length;
    const previousUnchanged = referenceRows.filter((row) => row.change !== null && Math.abs(row.change) <= EPS).length;
    const previousWorse = referenceRows.filter((row) => row.change !== null && row.change > EPS).length;
    const movers = [...referenceRows].sort((a, b) => Math.abs(b.change ?? 0) - Math.abs(a.change ?? 0));
    const gapBody = isValue(latestGap) ? `SCF − non-SCF gap is ${f2(Math.abs(latestGap))} kcal/mol${isValue(gaps[0]) ? ` for the latest round, from ${f2(Math.abs(gaps[0]))} at R0.` : "."}` : "SCF data-set results are not available for the latest round.";
    const parameterBody = isValue(latestParameter) ? `Fitted parameters changed ${f2(latestParameter)}% from the previous round. ${parameterConverged ? "The change is within the configured threshold." : "Another round may still shift them."}` : "Parameter snapshots are not available for the latest round.";
    const transferBody = worsening.length ? `${worsening.slice(0, 2).map((row) => row.dataset.name).join(" and ")} got worse in every round; ${worsening.length} reference sets drifted up throughout the chain.` : "No reference set became worse in every round.";
    const statusHead = h("div", { class: "density-section-head" },
      h("div", null, h("h3", { text: `Where ${latest.roundLabel} stands` }), h("p", { text: `Thresholds: gap ≤ ${DENSITY_THRESHOLDS.gapKcalMol.toFixed(2)} kcal/mol · parameter change ≤ ${DENSITY_THRESHOLDS.parameterPercent}%` }))
    );
    const statusVerdicts = h("div", { class: "density-verdict-grid" },
      densityVerdict(gapConverged ? "ok" : "warn", gapConverged ? "Converged" : "Still moving", "Self-consistency", gapBody),
      densityVerdict(parameterConverged ? "ok" : "warn", parameterConverged ? "Converged" : "Still moving", "Parameters", parameterBody),
      densityVerdict(worsening.length ? "bad" : "ok", worsening.length ? "Watch" : "Stable", "Transferability", transferBody)
    );
    const status = h("section", { class: "density-state-panel" }, statusHead, statusVerdicts);
    const kpiData = [
      ["SCF data-set MUE", scf(latest), "kcal/mol", isValue(scf(latest)) && isValue(scf(rounds[0])) ? `${signed(scf(latest) - scf(rounds[0]))} since R0` : "Latest round"],
      ["SCF − non-SCF gap", isValue(latestGap) ? Math.abs(latestGap) : null, "kcal/mol", gapConverged ? "Converged" : `Threshold ${DENSITY_THRESHOLDS.gapKcalMol.toFixed(2)}`],
      ["Parameter change", latestParameter, "%", parameterConverged ? "Within threshold" : `Threshold ${DENSITY_THRESHOLDS.parameterPercent}%`],
      ["Reference mean", referenceValues.at(-1), "kcal/mol", isValue(referenceValues.at(-1)) && isValue(referenceValues[0]) ? `${signed(referenceValues.at(-1) - referenceValues[0])} since R0` : "Latest round"],
    ];
    const kpis = h("div", { class: "density-kpis" }, kpiData.map(([label, value, unit, note]) => h("div", { class: "density-kpi" }, h("span", { class: "density-kpi-label", text: label }), h("strong", { text: f2(value) }), h("small", { text: unit }), h("p", { text: note }))));
    const chartSection = h("section", { class: "density-section" },
      h("div", { class: "density-section-head" }, h("div", null, h("h3", { text: "Convergence by round" }), h("p", { text: "Each round refits on the previous round's SCF densities with the same weights." })), h("div", { class: "density-head-tools" }, h("div", { class: "density-legend" }, h("span", null, h("i", { class: "density-legend-line nonscf" }), "Non-SCF / single series"), h("span", null, h("i", { class: "density-legend-line scf" }), "SCF"), h("span", null, h("i", { class: "density-legend-line threshold" }), "Threshold or CF22D")), densityExportButtons())),
      h("div", { class: "density-chart-grid" },
        densityCard("Data-set MUE (kcal/mol)", "SCF 1.68 → 0.57", `${f2(scf(rounds[0]))} → ${f2(scf(latest))}`, (el) => densityLineChart(el, { rounds, series: [{ label: "Non-SCF", values: rounds.map((round) => round.input.nonScf) }, { label: "SCF", values: rounds.map((round) => scf(round)) }] })),
        densityCard("SCF − non-SCF gap", "Absolute gap by round", `${isValue(latestGap) ? f2(Math.abs(latestGap)) : "—"} · ${gapConverged ? "converged" : "still moving"}`, (el) => densityLineChart(el, { rounds, series: [{ label: "Gap", values: gaps.map((value) => isValue(value) ? Math.abs(value) : null) }], threshold: DENSITY_THRESHOLDS.gapKcalMol, thresholdLabel: `≤ ${DENSITY_THRESHOLDS.gapKcalMol}` })),
        densityCard("Parameter change vs previous round", "Relative L2 change from each round's initial snapshot", `${isValue(latestParameter) ? f2(latestParameter) + "%" : "—"} · ${parameterConverged ? "converged" : "still moving"}`, (el) => densityLineChart(el, { rounds, series: [{ label: "Parameter change", values: parameterValues }], threshold: DENSITY_THRESHOLDS.parameterPercent, thresholdLabel: `≤ ${DENSITY_THRESHOLDS.parameterPercent}%` })),
        densityCard("Reference mean (kcal/mol)", "Shared built-in datasets against native CF22D", `${isValue(referenceValues.at(-1)) && isValue(referenceValues[0]) ? signed(referenceValues.at(-1) - referenceValues[0]) + " since R0" : "—"}`, (el) => densityLineChart(el, { rounds, series: [{ label: "Reference mean", values: referenceValues }], threshold: average(DATASETS.map((dataset) => dataset.original).filter(isValue)), thresholdLabel: "CF22D" }))
      )
    );
    const scatterSection = h("section", { class: "density-section density-wide" }, h("div", { class: "density-section-head" }, h("div", null, h("h3", { text: "Fit versus self-consistency" }), h("p", { text: "Lower-left is better. Compare non-SCF Input MUE on x with SCF Input MUE on y." })), h("span", { class: "density-subtle", text: "Weight scans provide context; density rounds are highlighted in blue." })), h("div", { class: "density-scatter-viz" }));
    charts.push({ el: scatterSection.querySelector(".density-scatter-viz"), draw: (el) => densityScatterChart(el, chain) });
    const reactionHead = h("div", { class: "density-section-head" },
      h("div", null, h("h3", { text: "Training reactions" }), h("p", { text: "SCF error (calculated − reference) per round. Dots darken from R0 to the latest round." })),
      h("div", { class: "density-round-key" }, rounds.map((round, index) => h("span", null, h("i", { class: `r${index}` }), round.roundLabel)))
    );
    const reactionHeadRow = h("div", { class: "density-reaction-head" },
      h("span", { text: "Reaction" }), h("span", { text: "Reference" }), h("span", { text: "−4          0          +4" }), h("span", { text: `${latest.roundLabel} error` }), h("span", { text: previous ? `${previous.roundLabel} → ${latest.roundLabel}` : "Change" })
    );
    const reactionRowsDom = reactionRows.map((row) => h("div", { class: "density-reaction-row" },
      h("div", null, h("strong", { text: row.name }), h("small", { text: row.state })),
      h("span", { class: "mono", text: f2(row.reference) }), h("div", { class: "density-reaction-viz" }),
      h("span", { class: "mono", text: signed(row.last) }),
      h("span", { class: row.change != null && row.change > EPS ? "density-bad" : "density-good", text: row.change == null ? "—" : `|e| ${row.change >= 0 ? "+" : "−"}${Math.abs(row.change).toFixed(2)}` })
    ));
    const reactionSection = h("section", { class: "density-section density-wide" }, reactionHead, h("div", { class: "density-reaction-table" }, reactionHeadRow, reactionRowsDom));
    reactionRows.forEach((row, index) => { const el = reactionSection.querySelectorAll(".density-reaction-viz")[index]; charts.push({ el, draw: (target) => densityReactionChart(target, row.values) }); });
    const filteredMovers = movers.filter((row) => !state.densityQuery || row.dataset.name.toLowerCase().includes(state.densityQuery.toLowerCase()) || row.dataset.type.toLowerCase().includes(state.densityQuery.toLowerCase())).slice(0, state.densityQuery ? movers.length : 8);
    const refHead = h("div", { class: "density-section-head" },
      h("div", null, h("h3", { text: "Reference datasets" }), h("p", { text: `${referenceRows.length} built-in sets. Largest movers between the last two rounds first.` })),
      h("div", { class: "density-ref-actions" },
        h("input", { type: "search", value: state.densityQuery, placeholder: "Search datasets", "aria-label": "Search density reference datasets", oninput: (event) => { state.densityQuery = event.target.value; renderPanel(); } }),
        h("button", { type: "button", class: "btn btn-secondary btn-sm", text: `Show all ${referenceRows.length}`, onclick: () => { state.densityQuery = ""; renderPanel(); } })
      )
    );
    const refBars = h("div", { class: "density-bars" },
      densityBar("R3 vs CF22D original", originalBetter, originalUnchanged, originalWorse, "better", "unchanged", "worse"),
      densityBar(`${latest.roundLabel} vs ${previous?.roundLabel || "previous"}`, previousBetter, previousUnchanged, previousWorse, "better", "unchanged", "worse")
    );
    const refHeadRow = h("div", { class: "density-ref-head" }, ["Dataset", "CF22D", "R0 → Rn", latest.roundLabel, previous ? `${previous.roundLabel} → ${latest.roundLabel}` : "Change", "vs CF22D", "Pattern"].map((text) => h("span", { text })));
    const refRowsDom = filteredMovers.map((row) => h("div", { class: "density-ref-row" },
      h("div", null, h("strong", { text: row.dataset.name }), h("small", { text: row.dataset.type })), h("span", { class: "mono", text: f2(row.dataset.original) }), h("div", { class: "density-spark" }), h("span", { class: "mono", text: f2(row.last) }),
      h("span", { class: row.change != null && row.change > EPS ? "density-bad" : "density-good", text: row.change == null ? "—" : signed(row.change) }),
      h("span", { class: row.vsOriginal != null && row.vsOriginal > EPS ? "density-bad" : "density-good", text: row.vsOriginal == null ? "—" : signed(row.vsOriginal) }),
      h("span", { class: `density-pattern ${row.pattern.toLowerCase().replace(/\s+/g, "-")}`, text: row.pattern })
    ));
    const refTable = h("div", { class: "density-ref-table" }, refHeadRow, refRowsDom);
    const refSection = h("section", { class: "density-section density-wide" }, refHead, refBars, refTable);
    filteredMovers.forEach((row, index) => { const el = refSection.querySelectorAll(".density-spark")[index]; charts.push({ el, draw: (target) => densitySparkline(target, row.values) }); });
    return h("div", { class: "density-chain-view" }, status, kpis, chartSection, scatterSection, reactionSection, refSection, h("p", { class: "density-footnote", text: `All values in kcal/mol. Gap convergence uses ≤ ${DENSITY_THRESHOLDS.gapKcalMol.toFixed(2)} kcal/mol; parameter convergence uses ≤ ${DENSITY_THRESHOLDS.parameterPercent}%. “Unchanged” means within ${EPS.toFixed(2)} kcal/mol.` }));
  }

  function densityBar(title, good, unchanged, bad, goodLabel, unchangedLabel, badLabel) {
    const total = Math.max(1, good + unchanged + bad);
    const segment = (value, cls) => h("span", { class: `density-bar-segment ${cls}`, style: `width:${value / total * 100}%` });
    return h("div", { class: "density-bar-card", role: "img", "aria-label": `${title}: ${good} better, ${unchanged} unchanged, ${bad} worse` }, h("strong", { text: title }), h("div", { class: "density-bar" }, segment(good, "better"), segment(unchanged, "unchanged"), segment(bad, "worse")), h("div", { class: "density-bar-labels" }, h("span", { text: `${good} ${goodLabel}` }), h("span", { text: `${unchanged} ${unchangedLabel}` }), h("span", { text: `${bad} ${badLabel}` })));
  }

  /* ------------------------------------------------------------------------
     Trends
     ------------------------------------------------------------------------ */
  function kpiDelta(value, base, baseLabel, lowerIsGood = true) {
    if (value == null || base == null) return h("div", { class: "an-kpi-delta", text: `No ${baseLabel} value to compare` });
    const d = value - base;
    if (Math.abs(d) < EPS) return h("div", { class: "an-kpi-delta" }, "Same as ", baseLabel);
    const better = lowerIsGood ? d < 0 : d > 0;
    const pct = base ? Math.round((Math.abs(d) / base) * 100) : null;
    return h(
      "div",
      { class: "an-kpi-delta " + (better ? "good" : "bad") },
      icon(d < 0 ? "i-arrow-down" : "i-arrow-up"),
      `${Math.abs(d).toFixed(2)} ${d < 0 ? "lower" : "higher"} than ${baseLabel}` + (pct != null && pct > 0 ? ` (${pct}%)` : "")
    );
  }

  function viewTrends() {
    const f = focusRun();
    const st = stats(f);
    const bName = baseName(f);
    const sc = f.input.scf.state;

    const scfTile =
      sc === "done"
        ? [h("div", { class: "an-kpi-value" }, f2(scf(f)), h("small", { text: "kcal/mol" })), kpiDelta(scf(f), scfBase(f), "CF22D (stored density)")]
        : sc === "running"
          ? [h("div", { class: "an-kpi-value an-kpi-state an-running" }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", { text: "Calculating" })), h("div", { class: "an-kpi-delta", text: "Single-point energies in progress" })]
          : [
              h("div", { class: "an-kpi-value an-kpi-state", text: sc === "failed" ? "Failed" : "Not calculated" }),
              h("div", { class: "an-kpi-delta" }, h("button", { type: "button", class: "link", disabled: !f.canScf || submitting, title: f.scfReason, onclick: () => queueScf([f]) }, sc === "failed" ? "Retry SCF Input" : "Calculate SCF Input")),
              sc === "failed" ? h("a", { class: "link", href: workspaceUrl(f, "energies") }, "View SCF log") : null,
            ];

    const testTile = f.test ? [
      h("div", { class: "an-kpi-value" }, f2(f.test.nonScf), h("small", { text: "kcal/mol" })),
      h("div", { class: "an-kpi-delta" }, f.test.original == null ? "Original test MUE unavailable" : `CF22D ${f2(f.test.original)}`),
    ] : null;

    const kpis = h(
      "div",
      { class: "an-kpis", role: "group", "aria-label": `Summary for ${displayRunName(f)}` },
      h("div", { class: "an-kpi" }, h("div", { class: "an-kpi-label", text: "Input MUE · non-SCF" }), h("div", { class: "an-kpi-value" }, f2(f.input.nonScf), h("small", { text: "kcal/mol" })), kpiDelta(f.input.nonScf, inputBase(f), bName)),
      h("div", { class: "an-kpi" }, h("div", { class: "an-kpi-label", text: "Input MUE · SCF" }), scfTile),
      f.test ? h("div", { class: "an-kpi" }, h("div", { class: "an-kpi-label", text: "Test set MUE · non-SCF" }), testTile) : null,
      h(
        "div",
        { class: "an-kpi" },
        h("div", { class: "an-kpi-label", text: `Reference MUE · mean of ${st.meanN}` }),
        h("div", { class: "an-kpi-value" }, f2(st.mean), h("small", { text: "kcal/mol" })),
        kpiDelta(st.mean, st.meanBase, bName)
      ),
      h(
        "div",
        { class: "an-kpi" },
        h("div", { class: "an-kpi-label", text: `Reference datasets vs ${bName}` }),
        h("div", { class: "an-kpi-value" }, String(st.improved), h("small", { text: `improved · ${st.worse} worse` })),
        h("div", { class: "an-kpi-delta", text: `Within ${ACC} kcal/mol: ${st.accBase} → ${st.acc}` })
      )
    );

    const trend = card({
      id: "trend",
      title: "MUE across runs",
      tools: [trendSeriesMenu(), scaleToggle()],
      below: h("div", { class: "an-legend an-trend-legend" }, trendEncodingLegend()),
      extraClass: "an-trend-card",
      draw: drawTrend,
      table: () => h("div", { class: "an-trend-tables" }, trendPanels().map((part) => h("section", { "aria-label": `${part.title} MUE table` },
        h("h4", { class: "an-trend-panel-title", text: part.title }),
        simpleTable(["Run", "Job", "Basis", "Inverse weight"].concat(part.series.map((item) => item.label)),
          runsIn().map((run) => [runLabel(run), run.jobId, run.basis || "—", weightText(run.effectiveWeight)]
            .concat(part.series.map((item) => item.get(run) == null ? (item.missing ? item.missing(run) : "—") : f2(item.get(run))))))
      ))),
    });

    const trade = card({
      id: "tradeoff",
      title: "Your data set vs reference databases",
      legend: [legendItem("an-key-1", "dot", "Run"), legendItem("an-key-ref", "line", `CF22D Input MUE ${f2(average(runsIn().map((run) => run.input.original).filter(isValue)))}`), ...basisLegend()],
      draw: drawTradeoff,
      table: () =>
        simpleTable(
          ["Run", "Input MUE · non-SCF", "Input MUE · SCF", "Δ vs CF22D", "Improved", "Worse"],
          runsIn().map((r) => {
            const st2 = stats(r);
            return [displayRunName(r), f2(r.input.nonScf), f2(scf(r)), signed(difference(scf(r), r.input.original)), String(st2.improved), String(st2.worse)];
          })
        ),
    });

    return [kpis, h("div", { class: "an-grid-2" }, trend, trade)];
  }

  /* --- MUE line chart: series model, legend, dataset picker ------------------ */
  const keyClass = (slot) => (slot === "ref" || String(slot).startsWith("ref:")) ? "ref" : String(slot);
  const JOB_SERIES_BASE = { 1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a", 4: "#eda100", 5: "#e87ba4", 6: "#4a3aa7", 7: "#e34948", ref: "#8e8e93" };
  function mixJobHex(hex, white) {
    const value = hex.replace("#", "");
    const rgb = [0, 2, 4].map((index) => parseInt(value.slice(index, index + 2), 16));
    return "#" + rgb.map((channel) => Math.round(channel + (255 - channel) * white).toString(16).padStart(2, "0")).join("");
  }
  function basisToneIndex(runOrBasis) {
    const basis = typeof runOrBasis === "string" ? runOrBasis : runOrBasis?.basis || "Basis not reported";
    return [...new Set(runsIn().map((run) => run.basis || "Basis not reported"))].indexOf(basis);
  }
  function seriesColor(seriesOrSlot, run) {
    const slot = typeof seriesOrSlot === "object" ? seriesOrSlot.slot : seriesOrSlot;
    const tone = typeof seriesOrSlot === "object" && seriesOrSlot.toneIndex != null ? seriesOrSlot.toneIndex : basisToneIndex(run);
    const base = JOB_SERIES_BASE[keyClass(slot)] || JOB_SERIES_BASE[Number(slot)] || JOB_SERIES_BASE[1];
    return mixJobHex(base, Math.min(.58, Math.max(0, tone) * .32));
  }
  function basisLegend() {
    const bases = [...new Set(runsIn().map((run) => run.basis || "Basis not reported"))];
    return bases.length < 2 ? [] : bases.map((basis, index) => h("span", { class: "an-basis-legend" }, h("i", { style: `background:${seriesColor({ slot: 1, toneIndex: index })}` }), basis));
  }

  function weightGroups(runs) {
    const groups = [];
    const byKey = new Map();
    for (const run of runs) {
      const key = run.effectiveWeight === null ? `unknown:${run.jobId}:${run.runId}` : `weight:${run.effectiveWeight}`;
      let group = byKey.get(key);
      if (!group) {
        group = { key, weight: run.effectiveWeight, runs: [] };
        byKey.set(key, group); groups.push(group);
      }
      group.runs.push(run);
    }
    groups.sort((a, b) => (b.weight ?? -Infinity) - (a.weight ?? -Infinity) || a.key.localeCompare(b.key, undefined, { numeric: true }));
    return groups;
  }

  const trendBasis = (run) => run.basis || "Basis not reported";
  const TREND_DASHES = [null, "7 4", "2 3", "9 3 2 3", "12 4", "5 3 2 3 2 3"];
  function trendBasisDash(basis) {
    const bases = [...new Set(RUNS.map(trendBasis))];
    const index = Math.max(0, bases.indexOf(basis));
    return index < TREND_DASHES.length ? TREND_DASHES[index] : `${14 + (index - TREND_DASHES.length) * 2} 3 2 3`;
  }
  const trendColor = (series) => `var(--viz-${keyClass(series.slot)})`;

  function trendSeries(all = false) {
    const bases = [...new Set(runsIn().map(trendBasis))];
    const specs = [
      { key: "input", name: "Non-SCF", label: "Train MUE · non-SCF", slot: 1, get: (run) => run.input.nonScf },
      { key: "scf", name: "SCF", label: "Train MUE · SCF", slot: 2, get: scf, missing: scfStateText },
      ...(runsIn().some((run) => run.test) ? [
        { key: "test", name: "Non-SCF", label: "Test set MUE · non-SCF", slot: 1, get: (run) => run.test?.nonScf ?? null },
        { key: "test-scf", name: "SCF", label: "Test set MUE · SCF", slot: 2, get: testScf },
        { key: "test-ref", name: "CF22D", label: "Test set CF22D", slot: "ref", context: true, get: (run) => run.test?.original ?? null },
      ] : []),
      { key: "ref", name: "CF22D", label: "Train CF22D", slot: "ref", context: true, get: (run) => run.input.original },
      ...state.trendDs.map(({ name, slot }) => ({ key: "ds:" + name, name, slot, dataset: DS_BY_NAME[name], get: (run) => mue(run, DS_BY_NAME[name]) })),
    ];
    const series = specs.flatMap((spec) => bases.map((basis) => ({
      ...spec,
      key: `${spec.key}:${basis}`,
      groupKey: spec.key,
      basis,
      label: bases.length > 1 ? `${spec.label || spec.name} · ${basis}` : spec.label || spec.name,
      dash: trendBasisDash(basis),
      matches: (run) => trendBasis(run) === basis,
      get: (run) => trendBasis(run) === basis ? spec.get(run) : null,
      missing: spec.missing ? (run) => trendBasis(run) === basis ? spec.missing(run) : "—" : null,
    })));
    return all ? series : series.filter((item) => !state.hidden.has(item.key) && !state.hidden.has(item.groupKey));
  }

  function trendPanels() {
    const series = trendSeries();
    const isTest = (item) => ["test", "test-scf", "test-ref"].includes(item.groupKey);
    return [{ id: "train", title: "Your data set", series: series.filter((item) => !isTest(item)) },
      ...(runsIn().some((run) => run.test) ? [{ id: "test", title: "Test set", series: series.filter(isTest) }] : [])];
  }

  function trendEncodingLegend() {
    return [legendItem("an-key-1", "dot", "Non-SCF"), legendItem("an-key-2", "dot", "SCF"),
      h("span", null, h("span", { class: "an-key-line an-key-ref an-key-dashed" }), "CF22D baseline"),
      ...(runsIn().some((run) => run.kind === "fork") ? [h("span", null, h("span", { class: "an-key-fork" }), "Fork of the run on its left")] : [])];
  }

  function toggleSeries(key) {
    const members = trendSeries(true).filter((series) => series.groupKey === key);
    const hidden = state.hidden.has(key) || (members.length && members.every((series) => state.hidden.has(series.key)));
    if (hidden) {
      state.hidden.delete(key);
      members.forEach((series) => state.hidden.delete(series.key));
    } else state.hidden.add(key);
    renderPanel();
  }

  function trendSeriesMenu() {
    const menu = h("details", { class: "an-series-menu", open: state.seriesMenuOpen });
    const summary = h("summary", { class: "link", text: "Series", "aria-label": "Choose visible MUE series" });
    const options = h("div", { class: "an-series-options", role: "group", "aria-label": "MUE series" });
    trendSeries(true).forEach((series) => {
      options.append(h("label", null,
        h("input", { type: "checkbox", "aria-label": series.label, checked: !state.hidden.has(series.key) && !state.hidden.has(series.groupKey), onchange: (event) => {
          state.seriesMenuOpen = true;
          // Expand an older group toggle into individual keys before changing one basis.
          if (state.hidden.has(series.groupKey)) {
            state.hidden.delete(series.groupKey);
            trendSeries(true).filter((item) => item.groupKey === series.groupKey).forEach((item) => state.hidden.add(item.key));
          }
          if (event.target.checked) state.hidden.delete(series.key); else state.hidden.add(series.key);
          renderPanel();
        }}), h("span", { text: series.label })));
    });
    options.append(datasetRow());
    menu.append(summary, options);
    menu.addEventListener("toggle", () => { if (menu.isConnected) state.seriesMenuOpen = menu.open; });
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { event.preventDefault(); closeTrendSeriesMenu(true); }
    });
    return menu;
  }

  function scaleToggle() {
    return h(
      "div",
      { class: "seg an-scale-seg", role: "group", "aria-label": "Y-axis scale" },
      [
        ["linear", "Linear"],
        ["log", "Log"],
      ].map(([v, t]) =>
        h("button", {
          type: "button",
          "data-scale": v,
          "aria-pressed": String(state.scale === v),
          onclick: () => {
            if (state.scale === v) return;
            state.scale = v;
            renderPanel();
          },
          text: t,
        })
      )
    );
  }

  function trendValues() {
    const runs = runsIn();
    return trendSeries()
      .flatMap((x) => runs.map((r) => x.get(r)))
      .filter((v) => plottable(v));
  }

  const plottable = (value) => isValue(value) && (state.scale !== "log" || value > 0);

  function datasetRow() {
    const row = h("div", { class: "an-ds-row" });
    state.trendDs.forEach(({ name, slot }) => {
      const members = trendSeries(true).filter((series) => series.groupKey === "ds:" + name);
      const hidden = state.hidden.has("ds:" + name) || members.every((series) => state.hidden.has(series.key));
      row.append(
        h(
          "span",
          { class: "an-chip" + (hidden ? " off" : "") },
          h(
            "button",
            { type: "button", class: "an-chip-main", "aria-pressed": String(!hidden), title: hidden ? `Show ${name}` : `Hide ${name}`, onclick: () => toggleSeries("ds:" + name) },
            name
          ),
          h(
            "button",
            {
              type: "button",
              class: "an-chip-x",
              "aria-label": `Remove ${name}`,
              onclick: () => {
                removeTrendDataset(name);
                renderPanel();
              },
            },
            icon("i-x")
          )
        )
      );
    });

    const full = state.trendDs.length >= MAX_DS;
    const add = h(
      "button",
      {
        type: "button",
        class: "btn btn-secondary btn-sm an-add-ds",
        "aria-haspopup": "dialog",
        "aria-expanded": String(state.pickerOpen),
        disabled: full,
        title: full ? `Up to ${MAX_DS} datasets` : null,
        onclick: (e) => {
          e.stopPropagation();
          state.pickerOpen = !state.pickerOpen;
          renderPicker(row);
        },
      },
      icon("i-plus"),
      state.trendDs.length ? "Add dataset" : "Add reference datasets"
    );
    row.append(add);
    if (state.trendDs.length) row.append(h("span", { class: "an-ds-note", text: `${state.trendDs.length} of ${MAX_DS}` }));
    renderPicker(row);
    return row;
  }

  function renderPicker(row) {
    const old = $(".an-picker", row);
    const keepScroll = old ? $(".an-picker-list", old).scrollTop : 0;
    if (old) old.remove();
    const btn = $(".an-add-ds", row);
    if (btn) btn.setAttribute("aria-expanded", String(state.pickerOpen));
    if (!state.pickerOpen) return;

    const q = state.pickerQuery.trim().toLowerCase();
    const chosen = new Set(state.trendDs.map((d) => d.name));
    const full = chosen.size >= MAX_DS;
    const list = h("div", { class: "an-picker-list", role: "group", "aria-label": "Reference datasets" });
    TYPES.forEach((type) => {
      const ds = DATASETS.filter((d) => d.type === type && (!q || d.name.toLowerCase().includes(q) || type.toLowerCase().includes(q)));
      if (!ds.length) return;
      list.append(h("div", { class: "an-picker-group", text: type }));
      ds.forEach((d) => {
        const on = chosen.has(d.name);
        list.append(
          h(
            "label",
            { class: "an-picker-item" + (!on && full ? " disabled" : "") },
            h("input", {
              type: "checkbox",
              checked: on,
              disabled: !on && full,
              "data-name": d.name,
              onchange: (e) => {
                if (e.target.checked) addTrendDataset(d.name);
                else removeTrendDataset(d.name);
                pickerFocus = d.name;
                renderPanel();
              },
            }),
            h("span", { class: "an-box" }, icon("i-check")),
            h("span", { class: "mono", text: d.name }),
            h("span", { class: "an-picker-val", text: f2(d.original) })
          )
        );
      });
    });
    if (!list.childElementCount) list.append(h("div", { class: "an-empty-note", text: "No datasets match." }));

    const search = h("input", {
      type: "search",
      placeholder: `Search ${DATASETS.length} datasets`,
      value: state.pickerQuery,
      autocomplete: "off",
      "aria-label": "Search reference datasets",
      oninput: (e) => {
        state.pickerQuery = e.target.value;
        pickerFocus = "__search";
        renderPicker(row);
      },
    });
    const pop = h(
      "div",
      { class: "an-picker", role: "dialog", "aria-label": "Add reference datasets", onclick: (e) => e.stopPropagation() },
      h("div", { class: "an-picker-head" }, h("b", { text: "Reference datasets" }), h("span", { text: full ? `Limit reached (${MAX_DS})` : `Pick up to ${MAX_DS} · CF22D MUE shown` })),
      h("label", { class: "search" }, h("span", { class: "sr", text: "Search datasets" }), icon("i-search"), search),
      list
    );
    row.append(pop);
    list.scrollTop = keepScroll;
    if (pickerFocus === "__search") {
      search.focus();
      search.setSelectionRange(search.value.length, search.value.length);
    } else if (pickerFocus) {
      const cb = list.querySelector(`input[data-name="${CSS.escape(pickerFocus)}"]`);
      if (cb) cb.focus({ preventScroll: true });
    } else {
      search.focus({ preventScroll: true });
    }
    pickerFocus = null;
  }
  let pickerFocus = null;

  function closePicker() {
    if (!state.pickerOpen) return;
    state.pickerOpen = false;
    $$(".an-ds-row", root).forEach((row) => renderPicker(row));
  }

  function closeTrendSeriesMenu(restoreFocus = false) {
    state.seriesMenuOpen = false;
    const menu = $(".an-series-menu");
    if (!menu) return;
    menu.open = false;
    if (restoreFocus) $("summary", menu)?.focus({ preventScroll: true });
  }

  document.addEventListener("click", (e) => {
    if ($(".an-series-menu[open]") && !e.target.closest(".an-series-menu")) closeTrendSeriesMenu();
    if (state.pickerOpen && !e.target.closest(".an-picker, .an-add-ds")) closePicker();
  }, { signal: lifecycle.signal });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $(".an-series-menu[open]")) {
      e.preventDefault();
      closeTrendSeriesMenu(true);
    }
    if (e.key === "Escape" && state.pickerOpen) {
      closePicker();
      const b = $(".an-add-ds", root);
      if (b) b.focus();
    }
  }, { signal: lifecycle.signal });

  /* --- Shared y-scales: linear from zero, or log decades -------------------- */
  function logDomain(lo, hi) {
    const a = Math.floor(Math.log10(lo));
    const b = Math.ceil(Math.log10(hi));
    const all = [];
    for (let e = a; e <= b; e++) for (const k of [1, 2, 5]) all.push(+(k * Math.pow(10, e)).toPrecision(3));
    const loT = Math.max(...all.filter((t) => t <= lo));
    const hiT = Math.min(...all.filter((t) => t >= hi));
    return { lo: loT, hi: hiT, ticks: all.filter((t) => t >= loT && t <= hiT), log: true, step: 1 };
  }

  function yDomain(values) {
    if (state.scale === "log") return logDomain(Math.min(...values) * 0.92, Math.max(...values) * 1.08);
    return niceDomain(0, Math.max(...values) * 1.05, 5);
  }

  function yMap(dom, top, height) {
    if (dom.log) {
      const a = Math.log10(dom.lo);
      const b = Math.log10(dom.hi);
      return (v) => top + height * (1 - (Math.log10(v) - a) / (b - a));
    }
    return (v) => top + height * (1 - (v - dom.lo) / (dom.hi - dom.lo));
  }

  const domTick = (t, dom) => (dom.log ? String(t) : tickText(t, dom.step));

  /* --- MUE line chart -------------------------------------------------------- */
  function wrapTrendLabel(text, width, size) {
    const lines = [];
    let line = "";
    for (const word of String(text).split(/\s+/)) {
      if (line && tw(`${line} ${word}`, size) > width) { lines.push(line); line = ""; }
      for (const character of (line ? " " : "") + word) {
        if (line && tw(line + character, size) > width) { lines.push(line); line = ""; }
        line += character;
      }
    }
    if (line) lines.push(line);
    return lines;
  }

  function placeTrendLabels(labels, y, top, bottom, gap) {
    labels.forEach((label) => { label.pointY = y(label.value); });
    labels.sort((a, b) => a.pointY - b.pointY || a.series.label.localeCompare(b.series.label));
    let edge = top;
    labels.forEach((label) => {
      label.labelY = Math.max(edge + label.height / 2, Math.min(bottom - label.height / 2, label.pointY));
      edge = label.labelY + label.height / 2 + gap;
    });
    edge = bottom;
    for (let i = labels.length - 1; i >= 0; i--) {
      const label = labels[i];
      label.labelY = Math.min(label.labelY, edge - label.height / 2);
      edge = label.labelY - label.height / 2 - gap;
    }
  }

  function trendRoot(run) {
    const seen = new Set();
    let rootRun = run;
    while (rootRun.kind === "fork") {
      if (seen.has(rootRun.id)) return run;
      seen.add(rootRun.id);
      const parent = BY_ID[rootRun.parent];
      if (!parent || parent.jobId !== run.jobId) return run;
      rootRun = parent;
    }
    return rootRun;
  }

  function trendColumns(runs) {
    const roots = new Map(runs.map((run) => { const parent = trendRoot(run); return [parent.id, parent]; }));
    return weightGroups([...roots.values()]).map((group) => {
      const families = group.runs.map((rootRun) => {
        const members = [];
        const seen = new Set();
        const visit = (run) => {
          if (seen.has(run.id)) return;
          seen.add(run.id); members.push(run);
          RUNS.filter((item) => item.jobId === run.jobId && item.parent === run.id)
            .sort((a, b) => (a.runId || a.id).localeCompare(b.runId || b.id, undefined, { numeric: true })).forEach(visit);
        };
        visit(rootRun);
        return { root: rootRun, members: members.filter((run) => runs.some((item) => item.id === run.id)), order: members };
      });
      return { weight: group.weight, families, runs: families.flatMap((family) => family.members),
        slots: Math.max(1, ...families.map((family) => family.order.length)) };
    });
  }

  function trendLinks(series, runs, columns) {
    const selected = new Map(runs.map((run) => [run.id, run]));
    const main = [], branches = [], previous = new Map();
    columns.forEach((column) => {
      column.families.forEach(({ root: run }) => {
        const job = run.jobId;
        if (run.kind === "fork" || !selected.has(run.id) || !series.matches(run) || !plottable(series.get(run))) { previous.delete(job); return; }
        const before = previous.get(job);
        if (before && before.column !== column) main.push([before.run, run]);
        previous.set(job, { run, column });
      });
    });
    runs.filter((run) => run.kind === "fork" && series.matches(run) && plottable(series.get(run))).forEach((run) => {
      const parent = selected.get(run.parent);
      if (parent && parent.jobId === run.jobId && series.matches(parent) && plottable(series.get(parent))) branches.push([parent, run]);
    });
    return { main, branches };
  }

  function trendDomain(values) {
    if (state.scale === "log") return yDomain(values);
    const max = Math.max(...values);
    if (!max) return niceDomain(0, 1, 3);
    const unit = Math.pow(10, Math.floor(Math.log10(max))) / 2;
    const hi = Math.ceil(max * 1.2 / unit) * unit;
    const raw = hi / 4;
    const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 5, 10].map((n) => n * magnitude).reduce((a, b) => Math.abs(a - raw) <= Math.abs(b - raw) ? a : b);
    const ticks = [];
    for (let value = 0; value <= hi + step * .001; value += step) ticks.push(Number(value.toPrecision(10)));
    return { lo: 0, hi, ticks, step };
  }

  function trendMainLabels(series, runs, width, size, lineHeight) {
    const bases = new Set(runs.map(trendBasis));
    return series.flatMap((item) => {
      const jobs = new Map();
      runs.filter((run) => run.kind !== "fork" && plottable(item.get(run))).forEach((run) => {
        // runs are ordered by descending inverse weight, so the last is the right endpoint.
        jobs.set(run.jobId, run);
      });
      return [...jobs.values()].map((run) => {
        const lines = wrapTrendLabel(item.name, width, size);
        if (bases.size > 1) lines.push(...wrapTrendLabel(item.basis, width, size));
        if (jobs.size > 1) lines.push(jobCode(run));
        return { series: item, run, value: item.get(run), lines, height: lineHeight * lines.length };
      });
    });
  }

  // Screen and publication export share this renderer so topology and fork positions cannot drift.
  function trendGraphic(requestedWidth, print = false, panelMark = "") {
    const runs = runsIn(), columns = trendColumns(runs), parts = trendPanels();
    const scale = print ? .5 : 1;
    const labelSize = 12 * scale, lineHeight = 16 * scale;
    const minPlot = columns.reduce((sum, column) => sum + Math.max(100, 62 + (column.slots - 1) * 24), 0);
    const W = print ? requestedWidth : Math.max(requestedWidth, minPlot + 56 + 124);
    const L = 56 * scale, labelWidth = 124 * scale, R = W - labelWidth;
    const band = (R - L) / Math.max(1, columns.length);
    const positions = new Map(), columnOf = new Map();
    columns.forEach((column, index) => {
      column.cx = L + band * (index + .5);
      column.families.forEach((family) => {
        const step = Math.min(46 * scale, band * .42 / Math.max(1, family.order.length - 1));
        family.order.forEach((run, slot) => { positions.set(run.id, column.cx + slot * step); columnOf.set(run.id, index); });
      });
    });
    let cursor = (panelMark ? 44 : 28) * scale;
    const panels = parts.map((part) => {
      const values = part.series.flatMap((item) => runs.filter((run) => !item.context || run.kind !== "fork").map(item.get)).filter(plottable);
      const dom = values.length ? trendDomain(values) : null;
      const labels = trendMainLabels(part.series, runs, labelWidth - 20 * scale, labelSize, lineHeight);
      const height = Math.max((part.id === "train" ? 200 : 188) * scale, labels.reduce((sum, label) => sum + label.height + 5 * scale, 0) + 12 * scale);
      const panel = { ...part, top: cursor, height, dom, labels };
      cursor += height + 84 * scale;
      return panel;
    });
    const bottom = panels.at(-1).top + panels.at(-1).height;
    const axisExtra = Math.max(0, ...columns.map((column) => column.families.length - 1)) * 14 * scale;
    const H = bottom + 60 * scale + axisExtra;
    const svg = s("svg", { xmlns: SVGNS, width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "MUE across runs: main runs and their fork branches" });
    const colour = (item) => print ? ({ 1: "#3987e5", 2: "#d95926" }[item.slot] || PRINT[item.slot]) : trendColor(item);
    const ink = print ? "#1d1d1f" : "var(--ink)", muted = print ? "#6e6e73" : "var(--ink-2)";
    const surface = print ? "#ffffff" : "var(--surface)";
    const text = (parent, x, y, value, size = 11 * scale, extra = {}) => s("text", { x, y, fill: muted, "font-size": size, text: value, ...extra }, parent);
    const line = (parent, x1, y1, x2, y2, stroke, width, extra = {}) => s("line", { x1, y1, x2, y2, stroke, "stroke-width": width, ...extra }, parent);
    const focusColumn = columnOf.get(state.focus);
    if (focusColumn != null) s("rect", { class: "an-trend-focus", x: L + band * focusColumn + 6 * scale, y: panels[0].top - 8 * scale,
      width: Math.max(1, band - 12 * scale), height: bottom - panels[0].top + 28 * scale, rx: 10 * scale,
      fill: print ? "#ecf4ff" : "var(--viz-focus)" }, svg);
    if (panelMark) text(svg, 0, 10 * scale, panelMark, 14 * scale, { "font-weight": 700, fill: ink });
    panels.forEach((part) => {
      const group = s("g", { "data-panel": part.id, "data-domain-hi": part.dom?.hi, "aria-label": part.title }, svg);
      text(group, 0, part.top - 16 * scale, part.title, 13 * scale, { "font-weight": 600, fill: ink });
      text(group, R, part.top - 16 * scale, "MUE (kcal/mol)", 11 * scale, { "text-anchor": "end" });
      if (!part.dom) { text(group, L, part.top + 36 * scale, state.scale === "log" ? "No positive values in the visible series" : "No results in the visible series"); return; }
      const y = yMap(part.dom, part.top, part.height);
      part.dom.ticks.forEach((tick) => {
        line(group, L, y(tick), R, y(tick), print ? (tick === 0 ? "#b8b8bd" : "#e8e8eb") : tick === 0 ? "var(--viz-axis)" : "var(--viz-grid)", scale);
        text(group, L - 10 * scale, y(tick) + 4 * scale, domTick(tick, part.dom), 11 * scale, { "text-anchor": "end" });
      });
      part.series.filter((item) => item.context).forEach((item) => {
        runs.filter((run) => run.kind !== "fork" && plottable(item.get(run))).forEach((run) => {
          const cx = positions.get(run.id);
          line(group, cx - band * .38, y(item.get(run)), cx + band * .38, y(item.get(run)), print ? PRINT.ref : "var(--viz-ref)", 2 * scale,
            { "stroke-dasharray": `${4 * scale} ${3 * scale}`, class: "an-trend-baseline", "data-run": run.id, "data-series": item.key });
        });
      });
      part.series.filter((item) => !item.context).forEach((item) => {
        const edges = trendLinks(item, runs, columns);
        edges.branches.forEach(([parent, run]) => line(group, positions.get(parent.id), y(item.get(parent)), positions.get(run.id), y(item.get(run)), colour(item), 1.5 * scale,
          { "stroke-dasharray": `${2 * scale} ${3 * scale}`, opacity: .8, class: "an-trend-branch", "data-from": parent.id, "data-to": run.id, "data-series": item.key }));
        edges.main.forEach(([a, b]) => line(group, positions.get(a.id), y(item.get(a)), positions.get(b.id), y(item.get(b)), colour(item), 2 * scale,
          { "stroke-dasharray": item.dash?.split(" ").map((n) => Number(n) * scale).join(" "), class: "an-trend-main", "data-from": a.id, "data-to": b.id, "data-series": item.key }));
        runs.filter((run) => plottable(item.get(run))).forEach((run) => {
          const fork = run.kind === "fork";
          const marker = s("circle", { cx: positions.get(run.id), cy: y(item.get(run)), r: (run.id === state.focus ? 6 : 4.5) * scale,
            fill: fork ? surface : colour(item), stroke: fork ? colour(item) : surface, "stroke-width": (fork ? 1.8 : 2) * scale,
            class: "an-trend-point", "data-run": run.id, "data-series": item.key, "data-fork": String(fork) }, group);
          s("title", { text: `${runLabel(run)} · ${item.label}: ${f2(item.get(run))} kcal/mol` }, marker);
        });
      });
      placeTrendLabels(part.labels, y, part.top + 4 * scale, part.top + part.height - 2 * scale, 4 * scale);
      part.labels.forEach((label) => {
        const node = s("text", { class: "an-trend-main-label", "data-series": label.series.key, fill: muted, "font-size": labelSize }, group);
        label.lines.forEach((value, i) => s("tspan", { x: R + 12 * scale, y: label.labelY - label.height / 2 + labelSize + i * lineHeight, text: value }, node));
      });
      if (!print) {
        // Per-run hit areas make each offset fork selectable, including by keyboard.
        columns.forEach((column) => column.families.forEach((family) => family.members.forEach((run) => {
          const cx = positions.get(run.id), others = family.members.map((r) => positions.get(r.id)).sort((a, b) => a - b);
          const at = others.indexOf(cx), x0 = at ? (others[at - 1] + cx) / 2 : L + band * columnOf.get(run.id);
          const x1 = at < others.length - 1 ? (cx + others[at + 1]) / 2 : L + band * (columnOf.get(run.id) + 1);
          const hit = s("rect", { class: "v-hit", x: x0, y: part.top, width: Math.max(1, x1 - x0), height: part.height,
            tabindex: 0, role: "button", "data-run": run.id, "aria-label": `${runLabel(run)} · ${part.title}` }, group);
          const show = (event) => showTip(event, [h("div", { class: "an-tip-head", text: runLabel(run) }),
            h("div", { class: "an-tip-sub", text: `${trendBasis(run)} · inverse weight ${weightText(run.effectiveWeight)}` }),
            ...part.series.filter((item) => item.matches(run)).map((item) => tipRow(`an-key-${keyClass(item.slot)}`, f2(item.get(run)), item.name))]);
          hit.addEventListener("pointermove", show); hit.addEventListener("focus", show);
          hit.addEventListener("pointerleave", hideTip); hit.addEventListener("blur", hideTip);
          hit.addEventListener("click", () => setFocus(run.id));
          hit.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); setFocus(run.id); } });
        })));
      }
    });
    columns.forEach((column, index) => {
      const selected = index === focusColumn;
      column.families.forEach((family, row) => text(svg, column.cx, bottom + (28 + row * 14) * scale, runLabel(family.root), 12 * scale,
        { "text-anchor": "middle", fill: selected ? ink : muted, "font-weight": selected ? 600 : 400 }));
      text(svg, column.cx, bottom + 45 * scale + axisExtra, `w ${weightText(column.weight)}`, 11 * scale, { "text-anchor": "middle" });
      const forks = new Map();
      column.families.forEach((family) => family.members.filter((run) => run.kind === "fork" && run.id !== family.root.id).forEach((run) => {
        const key = positions.get(run.id);
        if (!forks.has(key)) forks.set(key, []);
        forks.get(key).push((run.runId || run.id).split("/").at(-1).replace("fork-", "f"));
      }));
      forks.forEach((names, x) => text(svg, x, bottom + 28 * scale, [...new Set(names)].join("/"), 11 * scale, { "text-anchor": "middle" }));
    });
    text(svg, R + 12 * scale, bottom + 45 * scale + axisExtra, "inverse weight", 11 * scale);
    return svg;
  }

  function drawTrend(el) {
    const graphic = trendGraphic(Math.max(1, el.clientWidth));
    const scroll = h("div", { class: "an-trend-scroll", tabindex: 0, "aria-label": "MUE chart",
      onscroll: (event) => { state.trendScroll = event.target.scrollLeft; } }, graphic);
    el.append(scroll);
    scroll.scrollLeft = state.trendScroll;
  }

  /* --- Trade-off scatter ------------------------------------------------------ */
  function drawTradeoff(el) {
    const runs = runsIn();
    const W = Math.max(300, el.clientWidth);
    const H = 300;
    const m = { l: 56, r: 28, t: 16, b: 46 };
    const iw = W - m.l - m.r;
    const ih = H - m.t - m.b;

    const pts = runs.map((r) => ({ r, x: r.input.nonScf, y: scf(r) })).filter((point) => isValue(point.x) && isValue(point.y));
    if (!pts.length) { el.append(h("div", { class: "an-empty-note", text: "Non-SCF and SCF Input MUE are required for this comparison." })); return; }
    const xs = pts.map((p) => p.x);
    const originalInput = average(runs.map((run) => run.input.original).filter(isValue));
    const ys = pts.map((p) => p.y).concat(isValue(originalInput) ? [originalInput] : []);
    const xr = Math.max(...xs) - Math.min(...xs) || 0.2;
    const yr = Math.max(...ys) - Math.min(...ys) || 0.02;
    const dx = niceDomain(Math.max(0, Math.min(...xs) - xr * 0.18), Math.max(...xs) + xr * 0.18, 5);
    const dy = niceDomain(Math.max(0, Math.min(...ys) - yr * 0.25), Math.max(...ys) + yr * 0.25, 4);
    const X = (v) => m.l + (iw * (v - dx.lo)) / (dx.hi - dx.lo);
    const Y = (v) => m.t + ih * (1 - (v - dy.lo) / (dy.hi - dy.lo));

    const narrow = W < 520;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "Scatter plot of SCF Input MUE against non-SCF Input MUE for each run" }, el);
    const defs = s("defs", null, svg);
    const mk = s("marker", { id: "anArrow", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
    s("path", { d: "M0,0 L8,4 L0,8 z", style: "fill: var(--viz-path)" }, mk);

    dy.ticks.forEach((t) => {
      s("line", { class: "v-grid", x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t) }, svg);
      s("text", { class: "v-tick", x: m.l - 8, y: Y(t) + 4, "text-anchor": "end", text: tickText(t, dy.step) }, svg);
    });
    dx.ticks.forEach((t) => {
      s("line", { class: "v-grid", x1: X(t), x2: X(t), y1: m.t, y2: m.t + ih }, svg);
      s("text", { class: "v-tick", x: X(t), y: m.t + ih + 16, "text-anchor": "middle", text: tickText(t, dx.step) }, svg);
    });
    s("text", { class: "v-tick", x: m.l + iw / 2, y: H - 6, "text-anchor": "middle", text: "Input MUE · non-SCF (kcal/mol)" }, svg);
    s("text", { class: "v-tick", x: 14, y: m.t + ih / 2, "text-anchor": "middle", transform: `rotate(-90 14 ${m.t + ih / 2})`, text: "Input MUE · SCF (kcal/mol)" }, svg);

    // CF22D original Input MUE
    if (isValue(originalInput)) s("line", { class: "v-line v-sref", x1: m.l, x2: W - m.r, y1: Y(originalInput), y2: Y(originalInput), "stroke-width": 1.5 }, svg);

    // Lineage arrows
    pts.forEach((p) => {
      const a = includedAncestor(p.r);
      if (!a) return;
      const q = pts.find((z) => z.r.id === a.id);
      if (!q) return;
      const x1 = X(q.x), y1 = Y(q.y), x2 = X(p.x), y2 = Y(p.y);
      const len = Math.hypot(x2 - x1, y2 - y1);
      if (len < 16) return;
      const ux = (x2 - x1) / len, uy = (y2 - y1) / len;
      s("line", { class: "v-path", x1: x1 + ux * 8, y1: y1 + uy * 8, x2: x2 - ux * 9, y2: y2 - uy * 9, "marker-end": "url(#anArrow)" }, svg);
    });

    // Trade-off frontier (no other run is better on both axes)
    const front = pts
      .filter((p) => !pts.some((q) => q !== p && q.x <= p.x && q.y <= p.y && (q.x < p.x || q.y < p.y)))
      .sort((a, b) => a.x - b.x);
    if (front.length > 1) s("polyline", { class: "v-frontier", points: front.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ") }, svg);

    // Points + labels (greedy placement: right, left, above, below)
    const placed = [];
    const overlaps = (b) => placed.some((o) => !(b.x2 < o.x1 || b.x1 > o.x2 || b.y2 < o.y1 || b.y1 > o.y2));
    pts.forEach((p) => {
      const focus = p.r.id === state.focus;
      const cx = X(p.x), cy = Y(p.y);
      placed.push({ x1: cx - 6, x2: cx + 6, y1: cy - 6, y2: cy + 6 });
    });
    pts.forEach((p) => {
      const focus = p.r.id === state.focus;
      const cx = X(p.x), cy = Y(p.y);
      if (focus) s("circle", { class: "v-focus-ring", cx, cy, r: 9.5 }, svg);
      s("circle", { class: "v-dot v-f1", cx, cy, r: focus ? 6 : 5, style: `fill:${seriesColor(1, p.r)}` }, svg);
      const label = displayRunName(p.r);
      const w = label.length * 6.8 + 4;
      const opts = [
        { x: cx + 10, y: cy + 4, a: "start", b: { x1: cx + 9, x2: cx + 10 + w, y1: cy - 6, y2: cy + 6 } },
        { x: cx - 10, y: cy + 4, a: "end", b: { x1: cx - 10 - w, x2: cx - 9, y1: cy - 6, y2: cy + 6 } },
        { x: cx, y: cy - 11, a: "middle", b: { x1: cx - w / 2, x2: cx + w / 2, y1: cy - 21, y2: cy - 9 } },
        { x: cx, y: cy + 19, a: "middle", b: { x1: cx - w / 2, x2: cx + w / 2, y1: cy + 9, y2: cy + 21 } },
        { x: cx + 10, y: cy - 8, a: "start", b: { x1: cx + 9, x2: cx + 10 + w, y1: cy - 18, y2: cy - 6 } },
        { x: cx + 10, y: cy + 16, a: "start", b: { x1: cx + 9, x2: cx + 10 + w, y1: cy + 6, y2: cy + 18 } },
      ].filter((o) => o.b.x1 > m.l - 4 && o.b.x2 < W - 2);
      const pick = opts.find((o) => !overlaps(o.b)) || opts[0];
      if (pick) {
        placed.push(pick.b);
        s("text", { class: "v-tick mono v-halo" + (focus ? " strong" : ""), x: pick.x, y: pick.y, "text-anchor": pick.a, text: label }, svg);
      }
      const st2 = stats(p.r);
      const onFront = front.includes(p);
      const hit = s("circle", { class: "v-hit", cx, cy, r: 14, tabindex: 0, role: "button", "aria-label": `${displayRunName(p.r)}: non-SCF Input ${f2(p.x)}, SCF Input ${f2(p.y)}` }, svg);
      const show = (e) =>
        showTip(e, [
          h("div", { class: "an-tip-head", text: displayRunName(p.r) }),
          h("div", { class: "an-tip-sub", text: onFront ? "On the trade-off frontier" : runSubtitle(p.r) }),
          tipRow("an-key-1", f2(p.x), "Input MUE · non-SCF"),
          tipRow("an-key-2", f2(p.y), "Input MUE · SCF"),
          h("div", { class: "an-tip-sub", style: "margin:6px 0 0", text: `${st2.improved} improved · ${st2.worse} worse vs ${baseName(p.r)}` }),
        ]);
      hit.addEventListener("pointerenter", show);
      hit.addEventListener("pointermove", show);
      hit.addEventListener("pointerleave", hideTip);
      hit.addEventListener("focus", show);
      hit.addEventListener("blur", hideTip);
      hit.addEventListener("click", () => setFocus(p.r.id));
      hit.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setFocus(p.r.id);
        }
      });
    });
  }

  /* ------------------------------------------------------------------------
     Input vs SCF
     ------------------------------------------------------------------------ */
  function viewScf() {
    const runs = runsIn();

    const dumb = card({
      id: "scf",
      title: "Input MUE: non-SCF vs SCF",
      legend: [legendItem("an-key-1", "dot", "Non-SCF"), legendItem("an-key-2", "dot", "SCF")],
      draw: drawDumbbell,
      table: () =>
        simpleTable(
          ["Run", "Non-SCF", "SCF", "SCF − non-SCF", "CF22D original"],
          runs.map((r) => [displayRunName(r), f2(r.input.nonScf), scfStateText(r), signed(difference(scf(r), r.input.nonScf)), f2(r.input.original)])
        ),
    });

    return [dumb];
  }

  function drawDumbbell(el) {
    const runs = runsIn();
    const groups = [
      { label: "New fits (different inverse weights)", runs: runs.filter((r) => r.kind === "weight") },
      { label: "Forks (tuned weights)", runs: runs.filter((r) => r.kind === "fork") },
    ].filter((g) => g.runs.length);

    const W = Math.max(300, el.clientWidth);
    const narrow = W < 520;
    const labelWidth = Math.max(0, ...runs.map((run) => displayRunName(run).length * 7));
    const left = narrow ? Math.min(112, Math.max(64, labelWidth + 12)) : Math.max(120, labelWidth + 12);
    const m = { l: left, r: narrow ? 92 : 150, t: 10, b: 34 };
    const rowH = 38;
    const groupH = 30;
    const H = m.t + m.b + groups.reduce((a, g) => a + groupH + g.runs.length * rowH, 0);
    const iw = W - m.l - m.r;
    const vals = runs.flatMap((r) => [r.input.nonScf, scf(r)]).filter((v) => v != null);
    const dom = niceDomain(0, Math.max(0, ...vals) * 1.08, narrow ? 4 : 6);
    const X = (v) => m.l + (iw * (v - dom.lo)) / (dom.hi - dom.lo);

    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "Dumbbell chart of non-SCF and SCF Input MUE per run" }, el);
    dom.ticks.forEach((t) => {
      s("line", { class: t === 0 ? "v-axis" : "v-grid", x1: X(t), x2: X(t), y1: m.t, y2: H - m.b }, svg);
      s("text", { class: "v-tick", x: X(t), y: H - m.b + 16, "text-anchor": "middle", text: tickText(t, dom.step) }, svg);
    });
    s("text", { class: "v-tick", x: m.l + iw / 2, y: H - 4, "text-anchor": "middle", text: "Input MUE (kcal/mol)" }, svg);
    s("text", { class: "v-tick", x: W - 6, y: m.t + 18, "text-anchor": "end", text: "SCF − non-SCF" }, svg);

    let yc = m.t;
    groups.forEach((g) => {
      yc += groupH;
      s("text", { class: "v-label strong v-halo", x: 4, y: yc - 9, text: g.label }, svg);
      g.runs.forEach((r) => {
        const cy = yc + rowH / 2;
        const focus = r.id === state.focus;
        if (focus) s("rect", { class: "v-focus-band", x: 0, y: yc + 2, width: W, height: rowH - 4, rx: 8 }, svg);
        s("text", { class: "v-label mono" + (focus ? " strong" : ""), x: m.l - 12, y: cy + 4, "text-anchor": "end", text: displayRunName(r) }, svg);
        const a = r.input.nonScf;
        const b = scf(r);
        if (a != null && b != null) s("line", { class: "v-connector", x1: X(a), x2: X(b), y1: cy, y2: cy }, svg);
        if (a != null) s("circle", { class: "v-dot v-f1", cx: X(a), cy, r: focus ? 6 : 5 }, svg);
        if (b != null) s("circle", { class: "v-dot v-f2", cx: X(b), cy, r: focus ? 6 : 5 }, svg);

        const rx = W - 6;
        if (b != null) {
          const t = s("text", { class: "v-label strong", x: rx, y: cy + 4, "text-anchor": "end", text: signed(difference(b, a)) }, svg);
          t.setAttribute("aria-label", `SCF shift ${signed(difference(b, a))}`);
        } else if (r.input.scf.state === "running") {
          s("text", { class: "v-label", x: rx, y: cy + 4, "text-anchor": "end", text: "Calculating…" }, svg);
        } else if (!r.canScf) {
          s("text", { class: "v-label", x: rx, y: cy + 4, "text-anchor": "end", text: r.input.scf.state === "failed" ? "Failed" : "Unavailable" }, svg);
        } else {
          const t = s("text", { class: "v-label", x: rx, y: cy + 4, "text-anchor": "end", style: "fill: var(--accent-ink); cursor: pointer", tabindex: 0, role: "button", text: "Calculate →" }, svg);
          t.addEventListener("click", () => queueScf([r]));
          t.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              queueScf([r]);
            }
          });
        }

        const hit = s("rect", { class: "v-hit", x: 0, y: yc, width: W - m.r + 8, height: rowH, tabindex: 0, role: "button", "aria-label": `${displayRunName(r)}: non-SCF ${f2(a)}, SCF ${scfStateText(r)}` }, svg);
        const show = (e) =>
          showTip(e, [
            h("div", { class: "an-tip-head", text: displayRunName(r) }),
            h("div", { class: "an-tip-sub", text: runSubtitle(r) }),
            tipRow("an-key-1", f2(a), "Non-SCF"),
            tipRow("an-key-2", scfStateText(r), "SCF"),
            b != null ? h("div", { class: "an-tip-sub", style: "margin:6px 0 0", text: `Shift ${signed(b - a)} · CF22D ${f2(r.input.original)}` }) : null,
          ]);
        hit.addEventListener("pointermove", show);
        hit.addEventListener("pointerleave", hideTip);
        hit.addEventListener("focus", show);
        hit.addEventListener("blur", hideTip);
        hit.addEventListener("click", () => setFocus(r.id));
        yc += rowH;
      });
    });
  }

  /* ------------------------------------------------------------------------
     Wavefunction overlap
     ------------------------------------------------------------------------ */
  function viewOverlap() {
    const runs = runsIn();
    const available = runs.filter((run) => isValue(run.overlap?.mean));
    const pending = runs.filter((run) => run.canScf && (
      ["none", "failed"].includes(run.input.scf.state) ||
      (run.input.scf.state === "done" && ["none", "partial"].includes(run.overlap?.state))
    ));
    const mean = available.length ? available.reduce((sum, run) => sum + run.overlap.mean, 0) / available.length : null;
    const summary = h("p", { class: "an-summary-line" },
      available.length
        ? ["Across ", h("b", { text: plural(available.length, "run", "runs") }), " the mean overlap with the initial CF22D reference is ", h("b", { text: mean.toFixed(4) }), ".", pending.length ? ` ${plural(pending.length, "run is", "runs are")} ready to calculate.` : ""]
        : ["No wavefunction overlap has been recorded yet.", pending.length ? ` ${plural(pending.length, "run is", "runs are")} ready to calculate.` : ""]
    );
    const calculate = pending.length ? h("button", {
      type: "button", class: "btn btn-primary btn-sm", disabled: submitting,
      text: submitting ? "Submitting…" : pending.every((run) => run.input.scf.state === "done") ? `Calculate overlap (${pending.length})` : `Calculate SCF Input (${pending.length})`,
      onclick: () => queueScf(pending),
    }) : null;
    const report = card({
      id: "overlap",
      title: "Wavefunction overlap with initial CF22D",
      draw: drawOverlap,
      table: () => simpleTable(
        ["Run", "Overlap", "Molecules", "Reference"],
        runs.map((run) => [displayRunName(run), run.overlap?.mean == null ? (run.input.scf.state === "running" ? "Calculating…" : "—") : run.overlap.mean.toFixed(4), run.overlap?.total ? `${run.overlap.available}/${run.overlap.total}` : "—", run.overlap?.reference || "—"])
      ),
      tools: calculate,
    });
    return [summary, report];
  }

  function drawOverlap(el) {
    const runs = runsIn();
    const values = runs.map((run) => ({ run, value: run.overlap?.mean })).filter((item) => isValue(item.value));
    if (!values.length) {
      const pending = runs.filter((run) => run.canScf && run.input.scf.state !== "running" && run.overlap?.state !== "running");
      el.append(h("div", { class: "an-empty-note" }, "No overlap values are available.", pending.length ? h("button", { type: "button", class: "link", onclick: () => queueScf(pending) }, `Calculate SCF Input (${pending.length})`) : null));
      return;
    }
    const W = Math.max(300, el.clientWidth);
    const narrow = W < 520;
    // Reserve separate space for run labels, values, ticks and the axis title.
    const labelWidth = Math.max(...values.map(({ run }) => displayRunName(run).length * 7));
    const m = { l: Math.min(narrow ? 112 : 180, Math.max(narrow ? 64 : 96, labelWidth + 12)), r: narrow ? 72 : 84, t: 18, b: 58 };
    const rowH = 34;
    const H = m.t + m.b + values.length * rowH;
    const iw = W - m.l - m.r;
    const domain = overlapDomain(values.map(({ value }) => value), narrow ? 4 : 5);
    const X = (value) => m.l + iw * Math.max(0, Math.min(1, (value - domain.lo) / (domain.hi - domain.lo)));
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "Wavefunction overlap with initial CF22D per run" }, el);
    domain.ticks.forEach((tick) => {
      s("line", { class: tick === domain.lo ? "v-axis" : "v-grid", x1: X(tick), x2: X(tick), y1: m.t - 6, y2: H - m.b }, svg);
      s("text", { class: "v-tick", x: X(tick), y: H - m.b + 20, "text-anchor": "middle", text: overlapTickText(tick, domain.step) }, svg);
    });
    s("text", { class: "v-tick", x: m.l + iw / 2, y: H - 8, "text-anchor": "middle", text: "Occupied-orbital overlap" }, svg);
    values.forEach(({ run, value }, index) => {
      const y = m.t + rowH * index + rowH / 2;
      const focus = run.id === state.focus;
      if (focus) s("rect", { class: "v-focus-band", x: 0, y: y - rowH / 2 + 2, width: W, height: rowH - 4, rx: 8 }, svg);
      s("text", { class: "v-label mono" + (focus ? " strong" : ""), x: m.l - 10, y: y + 4, "text-anchor": "end", text: displayRunName(run) }, svg);
      s("line", { class: "v-connector", x1: X(domain.lo), x2: X(value), y1: y, y2: y }, svg);
      s("circle", { class: "v-dot v-f1", cx: X(value), cy: y, r: focus ? 7 : 6 }, svg);
      s("text", { class: "v-label strong", x: W - 6, y: y + 4, "text-anchor": "end", text: value.toFixed(4) }, svg);
      const hit = s("rect", { class: "v-hit", x: 0, y: y - rowH / 2, width: W, height: rowH, tabindex: 0, role: "button", "aria-label": `${displayRunName(run)}: overlap ${value.toFixed(4)}` }, svg);
      hit.addEventListener("click", () => setFocus(run.id));
      hit.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setFocus(run.id); }
      });
    });
  }

  // Overlap values are bounded by one, but real calculations usually cluster
  // close to one. Zoom that common case so differences between runs remain
  // legible; a low outlier keeps the full 0–1 context.
  function overlapDomain(values, target = 5) {
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    if (lo >= 0.8 && hi >= 0.9) {
      const span = Math.max(hi - lo, 0.01);
      const pad = Math.max(0.01, span * 0.18);
      return niceDomain(Math.max(0, lo - pad), 1, target);
    }
    return { lo: 0, hi: 1, ticks: [0, 0.25, 0.5, 0.75, 1], step: 0.25 };
  }

  function overlapTickText(value, step) {
    let decimals = Math.max(2, Math.min(5, Math.ceil(-Math.log10(step))));
    while (decimals < 5 && Math.abs(Number(step.toFixed(decimals)) - step) > 1e-9) decimals++;
    return value.toFixed(decimals);
  }

  /* ------------------------------------------------------------------------
     All changes
     ------------------------------------------------------------------------ */
  function maxAbsDelta(ds, runs) {
    return runs.reduce((a, r) => Math.max(a, Math.abs(delta(r, ds) ?? 0)), 0);
  }

  function filteredDatasets() {
    const q = state.dsQuery.trim().toLowerCase();
    return DATASETS.filter((d) => (!q || d.name.toLowerCase().includes(q) || d.type.toLowerCase().includes(q)) &&
      (!state.hideUnchanged || maxAbsDelta(d, runsIn()) > EPS));
  }

  function changeStats(run) { return stats(run, filteredDatasets()); }

  function viewChanges() {
    const runs = runsIn();
    if (!DATASETS.length) return [h("div", { class: "empty" }, h("p", { text: "No reference dataset MUEs are available for this job yet." }))];
    const available = filteredDatasets();
    if (!available.some((d) => d.name === state.dataset)) {
      const f = focusRun();
      state.dataset = [...available].sort((a, b) => Math.abs(delta(f, b) ?? 0) - Math.abs(delta(f, a) ?? 0))[0]?.name || null;
    }

    const search = h(
      "label",
      { class: "search" },
      h("span", { class: "sr", text: "Search datasets" }),
      icon("i-search"),
      h("input", {
        type: "search",
        placeholder: "Search datasets",
        "aria-label": "Search datasets",
        value: state.dsQuery,
        autocomplete: "off",
        oninput: (e) => {
          state.dsQuery = e.target.value;
          renderPanel();
        },
      })
    );
    const sortSeg = h(
      "div",
      { class: "seg", role: "group", "aria-label": "Sort datasets" },
      [
        ["type", "By type"],
        ["change", "Largest change"],
        ["name", "A–Z"],
      ].map(([v, t]) =>
        h("button", {
          type: "button",
          "data-sort": v,
          "aria-pressed": String(state.sort === v),
          onclick: (e) => {
            state.sort = v;
            setPressed(e.currentTarget.parentElement, "sort", v);
            renderPanel();
          },
          text: t,
        })
      )
    );
    const hideChip = h("button", {
      type: "button",
      class: "toggle-chip",
      "aria-pressed": String(state.hideUnchanged),
      onclick: (e) => {
        state.hideUnchanged = !state.hideUnchanged;
        e.currentTarget.setAttribute("aria-pressed", String(state.hideUnchanged));
        renderPanel();
      },
      text: "Hide unchanged",
    });
    const toolbar = h("div", { class: "an-toolbar" }, search, sortSeg, hideChip);

    const counts = card({
      id: "counts",
      title: "Reference datasets improved vs worse",
      legend: [legendItem("an-key-better", "rect", "Improved · lower MUE"), legendItem("an-key-worse", "rect", "Worse · higher MUE")],
      draw: drawCounts,
      table: () =>
        simpleTable(
          ["Run", "Improved", "Worse", "Unchanged", `Within ${ACC} kcal/mol`, "Unavailable"],
          runs.map((r) => {
            const st = changeStats(r);
            return [displayRunName(r), String(st.improved), String(st.worse), String(st.unchanged), `${st.accBase} → ${st.acc}`, String(st.missing)];
          })
        ),
    });

    const heatCard = card({
      id: "heat",
      title: "Every MUE change",
      draw: (el) => {
        heatEl = el;
        renderHeat();
      },
      table: heatTable,
    });
    if (!state.tables.has("heat")) {
      heatCard.append(
        h(
          "div",
          { class: "an-scale", "aria-hidden": "true" },
          h("span", { text: "Lower MUE" }),
          h("div", { class: "an-scale-bar" }),
          h("span", { text: "Higher MUE" }),
          h("div", { class: "an-scale-ticks" }, h("span", { text: `≤ −${CLAMP}` }), h("span", { text: "0" }), h("span", { text: `≥ +${CLAMP}` }))
        )
      );
    }

    drillEl = h("div", { class: "an-drill" });
    renderDrill();

    return [toolbar, counts, h("div", { class: "an-changes-grid" }, heatCard, drillEl)];
  }

  function barPath(x0, x1, y0, hgt, roundRight) {
    const r = Math.min(4, Math.abs(x1 - x0), hgt / 2);
    if (Math.abs(x1 - x0) < 0.5) return "";
    if (roundRight) return `M${x0},${y0} H${x1 - r} Q${x1},${y0} ${x1},${y0 + r} V${y0 + hgt - r} Q${x1},${y0 + hgt} ${x1 - r},${y0 + hgt} H${x0} Z`;
    return `M${x1},${y0} H${x0 + r} Q${x0},${y0} ${x0},${y0 + r} V${y0 + hgt - r} Q${x0},${y0 + hgt} ${x0 + r},${y0 + hgt} H${x1} Z`;
  }

  function drawCounts(el) {
    const runs = runsIn();
    const W = Math.max(300, el.clientWidth);
    const narrow = W < 520;
    const labelWidth = Math.max(0, ...runs.map((run) => displayRunName(run).length * 7));
    const left = narrow ? Math.min(112, Math.max(60, labelWidth + 12)) : Math.max(128, labelWidth + 12);
    const m = { l: left, r: 12, t: 26, b: 8 };
    const rowH = 30;
    const barH = 16;
    const H = m.t + m.b + runs.length * rowH;
    const iw = W - m.l - m.r;
    const cx = m.l + iw / 2;
    const max = Math.max(1, ...runs.map((r) => Math.max(changeStats(r).improved, changeStats(r).worse)));
    const sc = (iw / 2 - 30) / niceDomain(0, max, 4).hi;

    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "Diverging bar chart of improved and worse reference datasets per run" }, el);
    s("text", { class: "v-tick", x: cx - 8, y: 12, "text-anchor": "end", text: "← Improved" }, svg);
    s("text", { class: "v-tick", x: cx + 8, y: 12, text: "Worse →" }, svg);

    runs.forEach((r, i) => {
      const st = changeStats(r);
      const y0 = m.t + i * rowH;
      const cy = y0 + rowH / 2;
      const focus = r.id === state.focus;
      if (focus) s("rect", { class: "v-focus-band", x: 0, y: y0 + 1, width: W, height: rowH - 2, rx: 8 }, svg);
      s("text", { class: "v-label mono" + (focus ? " strong" : ""), x: m.l - 12, y: cy + 4, "text-anchor": "end", text: displayRunName(r) }, svg);
      const li = cx - 1 - st.improved * sc;
      const ri = cx + 1 + st.worse * sc;
      s("path", { class: "v-better", d: barPath(li, cx - 1, cy - barH / 2, barH, false) }, svg);
      s("path", { class: "v-worse", d: barPath(cx + 1, ri, cy - barH / 2, barH, true) }, svg);
      s("text", { class: "v-label" + (focus ? " strong" : ""), x: li - 6, y: cy + 4, "text-anchor": "end", text: st.improved }, svg);
      s("text", { class: "v-label" + (focus ? " strong" : ""), x: ri + 6, y: cy + 4, text: st.worse }, svg);

      const hit = s("rect", { class: "v-hit", x: 0, y: y0, width: W, height: rowH, tabindex: 0, role: "button", "aria-label": `${displayRunName(r)}: ${st.improved} improved, ${st.worse} worse` }, svg);
      const show = (e) =>
        showTip(e, [
          h("div", { class: "an-tip-head", text: displayRunName(r) }),
          h("div", { class: "an-tip-sub", text: `vs ${baseName(r)}` }),
          tipRow("an-key-better", String(st.improved), "improved"),
          tipRow("an-key-worse", String(st.worse), "worse"),
          h("div", { class: "an-tip-sub", style: "margin:6px 0 0", text: `${st.unchanged} unchanged · within ${ACC} kcal/mol ${st.accBase} → ${st.acc}` }),
        ]);
      hit.addEventListener("pointermove", show);
      hit.addEventListener("pointerleave", hideTip);
      hit.addEventListener("focus", show);
      hit.addEventListener("blur", hideTip);
      hit.addEventListener("click", () => setFocus(r.id));
    });
    s("line", { class: "v-axis", x1: cx, x2: cx, y1: m.t - 4, y2: H - m.b }, svg);
  }

  /* --- Heatmap ---------------------------------------------------------------- */
  let heatEl = null;
  let drillEl = null;

  function cellColor(d) {
    if (!isValue(d)) return "var(--fill-2)";
    if (Math.abs(d) < EPS) return "var(--div-mid)";
    const pct = Math.round(Math.min(1, Math.abs(d) / CLAMP) * 88 + 12);
    return `color-mix(in oklab, var(${d < 0 ? "--div-better" : "--div-worse"}) ${pct}%, var(--div-mid))`;
  }

  // Rows exactly as the heatmap shows them (search, sort, hide unchanged, collapsed types)
  function heatModel() {
    const runs = runsIn();
    const q = state.dsQuery.trim().toLowerCase();
    const rows = filteredDatasets();
    const items = [];
    if (state.sort === "type") {
      TYPES.forEach((type) => {
        const ds = rows.filter((d) => d.type === type);
        if (!ds.length) return;
        const collapsed = state.collapsed.has(type) && !q;
        items.push({ kind: "group", type, ds, collapsed });
        if (!collapsed) ds.forEach((d) => items.push({ kind: "ds", d }));
      });
    } else {
      const f = focusRun();
      const sorted = state.sort === "name" ? [...rows].sort((a, b) => a.name.localeCompare(b.name)) : [...rows].sort((a, b) => Math.abs(delta(f, b)) - Math.abs(delta(f, a)));
      sorted.forEach((d) => items.push({ kind: "ds", d }));
    }
    return { runs, rows, items };
  }

  const groupDelta = (r, ds) => average(ds.map((d) => delta(r, d)).filter(isValue));

  function heatTable() {
    const { runs, items } = heatModel();
    return simpleTable(["Dataset / group", "Type", "CF22D"].concat(runs.map((run) => run.short)), items.map((item) => {
      if (item.kind === "ds") {
        const d = item.d;
        return [d.name, d.type, f2(d.original)].concat(runs.map((run) => `${f2(mue(run, d))} (${signed(delta(run, d))})`));
      }
      return [item.type, "Group mean", f2(average(item.ds.map((d) => d.original).filter(isValue)))].concat(runs.map((run) => {
        const paired = item.ds.filter((d) => delta(run, d) !== null);
        return `${f2(average(paired.map((d) => mue(run, d))))} (${signed(groupDelta(run, paired))})`;
      }));
    }));
  }

  function renderHeat() {
    if (!heatEl) return;
    const { runs, rows, items } = heatModel();

    const wrap = h("div", { class: "an-heat", style: `--heat-cols:${runs.length}` });
    wrap.append(
      h(
        "div",
        { class: "an-heat-row an-heat-head", role: "row" },
        h("span", { class: "an-heat-col", style: "text-align:left;padding-left:6px", text: "Dataset" }),
        runs.map((r) => h("span", { class: "an-heat-col" + (r.id === state.focus ? " focus" : ""), title: displayRunName(r), text: displayRunName(r) }))
      )
    );

    const scroll = h("div", { class: "an-heat-scroll" });
    const datasetRow = (d) =>
      h(
        "div",
        { class: "an-heat-row" + (d.name === state.dataset ? " selected" : ""), "data-ds": d.name },
        h("button", { type: "button", class: "an-heat-name", title: `${d.name} · ${d.type}`, text: d.name, onclick: () => selectDataset(d.name) }),
        runs.map((r) => h("button", { type: "button", class: "an-cell", "data-run": r.id, "aria-label": `${d.name}, ${displayRunName(r)}: MUE ${f2(mue(r, d))}, ${baseName(r)} ${f2(baseMue(r, d))}, change ${signed(delta(r, d))}`, style: `background:${cellColor(delta(r, d))}`, text: delta(r, d) === null ? "—" : null }))
      );

    if (!rows.length) scroll.append(h("div", { class: "an-empty-note", text: "No datasets match." }));
    items.forEach((it) => {
      if (it.kind === "ds") {
        scroll.append(datasetRow(it.d));
        return;
      }
      const { type, ds, collapsed } = it;
      scroll.append(
        h(
          "div",
          { class: "an-heat-row an-heat-group" + (collapsed ? " collapsed" : ""), "data-type": type },
          h(
            "button",
            {
              type: "button",
              class: "an-heat-name",
              "aria-expanded": String(!collapsed),
              title: type,
              onclick: () => {
                if (state.collapsed.has(type)) state.collapsed.delete(type);
                else state.collapsed.add(type);
                renderHeat();
                syncUrl();
              },
            },
            icon("i-chev"),
            h("span", { style: "overflow:hidden;text-overflow:ellipsis", text: type }),
            h("small", { text: ` ${ds.length}` })
          ),
          runs.map((r) => h("button", { type: "button", class: "an-cell", "data-run": r.id, "data-type": type, "aria-label": `${type}, ${displayRunName(r)}: mean change ${signed(groupDelta(r, ds))}`, style: `background:${cellColor(groupDelta(r, ds))}`, text: groupDelta(r, ds) === null ? "—" : null }))
        )
      );
    });

    // One delegated hover layer for every cell
    const showCell = (e) => {
      const cell = e.target.closest(".an-cell");
      if (!cell) return;
      const r = BY_ID[cell.dataset.run];
      if (cell.dataset.type) {
        const ds = filteredDatasets().filter((d) => d.type === cell.dataset.type);
        const md = groupDelta(r, ds);
        const better = ds.filter((d) => delta(r, d) < -EPS).length;
        const worse = ds.filter((d) => delta(r, d) > EPS).length;
        showTip(e, [
          h("div", { class: "an-tip-head", text: cell.dataset.type }),
          h("div", { class: "an-tip-sub", text: `${displayRunName(r)} · ${plural(ds.length, "dataset", "datasets")}` }),
          tipRow(md < 0 ? "an-key-better" : "an-key-worse", signed(md), `mean change vs ${baseName(r)}`),
          h("div", { class: "an-tip-sub", style: "margin:6px 0 0", text: `${better} improved · ${worse} worse` }),
        ]);
        return;
      }
      const d = DATASETS.find((x) => x.name === cell.parentElement.dataset.ds);
      const dv = delta(r, d);
      showTip(e, [
        h("div", { class: "an-tip-head", text: d.name }),
        h("div", { class: "an-tip-sub", text: `${displayRunName(r)} · ${d.type}` }),
        tipRow("an-key-1", f2(mue(r, d)), "MUE"),
        tipRow("an-key-ref", f2(baseMue(r, d)), baseName(r)),
        tipRow(dv < 0 ? "an-key-better" : "an-key-worse", signed(dv), dv === null ? "value or baseline unavailable" : Math.abs(dv) <= EPS ? "unchanged" : dv < 0 ? "better" : "worse"),
      ]);
    };
    scroll.addEventListener("pointerover", showCell);
    scroll.addEventListener("focusin", (event) => showCell({ target: event.target, currentTarget: event.target, type: "focus" }));
    scroll.addEventListener("focusout", hideTip);
    scroll.addEventListener("pointermove", (e) => {
      if (!tip.hidden && e.target.closest(".an-cell")) {
        const tw = tip.offsetWidth;
        const left = e.clientX + 16 + tw > window.innerWidth - 8 ? e.clientX - tw - 16 : e.clientX + 16;
        tip.style.left = left + "px";
        tip.style.top = e.clientY + 16 + "px";
      }
    });
    scroll.addEventListener("pointerout", (e) => {
      if (e.target.closest(".an-cell")) hideTip();
    });
    scroll.addEventListener("click", (e) => {
      const cell = e.target.closest(".an-cell");
      if (cell && cell.parentElement.dataset.ds) selectDataset(cell.parentElement.dataset.ds);
    });

    wrap.append(scroll);
    const prev = heatEl.querySelector(".an-heat");
    const keep = prev ? prev.scrollTop : 0;
    heatEl.replaceChildren(wrap);
    wrap.scrollTop = keep;
  }

  function selectDataset(name) {
    state.dataset = name;
    syncUrl();
    $$(".an-heat-row[data-ds]", heatEl || document).forEach((r) => r.classList.toggle("selected", r.dataset.ds === name));
    renderDrill();
  }

  /* --- Dataset drill-down ----------------------------------------------------- */
  function renderDrill() {
    if (!drillEl) return;
    const d = DATASETS.find((x) => x.name === state.dataset);
    if (!d) { drillEl.replaceChildren(h("p", { class: "an-empty-note", text: "Select a reference dataset to inspect it." })); return; }
    const runs = runsIn();
    const showTable = state.tables.has("drill");
    const viz = h("div", { class: "an-viz" });
    const c = h(
      "section",
      { class: "an-card", "aria-label": `Dataset ${d.name}` },
      h(
        "div",
        { class: "an-card-head" },
        h("div", { class: "an-card-title" }, h("h3", { text: d.name })),
        h(
          "div",
          { class: "an-card-tools" },
          h("div", { class: "an-legend" }, legendItem("an-key-1", "line", "MUE"), legendItem("an-key-ref", "line", "CF22D")),
          exportButton("drill", `${d.name} across runs`),
          h("button", { type: "button", class: "link", "aria-pressed": String(showTable), onclick: () => {
            if (showTable) state.tables.delete("drill"); else state.tables.add("drill");
            renderDrill(); syncUrl();
          } }, icon(showTable ? "i-chart" : "i-table"), showTable ? "Chart" : "Table")
        )
      ),
      h(
        "div",
        { class: "an-drill-add" },
        (() => {
          const inChart = state.trendDs.some((x) => x.name === d.name);
          const full = state.trendDs.length >= MAX_DS;
          return h(
            "button",
            {
              type: "button",
              class: "btn btn-secondary btn-sm",
              disabled: inChart || full,
              onclick: () => {
                if (addTrendDataset(d.name)) {
                  toast(`${d.name} added to MUE across runs (Trends)`);
                  renderDrill();
                  syncUrl();
                }
              },
            },
            icon(inChart ? "i-check" : "i-plus"),
            inChart ? "In MUE across runs" : full ? `Line chart full (${MAX_DS})` : "Add to MUE across runs"
          );
        })()
      ),
      h("div", { class: "an-card-body" }, showTable ? simpleTable(["Run", "MUE", "Baseline", "Change"], runs.map((run) => [displayRunName(run), f2(mue(run, d)), f2(baseMue(run, d)), signed(delta(run, d))])) : viz),
      h(
        "ul",
        { class: "an-drill-list" },
        runs.map((r) => {
          const dv = delta(r, d);
          return h(
            "li",
            { class: r.id === state.focus ? "focus" : null },
            h("span", { class: "mono", text: displayRunName(r) }),
            h("span", { text: f2(mue(r, d)) }),
            h("span", { class: Math.abs(dv) < EPS ? "muted" : dv < 0 ? "change-good" : "change-bad", text: signed(dv) })
          );
        })
      )
    );
    drillEl.replaceChildren(c);
    if (!showTable) requestAnimationFrame(() => { if (!disposed && viz.isConnected) drawDrill(viz, d); });
  }

  function drawDrill(el, d) {
    const runs = runsIn();
    const W = Math.max(220, el.clientWidth);
    const n = runs.length;
    const rotatedLabels = n > 6 || W < 360;
    const H = rotatedLabels ? 208 : 170;
    const m = { l: 40, r: 14, t: 12, b: rotatedLabels ? 62 : 26 };
    const iw = W - m.l - m.r;
    const ih = H - m.t - m.b;
    const band = iw / n;
    const xi = (i) => m.l + band * (i + 0.5);
    const vals = runs.map((r) => mue(r, d)).concat(d.original).filter(isValue);
    if (!vals.length) { el.append(h("div", { class: "an-empty-note", text: "No MUE values are available for this dataset in the included runs." })); return; }
    const span = Math.max(...vals) - Math.min(...vals) || Math.max(0.1, d.original * 0.05);
    const dom = niceDomain(Math.max(0, Math.min(...vals) - span * 0.3), Math.max(...vals) + span * 0.3, 4);
    const y = (v) => m.t + ih * (1 - (v - dom.lo) / (dom.hi - dom.lo));
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": `MUE of ${d.name} across runs` }, el);
    const fi = runs.findIndex((r) => r.id === state.focus);
    if (fi >= 0) s("rect", { class: "v-focus-band", x: xi(fi) - band / 2 + 2, y: m.t, width: band - 4, height: ih, rx: 6 }, svg);
    dom.ticks.forEach((t) => {
      s("line", { class: "v-grid", x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }, svg);
      s("text", { class: "v-tick", x: m.l - 6, y: y(t) + 4, "text-anchor": "end", text: tickText(t, dom.step) }, svg);
    });
    runs.forEach((r, i) => {
      const attrs = { class: "v-tick mono" + (r.id === state.focus ? " strong" : ""), x: xi(i), y: H - (rotatedLabels ? 16 : 8), "text-anchor": rotatedLabels ? "end" : "middle", text: displayRunName(r) };
      if (rotatedLabels) attrs.transform = `rotate(-42 ${xi(i)} ${H - 16})`;
      s("text", attrs, svg);
    });
    if (isValue(d.original)) s("line", { class: "v-line v-sref", x1: m.l, x2: W - m.r, y1: y(d.original), y2: y(d.original), "stroke-width": 1.5 }, svg);
    runs.forEach((r) => {
      const p = includedAncestor(r);
      if (!p || mue(p, d) === null || mue(r, d) === null) return;
      const a = runs.indexOf(p);
      const b = runs.indexOf(r);
      s("line", { class: "v-line v-s1", x1: xi(a), y1: y(mue(p, d)), x2: xi(b), y2: y(mue(r, d)) }, svg);
    });
    runs.forEach((r, i) => { if (mue(r, d) !== null) s("circle", { class: "v-dot v-f1", cx: xi(i), cy: y(mue(r, d)), r: r.id === state.focus ? 5.5 : 4.5 }, svg); });
  }

  /* ==========================================================================
     Figure export · Nature style
     Arial / Helvetica, 5–7 pt text, 8 pt bold lowercase panel label, black
     text, 0.5 pt axes with outward ticks, no gridlines, white background.
     Widths 89 / 120 / 136 / 183 mm, depth up to 247 mm. SVG keeps every
     label as editable text; PNG is rasterised at 300 or 600 dpi and carries
     that resolution in its pHYs chunk.
     ========================================================================== */
  const PT_MM = 72 / 25.4;
  const NAT = {
    font: "Arial, Helvetica, sans-serif",
    title: 7,
    tick: 6,
    small: 5,
    panel: 8,
    axis: 0.5,
    line: 1,
    ctx: 0.75,
    tickLen: 2.5,
    dot: 1.8,
    ink: "#000000",
    maxDepthPt: 247 * PT_MM,
  };
  const PRINT = { 1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a", 4: "#eda100", 5: "#e87ba4", 6: "#008300", 7: "#4a3aa7", 8: "#e34948", ref: "#8e8e93" };
  const PRINT_DIV = { better: "#2a78d6", mid: "#f0f0f0", worse: "#e34948" };
  const PRINT_PATH = "#a1a1a6";
  const PRINT_FRONTIER = "#9fc1ec";

  // OKLab mixing so printed heat colours match the on-screen color-mix()
  const toLin = (c) => ((c /= 255) <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const toSrgb = (c) => Math.round(Math.min(1, Math.max(0, c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055)) * 255);
  function hexToLab(hex) {
    const n = parseInt(hex.slice(1), 16);
    const r = toLin((n >> 16) & 255), g = toLin((n >> 8) & 255), b = toLin(n & 255);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const q = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * q, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * q, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * q];
  }
  function labToHex([L, A, B]) {
    const l = Math.pow(L + 0.3963377774 * A + 0.2158037573 * B, 3);
    const m = Math.pow(L - 0.1055613458 * A - 0.0638541728 * B, 3);
    const q = Math.pow(L - 0.0894841775 * A - 1.291485548 * B, 3);
    const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * q, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * q, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * q];
    return "#" + rgb.map((c) => toSrgb(c).toString(16).padStart(2, "0")).join("");
  }
  function mixHex(a, b, t) {
    const A = hexToLab(a);
    const B = hexToLab(b);
    return labToHex(A.map((v, i) => v * t + B[i] * (1 - t)));
  }
  function printCell(d) {
    if (!isValue(d)) return "#ffffff";
    if (Math.abs(d) < EPS) return PRINT_DIV.mid;
    return mixHex(d < 0 ? PRINT_DIV.better : PRINT_DIV.worse, PRINT_DIV.mid, Math.min(1, Math.abs(d) / CLAMP) * 0.88 + 0.12);
  }

  // Text metrics in points (Arial)
  const measureCtx = document.createElement("canvas").getContext("2d");
  function tw(str, size, bold) {
    measureCtx.font = `${bold ? "bold " : ""}${size}px Arial, Helvetica, sans-serif`;
    return measureCtx.measureText(String(str)).width;
  }

  const xe = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const r2 = (v) => Math.round(v * 100) / 100;
  const attrs = (o) =>
    Object.entries(o)
      .filter(([, v]) => v != null && v !== false)
      .map(([k, v]) => ` ${k}="${typeof v === "number" ? r2(v) : xe(v)}"`)
      .join("");

  // "MUE (kcal mol⁻¹)" with a real superscript that stays editable text
  const UNIT_TEXT = " (kcal mol−1)";
  const unitTitle = (prefix) => `${xe(prefix)} (kcal mol<tspan dy="-2.2" font-size="5">−1</tspan><tspan dy="2.2">)</tspan>`;

  function makeFig(wPt) {
    const out = [];
    const defs = [];
    const f = {
      w: wPt,
      h: 0,
      warn: null,
      defs,
      el: (tag, o, inner) => out.push(inner == null ? `<${tag}${attrs(o)}/>` : `<${tag}${attrs(o)}>${inner}</${tag}>`),
      line: (x1, y1, x2, y2, stroke = NAT.ink, w = NAT.axis, extra = {}) => f.el("line", { x1, y1, x2, y2, stroke, "stroke-width": w, ...extra }),
      text: (x, y, str, o = {}) =>
        f.el(
          "text",
          {
            x,
            y,
            "font-size": o.size || NAT.tick,
            "font-weight": o.bold ? "bold" : null,
            "text-anchor": o.anchor || null,
            fill: NAT.ink,
            transform: o.rotate ? `rotate(${o.rotate} ${r2(x)} ${r2(y)})` : null,
          },
          o.rich ? str : xe(str)
        ),
      dot: (cx, cy, r, fill) => f.el("circle", { cx, cy, r, fill, stroke: "#ffffff", "stroke-width": 0.5 }),
      body: () => out.join("\n"),
      toString: (title) =>
        `<?xml version="1.0" encoding="UTF-8"?>\n` +
        `<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="${r2(f.w / PT_MM)}mm" height="${r2(f.h / PT_MM)}mm" viewBox="0 0 ${r2(f.w)} ${r2(f.h)}" font-family="${NAT.font}">\n` +
        `<title>${xe(title)}</title>\n` +
        (defs.length ? `<defs>${defs.join("")}</defs>\n` : "") +
        `<rect width="${r2(f.w)}" height="${r2(f.h)}" fill="#ffffff"/>\n` +
        out.join("\n") +
        `\n</svg>\n`,
    };
    return f;
  }

  const plotHeight = (wPt) => Math.max(112, Math.min(200, wPt * 0.42));

  // Panel label (8 pt bold) and a frameless legend that wraps to the figure width
  function pHeader(f, panel, items) {
    let x0 = 0;
    if (panel) {
      f.text(0, NAT.panel, panel, { size: NAT.panel, bold: true });
      x0 = tw(panel, NAT.panel, true) + 7;
    }
    if (!items.length) return panel ? NAT.panel + 6 : 2;
    const rowH = 9;
    const key = 9;
    let line = 0;
    let x = x0;
    items.forEach((it) => {
      const w = key + 3 + tw(it.label, NAT.tick) + 9;
      if (x + w > f.w + 6 && x > x0) {
        line += 1;
        x = x0;
      }
      const cy = 5.8 + line * rowH;
      if (it.kind === "line") f.line(x, cy, x + key, cy, it.color, it.width || NAT.line, { "stroke-dasharray": it.dash });
      else if (it.kind === "dot") f.dot(x + key / 2, cy, NAT.dot, it.color);
      else f.el("rect", { x: x + 2, y: cy - 2.5, width: 5, height: 5, fill: it.color });
      f.text(x + key + 3, cy + 2.1, it.label);
      x += w;
    });
    return 5.8 + line * rowH + 8;
  }

  const yAxisWidth = (dom, fmt, title) => NAT.tickLen + 1.5 + Math.max(...dom.ticks.map((t) => tw(fmt(t), NAT.tick))) + (title ? 4.5 + NAT.title : 0) + 1;

  function pAxisY(f, { x, top, bottom, dom, y, fmt, title }) {
    f.line(x, top, x, bottom);
    let maxW = 0;
    dom.ticks.forEach((t) => {
      const yy = y(t);
      f.line(x - NAT.tickLen, yy, x, yy);
      const lab = fmt(t);
      maxW = Math.max(maxW, tw(lab, NAT.tick));
      f.text(x - NAT.tickLen - 1.5, yy + 2.1, lab, { anchor: "end" });
    });
    if (title) f.text(x - NAT.tickLen - 1.5 - maxW - 4.5, (top + bottom) / 2, title, { size: NAT.title, anchor: "middle", rotate: -90, rich: true });
  }

  function pAxisX(f, { y, x0, x1, dom, X, fmt, title }) {
    f.line(x0, y, x1, y);
    dom.ticks.forEach((t) => {
      f.line(X(t), y, X(t), y + NAT.tickLen);
      f.text(X(t), y + NAT.tickLen + 6.5, fmt(t), { anchor: "middle" });
    });
    if (title) f.text((x0 + x1) / 2, y + NAT.tickLen + 15.5, title, { size: NAT.title, anchor: "middle", rich: true });
    return y + NAT.tickLen + (title ? 18 : 9);
  }

  function pAxisRuns(f, { y, x0, x1, runs, xi, title }) {
    f.line(x0, y, x1, y);
    const band = runs.length > 1 ? xi(1) - xi(0) : x1 - x0;
    const crowded = Math.max(...runs.map((r) => tw(displayRunName(r), NAT.tick))) > band - 2;
    runs.forEach((r, i) => {
      f.line(xi(i), y, xi(i), y + NAT.tickLen);
      f.text(xi(i), y + NAT.tickLen + 6.5, displayRunName(r), { anchor: "middle" });
      f.text(xi(i), y + NAT.tickLen + 12.5, r.kind === "weight" ? `w ${weightText(r.inverseWeight)}` : "fork", { anchor: "middle", size: NAT.small });
    });
    if (title) f.text((x0 + x1) / 2, y + NAT.tickLen + 21.5, title, { size: NAT.title, anchor: "middle", rich: true });
    return y + NAT.tickLen + (title ? 24 : 15);
  }

  const linFmt = (dom) => (t) => tickText(t, dom.step);

  /* --- Print: MUE across runs ------------------------------------------------ */
  function pTrend(wPt, panel) {
    const graphic = trendGraphic(wPt, true, panel);
    const figure = makeFig(wPt);
    figure.el("g", {}, graphic.innerHTML);
    figure.h = Number(graphic.getAttribute("height"));
    return figure;
  }

  /* --- Print: trade-off scatter ---------------------------------------------- */
  function pTradeoff(wPt, panel) {
    const f = makeFig(wPt);
    const runs = runsIn();
    const originalInput = average(runs.map((run) => run.input.original).filter(isValue));
    const pts = runs.map((r) => ({ r, x: r.input.nonScf, y: scf(r) })).filter((point) => isValue(point.x) && isValue(point.y));
    if (!pts.length) { f.text(0, 10, "No paired non-SCF and SCF Input MUE values"); f.h = 20; return f; }
    const front = pts.filter((p) => !pts.some((q) => q !== p && q.x <= p.x && q.y <= p.y && (q.x < p.x || q.y < p.y))).sort((a, b) => a.x - b.x);
    const top =
      pHeader(f, panel, [
        { label: "Run", kind: "dot", color: PRINT[1] },
        { label: `CF22D Input MUE (${f2(originalInput)})`, kind: "line", color: PRINT.ref, width: NAT.ctx },
        { label: "Trade-off frontier", kind: "line", color: PRINT_FRONTIER, width: NAT.ctx },
      ]) + 3;

    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y).concat(isValue(originalInput) ? [originalInput] : []);
    const xr = Math.max(...xs) - Math.min(...xs) || 0.2;
    const yr = Math.max(...ys) - Math.min(...ys) || 0.02;
    const dx = niceDomain(Math.max(0, Math.min(...xs) - xr * 0.18), Math.max(...xs) + xr * 0.18, 5);
    const dy = niceDomain(Math.max(0, Math.min(...ys) - yr * 0.25), Math.max(...ys) + yr * 0.25, 4);
    const left = yAxisWidth(dy, linFmt(dy), true);
    const right = 6;
    const ph = plotHeight(wPt);
    const X = (v) => left + ((wPt - left - right) * (v - dx.lo)) / (dx.hi - dx.lo);
    const Y = (v) => top + ph * (1 - (v - dy.lo) / (dy.hi - dy.lo));

    pAxisY(f, { x: left, top, bottom: top + ph, dom: dy, y: Y, fmt: linFmt(dy), title: unitTitle("Input MUE, SCF") });
    const bottom = pAxisX(f, { y: top + ph, x0: left, x1: wPt - right, dom: dx, X, fmt: linFmt(dx), title: unitTitle("Input MUE, non-SCF") });

    if (isValue(originalInput)) f.line(left, Y(originalInput), wPt - right, Y(originalInput), PRINT.ref, NAT.ctx);
    f.defs.push(`<marker id="arrow" viewBox="0 0 6 6" refX="5.5" refY="3" markerWidth="3.2" markerHeight="3.2" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="${PRINT_PATH}"/></marker>`);
    pts.forEach((p) => {
      const a = includedAncestor(p.r);
      if (!a) return;
      const q = pts.find((z) => z.r.id === a.id);
      if (!q) return;
      const x1 = X(q.x), y1 = Y(q.y), x2 = X(p.x), y2 = Y(p.y);
      const len = Math.hypot(x2 - x1, y2 - y1);
      if (len < 7) return;
      const ux = (x2 - x1) / len, uy = (y2 - y1) / len;
      f.line(x1 + ux * 3, y1 + uy * 3, x2 - ux * 3.2, y2 - uy * 3.2, PRINT_PATH, 0.5, { "marker-end": "url(#arrow)" });
    });
    if (front.length > 1) f.el("polyline", { points: front.map((p) => `${r2(X(p.x))},${r2(Y(p.y))}`).join(" "), fill: "none", stroke: PRINT_FRONTIER, "stroke-width": NAT.ctx });

    const placed = pts.map((p) => ({ x1: X(p.x) - 2.5, x2: X(p.x) + 2.5, y1: Y(p.y) - 2.5, y2: Y(p.y) + 2.5 }));
    const hit = (b) => placed.some((o) => !(b.x2 < o.x1 || b.x1 > o.x2 || b.y2 < o.y1 || b.y1 > o.y2));
    pts.forEach((p) => {
      const cx = X(p.x), cy = Y(p.y);
      f.dot(cx, cy, 2.2, PRINT[1]);
      const label = displayRunName(p.r);
      const w = tw(label, NAT.small);
      const opts = [
        { x: cx + 3.5, y: cy + 1.8, a: null, b: { x1: cx + 3, x2: cx + 4 + w, y1: cy - 2.5, y2: cy + 2.5 } },
        { x: cx - 3.5, y: cy + 1.8, a: "end", b: { x1: cx - 4 - w, x2: cx - 3, y1: cy - 2.5, y2: cy + 2.5 } },
        { x: cx, y: cy - 3.8, a: "middle", b: { x1: cx - w / 2, x2: cx + w / 2, y1: cy - 8, y2: cy - 3 } },
        { x: cx, y: cy + 7.5, a: "middle", b: { x1: cx - w / 2, x2: cx + w / 2, y1: cy + 3, y2: cy + 8 } },
      ].filter((o) => o.b.x1 > left && o.b.x2 < wPt);
      const pick = opts.find((o) => !hit(o.b)) || opts[0];
      if (pick) {
        placed.push(pick.b);
        f.text(pick.x, pick.y, label, { size: NAT.small, anchor: pick.a });
      }
    });
    f.h = bottom + 2;
    return f;
  }

  /* --- Print: non-SCF vs SCF dumbbell ---------------------------------------- */
  function pDumbbell(wPt, panel) {
    const f = makeFig(wPt);
    const runs = runsIn();
    const groups = [
      { label: "New fits (inverse weight)", runs: runs.filter((r) => r.kind === "weight") },
      { label: "Forks (tuned weights)", runs: runs.filter((r) => r.kind === "fork") },
    ].filter((g) => g.runs.length);
    let yc = pHeader(f, panel, [
      { label: "Non-SCF", kind: "dot", color: PRINT[1] },
      { label: "SCF", kind: "dot", color: PRINT[2] },
    ]);
    const labelW = Math.max(...runs.map((r) => tw(displayRunName(r), NAT.tick)), ...groups.map((g) => tw(g.label, NAT.tick, true) * 0.6)) + 6;
    const rightW = Math.max(tw("SCF − non-SCF", NAT.small), tw("not calculated", NAT.small)) + 4;
    const x0 = labelW;
    const x1 = wPt - rightW - 4;
    const vals = runs.flatMap((r) => [r.input.nonScf, scf(r)]).filter((v) => v != null);
    const dom = niceDomain(0, Math.max(0, ...vals) * 1.08, wPt < 300 ? 4 : 6);
    const X = (v) => x0 + ((x1 - x0) * (v - dom.lo)) / (dom.hi - dom.lo);
    const rowH = 10;

    f.text(wPt, yc + 5, "SCF − non-SCF", { size: NAT.small, anchor: "end" });
    groups.forEach((g) => {
      yc += 8.5;
      f.text(0, yc, g.label, { bold: true });
      yc += 2;
      g.runs.forEach((r) => {
        const cy = yc + rowH / 2;
        f.text(labelW - 4, cy + 2.1, displayRunName(r), { anchor: "end" });
        const a = r.input.nonScf;
        const b = scf(r);
        if (a != null && b != null) f.line(X(a), cy, X(b), cy, PRINT_PATH, NAT.line);
        if (a != null) f.dot(X(a), cy, 2, PRINT[1]);
        if (b != null) f.dot(X(b), cy, 2, PRINT[2]);
        const right = b != null ? signed(difference(b, a)) : scfStateText(r);
        f.text(wPt, cy + 2.1, right, { anchor: "end", size: b != null ? NAT.tick : NAT.small });
        yc += rowH;
      });
    });
    const bottom = pAxisX(f, { y: yc + 3, x0, x1, dom, X, fmt: linFmt(dom), title: unitTitle("Input MUE") });
    f.h = bottom + 2;
    return f;
  }

  /* --- Print: wavefunction overlap ------------------------------------------- */
  function pOverlap(wPt, panel) {
    const f = makeFig(wPt);
    const runs = runsIn();
    const values = runs.map((run) => run.overlap?.mean).filter(isValue);
    const dom = values.length ? overlapDomain(values, wPt < 300 ? 4 : 6) : { lo: 0, hi: 1, ticks: [0, .25, .5, .75, 1], step: .25 };
    let yc = pHeader(f, panel, []);
    const labelW = Math.max(36, ...runs.map((run) => tw(displayRunName(run), NAT.tick))) + 6;
    const rightW = Math.max(tw("not calculated", NAT.small), tw("0.0000", NAT.tick)) + 4;
    const x0 = labelW;
    const x1 = wPt - rightW - 4;
    const X = (value) => x0 + (x1 - x0) * Math.max(0, Math.min(1, (value - dom.lo) / (dom.hi - dom.lo)));
    const rowH = 10;
    f.text(wPt, yc + 5, "Occupied-orbital overlap", { size: NAT.small, anchor: "end" });
    runs.forEach((run) => {
      yc += rowH;
      const value = run.overlap?.mean;
      f.text(labelW - 4, yc + 2.1, displayRunName(run), { anchor: "end" });
      if (isValue(value)) {
        f.line(x0, yc + 1, X(value), yc + 1, PRINT_PATH, NAT.line);
        f.dot(X(value), yc + 1, 2, PRINT[1]);
        f.text(wPt, yc + 2.1, value.toFixed(4), { anchor: "end" });
      } else f.text(wPt, yc + 2.1, run.input.scf.state === "running" ? "calculating" : "—", { anchor: "end", size: NAT.small });
    });
    const bottom = pAxisX(f, { y: yc + 3, x0, x1, dom, X, fmt: (value) => overlapTickText(value, dom.step), title: "Overlap" });
    f.h = bottom + 2;
    return f;
  }

  /* --- Print: improved vs worse ---------------------------------------------- */
  function pCounts(wPt, panel) {
    const f = makeFig(wPt);
    const runs = runsIn();
    let yc =
      pHeader(f, panel, [
        { label: "Improved (lower MUE)", kind: "rect", color: PRINT_DIV.better },
        { label: "Worse (higher MUE)", kind: "rect", color: PRINT_DIV.worse },
      ]) + 2;
    const labelW = Math.max(...runs.map((r) => tw(displayRunName(r), NAT.tick))) + 6;
    const x0 = labelW;
    const x1 = wPt - 2;
    const cx = (x0 + x1) / 2;
    const max = Math.max(1, ...runs.map((r) => Math.max(changeStats(r).improved, changeStats(r).worse)));
    const dom = niceDomain(0, max, 3);
    const sc = (cx - x0 - 12) / dom.hi;
    const rowH = 10;
    const top = yc;
    runs.forEach((r) => {
      const st = changeStats(r);
      const cy = yc + rowH / 2;
      f.text(labelW - 4, cy + 2.1, displayRunName(r), { anchor: "end" });
      f.el("rect", { x: cx - st.improved * sc, y: cy - 3, width: st.improved * sc, height: 6, fill: PRINT_DIV.better });
      f.el("rect", { x: cx, y: cy - 3, width: st.worse * sc, height: 6, fill: PRINT_DIV.worse });
      f.text(cx - st.improved * sc - 1.5, cy + 2.1, st.improved, { anchor: "end" });
      f.text(cx + st.worse * sc + 1.5, cy + 2.1, st.worse);
      yc += rowH;
    });
    f.line(cx, top, cx, yc);
    const ticks = dom.ticks.filter((t) => t > 0);
    const y = yc + 2;
    f.line(cx - dom.hi * sc, y, cx + dom.hi * sc, y);
    [0, ...ticks].forEach((t) => {
      [-1, 1].forEach((sgn) => {
        if (t === 0 && sgn < 0) return;
        const xx = cx + sgn * t * sc;
        f.line(xx, y, xx, y + NAT.tickLen);
        f.text(xx, y + NAT.tickLen + 6.5, t, { anchor: "middle" });
      });
    });
      f.text(cx, y + NAT.tickLen + 15.5, `Reference datasets vs CF22D original (n = ${filteredDatasets().length})`, { size: NAT.title, anchor: "middle" });
    f.h = y + NAT.tickLen + 20;
    return f;
  }

  /* --- Print: heatmap -------------------------------------------------------- */
  function pHeat(wPt, panel) {
    const f = makeFig(wPt);
    const { runs, items } = heatModel();
    let yc = pHeader(f, panel, []);
    // Diverging scale legend
    const scaleTitle = "ΔMUE vs CF22D original";
    const tW = tw(scaleTitle + UNIT_TEXT, NAT.tick) + 4;
    const gx = (panel ? tw(panel, NAT.panel, true) + 7 : 0) + tW;
    const gy = panel ? 3 : yc + 1;
    f.text(gx - 4, gy + 4.4, unitTitle(scaleTitle), { anchor: "end", rich: true });
    const stops = [];
    for (let k = 0; k <= 10; k++) {
      const d = -CLAMP + (2 * CLAMP * k) / 10;
      stops.push(`<stop offset="${k * 10}%" stop-color="${printCell(d)}"/>`);
    }
    f.defs.push(`<linearGradient id="div" x1="0" x2="1" y1="0" y2="0">${stops.join("")}</linearGradient>`);
    const gw = 56;
    f.el("rect", { x: gx, y: gy, width: gw, height: 5, fill: "url(#div)" });
    [
      [0, `≤ −${CLAMP}`],
      [0.5, "0"],
      [1, `≥ +${CLAMP}`],
    ].forEach(([t, lab]) => f.text(gx + gw * t, gy + 11.5, lab, { size: NAT.small, anchor: t === 0 ? "start" : t === 1 ? "end" : "middle" }));
    yc = Math.max(yc, gy + 16);

    const nameW = Math.max(40, ...items.map((it) => (it.kind === "group" ? tw(it.type, NAT.small, true) + 2 : tw(it.d.name, NAT.small) + 4))) + 4;
    const gap = 0.6;
    const cw = (wPt - nameW) / Math.max(1, runs.length);
    let rowH = 6.4;
    const need = yc + 9 + items.length * rowH;
    if (need > NAT.maxDepthPt) {
      rowH = Math.max(5.2, (NAT.maxDepthPt - yc - 9) / items.length);
      if (yc + 9 + items.length * rowH > NAT.maxDepthPt) f.warn = `${items.length} rows exceed one Nature page (247 mm). Collapse types or filter rows for a submission figure.`;
    }
    runs.forEach((r, i) => f.text(nameW + cw * i + cw / 2, yc + 6, displayRunName(r), { anchor: "middle" }));
    yc += 9;
    items.forEach((it) => {
      if (it.kind === "group") {
        f.text(0, yc + rowH - 1.6, it.type, { size: NAT.small, bold: true });
        runs.forEach((r, i) => f.el("rect", { x: nameW + cw * i + gap / 2, y: yc + gap / 2, width: cw - gap, height: rowH - gap, fill: printCell(groupDelta(r, it.ds)) }));
      } else {
        f.text(2, yc + rowH - 1.6, it.d.name, { size: NAT.small });
        runs.forEach((r, i) => f.el("rect", { x: nameW + cw * i + gap / 2, y: yc + gap / 2, width: cw - gap, height: rowH - gap, fill: printCell(delta(r, it.d)) }));
      }
      yc += rowH;
    });
    f.h = yc + 2;
    return f;
  }

  /* --- Print: one dataset across runs ----------------------------------------- */
  function pDrill(wPt, panel) {
    const f = makeFig(wPt);
    const d = DS_BY_NAME[state.dataset];
    const runs = runsIn();
    const top =
      pHeader(f, panel, [
        { label: d.name, kind: "line", color: PRINT[1] },
        { label: `CF22D original (${f2(d.original)})`, kind: "line", color: PRINT.ref, width: NAT.ctx },
      ]) + 3;
    const vals = runs.map((r) => mue(r, d)).concat(d.original).filter(isValue);
    if (!vals.length) { f.text(0, top + 10, "No dataset MUE values available"); f.h = top + 20; return f; }
    const span = Math.max(...vals) - Math.min(...vals) || Math.max(0.1, d.original * 0.05);
    const dom = niceDomain(Math.max(0, Math.min(...vals) - span * 0.3), Math.max(...vals) + span * 0.3, 4);
    const left = yAxisWidth(dom, linFmt(dom), true);
    const right = 4;
    const ph = plotHeight(wPt);
    const y = (v) => top + ph * (1 - (v - dom.lo) / (dom.hi - dom.lo));
    const band = (wPt - left - right) / runs.length;
    const xi = (i) => left + band * (i + 0.5);
    pAxisY(f, { x: left, top, bottom: top + ph, dom, y, fmt: linFmt(dom), title: unitTitle(`${d.name} MUE`) });
    const bottom = pAxisRuns(f, { y: top + ph, x0: left, x1: wPt - right, runs, xi, title: "Run" });
    if (isValue(d.original)) f.line(left, y(d.original), wPt - right, y(d.original), PRINT.ref, NAT.ctx);
    runs.forEach((r, i) => {
      const p = includedAncestor(r);
      if (p && mue(p, d) !== null && mue(r, d) !== null) f.line(xi(runs.indexOf(p)), y(mue(p, d)), xi(i), y(mue(r, d)), PRINT[1], NAT.line, { "stroke-linecap": "round" });
    });
    runs.forEach((r, i) => { if (mue(r, d) !== null) f.dot(xi(i), y(mue(r, d)), NAT.dot, PRINT[1]); });
    f.h = bottom + 2;
    return f;
  }

  const PRINTERS = { trend: pTrend, tradeoff: pTradeoff, scf: pDumbbell, overlap: pOverlap, counts: pCounts, heat: pHeat, drill: pDrill };

  /* --- PNG: rasterise the SVG and record its dpi ------------------------------ */
  const CRC = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  async function withDpi(blob, dpi) {
    const src = new Uint8Array(await blob.arrayBuffer());
    const ppm = Math.round(dpi / 0.0254);
    const chunk = new Uint8Array(21);
    const dv = new DataView(chunk.buffer);
    dv.setUint32(0, 9);
    chunk.set([0x70, 0x48, 0x59, 0x73], 4); // "pHYs"
    dv.setUint32(8, ppm);
    dv.setUint32(12, ppm);
    chunk[16] = 1; // unit: metre
    dv.setUint32(17, crc32(chunk.subarray(4, 17)));
    // Drop any existing pHYs, then insert ours right after IHDR
    const parts = [src.subarray(0, 33), chunk];
    let p = 33;
    while (p < src.length) {
      const len = new DataView(src.buffer, src.byteOffset + p).getUint32(0);
      const type = String.fromCharCode(...src.subarray(p + 4, p + 8));
      const end = p + 12 + len;
      if (type !== "pHYs") parts.push(src.subarray(p, end));
      p = end;
    }
    return new Blob(parts, { type: "image/png" });
  }

  async function svgToPng(fig, dpi) {
    let d = dpi;
    let w = Math.round((fig.wPt / 72) * d);
    let hh = Math.round((fig.hPt / 72) * d);
    const LIMIT = 16e6; // stay under the smallest browser canvas limit
    if (w * hh > LIMIT) {
      d = Math.floor(d * Math.sqrt(LIMIT / (w * hh)));
      w = Math.round((fig.wPt / 72) * d);
      hh = Math.round((fig.hPt / 72) * d);
    }
    const url = URL.createObjectURL(new Blob([fig.svg], { type: "image/svg+xml" }));
    try {
      const img = new Image();
      await new Promise((ok, fail) => {
        img.onload = ok;
        img.onerror = fail;
        img.src = url;
      });
      const c = document.createElement("canvas");
      c.width = w;
      c.height = hh;
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, w, hh);
      ctx.drawImage(img, 0, 0, w, hh);
      const blob = await new Promise((ok) => c.toBlob(ok, "image/png"));
      return { blob: await withDpi(blob, d), dpi: d, w, h: hh };
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function downloadBlob(blob, name) {
    const a = h("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 0);
  }

  /* --- Export dialog ---------------------------------------------------------- */
  const expState = { chart: null, title: "", format: "svg", width: 89, dpi: 300, panel: "" };
  let expDlg = null;
  let expUrl = null;

  function expSeg(name, label, options, get, set) {
    const lid = `anExp-${name}-l`;
    return h(
      "div",
      { class: "field", "data-field": name },
      h("span", { class: "flabel", id: lid, text: label }),
      h(
        "div",
        { class: "seg full", role: "group", "aria-labelledby": lid },
        options.map(([v, t]) =>
          h("button", {
            type: "button",
            "data-v": String(v),
            "aria-pressed": String(String(get()) === String(v)),
            onclick: (e) => {
              set(v);
              setPressed(e.currentTarget.parentElement, "v", String(v));
              updateExport();
            },
            text: t,
          })
        )
      )
    );
  }

  function buildExportDialog() {
    expDlg = h(
      "dialog",
      { class: "sheet an-export", "aria-labelledby": "anExpTitle" },
      h(
        "div",
        { class: "sheet-head" },
        h("div", null, h("h3", { id: "anExpTitle", text: "Export figure" }), h("p", { id: "anExpSub" })),
        h("button", { type: "button", class: "icon-btn", "aria-label": "Close", onclick: () => expDlg.close() }, icon("i-x"))
      ),
      h(
        "div",
        { class: "sheet-body" },
        h("div", { class: "an-exp-preview" }, h("img", { id: "anExpImg", alt: "Preview of the exported figure" })),
        h("p", { class: "an-exp-warn", id: "anExpWarn", hidden: true }),
        h(
          "div",
          null,
          h("div", { class: "group-label", text: "Figure" }),
          h(
            "div",
            { class: "group" },
            expSeg("format", "Format", [["svg", "SVG"], ["png", "PNG"]], () => expState.format, (v) => (expState.format = v)),
            expSeg("width", "Width", [[89, "89 mm"], [120, "120 mm"], [136, "136 mm"], [183, "183 mm"]], () => expState.width, (v) => (expState.width = v)),
            expSeg("dpi", "Resolution", [[300, "300 dpi"], [600, "600 dpi"]], () => expState.dpi, (v) => (expState.dpi = v)),
            h(
              "div",
              { class: "field" },
              h("label", { for: "anExpPanel", text: "Panel label" }),
              h("input", {
                class: "inp",
                id: "anExpPanel",
                maxlength: 2,
                placeholder: "None",
                autocomplete: "off",
                style: "max-width:120px",
                oninput: (e) => {
                  expState.panel = e.target.value.trim().toLowerCase();
                  updateExport();
                },
              }),
              h("div", { class: "help", text: "Optional. Nature uses 8 pt bold lowercase letters: a, b, c." })
            )
          )
        ),
        h(
          "p",
          { class: "an-exp-note" },
          h("b", { text: "Nature style. " }),
          "Arial, 5–7 pt text, black labels, 0.5 pt axes with outward ticks, no gridlines, white background. Widths match Nature's 1, 1.5 and 2 column sizes. Nature prefers vector files for final figures: use SVG (open it in Illustrator or Inkscape to save as PDF or EPS). PNG suits drafts, slides and Extended Data."
        )
      ),
      h(
        "div",
        { class: "sheet-foot" },
        h("span", { class: "hint", id: "anExpHint", role: "status" }),
        h("button", { type: "button", class: "btn btn-secondary", onclick: () => expDlg.close() }, "Cancel"),
        h("button", { type: "button", class: "btn btn-primary", id: "anExpGo", onclick: doExport }, icon("i-down"), h("span", { text: "Download SVG" }))
      )
    );
    expDlg.addEventListener("close", () => {
      if (expUrl) URL.revokeObjectURL(expUrl);
      expUrl = null;
    });
    root.append(expDlg);
  }

  function buildFigure() {
    const wPt = expState.width * PT_MM;
    if (expState.chart === "density") {
      const chain = densityChainModel();
      const figure = densityNatureSvg(chain, expState.width);
      return { svg: figure.svg, wPt: figure.wPt, hPt: figure.hPt, warn: null };
    }
    const f = PRINTERS[expState.chart](wPt, expState.panel);
    return { svg: f.toString(`${JOB.id} · ${expState.title}`), wPt, hPt: f.h, warn: f.warn };
  }

  function updateExport() {
    const fig = buildFigure();
    if (expUrl) URL.revokeObjectURL(expUrl);
    expUrl = URL.createObjectURL(new Blob([fig.svg], { type: "image/svg+xml" }));
    const img = $("#anExpImg");
    img.src = expUrl;
    const tall = fig.hPt > fig.wPt * 1.2;
    img.parentElement.classList.toggle("tall", tall);
    img.style.width = tall ? `min(100%, ${Math.round(expState.width * 3.78 * 1.7)}px)` : "";
    const png = expState.format === "png";
    $('[data-field="dpi"]', expDlg).hidden = !png;
    const wmm = expState.width;
    const hmm = fig.hPt / PT_MM;
    let hint = `${wmm} × ${hmm.toFixed(0)} mm`;
    if (png) {
      const px = (v) => Math.round((v / 72) * expState.dpi);
      hint += ` · ${px(fig.wPt)} × ${px(fig.hPt)} px`;
    } else hint += " · editable text";
    $("#anExpHint").textContent = hint;
    $("#anExpGo span").textContent = png ? "Download PNG" : "Download SVG";
    const sub = expState.chart === "heat" ? `${expState.title} · the ${heatModel().items.length} rows currently shown` : expState.chart === "density" ? `${expState.title} · R0–R${densityChainModel()?.runs.length - 1}` : expState.title;
    $("#anExpSub").textContent = sub;
    const warn = $("#anExpWarn");
    warn.hidden = !fig.warn;
    warn.textContent = fig.warn || "";
  }

  function openExport(chart, title) {
    expState.chart = chart;
    expState.title = title;
    if (!expDlg) buildExportDialog();
    hideTip();
    closePicker();
    updateExport();
    expDlg.showModal();
  }

  async function doExport() {
    const fig = buildFigure();
    const base = `${state.selectedJobs.size > 1 ? "multi-job" : state.job}-${expState.chart}${expState.panel ? "-" + expState.panel : ""}-${expState.width}mm`;
    const btn = $("#anExpGo");
    btn.disabled = true;
    try {
      if (expState.format === "svg") {
        downloadBlob(new Blob([fig.svg], { type: "image/svg+xml" }), `${base}.svg`);
        toast(`Saved ${base}.svg`);
      } else {
        const out = await svgToPng(fig, expState.dpi);
        downloadBlob(out.blob, `${base}-${out.dpi}dpi.png`);
        toast(out.dpi < expState.dpi ? `Saved at ${out.dpi} dpi (figure too large for ${expState.dpi} dpi)` : `Saved ${base}-${out.dpi}dpi.png`);
      }
      expDlg.close();
    } catch (err) {
      toast("Export failed. Try SVG instead.");
    } finally {
      btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------------------
     CSV export (current inclusion + baseline)
     ------------------------------------------------------------------------ */
  function exportCsv() {
    const runs = runsIn();
    const esc = (value) => {
      const v = value == null ? "" : typeof value === "string" && /^[=+@-]/.test(value) ? "'" + value : value;
      return /[",\r\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
    };
    const lines = [];
    lines.push(["section", "run", "kind", "inverse_weight", "input_mue_nonscf", "input_mue_scf", "scf_state", "cf22d_input_mue"].join(","));
    runs.forEach((r) => lines.push(["input", displayRunName(r), r.kind, r.inverseWeight ?? "", r.input.nonScf, scf(r) ?? "", r.input.scf.state, r.input.original].map(esc).join(",")));
    lines.push("");
    lines.push(["dataset", "type", "cf22d_original"].concat(runs.flatMap((r) => [`${displayRunName(r)}_mue`, `${displayRunName(r)}_delta_vs_original`])).map(esc).join(","));
    DATASETS.forEach((d) => lines.push([d.name, d.type, d.original].concat(runs.flatMap((r) => [mue(r, d), delta(r, d) === null ? null : Math.round(delta(r, d) * 1000) / 1000])).map(esc).join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = h("a", { href: URL.createObjectURL(blob), download: `${state.selectedJobs.size > 1 ? "multi-job" : state.job}-analysis.csv` });
    document.body.append(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 0);
  }

  /* ------------------------------------------------------------------------
     Wiring
     ------------------------------------------------------------------------ */
  function render() {
    statCache.clear();
    renderSidebar();
    renderHeader();
    renderPanel();
  }

  $("#anLevel").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.level = b.dataset.level;
    state.runQuery = "";
    $("#anRunSearch").value = "";
    renderSidebar();
  });

  $("#anKind").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.kind = b.dataset.kind;
    renderSidebar();
    syncUrl();
  });

  $("#anRunSearch").addEventListener("input", (e) => {
    state.runQuery = e.target.value;
    renderSidebar();
  });

  const tablist = $('[role="tablist"]', root);
  tablist.addEventListener("click", (e) => {
    const b = e.target.closest('[role="tab"]');
    if (!b || b.dataset.tab === state.tab) return;
    state.tab = b.dataset.tab;
    render();
  });
  tablist.addEventListener("keydown", (e) => {
    const tabs = $$('[role="tab"]', tablist);
    const i = tabs.findIndex((t) => t.dataset.tab === state.tab);
    let j = null;
    if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
    if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
    if (e.key === "Home") j = 0;
    if (e.key === "End") j = tabs.length - 1;
    if (j == null) return;
    e.preventDefault();
    state.tab = tabs[j].dataset.tab;
    render();
    tabs[j].focus();
  });

  $("#anExport").addEventListener("click", exportCsv);
  $(".js-new").addEventListener("click", actions.onNew);
  const refreshButton = h("button", { type: "button", class: "icon-btn", "aria-label": "Refresh analysis", title: "Refresh analysis", onclick: actions.onRefresh }, icon("i-refresh"));
  $("#anActions").prepend(refreshButton);

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !document.querySelector("dialog[open]") && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      e.preventDefault();
      $("#anRunSearch").focus();
    }
  }, { signal: lifecycle.signal });

  // Redraw SVG charts when the panel width changes
  let lastW = 0;
  let raf = 0;
  const resizeObserver = new ResizeObserver((entries) => {
    const w = Math.round(entries[0].contentRect.width);
    if (w === lastW) return;
    lastW = w;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      if (disposed) return;
      drawCharts();
      if (state.tab === "changes") {
        const d = DATASETS.find((x) => x.name === state.dataset);
        const viz = drillEl && $(".an-viz", drillEl);
        if (d && viz) {
          viz.replaceChildren();
          drawDrill(viz, d);
        }
      }
    });
  });
  resizeObserver.observe(panel);

  window.addEventListener("scroll", () => {
    if (!tip.hidden && focusedTip?.isConnected && document.activeElement === focusedTip) {
      positionTip({ type: "focus", currentTarget: focusedTip });
    } else hideTip();
  }, { passive: true, signal: lifecycle.signal });

  render();
  return {
    update(next) {
      const allIncluded = state.included.size === RUNS.length;
      const previousKeys = new Set(RUNS.map(stableKey));
      const includedKeys = new Set(runsIn().map(stableKey));
      const focusedKey = focusRun() ? stableKey(focusRun()) : null;
      const previousJobs = new Set(JOB.selectedJobIds || [JOB.id]);
      DATA = next; JOB = DATA.job; RUNS = JOB.runs; DATASETS = JOB.datasets;
      TYPES = [...new Set(DATASETS.map((d) => d.type))];
      BY_ID = Object.fromEntries(RUNS.map((r) => [r.id, r]));
      DS_BY_NAME = Object.fromEntries(DATASETS.map((d) => [d.name, d]));
      state.selectedJobs = new Set(next.selectedJobIds || next.job.selectedJobIds || [next.focusJobId || next.job.primaryJobId || next.job.id]);
      if (!state.selectedJobs.has(state.job)) state.job = next.focusJobId || [...state.selectedJobs][0];
      state.included = new Set(RUNS.filter((run) => includedKeys.has(stableKey(run)) || !previousJobs.has(run.jobId) || (allIncluded && !previousKeys.has(stableKey(run)))).map((run) => run.id));
      for (const run of RUNS) {
        if (state.included.size >= Math.min(2, RUNS.length)) break;
        state.included.add(run.id);
      }
      state.focus = runsIn().find((run) => stableKey(run) === focusedKey)?.id || runsIn().filter((run) => run.jobId === state.job).at(-1)?.id || runsIn().at(-1)?.id || "";
      if (!DS_BY_NAME[state.dataset]) state.dataset = null;
      state.trendDs = state.trendDs.filter((dataset) => DS_BY_NAME[dataset.name]);
      render();
    },
    updateJobs(jobs) { DATA.jobs = jobs; renderSidebar(); },
    cancelJobChange() {
      state.selectedJobs = new Set(JOB.selectedJobIds || [JOB.id]);
      if (!state.selectedJobs.has(state.job)) state.job = [...state.selectedJobs][0];
      render();
    },
    setLoading(loading) {
      root.classList.toggle("an-refreshing", loading);
      root.setAttribute("aria-busy", String(loading));
      refreshButton.disabled = loading;
    },
    destroy() {
      disposed = true; lifecycle.abort(); resizeObserver.disconnect(); cancelAnimationFrame(raf);
      if (expUrl) URL.revokeObjectURL(expUrl);
      expDlg?.close(); expDlg?.remove(); root.replaceChildren();
    },
  };
}
