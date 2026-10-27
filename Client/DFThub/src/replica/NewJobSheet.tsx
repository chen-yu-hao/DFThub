import axios from "axios";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Icon } from "./Icons";
import { basisOptions, ecpOptions, zetaOptions } from "./basis";

type Props = {
  open: boolean;
  onClose: () => void;
  username: string;
  email: string;
  existingIds: string[];
  initial?: { basis?: string; email?: string; id?: string };
  onSubmitted: (id: string) => void;
  onNotify: (message: string, kind?: string) => void;
};

const newId = () => "dft_" + Math.random().toString(36).slice(2, 8);
const datasetName = (name: string) => name.replace(/(?:\.tar\.gz|\.tgz|\.ref|_ref)$/i, "");
const uploadDatasetName = (name: string) => datasetName(name).replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "dataset";

function DatasetDrop({ kind, file, onChange, disabled }: {
  kind: "Tgz" | "Ref"; file: File | null; onChange: (file: File | null) => void; disabled: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const geometry = kind === "Tgz";
  const valid = !file || (geometry ? /\.(tgz|tar\.gz)$/i.test(file.name) : /(\.ref|_ref)$/i.test(file.name));
  const error = geometry ? "Choose a .tgz or .tar.gz archive of XYZ files." : "Choose a .ref or _ref reference energy file.";
  return (
    <label className={`drop${file ? valid ? " has" : " bad" : ""}${over ? " over" : ""}`} id={`drop${kind}`}
      onDragOver={(event) => { event.preventDefault(); if (!disabled) setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => { event.preventDefault(); setOver(false); if (!disabled && event.dataTransfer.files[0]) onChange(event.dataTransfer.files[0]); }}>
      <input ref={input} type="file" id={`f${kind}`} disabled={disabled} aria-label={geometry ? "Geometry archive" : "Reference energies"}
        accept={geometry ? ".tgz,.gz,application/gzip,application/x-gzip" : undefined}
        onChange={(event) => { if (event.target.files?.[0]) onChange(event.target.files[0]); }} />
      <span className="ico"><Icon name={file && valid ? "check" : geometry ? "archive" : "doc"} /></span>
      <span style={{ minWidth: 0, overflowWrap: "anywhere" }}><b data-t>{file?.name || (geometry ? "Geometries (.tgz)" : "Reference energies (.ref)")}</b>
        <span data-s>{!valid ? error : file ? `${(file.size / 1024).toFixed(file.size < 10240 ? 1 : 0)} KB · ready · click to replace` : `Drop YourDatabaseName.${geometry ? "tgz" : "ref"} here, or click to choose`}</span>
      </span>
      <button type="button" className="icon-btn x" aria-label={geometry ? "Remove geometry file" : "Remove reference file"} hidden={!file}
        onClick={(event) => { event.preventDefault(); event.stopPropagation(); if (input.current) input.current.value = ""; onChange(null); }}>
        <Icon name="x" />
      </button>
    </label>
  );
}

function OptionalTestDrop({ kind, file, onChange, disabled }: {
  kind: "Tgz" | "Ref"; file: File | null; onChange: (file: File | null) => void; disabled: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const geometry = kind === "Tgz";
  const valid = !file || (geometry ? /\.(tgz|tar\.gz)$/i.test(file.name) : /(\.ref|_ref)$/i.test(file.name));
  return (
    <label className={`drop${file ? valid ? " has" : " bad" : ""}`} id={`dropTest${kind}`}>
      <input ref={input} type="file" id={`fTest${kind}`} disabled={disabled}
        aria-label={geometry ? "Test geometry archive" : "Test reference energies"}
        accept={geometry ? ".tgz,.gz,application/gzip,application/x-gzip" : undefined}
        onChange={(event) => { if (event.target.files?.[0]) onChange(event.target.files[0]); }} />
      <span className="ico"><Icon name={file && valid ? "check" : geometry ? "archive" : "doc"} /></span>
      <span style={{ minWidth: 0, overflowWrap: "anywhere" }}><b data-t>{file?.name || (geometry ? "Test geometries (.tgz)" : "Test reference energies (.ref)")}</b>
        <span data-s>{!valid ? (geometry ? "Choose a .tgz or .tar.gz archive." : "Choose a .ref or _ref file.") : file ? "Ready · excluded from optimization" : "Optional · upload with its matching reference file"}</span>
      </span>
      <button type="button" className="icon-btn x" aria-label={geometry ? "Remove test geometry file" : "Remove test reference file"} hidden={!file}
        onClick={(event) => { event.preventDefault(); event.stopPropagation(); if (input.current) input.current.value = ""; onChange(null); }}><Icon name="x" /></button>
    </label>
  );
}

export default function NewJobSheet(props: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const picker = useRef<HTMLDetailsElement>(null);
  const advanced = useRef<HTMLDetailsElement>(null);
  const pending = useRef(false);
  const [jobId, setJobId] = useState(newId);
  const [email, setEmail] = useState(props.email);
  const [archive, setArchive] = useState<File | null>(null);
  const [reference, setReference] = useState<File | null>(null);
  const [testArchive, setTestArchive] = useState<File | null>(null);
  const [testReference, setTestReference] = useState<File | null>(null);
  const [weight, setWeight] = useState("0.02");
  const [basis, setBasis] = useState("def2-qzvp");
  const [remarks, setRemarks] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [fileVersion, setFileVersion] = useState(0);
  const selected = basisOptions.find((option) => option.value === basis) || basisOptions.find((option) => option.value === "def2-qzvp")!;
  const available = basisOptions.filter((option) => option.zeta === selected.zeta && option.ecp === selected.ecp);
  const canUseEcp = basisOptions.some((option) => option.zeta === selected.zeta && option.ecp);

  useEffect(() => {
    if (props.open && !dialog.current?.open) {
      setJobId(props.initial?.id ? props.initial.id + "_v2" : newId());
      setEmail(props.initial?.email || props.email);
      setBasis(basisOptions.find((option) => option.value === props.initial?.basis?.toLowerCase())?.value || "def2-qzvp");
      setArchive(null); setReference(null); setTestArchive(null); setTestReference(null); setWeight("0.02"); setRemarks(""); setError(""); setStatus("");
      setFileVersion((value) => value + 1);
      setMenuOpen(false);
      if (picker.current) picker.current.open = false;
      if (advanced.current) advanced.current.open = false;
      dialog.current?.showModal();
      dialog.current?.querySelector<HTMLInputElement>("#fId")?.focus();
    } else if (!props.open && dialog.current?.open) dialog.current.close();
  }, [props.open]);

  const idError = !jobId.trim() ? "Give the job an ID." : !/^[A-Za-z0-9_-]+$/.test(jobId.trim()) ? "Use only letters, numbers, - and _." : props.existingIds.includes(jobId.trim()) ? "You already have a job with this ID." : "";
  const emailError = !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) ? "Enter a valid notification email." : "";
  const weightNumber = Number(weight);
  const weightError = !weight.trim() || !Number.isFinite(weightNumber) || weightNumber < 0.001 || weightNumber > 10 ? "Enter a value from 0.001 to 10." : "";
  const filesValid = Boolean(archive && /\.(tgz|tar\.gz)$/i.test(archive.name) && reference && /(\.ref|_ref)$/i.test(reference.name));
  const testFilesValid = Boolean(testArchive && /\.(tgz|tar\.gz)$/i.test(testArchive.name) && testReference && /(\.ref|_ref)$/i.test(testReference.name));
  const testFilesPartial = Boolean(testArchive) !== Boolean(testReference);
  const valid = !idError && !emailError && !weightError && filesValid && !testFilesPartial && (!testArchive && !testReference || testFilesValid);
  const missing = [!archive && "a geometry archive", !reference && "a reference file"].filter(Boolean);
  const hint = submitting ? status : missing.length ? `Add ${missing.join(" and ")} to submit.` : testFilesPartial ? "Add both test files or remove the test file." : valid ? "Ready to submit." : "Fix the highlighted fields to submit.";

  function chooseLevel(zeta: string, ecp: boolean) {
    const next = basisOptions.find((option) => option.zeta === zeta && option.ecp === ecp) || basisOptions.find((option) => option.zeta === zeta)!;
    setBasis(next.value);
    if (picker.current) picker.current.open = false;
  }

  async function downloadTemplate() {
    try {
      const response = await axios.get("/api_dft/download/Work/template", { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = response.headers["content-disposition"]?.match(/filename="?([^";]+)"?/i)?.[1] || "template.tgz";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { props.onNotify("The template could not be downloaded. Please try again.", "bad"); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || !valid || !archive || !reference) return;
    pending.current = true; setSubmitting(true); setError(""); setStatus("Uploading…");
    const id = jobId.trim();
    const workDir = `Work/${props.username}/${id}/`;
    const upload = new FormData();
    upload.append("folder_dir", workDir + "upload");
    const dataset = uploadDatasetName(archive.name);
    // The backend reads the first comma-delimited value as the archive stem.
    upload.append("files", archive, `${dataset}.tgz`);
    upload.append("files", reference, `${dataset}.ref`);
    if (testFilesValid && testArchive && testReference) {
      const testName = uploadDatasetName(testArchive.name);
      upload.append("files", testArchive, `test_${testName}.tgz`);
      upload.append("files", testReference, `test_${testName}.ref`);
      upload.append("files", new File([JSON.stringify({ geometry: `test_${testName}.tgz`, reference: `test_${testName}.ref`, dataset: testName })], "test_manifest.json", { type: "application/json" }));
    }
    upload.append("files", new File(["Database,Description,Type,Source,Number,Inverse Weight\n" + dataset + ",,,uploaded,," + weight + "\n"], "init_weight.csv", { type: "text/csv" }));
    try {
      const uploaded = await axios.put("/api_dft/upload", upload);
      if (uploaded.data.result === "error") throw new Error(uploaded.data.msg || "The files could not be uploaded.");
      setStatus("Submitting…");
      const response = await axios.post("/api_dft/submit", { mode: "new", work_dir: workDir, weightFile: "weight_0", basis, email: email.trim(), reMark: remarks });
      if (response.data.result === "error") throw new Error(response.data.msg || "The job could not be submitted.");
      props.onSubmitted(id);
      props.onClose();
      props.onNotify(`${id} submitted. Follow its progress in your workspace.`, "good");
    } catch (failure: any) {
      const detail = failure.response?.data?.detail;
      const validation = detail && typeof detail === "object" ? JSON.stringify(detail) : detail;
      setError(failure.response?.data?.msg || validation || failure.message || "The job could not be submitted. Please try again.");
      setStatus("");
    } finally { pending.current = false; setSubmitting(false); }
  }

  const close = () => { if (!pending.current) props.onClose(); };
  return (
    <dialog ref={dialog} className="sheet" id="newSheet" aria-labelledby="newTitle" onCancel={(event) => { event.preventDefault(); close(); }}
      onClick={(event) => { if (event.target === event.currentTarget) close(); }}>
      <form id="newForm" noValidate onSubmit={submit} style={{ display: "contents" }} aria-busy={submitting}>
        <div className="sheet-head"><div><h3 id="newTitle">New job</h3><p>Upload a data set and we&apos;ll fit a functional to it.</p></div>
          <button type="button" className="icon-btn" onClick={close} disabled={submitting} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="sheet-body"><fieldset disabled={submitting} style={{ display: "contents" }}>
          <div><div className="group-label">Job</div><div className="group">
            <div className="field"><label htmlFor="fId">Job ID</label><div className="inp-row">
              <input className={`inp mono${idError ? " bad" : ""}`} id="fId" autoComplete="off" spellCheck={false} value={jobId} onChange={(event) => setJobId(event.target.value)} aria-describedby="fIdHelp" aria-invalid={Boolean(idError)} required />
              <button type="button" className="icon-btn" id="regenId" aria-label="Generate a new ID" title="Generate a new ID" onClick={() => setJobId(newId())}><Icon name="refresh" /></button></div>
              <div className={`help${idError ? " err" : ""}`} id="fIdHelp">{idError || "Letters, numbers, - and _. Choose a name you can recognize."}</div>
            </div>
            <div className="field"><label htmlFor="fEmail">Email</label><input className={`inp${emailError ? " bad" : ""}`} id="fEmail" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} aria-describedby="fEmailHelp" aria-invalid={Boolean(emailError)} required />
              <div className={`help${emailError ? " err" : ""}`} id="fEmailHelp">{emailError || "We’ll email you when each step finishes."}</div>
            </div>
          </div></div>
          <div><div className="group-label">Data set</div><div className="group" style={{ padding: 14, display: "grid", gap: 12 }}>
            <DatasetDrop key={`tgz-${fileVersion}`} kind="Tgz" file={archive} onChange={setArchive} disabled={submitting} />
            <DatasetDrop key={`ref-${fileVersion}`} kind="Ref" file={reference} onChange={setReference} disabled={submitting} />
            {archive && reference && datasetName(archive.name) !== datasetName(reference.name) && <div className="help" id="fileWarn" style={{ color: "var(--warn)" }}>File names differ ({datasetName(archive.name)} vs {datasetName(reference.name)}). That&apos;s fine if they belong to the same data set.</div>}
            <details className="req"><summary><Icon name="chev" />File requirements</summary><ul>
              <li>Each <span className="tag">.xyz</span> file holds one molecule or transition state, with its charge and spin multiplicity on line 2.</li>
              <li>Every file in the archive needs a unique name.</li>
              <li>The <span className="tag">.ref</span> file lists each reaction formula with its reference energy, from experiment or high-level calculations such as CCSD(T)/CBS.</li>
              <li>Molecule names in the <span className="tag">.ref</span> file must match the <span className="tag">.xyz</span> file names.</li>
            </ul><p style={{ marginTop: 8 }}><button type="button" className="link" onClick={downloadTemplate}><Icon name="down" />Download the template</button></p></details>
          </div></div>
          <div><div className="group-label">Training</div><div className="group"><div className="field stack">
            <div className="inp-row" style={{ justifyContent: "space-between" }}><label htmlFor="fW" className="flabel" style={{ fontSize: 15, fontWeight: 500 }}>Initial inverse weight</label>
              <input className={`inp mono num${weightError ? " bad" : ""}`} id="fW" type="number" min="0.001" max="10" step="any" inputMode="decimal" value={weight} onChange={(event) => setWeight(event.target.value)} style={{ width: 110, textAlign: "right" }} aria-describedby="fWHelp" aria-invalid={Boolean(weightError)} required /></div>
            <div className="slider"><input type="range" id="fWr" min="-3" max="1" step="0.01" aria-label="Initial inverse weight (log scale)" value={Math.log10(Math.min(10, Math.max(0.001, weightNumber || 0.001)))} onChange={(event) => setWeight(String(Number(Math.pow(10, Number(event.target.value)).toPrecision(2))))} />
              <div className="ticks"><span>0.001</span><span>0.01</span><span>0.1</span><span>1</span><span>10</span></div></div>
            <div className={`help${weightError ? " err" : ""}`} id="fWHelp">{weightError || "Lower values give your data set more influence on the fit. Range 0.001–10, default 0.02."}</div>
          </div></div></div>
          <details ref={advanced} className="advanced-settings" onToggle={(event) => { if (!event.currentTarget.open && picker.current?.open) picker.current.open = false; }}>
            <summary><span><b>Advanced settings</b><small>Test set, basis set and notes</small></span><Icon name="chev" /></summary>
            <div className="advanced-settings-body">
          <div><div className="group-label">Optional test set</div><div className="group" style={{ padding: 14, display: "grid", gap: 12 }}>
            <p className="help" style={{ margin: 0 }}>Evaluated after fitting and during Input SCF. Test data never changes the optimized parameters.</p>
            <OptionalTestDrop key={`test-tgz-${fileVersion}`} kind="Tgz" file={testArchive} onChange={setTestArchive} disabled={submitting} />
            <OptionalTestDrop key={`test-ref-${fileVersion}`} kind="Ref" file={testReference} onChange={setTestReference} disabled={submitting} />
            {testArchive && testReference && datasetName(testArchive.name) !== datasetName(testReference.name) && <div className="help" style={{ color: "var(--warn)" }}>Test file names differ; they will still be evaluated as one test set.</div>}
          </div></div>
          <div><div className="group-label">Basis set</div><div className="group">
            <div className="field"><span className="flabel" id="zLbl">Zeta level</span><div className="seg full" role="group" aria-labelledby="zLbl" id="fZeta">
              {zetaOptions.map((option) => <button key={option.value} type="button" data-v={option.value} aria-label={`${option.value}-zeta (${option.name})`} aria-pressed={selected.zeta === option.value} onClick={() => chooseLevel(option.value, selected.ecp)}><span className="zeta-name">{option.name}</span><span className="zeta-short">{option.value}ζ</span></button>)}
            </div></div>
            <div className="field"><span className="flabel" id="eLbl">Core electrons</span><div className="seg full" role="group" aria-labelledby="eLbl" id="fEcp">
              {ecpOptions.map((option) => <button key={option.value} type="button" data-v={option.value} aria-pressed={(selected.ecp ? "ecp" : "ae") === option.value} disabled={option.value === "ecp" && !canUseEcp} onClick={() => chooseLevel(selected.zeta, option.value === "ecp")}>{option.name}</button>)}
            </div></div>
            <div className="field"><span className="flabel" id="fBasisLabel">Final basis</span>
              <details ref={picker} onToggle={(event) => setMenuOpen(event.currentTarget.open)} onKeyDown={(event) => { if (event.key === "Escape" && picker.current?.open) { event.preventDefault(); event.stopPropagation(); picker.current.open = false; picker.current.querySelector("summary")?.focus(); } }}>
                <summary className="select" id="fBasis" aria-labelledby="fBasisLabel fBasis" style={{ height: 34, width: "100%", listStyle: "none", display: "flex", alignItems: "center", cursor: "pointer" }}>{selected.name}</summary>
                {menuOpen && <div className="basis-options" role="group" aria-label="Available basis sets" style={{ display: "grid", gap: 4, maxHeight: 260, overflowY: "auto", paddingTop: 6 }}>
                  {available.map((option) => <button type="button" key={option.value} data-basis={option.value} aria-pressed={option.value === basis} onClick={() => { setBasis(option.value); if (picker.current) { picker.current.open = false; picker.current.querySelector("summary")?.focus(); } }} style={{ display: "block", textAlign: "left", padding: "9px 10px", border: 0, borderRadius: "var(--r-sm)", background: option.value === basis ? "var(--accent-tint)" : "var(--fill-2)", color: "var(--ink)" }}>
                    <b style={{ display: "block", fontSize: 13 }}>{option.name}</b><span style={{ display: "block", marginTop: 3, fontSize: 13, color: "var(--ink-2)", lineHeight: 1.4 }}>{option.description}</span>
                  </button>)}
                </div>}
              </details><div className="help">Suggested from your zeta level and core treatment.</div>
            </div>
          </div></div>
          <div><div className="group-label">Notes</div><div className="group"><div className="field stack">
            <label htmlFor="fRemark" className="sr">Remarks</label><textarea className="inp" id="fRemark" maxLength={500} value={remarks} onChange={(event) => setRemarks(event.target.value)} placeholder="Anything the team should know about this data set (optional)" />
            <div className="help" style={{ textAlign: "right" }}><span id="remCount" className="num">{remarks.length}</span>/500</div>
          </div></div></div>
            </div>
          </details>
          {error && <p className="err-pos" role="alert">{error}</p>}
        </fieldset></div>
        <div className="sheet-foot"><span className={`hint${valid && !submitting ? " ok" : ""}`} id="submitHint" role="status">{hint}</span>
          <button type="button" className="btn btn-secondary" onClick={close} disabled={submitting}>Cancel</button>
          <button type="submit" className="btn btn-primary" id="submitBtn" disabled={!valid || submitting}>{submitting ? status : "Submit job"}</button>
        </div>
      </form>
    </dialog>
  );
}
