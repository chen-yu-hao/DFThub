import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Icon } from "./Icons";

type Notify = (message: string, kind?: "good" | "bad" | "info") => void;
type User = { username: string; email: string };
type Theme = "system" | "light" | "dark";
export type Page = "overview" | "workspace" | "analyze" | "energy" | "guide";
const themes: Theme[] = ["system", "light", "dark"];
const email = "ECNU_DFThub@163.com";
const citation =
  "Yiwei Liu, Cheng Zhang, Zhonghua Liu, Donald G. Truhlar*, Ying Wang*, and Xiao He*, Supervised Learning of a Chemistry Functional with Damped Dispersion, Nat. Comput. Sci., 2023, 3, 48–58.";

async function copyText(value: string, success: string, onNotify: Notify) {
  try {
    await navigator.clipboard.writeText(value);
    onNotify(success, "good");
  } catch {
    const focused = document.activeElement as HTMLElement | null;
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.style.cssText = "position:fixed;left:-9999px;top:0";
    document.body.append(textarea);
    textarea.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch {
      /* Use the visible text if clipboard access is unavailable. */
    }
    textarea.remove();
    focused?.focus();
    onNotify(
      copied
        ? success
        : "Copy isn’t available here. Select the text to copy it.",
      copied ? "good" : "info",
    );
  }
}

export function Header(props: {
  page: Page;
  user: User | null;
  onNew: () => void;
  onLogin: () => void;
  onLogout: () => void;
  onNotify: Notify;
}) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<Theme | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const avatarRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let saved: unknown;
    try {
      saved = JSON.parse(localStorage.getItem("dfthub.theme") || '"system"');
    } catch {
      saved = "system";
    }
    setTheme(themes.includes(saved as Theme) ? (saved as Theme) : "system");
  }, []);

  useEffect(() => {
    if (!theme) return;
    if (theme === "system")
      document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("dfthub.theme", JSON.stringify(theme));
    } catch {
      /* Appearance still works without local storage. */
    }
  }, [theme]);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (
        !menuRef.current?.contains(event.target as Node) &&
        !avatarRef.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  function onMenuKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      avatarRef.current?.focus();
      return;
    }
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') || [],
    );
    const current = items.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : (current + (event.key === "ArrowDown" ? 1 : -1) + items.length) %
            items.length;
    items[next]?.focus();
  }

  const initials = props.user?.username.slice(0, 2).toUpperCase();
  const appearance = theme || "system";

  return (
    <header className="nav">
      <div className="wrap">
        <a
          className="brand"
          href="/"
          aria-label="DFThub home"
          aria-current={props.page === "overview" ? "page" : undefined}
        >
          <span className="logo hydrogen-logo">
            <img src="/favicon.svg" alt="" aria-hidden="true" />
          </span>
          DFThub
        </a>
        <nav className="nav-links" aria-label="Sections">
          <a
            href="/workspace/"
            aria-current={props.page === "workspace" ? "page" : undefined}
          >
            <Icon name="grid" />Workspace
          </a>
          <a href="/analyze/" className="nav-analyze" aria-current={props.page === "analyze" ? "page" : undefined}>
            <Icon name="chart" />Analyze
          </a>
          <a href="/energy/" aria-current={props.page === "energy" ? "page" : undefined}>
            <Icon name="atom" />DFT energy
          </a>
          <a href="/guide/" aria-current={props.page === "guide" ? "page" : undefined}>
            Guide
          </a>
        </nav>
        <div className="nav-right" style={{ position: "relative" }}>
          <button
            type="button"
            className="btn btn-primary btn-sm js-new"
            title="New job (N)"
            onClick={props.onNew}
          >
            <Icon name="plus" />
            New job
          </button>
          {props.user ? <button type="button" className="avatar" id="avatarBtn" ref={avatarRef} aria-haspopup="menu" aria-expanded={open} aria-controls="acctMenu" aria-label="Open account menu" onClick={() => setOpen(!open)}>{initials}</button> : <button type="button" className="btn btn-secondary btn-sm" id="signIn" onClick={props.onLogin}><Icon name="user" />Sign in</button>}
          <div
            className="menu"
            id="acctMenu"
            ref={menuRef}
            role="menu"
            hidden={!open}
            onKeyDown={onMenuKey}
          >
            <div className="menu-head">
              <b>{props.user?.username || "Your workspace"}</b>
              <span>{props.user?.email || "Sign in to manage your jobs"}</span>
            </div>
            <button
              type="button"
              role="menuitem"
              className="js-docs"
              onClick={() => {
                window.location.href = "/api_dft/docs";
              }}
            >
              <Icon name="doc" />
              API docs
            </button>
            <a
              type="button"
              role="menuitem"
              id="contactBtn"
              href={`mailto:${email}`}
              onClick={() => setOpen(false)}
            >
              <Icon name="mail" />
              Contact the team
            </a>
            <button type="button" role="menuitem" id="copyContact" onClick={() => void copyText(email, `${email} copied`, props.onNotify)}><Icon name="copy" />Copy email</button>
            <button
              type="button"
              role="menuitem"
              id="themeBtn"
              onClick={() =>
                setTheme(
                  themes[(themes.indexOf(appearance) + 1) % themes.length],
                )
              }
            >
              <Icon name="bolt" />
              Appearance:{" "}
              <span id="themeLbl">
                {appearance[0].toUpperCase() + appearance.slice(1)}
              </span>
            </button>
            <button
              type="button"
              role="menuitem"
              id="sessionAction"
              onClick={() => {
                setOpen(false);
                props.user ? props.onLogout() : props.onLogin();
              }}
            >
              <Icon name={props.user ? "ext" : "user"} />
              {props.user ? "Sign out" : "Sign in"}
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}

export function Hero({
  count,
  onNew,
}: {
  count: number | null;
  onNew: () => void;
}) {
  return (
    <section className="hero" aria-labelledby="heroTitle">
      <div>
        <div className="eyebrow">Density functional research workspace</div>
        <h1 id="heroTitle">
          Make every calculation <em>count.</em>
        </h1>
        <p className="lead">
          Parameterize a density functional for the reactions and molecular
          systems that matter to your research.
        </p>
        <div className="hero-cta">
          <button
            type="button"
            className="btn btn-primary btn-lg js-new"
            onClick={onNew}
          >
            <Icon name="plus" />
            Start a new job
          </button>
          <a className="link" href="/guide/">
            Learn how it works <Icon name="chev" />
          </a>
        </div>
        <div className="hero-meta">
          {count !== null && count >= 0 && (
            <span role="status">
              <Icon name="check" />
              <b className="num" id="jobsTotal">
                {count}
              </b>
              &nbsp;jobs submitted
            </span>
          )}
        </div>
      </div>
      <aside className="how" aria-labelledby="howTitle">
        <h2 id="howTitle">How it works</h2>
        <p>
          Get a specific-reaction-parameterized (SRP) functional fitted to your
          own data.
        </p>
        <ol>
          <li>
            <b>Upload your data set</b>
            <p>
              Geometries as <span className="tag">.xyz</span> files in one{" "}
              <span className="tag">.tgz</span>, plus a{" "}
              <span className="tag">.ref</span> file of reaction formulas and
              reference energies, e.g. CCSD(T)/CBS.
            </p>
          </li>
          <li>
            <b>Choose an inverse weight</b>
            <p>
              Sets how strongly your set pulls the fit against the built-in
              training databases. Default 0.02.
            </p>
          </li>
          <li>
            <b>Tune and resubmit</b>
            <p>
              Adjust weights per database until the total MUE suits you, then
              compute converged single-point energies.
            </p>
          </li>
        </ol>
      </aside>
    </section>
  );
}

export function Citation({ onNotify }: { onNotify: Notify }) {
  return (
    <section className="cite" aria-label="How to cite">
      <Icon name="info" />
      <div>
        <b>Please cite DFThub when you publish or report results.</b>
        <ol>
          <li>DFThub (this paper)</li>
          <li id="citeText">
            Yiwei Liu, Cheng Zhang, Zhonghua Liu, Donald G. Truhlar*, Ying
            Wang*, and Xiao He*, Supervised Learning of a Chemistry Functional
            with Damped Dispersion, <i>Nat. Comput. Sci.</i>, 2023, 3, 48–58.
          </li>
        </ol>
      </div>
      <div className="cite-actions">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          id="copyCite"
          onClick={() => {
            void copyText(citation, "Citation copied", onNotify);
          }}
        >
          <Icon name="copy" />
          Copy citation
        </button>
        <a
          className="btn btn-secondary btn-sm"
          href="https://www.nature.com/articles/s43588-022-00371-5"
          target="_blank"
          rel="noopener noreferrer"
        >
          Paper <Icon name="ext" />
        </a>
      </div>
    </section>
  );
}

export function Footer({ onNotify }: { onNotify: Notify }) {
  return (
    <footer>
      <div className="wrap">
        <a className="brand" href="/" style={{ fontSize: 15 }}>
          <span className="logo hydrogen-logo" style={{ width: 22, height: 22, borderRadius: 6 }}>
            <img src="/favicon.svg" alt="" aria-hidden="true" />
          </span>
          DFThub
        </a>
        <span className="sp" />
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Icon name="mail" />
          <span id="contactAddr">{email}</span>
          <button
            type="button"
            className="icon-btn"
            id="copyMail"
            aria-label="Copy email address"
            style={{ width: 24, height: 24 }}
            onClick={() => {
              void copyText(email, "Email address copied", onNotify);
            }}
          >
            <Icon name="copy" />
          </button>
        </span>
      </div>
    </footer>
  );
}
