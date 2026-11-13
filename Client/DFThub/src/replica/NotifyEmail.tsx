import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useAuth } from "../contexts/AuthContext";
import { Icon } from "./Icons";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Fields to add to a /api_dft/submit request, or null when the user cancelled. */
export type NotifyFields = { email?: string };

type NotifyEmail = {
  /** Call before every calculation request; resolves at once unless an address is missing. */
  ask: () => Promise<NotifyFields | null>;
  /** Offer this address again for later calculations in this page. */
  remember: (address: string) => void;
};

const Context = createContext<NotifyEmail | null>(null);

/**
 * With mail on, every calculation request needs a notification address. When the
 * account has one, the server uses it and nothing is asked. An account without an
 * address is asked at each request. The last address is held in memory for this
 * page only: never in browser storage, never with the job, and dropped on reload
 * or when the account changes.
 */
export function NotifyEmailProvider({ children }: { children: ReactNode }) {
  const { user, features } = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const pending = useRef<((value: NotifyFields | null) => void) | null>(null);
  const [remembered, setRemembered] = useState("");
  const [address, setAddress] = useState("");
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState(false);
  const needed = features.mail && !!user && !user.email;
  const invalid = !EMAIL.test(address.trim());

  useEffect(() => setRemembered(""), [user?.username]);

  const finish = useCallback((value: NotifyFields | null) => {
    const resolve = pending.current;
    pending.current = null;
    setOpen(false);
    resolve?.(value);
  }, []);

  useEffect(() => { if (!needed) finish(null); }, [needed, finish]);

  const ask = useCallback((): Promise<NotifyFields | null> => {
    if (!needed) return Promise.resolve({});
    pending.current?.(null);
    setAddress(remembered);
    setChecked(false);
    setOpen(true);
    return new Promise((resolve) => { pending.current = resolve; });
  }, [needed, remembered]);

  const remember = useCallback((value: string) => setRemembered(value.trim()), []);

  useEffect(() => {
    if (open && !dialog.current?.open) {
      dialog.current?.showModal();
      dialog.current?.querySelector<HTMLInputElement>("#notifyEmail")?.focus();
    } else if (!open && dialog.current?.open) dialog.current.close();
  }, [open]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setChecked(true);
    if (invalid) return;
    const value = address.trim();
    setRemembered(value);
    finish({ email: value });
  }

  return <Context.Provider value={{ ask, remember }}>
    {children}
    {needed && <dialog ref={dialog} className="sheet" aria-labelledby="notifyTitle" style={{ width: "min(480px, calc(100vw - 24px))" }}
      onCancel={(event) => { event.preventDefault(); finish(null); }} onClick={(event) => { if (event.target === event.currentTarget) finish(null); }}>
      <form onSubmit={submit} style={{ display: "contents" }} noValidate>
        <div className="sheet-head"><div><h3 id="notifyTitle">Notification email</h3><p>Your account has no email address.</p></div>
          <button type="button" className="icon-btn" aria-label="Close" onClick={() => finish(null)}><Icon name="x" /></button>
        </div>
        <div className="sheet-body"><div className="group">
          <div className="field"><label htmlFor="notifyEmail">Email for this calculation</label>
            <input className={`inp${checked && invalid ? " bad" : ""}`} id="notifyEmail" type="email" autoComplete="email" required value={address}
              onChange={(event) => setAddress(event.target.value)} aria-describedby="notifyHelp" aria-invalid={checked && invalid} placeholder="you@example.com" />
            <div className={`help${checked && invalid ? " err" : ""}`} id="notifyHelp">{checked && invalid ? "Enter a valid email address."
              : "This server emails you when the calculation is submitted and when it finishes. The address is not saved with the job; this page offers it again until you reload."}</div>
          </div>
        </div></div>
        <div className="sheet-foot"><span className="hint" />
          <button type="button" className="btn btn-secondary" onClick={() => finish(null)}>Cancel</button>
          <button type="submit" className="btn btn-primary">Continue</button>
        </div>
      </form>
    </dialog>}
  </Context.Provider>;
}

export function useNotifyEmail() {
  const context = useContext(Context);
  if (!context) throw new Error("useNotifyEmail must be used within NotifyEmailProvider");
  return context;
}
