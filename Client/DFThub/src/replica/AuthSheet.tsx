import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../contexts/AuthContext";
import { Icon } from "./Icons";

export default function AuthSheet({ open, onClose, intent }: { open: boolean; onClose: () => void; intent?: "new" }) {
  const { login, register } = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const pending = useRef(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const usernameError = mode === "register" && username.trim() && !/^[A-Za-z0-9_-]{3,32}$/.test(username.trim()) ? "Use 3–32 letters, numbers, - or _." : "";
  const passwordError = mode === "register" && password.length > 0 && password.length < 6 ? "Use at least 6 characters." : "";
  const confirmError = mode === "register" && confirmPassword.length > 0 && password !== confirmPassword ? "Passwords do not match." : "";

  useEffect(() => {
    if (open && !dialog.current?.open) { setError(""); dialog.current?.showModal(); dialog.current?.querySelector<HTMLInputElement>("#authEmail")?.focus(); }
    else if (!open && dialog.current?.open) { dialog.current.close(); setPassword(""); setConfirmPassword(""); }
  }, [open]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    setError("");
    if (mode === "register" && (usernameError || passwordError || confirmError || password !== confirmPassword)) { setError(usernameError || passwordError || confirmError || "Passwords do not match."); return; }
    pending.current = true; setBusy(true);
    try {
      const message = mode === "login" ? await login(email.trim(), password) : await register(username.trim(), email.trim(), password);
      if (message) setError(message);
      else { setPassword(""); setConfirmPassword(""); }
    } finally { pending.current = false; setBusy(false); }
  }
  const close = () => { if (!pending.current) onClose(); };
  return (
    <dialog ref={dialog} className="sheet" aria-labelledby="authTitle" style={{ width: "min(540px, calc(100vw - 24px))" }}
      onCancel={(event) => { event.preventDefault(); close(); }} onClick={(event) => { if (event.target === event.currentTarget) close(); }}>
      <form onSubmit={submit} style={{ display: "contents" }} aria-busy={busy}>
        <div className="sheet-head"><div><h3 id="authTitle">{mode === "login" ? (intent === "new" ? "Sign in to start a new job" : "Sign in to DFThub") : "Create your account"}</h3><p>Access your research workspace.</p></div>
          <button type="button" className="icon-btn" aria-label="Close" onClick={close} disabled={busy}><Icon name="x" /></button>
        </div>
        <div className="sheet-body"><fieldset disabled={busy} style={{ display: "contents" }}>
          <div className="seg full" role="group" aria-label="Account access">
            <button type="button" aria-pressed={mode === "login"} onClick={() => { setMode("login"); setError(""); }}>Sign in</button>
            <button type="button" aria-pressed={mode === "register"} onClick={() => { setMode("register"); setError(""); }}>Create account</button>
          </div>
          <div className="group">
            {mode === "register" && <div className="field"><label htmlFor="authUsername">Username</label><input className={`inp${usernameError ? " bad" : ""}`} id="authUsername" autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} aria-invalid={Boolean(usernameError)} /><div className={`help${usernameError ? " err" : ""}`}>{usernameError || "3–32 letters, numbers, - and _. Used to name your workspace."}</div></div>}
            <div className="field"><label htmlFor="authEmail">Email</label><input className="inp" id="authEmail" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" /></div>
            <div className="field"><label htmlFor="authPassword">Password</label><input className={`inp${passwordError ? " bad" : ""}`} id="authPassword" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={mode === "register" ? 6 : undefined} required value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "register" ? "At least 6 characters" : "Your password"} aria-invalid={Boolean(passwordError)} />{mode === "register" && <div className={`help${passwordError ? " err" : ""}`}>{passwordError || "At least 6 characters."}</div>}</div>
            {mode === "register" && <div className="field"><label htmlFor="authConfirm">Confirm password</label><input className={`inp${confirmError ? " bad" : ""}`} id="authConfirm" type="password" autoComplete="new-password" required value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} aria-invalid={Boolean(confirmError)} /><div className={`help${confirmError ? " err" : ""}`}>{confirmError || "Repeat your password."}</div></div>}
          </div>
          {error && <p className="err-pos" role="alert">{error}</p>}
        </fieldset></div>
        <div className="sheet-foot"><span className="hint" role="status">{busy ? "Connecting to your workspace…" : "Your account keeps your research in one place."}</span>
          {mode === "login" && <a className="link" href="mailto:ECNU_DFThub@163.com?subject=DFThub%20password%20reset">Contact admin to reset password</a>}
          <button type="button" className="btn btn-secondary" onClick={close} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Please wait…" : "Continue"}</button>
        </div>
      </form>
    </dialog>
  );
}
