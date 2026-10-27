/*
 * Sliding selection pill for segmented toggles (.seg), modelled on
 * apple.com's TabNav. No dependencies.
 *
 * It measures the selected button (aria-pressed="true" or
 * aria-selected="true") and writes its box to CSS variables on the .seg
 * element. CSS draws the pill as .seg::before and animates it to the new
 * position. The script never adds or removes DOM nodes, so it is safe next
 * to React/Astro rendering.
 */
(() => {
  const SEG = ".seg";
  const tracked = new WeakSet();

  const isSelected = (el) =>
    el.getAttribute("aria-pressed") === "true" ||
    el.getAttribute("aria-selected") === "true";

  // Size or layout changes (fonts, viewport, dialog opening) move the pill
  // instantly; only a change of selection animates it.
  const resizeObserver =
    "ResizeObserver" in window
      ? new ResizeObserver((entries) => {
          const segs = new Set();
          for (const entry of entries) {
            const seg = entry.target.matches(SEG)
              ? entry.target
              : entry.target.closest(SEG);
            if (seg) segs.add(seg);
          }
          segs.forEach((seg) => place(seg, true));
        })
      : null;

  function place(seg, instant) {
    const selected = Array.from(seg.children).find(
      (child) => child.tagName === "BUTTON" && isSelected(child)
    );
    const style = seg.style;

    if (!selected || !selected.offsetWidth) {
      style.setProperty("--seg-o", "0");
      if (!seg.hasAttribute("data-seg-ready") && !selected) {
        seg.setAttribute("data-seg-ready", "");
      }
      return;
    }

    if (instant) seg.setAttribute("data-seg-instant", "");

    style.setProperty("--seg-x", selected.offsetLeft + "px");
    style.setProperty("--seg-y", selected.offsetTop + "px");
    style.setProperty("--seg-w", selected.offsetWidth + "px");
    style.setProperty("--seg-h", selected.offsetHeight + "px");
    style.setProperty("--seg-o", "1");
    seg.setAttribute("data-seg-ready", "");

    if (instant) {
      // Let the browser apply the new position before transitions return.
      requestAnimationFrame(() =>
        requestAnimationFrame(() => seg.removeAttribute("data-seg-instant"))
      );
    }
  }

  function track(seg) {
    if (resizeObserver) {
      for (const child of seg.children) {
        if (child.tagName === "BUTTON" && !tracked.has(child)) {
          tracked.add(child);
          resizeObserver.observe(child);
        }
      }
      if (!tracked.has(seg)) {
        tracked.add(seg);
        resizeObserver.observe(seg);
      }
    }
  }

  function scan(root) {
    const segs = [];
    if (root.nodeType !== 1) return segs;
    if (root.matches(SEG)) segs.push(root);
    root.querySelectorAll(SEG).forEach((seg) => segs.push(seg));
    return segs;
  }

  function untrack(root) {
    if (!resizeObserver || root.nodeType !== 1 || root.isConnected) return;
    // Tabs replace their content; release observers for controls that unmount.
    for (const element of [root, ...root.querySelectorAll("*")]) {
      if (tracked.delete(element)) resizeObserver.unobserve(element);
    }
  }

  function init() {
    scan(document.body).forEach((seg) => {
      track(seg);
      place(seg, true);
    });

    new MutationObserver((mutations) => {
      const moved = new Set();
      const fresh = new Set();

      for (const m of mutations) {
        if (m.type === "attributes") {
          const seg = m.target.parentElement && m.target.parentElement.closest(SEG);
          if (seg && m.target.parentElement === seg) moved.add(seg);
        } else {
          m.removedNodes.forEach(untrack);
          m.addedNodes.forEach((node) => scan(node).forEach((seg) => fresh.add(seg)));
          const seg = m.target.nodeType === 1 && m.target.closest(SEG);
          if (seg) fresh.add(seg);
        }
      }

      fresh.forEach((seg) => {
        track(seg);
        place(seg, true);
      });
      moved.forEach((seg) => {
        if (!fresh.has(seg)) place(seg, false);
      });
    }).observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-pressed", "aria-selected"],
    });

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() =>
        scan(document.body).forEach((seg) => place(seg, true))
      );
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
