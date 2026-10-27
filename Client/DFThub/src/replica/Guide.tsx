import { useEffect, useRef } from "react";
import rawMarkup from "./guide-content.html?raw";

type Notify = (message: string, kind?: "good" | "bad" | "info") => void;

// Keep the authored guide markup in a separate HTML file so its examples stay
// readable, while adapting links to the standalone Astro routes at build time.
const guideMarkup = rawMarkup
  .replace(/^<main id="top"><div class="wrap">/, "")
  .replace(/<\/div><\/main>\s*$/, "")
  .replaceAll("DFThub.html#workspace", "/workspace/")
  .replaceAll("DFThub.html#top", "/")
  .replaceAll("analyze.html", "/analyze/")
  .replaceAll("https://dfthub.ecnu.space/api_dft/docs", "/api_dft/docs")
  .replaceAll("https://dfthub.ecnu.space/api_dft/download/Work/template", "/api_dft/download/Work/template");

export default function Guide({ onNotify }: { onNotify: Notify }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = host.current;
    if (!root) return;

    const links = Array.from(root.querySelectorAll<HTMLAnchorElement>('.gd-toc a[href^="#"]'));
    const sections = links
      .map((link) => root.querySelector<HTMLElement>(link.getAttribute("href") || ""))
      .filter((section): section is HTMLElement => Boolean(section));
    let last = "";
    let ticking = false;

    function setCurrent(id: string) {
      links.forEach((link) => {
        const active = link.getAttribute("href") === `#${id}`;
        if (active) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
        const list = link.closest("ol");
        if (active && list && list.scrollWidth > list.clientWidth) {
          list.scrollTo({ left: Math.max(0, link.offsetLeft - 16), behavior: "smooth" });
        }
      });
    }

    function updateCurrent() {
      ticking = false;
      if (!sections.length) return;
      const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
      let current = sections[0];
      if (atEnd) current = sections[sections.length - 1];
      else sections.forEach((section) => {
        if (section.getBoundingClientRect().top <= 160) current = section;
      });
      if (current.id !== last) {
        last = current.id;
        setCurrent(current.id);
      }
    }

    const onScroll = () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(updateCurrent);
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", updateCurrent);
    updateCurrent();

    const copyButtons = Array.from(root.querySelectorAll<HTMLButtonElement>(".gd-code .icon-btn"));
    const copyHandlers = copyButtons.map((button) => {
      const pre = button.closest(".gd-code")?.querySelector("pre");
      const handler = async () => {
        if (!pre) return;
        try {
          await navigator.clipboard.writeText(pre.textContent || "");
          button.setAttribute("aria-label", "Copied");
          button.querySelector("use")?.setAttribute("href", "#i-check");
          onNotify("Code copied", "good");
          window.setTimeout(() => {
            button.setAttribute("aria-label", "Copy");
            button.querySelector("use")?.setAttribute("href", "#i-copy");
          }, 1600);
        } catch {
          const range = document.createRange();
          range.selectNodeContents(pre);
          const selection = window.getSelection();
          selection?.removeAllRanges();
          selection?.addRange(range);
          onNotify("Select the highlighted text to copy it", "info");
        }
      };
      button.addEventListener("click", handler);
      return [button, handler] as const;
    });

    const citationButton = root.querySelector<HTMLButtonElement>("#gdCopyCite");
    const citationText = root.querySelector<HTMLElement>("#gdCiteText");
    const citationHandler = async () => {
      if (!citationButton || !citationText) return;
      try {
        await navigator.clipboard.writeText(citationText.textContent?.trim() || "");
        const label = citationButton.querySelector("span");
        if (label) label.textContent = "Copied";
        onNotify("Citation copied", "good");
        window.setTimeout(() => {
          if (label) label.textContent = "Copy citation";
        }, 1600);
      } catch {
        onNotify("Copy is unavailable here; select the citation text", "info");
      }
    };
    citationButton?.addEventListener("click", citationHandler);

    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", updateCurrent);
      copyHandlers.forEach(([button, handler]) => button.removeEventListener("click", handler));
      citationButton?.removeEventListener("click", citationHandler);
    };
  }, [onNotify]);

  return <div ref={host} className="guide-host" dangerouslySetInnerHTML={{ __html: guideMarkup }} />;
}
