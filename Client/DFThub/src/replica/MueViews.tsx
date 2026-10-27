import { useId, useMemo, useState } from "react";
import type { DatasetMue } from "./mue";
import { compareDatasets, overallByType, overviewStats, typeNames } from "./mueAnalysis";
import type { Comparison } from "./mueAnalysis";
import type { WorkspaceTestSet } from "./testSet";

const views = [["overview", "Overview"], ["types", "Overall MUE by type"], ["datasets", "MUE by dataset"]] as const;
type View = typeof views[number][0];
type BarRow = { key: string; name: string; value: number | null; original: number | null; subtitle?: string };

function ComparisonBars({ rows, scope }: { rows: BarRow[]; scope: string }) {
  const max = Math.max(1, Math.ceil(Math.max(0, ...rows.flatMap((row) => [row.value ?? 0, row.original ?? 0]))));
  return <>
    <div className="mue-legend"><span><i className="mue-swatch original" />Original (CF22D)</span><span><i className="mue-swatch optimized" />Optimized</span></div>
    <div className="bars" aria-label={scope}>
      {rows.map((row) => <div className="mue-pair" key={row.key} data-dataset={row.key}>
        <div className="mue-dataset">{row.name}{row.subtitle && <span className="mue-group-subtitle">{row.subtitle}</span>}</div>
        {([["original", "Original", row.original], ["optimized", "Optimized", row.value]] as const).map(([series, label, value]) =>
          <div key={series} className="bar-row" data-series={series} title={`${row.name} · ${label}: ${value === null ? "not available" : value.toFixed(4) + " kcal/mol"}`}>
            <span className="lbl">{label}</span>
            <span className="bar-track">{value !== null && <span className={`bar ${series}`} style={{ display: "block", width: `${value / max * 100}%`, minWidth: value === 0 ? 0 : undefined }} />}</span>
            <span className="v num" aria-label={`${row.name} ${label} MUE`}>{value === null ? "—" : value.toFixed(2)}</span>
          </div>)}
      </div>)}
    </div>
    <div className="axis" aria-hidden="true"><span /><div>{[0, .25, .5, .75, 1].map((ratio) => <span key={ratio} className="num">{Number((ratio * max).toFixed(2))}</span>)}</div><span /></div>
  </>;
}

function ChangeList({ rows, title, variant }: { rows: Comparison[]; title: string; variant: "worse" | "better" }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  return <section className={`mue-changes ${variant}`} aria-label={title}>
    <header><h4>{title}</h4>{rows.length > 5 && <button type="button" className="link" aria-controls={id} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Show top 5" : `See all ${rows.length}`}</button>}</header>
    <ul id={id}>{(expanded ? rows : rows.slice(0, 5)).map((row) => <li key={row.key}>
      <span className="change-name" title={row.name}>{row.name}</span><span className="change-values mono num">{row.original!.toFixed(2)} → {row.value.toFixed(2)}</span>
      <strong className="change-delta num">{row.delta! > 0 ? "+" : "−"}{Math.abs(row.delta!).toFixed(2)}</strong>
    </li>)}{!rows.length && <li className="muted">No paired reference datasets {variant === "worse" ? "got worse" : "improved"}.</li>}</ul>
  </section>;
}

export default function MueViews(props: {
  rows: DatasetMue[]; original: Map<string, number>; weights: string; counts: Record<string, number>;
  testSet?: WorkspaceTestSet | null;
}) {
  const [view, setView] = useState<View>("overview");
  const id = useId();
  const rows = useMemo(() => compareDatasets(props.rows, props.original, props.weights, props.counts), [props.rows, props.original, props.weights, props.counts]);
  const stats = useMemo(() => overviewStats(rows), [rows]);
  const groups = useMemo(() => overallByType(rows), [rows]);
  const excluded = rows.filter((row) => row.original === null || (row.type !== "Input" && row.points === null)).length;
  const input = stats.input;
  const percent = input?.original && input.original > 0 ? (input.value - input.original) / input.original * 100 : null;
  const test = props.testSet;
  const testRow: BarRow | null = test ? { key: "test_input", name: "Test", value: test.value, original: test.original,
    subtitle: `Test set${test.points === null ? "" : ` · ${test.points} data points`}` } : null;
  const typeRows: BarRow[] = groups.map((group) => ({ key: group.key.toLowerCase(), name: group.key, original: group.original, value: group.value,
    subtitle: `${typeNames[group.key]} · ${group.datasets} dataset${group.datasets === 1 ? "" : "s"}${group.points === null ? "" : ` · ${group.points} data points`}` }));
  const datasetRows: BarRow[] = [...rows];
  if (testRow) {
    typeRows.splice(typeRows.findIndex((row) => row.key === "input") + 1, 0, testRow);
    datasetRows.splice(datasetRows.findIndex((row) => row.key === "input") + 1, 0, testRow);
  }

  return <section className="box mue-comparison mue-views" aria-label="MUE analysis">
    <div className="box-head mue-views-head">
      <div className="seg mue-view-switch" role="group" aria-label="MUE views">
        {views.map(([key, label]) => <button type="button" key={key} aria-pressed={view === key} aria-controls={id} onClick={() => setView(key)}>{label}</button>)}
      </div><span className="muted">kcal/mol</span>
    </div>
    <div id={id} className="mue-view-content">
      {view === "overview" && <div className="mue-overview">
        {rows.length || test ? <div className={"mue-summary" + (test ? " has-test" : "")} aria-label="MUE overview statistics">
          <section className="input-summary"><h4>Your data set · MUE</h4><p className="summary-value num">{input ? input.value.toFixed(2) : "—"}<small>kcal/mol</small></p>
            <p>{input?.original !== null && input?.original !== undefined ? <>from <strong className="num">{input.original.toFixed(2)}</strong> with original CF22D parameters{percent !== null && <> · <strong className={percent < 0 ? "change-good" : percent > 0 ? "change-bad" : ""}>{Math.abs(percent).toFixed(0)}% {percent < 0 ? "lower" : percent > 0 ? "higher" : "unchanged"}</strong></>}</> : "Original Input MUE is not available for this run."}</p>
          </section>
          {test && <section className="test-summary"><h4>Test set · MUE</h4>
            <p className="summary-value num">{test.value === null ? "—" : test.value.toFixed(2)}<small>kcal/mol</small></p>
            <p>{test.original !== null ? <>from <strong className="num">{test.original.toFixed(2)}</strong> with original CF22D parameters</> : "Original Test MUE is not available for this run."}</p>
            {!test.complete && <p>Test evaluation incomplete.</p>}
          </section>}
          <section><h4>Reference databases</h4><p className="summary-value num">{stats.improved.length} of {stats.references}</p><p>{stats.improved.length} of {stats.references} paired reference datasets improved · <strong className="change-bad">{stats.worse.length} got worse</strong>{stats.unchanged > 0 && <> · {stats.unchanged} unchanged</>}</p></section>
          <section><h4>Within chemical accuracy</h4><p className="summary-value num">{stats.beforeAccurate} → {stats.afterAccurate}</p><p>paired reference datasets with MUE under 1 kcal/mol</p></section>
        </div> : <div className="empty" role="status"><h4>No MUE results yet</h4><p>Statistics appear when this run produces dataset MUE results.</p></div>}
        {stats.references !== stats.totalReferences && <p className="mue-note">Comparison coverage: {stats.references} of {stats.totalReferences} reference datasets have both original and optimized MUE.</p>}
        {rows.length > 0 && <div className="mue-change-grid"><ChangeList rows={stats.worse} title="Got worse" variant="worse" /><ChangeList rows={stats.improved} title="Biggest improvements" variant="better" /></div>}
      </div>}
      {view === "types" && <>
        <p className="mue-note mue-view-note">Overall MUE = Σ(data points × dataset MUE) / Σ(data points). Original and optimized use the same paired datasets; inverse weights are not applied.</p>
        {typeRows.length ? <ComparisonBars scope="Overall MUE by type" rows={typeRows} /> : <div className="empty"><p>Category MUE is not available until paired MUE values and data-point counts are present.</p></div>}
        {excluded > 0 && <p className="mue-note">{excluded} dataset{excluded === 1 ? "" : "s"} omitted from category comparison because baseline or data-point counts are unavailable.</p>}
      </>}
      {view === "datasets" && <>
        <p className="mue-note mue-view-note">Native LibXC CF22D on stored densities. Input is evaluated separately for each job. Only dataset errors are plotted.</p>
        {datasetRows.length ? <ComparisonBars scope="MUE by dataset" rows={datasetRows} /> : <div className="empty"><p>Dataset MUE values are not available for this run yet.</p></div>}
        {rows.some((row) => row.original === null) && <p className="mue-note">— Original MUE is unavailable for this dataset; no baseline is assumed.</p>}
      </>}
    </div>
  </section>;
}
