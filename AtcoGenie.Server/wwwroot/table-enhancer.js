/**
 * AtcoGenie — Table Enhancer v3
 * ================================
 * Applied without rebuilding the React bundle.
 *
 * Behaviours:
 *  1. MESSAGE WIDTH — Globally widens all AI response bubbles by removing
 *                     Tailwind max-w-* prose constraints from the message
 *                     container. Runs on all messages, not just those with tables.
 *
 *  2. TABLE WIDTH   — Tables break out of any remaining width constraint so
 *                     all columns are visible (horizontal scroll if truly wider
 *                     than the chat column).
 *
 *  3. TABLE HEIGHT  — Tables with > MAX_VISIBLE_ROWS rows are capped at a
 *                     fixed height with an internal vertical scrollbar.
 *                     <thead> sticks to the top with a solid opaque background.
 */
(function () {
  "use strict";

  const MAX_VISIBLE_ROWS = 10;
  const ROW_HEIGHT_PX    = 46;
  const MAX_HEIGHT_PX    = (MAX_VISIBLE_ROWS + 1) * ROW_HEIGHT_PX;

  /* ── Global CSS ───────────────────────────────────────────────────────── */
  const CSS = `
    /* === 1. Widen ALL message bubbles === */
    .ag-msg-expand {
      max-width: 90% !important;
      width: 90% !important;
    }

    /* === 2. Table wrapper === */
    .ag-tbl {
      contain: none !important;
      width: 100% !important;
      max-width: 100% !important;
      overflow-x: auto !important;
      overflow-y: auto !important;
      max-height: ${MAX_HEIGHT_PX}px;
      border-radius: 8px;
      position: relative;
      scrollbar-width: thin;
      scrollbar-color: rgba(99,102,241,0.40) rgba(99,102,241,0.06);
    }
    .ag-tbl.ag-tbl-sm {
      max-height: none !important;
      overflow-y: visible !important;
    }

    /* Webkit scrollbars */
    .ag-tbl::-webkit-scrollbar        { width: 7px; height: 7px; }
    .ag-tbl::-webkit-scrollbar-track  { background: rgba(99,102,241,0.06); border-radius: 4px; }
    .ag-tbl::-webkit-scrollbar-thumb  { background: rgba(99,102,241,0.40); border-radius: 4px; }
    .ag-tbl::-webkit-scrollbar-thumb:hover { background: rgba(99,102,241,0.65); }
    .ag-tbl::-webkit-scrollbar-corner { background: rgba(99,102,241,0.06); }

    /* === 3. Table element === */
    .ag-tbl table {
      width: max-content !important;
      min-width: 100% !important;
      content-visibility: visible !important;
      contain: none !important;
      table-layout: auto !important;
    }

    /* === 4. Text wrap on data cells — prevents one long row from
              blowing out the column width. Headers stay single-line. === */
    .ag-tbl tbody td {
      white-space: normal !important;
      word-break: break-word !important;
      max-width: 340px;
    }
    .ag-tbl thead th,
    .ag-tbl thead td {
      white-space: nowrap;
    }

    /* === 5. Sticky header — inherits the SPA's own header background.
              JS resolves the actual colour and applies it inline so rows
              scrolling underneath are fully hidden. === */
    .ag-tbl thead th,
    .ag-tbl thead td {
      position: sticky !important;
      top: 0 !important;
      z-index: 10 !important;
      background-color: inherit !important;  /* overridden inline by JS */
      background-clip: padding-box !important;
      box-shadow: 0 2px 4px rgba(0,0,0,0.12);
    }

    /* === 6. Row count badge — outer spacing so it doesn't sit flush === */
    .ag-tbl-badge {
      display: inline-block;
      font-size: 11px;
      font-weight: 600;
      color: #4f46e5;
      background: rgba(99,102,241,0.10);
      border: 1px solid rgba(99,102,241,0.25);
      border-radius: 999px;
      padding: 3px 12px;
      margin: 8px 0 8px 2px;
      font-family: system-ui, -apple-system, sans-serif;
      letter-spacing: 0.02em;
      user-select: none;
    }
  `;

  function injectStyles() {
    if (document.getElementById("ag-tbl-style")) return;
    const s = document.createElement("style");
    s.id = "ag-tbl-style";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /* ── Resolve actual background colour for the sticky header ──────────── */
  function resolveHeaderBg(table) {
    // 1. Try the first <thead tr> — SPA often styles this row directly
    const theadRow = table.querySelector("thead tr");
    if (theadRow) {
      const bg = window.getComputedStyle(theadRow).backgroundColor;
      if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") return bg;
    }
    // 2. Try <thead> itself
    const thead = table.querySelector("thead");
    if (thead) {
      const bg = window.getComputedStyle(thead).backgroundColor;
      if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") return bg;
    }
    // 3. Walk up from the table to find the nearest opaque ancestor
    let node = table.parentElement;
    while (node && node !== document.body) {
      const bg = window.getComputedStyle(node).backgroundColor;
      if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") return bg;
      node = node.parentElement;
    }
    // 4. Neutral fallback — light gray, not plain white
    return "#f1f5f9";
  }

  // IDs belonging to our own injected UI — never widen these
  const OWN_IDS = new Set([
    "genie-pills", "genie-file-panel", "genie-toasts",
    "ag-ms-wrap", "ag-model-pill", "ag-model-dropdown",
    "ag-tbl-style", "ag-ms-style", "genie-upload-css",
  ]);

  /* ── Expand a single element's max-width constraint ──────────────────── */
  function releaseMaxWidth(el) {
    if (!el || el.dataset.agExpanded) return;

    // Skip our own injected nodes and any of their descendants
    if (OWN_IDS.has(el.id)) return;
    let anc = el.parentElement;
    while (anc) {
      if (OWN_IDS.has(anc.id)) return;
      anc = anc.parentElement;
    }

    const mw = window.getComputedStyle(el).maxWidth;
    if (!mw || mw === "none" || mw.includes("%")) return;

    // Only target elements that look like message-level prose containers:
    //  - max-width is a large px value (> 400px) — real bubble clamp
    //  - element is actually wide enough on screen (> 300px rendered width)
    const mwPx = parseFloat(mw);
    if (isNaN(mwPx) || mwPx < 400) return;   // skip small chips/buttons
    if (el.offsetWidth < 300) return;         // skip tiny rendered nodes

    el.dataset.agExpanded = "1";
    el.classList.add("ag-msg-expand");
  }

  /* ── Expand ALL message bubbles in the chat area ─────────────────────── */
  function expandAllMessages() {
    const chatRoot = document.querySelector("main") || document.body;
    // Only scan structural block elements — not inline/widget nodes
    chatRoot.querySelectorAll("div, article, section").forEach(el => {
      releaseMaxWidth(el);
    });
  }

  /* ── Walk up from the table wrapper to release any remaining clamp ───── */
  function expandTableAncestors(wrapper) {
    let node = wrapper.parentElement;
    let depth = 0;
    while (node && node !== document.body && depth < 8) {
      releaseMaxWidth(node);
      node = node.parentElement;
      depth++;
    }
  }

  /* ── Core table enhancement ───────────────────────────────────────────── */
  function enhanceWrapper(wrapper) {
    if (wrapper.dataset.agTbl) return;
    const table = wrapper.querySelector("table");
    if (!table) return;

    wrapper.dataset.agTbl = "1";
    wrapper.classList.add("ag-tbl");

    expandTableAncestors(wrapper);

    const rowCount = table.querySelectorAll("tbody tr").length;
    if (rowCount <= MAX_VISIBLE_ROWS) {
      wrapper.classList.add("ag-tbl-sm");
    } else {
      if (!wrapper.previousElementSibling?.classList.contains("ag-tbl-badge")) {
        const badge = document.createElement("div");
        badge.className = "ag-tbl-badge";
        badge.textContent = `${rowCount.toLocaleString()} rows — scroll to explore`;
        wrapper.parentNode.insertBefore(badge, wrapper);
      }
    }

    // Solid background on sticky header cells — resolved from the table itself
    const headerBg = resolveHeaderBg(table);
    table.querySelectorAll("thead th, thead td").forEach(cell => {
      cell.style.setProperty("background-color", headerBg, "important");
    });
  }

  /* ── Scan ─────────────────────────────────────────────────────────────── */
  function scan() {
    expandAllMessages();
    document.querySelectorAll(".overflow-x-auto").forEach(enhanceWrapper);
    document.querySelectorAll("table").forEach(t => {
      const p = t.parentElement;
      if (p && !p.dataset.agTbl) enhanceWrapper(p);
    });
  }

  /* ── Boot ─────────────────────────────────────────────────────────────── */
  function boot() {
    injectStyles();
    scan();
    const obs = new MutationObserver(() => scan());
    obs.observe(document.body, { childList: true, subtree: true });
    console.log("[AtcoGenie] 📊 Table enhancer v3 ready.");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    setTimeout(boot, 600);
  }
})();
