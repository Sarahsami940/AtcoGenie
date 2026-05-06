/**
 * AtcoGenie â€” Theme Init v4
 *
 * - Sidebar: #071D44 solid + bright gradient blobs (#1657CB light end)
 * - Chat header: max-width constraint applied via JS
 * - Blobs injected INSIDE the sidebar container
 * - Hover text fix via mouseenter/leave listeners
 */
(function () {
  "use strict";

  const SB_BG      = "#071D44";
  const SB_BLOB    = "#1657CB";
  const SB_HOVER   = "rgba(255,255,255,0.09)";
  const SB_ACTIVE  = "rgba(255,255,255,0.14)";
  const SB_TEXT    = "#c5d8f8";
  const SB_HEADING = "rgba(197,216,248,0.45)";
  const SB_BORDER  = "rgba(255,255,255,0.07)";
  const SB_WHITE   = "#ffffff";

  /* â”€â”€ 1. Find sidebar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  function findSidebar() {
    const btns = Array.from(document.querySelectorAll("button, a, div[role='button']"));
    const newChat = btns.find(el => /new\s*chat/i.test(el.textContent?.trim() || ""));
    if (newChat) {
      let el = newChat.parentElement;
      for (let i = 0; i < 12; i++) {
        if (!el) break;
        const w = el.offsetWidth, h = el.offsetHeight;
        if (w > 40 && w < 360 && h > 300) return el;
        el = el.parentElement;
      }
    }
    for (const sel of ['[class*="sidebar"]', '[class*="Sidebar"]', '[class*="side-bar"]']) {
      const el = document.querySelector(sel);
      if (el && el.offsetWidth > 40 && el.offsetWidth < 360 && el.offsetHeight > 300) return el;
    }
    return Array.from(document.querySelectorAll("div")).find(d =>
      d.offsetWidth > 80 && d.offsetWidth < 320 && d.offsetHeight > 400 && d.children.length > 1
    ) || null;
  }

  /* â”€â”€ 2. Inject gradient blobs INSIDE the sidebar â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  function injectSidebarBlobs(sb) {
    if (sb.querySelector(".ag-sb-blob")) return; // already done

    const blobs = [
      // Top-right corner blob â€” brightest
      {
        id: "ag-sb-blob-1",
        style: `
          width: 220px; height: 220px;
          top: -60px; right: -60px;
          background: radial-gradient(ellipse at center,
            ${SB_BLOB}cc 0%,
            ${SB_BLOB}55 45%,
            transparent 75%);
          filter: blur(38px);
          opacity: 0.75;
          animation: agSbBlob1 20s ease-in-out infinite alternate;
        `
      },
      // Bottom-left blob â€” medium
      {
        id: "ag-sb-blob-2",
        style: `
          width: 200px; height: 200px;
          bottom: 80px; left: -50px;
          background: radial-gradient(ellipse at center,
            ${SB_BLOB}aa 0%,
            ${SB_BLOB}33 50%,
            transparent 80%);
          filter: blur(45px);
          opacity: 0.6;
          animation: agSbBlob2 26s ease-in-out infinite alternate;
          animation-delay: -9s;
        `
      },
      // Mid blob â€” subtle
      {
        id: "ag-sb-blob-3",
        style: `
          width: 160px; height: 160px;
          top: 38%; left: 10%;
          background: radial-gradient(ellipse at center,
            ${SB_BLOB}88 0%,
            ${SB_BLOB}22 55%,
            transparent 80%);
          filter: blur(50px);
          opacity: 0.45;
          animation: agSbBlob3 32s ease-in-out infinite alternate;
          animation-delay: -5s;
        `
      }
    ];

    blobs.forEach(({ id, style }) => {
      const el = document.createElement("div");
      el.id = id;
      el.className = "ag-sb-blob";
      el.style.cssText = `position:absolute;border-radius:50%;pointer-events:none;z-index:0;${style}`;
      sb.appendChild(el);
    });

    // Inject sidebar blob keyframes if not present
    if (!document.getElementById("ag-sb-kf")) {
      const s = document.createElement("style");
      s.id = "ag-sb-kf";
      s.textContent = `
        @keyframes agSbBlob1 {
          0%   { transform: translate(0,0) scale(1); }
          40%  { transform: translate(-20px,18px) scale(1.08); }
          100% { transform: translate(14px,-22px) scale(0.95); }
        }
        @keyframes agSbBlob2 {
          0%   { transform: translate(0,0) scale(1); }
          45%  { transform: translate(18px,-24px) scale(1.06); }
          100% { transform: translate(-22px,16px) scale(0.97); }
        }
        @keyframes agSbBlob3 {
          0%   { transform: translate(0,0) scale(1); }
          50%  { transform: translate(-10px,-20px) scale(1.04); }
          100% { transform: translate(10px,18px) scale(0.98); }
        }
      `;
      document.head.appendChild(s);
    }
  }

  /* â”€â”€ 3. Apply all sidebar styles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  function styleSidebar(sb) {
    if (sb.dataset.agSidebarDone) return;
    sb.dataset.agSidebarDone = "1";
    sb.setAttribute("data-ag-sidebar", "true");

    // Core background
    sb.style.setProperty("background", SB_BG, "important");
    sb.style.setProperty("border-right", `1px solid ${SB_BORDER}`, "important");
    sb.style.setProperty("position", "relative", "important");
    // NOTE: Do NOT set overflow:hidden — it clips position:fixed dropdowns
    // (the 3-dot menu). Blobs are clipped via their own container instead.
    sb.style.setProperty("overflow-y", "auto", "important");
    sb.style.setProperty("overflow-x", "hidden", "important");

    // Inject blobs into sidebar
    injectSidebarBlobs(sb);

    // Paint children + set up hover listeners
    paintChildren(sb);

    // Re-paint on React re-renders
    new MutationObserver(() => paintChildren(sb))
      .observe(sb, { childList: true, subtree: true });
  }

  // Module-level: apply the active chat highlight style
  function applyActiveHighlight(sb, el) {
    if (!el || el.dataset.agActiveMarked) return;
    if (!sb.contains(el)) return;
    el.dataset.agActiveMarked = "1";
    el.setAttribute("data-ag-active-chat", "true");
    el.style.setProperty("background", "rgba(255,255,255,0.18)", "important");
    el.style.setProperty("border-left", "3px solid #60a5fa", "important");
    el.style.setProperty("border-radius", "0 8px 8px 0", "important");
    el.style.setProperty("color", "#ffffff", "important");
    el.querySelectorAll("*").forEach(c => c.style.setProperty("color", "#ffffff", "important"));
  }

  /* ── Helper: check if element is inside a floating popup layer ── */
  function isInsideFloatingLayer(el) {
    let node = el;
    while (node && node !== document.body) {
      const pos = window.getComputedStyle(node).position;
      if (pos === "fixed" || pos === "absolute") {
        // Check if it has high z-index (popup indicator)
        const z = parseInt(window.getComputedStyle(node).zIndex, 10);
        if (z >= 100) return true;
      }
      if (node.matches && node.matches('[role="menu"], [role="listbox"], [role="dialog"], [role="tooltip"]')) return true;
      node = node.parentElement;
    }
    return false;
  }

  function paintChildren(sb) {
    // 1. Strip light backgrounds — skip overlays, menus, and any absolute/fixed elements
    sb.querySelectorAll("*").forEach(el => {
      if (el.classList.contains("ag-sb-blob")) return;
      // Skip any element that is (or is inside) a floating/popup layer
      const pos = window.getComputedStyle(el).position;
      if (pos === "absolute" || pos === "fixed") return;
      if (isInsideFloatingLayer(el)) return;
      const bg = window.getComputedStyle(el).backgroundColor;
      if (isLightBg(bg)) {
        el.style.setProperty("background-color", "transparent", "important");
        el.style.setProperty("background", "transparent", "important");
      }
    });

    // 1b. Capture active chat â€” ONLY look at BUTTON elements
    //     Chat list items are <button>s; profile divs and panels are not
    const activeCandidates = [];
    sb.querySelectorAll("button").forEach(btn => {
      // Must have had a light (non-dark) computed background before we stripped it
      // Re-check via className for exact token (not hover: variants)
      const tokens = new Set((btn.className || "").toString().split(/\s+/));
      const hasActiveBg = tokens.has("bg-slate-100") || tokens.has("bg-slate-200") ||
                          tokens.has("bg-blue-50")   || tokens.has("bg-blue-100");
      if (!hasActiveBg) return;

      const txt = (btn.textContent?.trim() || "");
      // Skip known UI buttons by exact text
      if (/^(new\s*chat|chats?|archived?|search|\+)$/i.test(txt)) return;
      // Chat titles are between ~8 and 80 chars
      if (txt.length < 8 || txt.length > 80) return;

      activeCandidates.push(btn);
    });
    activeCandidates.forEach(el => applyActiveHighlight(sb, el));

    // 1c. Also check aria attributes
    sb.querySelectorAll("[aria-current], [aria-selected='true']").forEach(el => {
      applyActiveHighlight(sb, el);
    });

    // 1d. Click listeners for active-chat tracking â€” only on real chat-list items
    sb.querySelectorAll("button, a, [role='button']").forEach(btn => {
      if (btn.dataset.agClickHandler) return;
      // Skip buttons inside dropdown menus (Unarchive, Delete, etc.)
      const pos = window.getComputedStyle(btn).position;
      if (pos === "absolute" || pos === "fixed") return;
      if (btn.closest('[role="menu"], [role="listbox"], [role="dialog"]')) return;
      const txt = (btn.textContent?.trim() || "");
      // Skip icon-only buttons (â‹® ellipsis, search icon, etc.)
      if (txt.length < 8 || txt.length > 100) return;
      if (/^(new\s*chat|chats?|archived?|search|\+|â‹®|â€¦|â€¢â€¢â€¢)$/i.test(txt)) return;
      btn.dataset.agClickHandler = "1";
      btn.addEventListener("click", () => {
        // Only clear/set if this looks like a chat item (not a folder, tab, etc.)
        sb.querySelectorAll("[data-ag-active-chat]").forEach(old => {
          old.removeAttribute("data-ag-active-chat");
          delete old.dataset.agActiveMarked;
          old.style.removeProperty("background");
          old.style.removeProperty("border-left");
          old.style.removeProperty("border-radius");
        });
        // Mark clicked item after React settles
        setTimeout(() => applyActiveHighlight(sb, btn), 250);
      });
    });

    // 2. Force text colour
    sb.querySelectorAll("*").forEach(el => {
      if (el.classList.contains("ag-sb-blob")) return;
      if (el.tagName === "svg" || el.tagName === "path") return;
      const col = window.getComputedStyle(el).color;
      if (!isLightColor(col)) {
        el.style.setProperty("color", SB_TEXT, "important");
      }
    });

    // 3. Section headings â€” FOLDERS, RECENT only (NOT Chats/Archived tabs)
    sb.querySelectorAll("*").forEach(el => {
      const txt = el.textContent?.trim().toUpperCase();
      if (el.children.length === 0 && (
        txt === "FOLDERS" || txt === "RECENT" || txt === "TODAY" ||
        txt === "YESTERDAY" || txt === "PINNED FOLDERS" || txt === "RECENT CHATS"
      )) {
        el.style.setProperty("color", SB_HEADING, "important");
        el.style.setProperty("font-size", "10px", "important");
        el.style.setProperty("letter-spacing", "0.1em", "important");
        el.style.setProperty("font-weight", "600", "important");
      }
      // Chats / Archived tab labels â€” keep bright white
      if (el.children.length === 0 && (txt === "CHATS" || txt === "ARCHIVED")) {
        el.style.setProperty("color", "rgba(255,255,255,0.85)", "important");
        el.style.setProperty("font-size", "12px", "important");
        el.style.setProperty("font-weight", "600", "important");
      }
    });


    // 4. Active items
    sb.querySelectorAll('[aria-current], [aria-selected="true"], [class*="bg-blue-50"], [class*="bg-blue-100"]')
      .forEach(el => {
        el.style.setProperty("background", SB_ACTIVE, "important");
        el.style.setProperty("border-radius", "8px", "important");
      });

    // 5. New Chat button â€” blue accent
    const allBtns = Array.from(sb.querySelectorAll("button, a"));
    const newChatBtn = allBtns.find(el => /new\s*chat/i.test(el.textContent?.trim() || ""));
    if (newChatBtn) {
      newChatBtn.style.setProperty("background", "#1657CB", "important");
      newChatBtn.style.setProperty("color", SB_WHITE, "important");
      newChatBtn.style.setProperty("border-radius", "10px", "important");
      newChatBtn.style.setProperty("box-shadow", "0 2px 12px rgba(0,0,0,0.3)", "important");
      newChatBtn.style.setProperty("position", "relative", "important");
      newChatBtn.style.setProperty("z-index", "2", "important");
      newChatBtn.querySelectorAll("*").forEach(c => c.style.setProperty("color", SB_WHITE, "important"));
    }

    // 6. Hover / mouseleave on clickable items
    sb.querySelectorAll("button, a, li, [role='button'], [class*='cursor-pointer']").forEach(el => {
      if (el.dataset.agHover) return;
      if (el === newChatBtn) return; // skip new-chat button
      // Skip the 3-dot trigger button — its visibility is handled by CSS
      if (el.classList.contains("opacity-0") || (el.className || "").toString().includes("group-hover")) return;
      el.dataset.agHover = "1";

      el.addEventListener("mouseenter", () => {
        if (!el.dataset.agActive) {
          el.style.setProperty("background", SB_HOVER, "important");
          el.style.setProperty("border-radius", "8px", "important");
          el.querySelectorAll("*").forEach(c => {
            // Don't touch children that are inside opacity-0 buttons (3-dot trigger)
            if (c.closest && c.closest('button[class*="opacity-0"]')) return;
            c.style.setProperty("color", SB_WHITE, "important");
          });
          el.style.setProperty("color", SB_WHITE, "important");
        }
      });
      el.addEventListener("mouseleave", () => {
        if (!el.dataset.agActive) {
          el.style.removeProperty("background");
          el.style.setProperty("color", SB_TEXT, "important");
          el.querySelectorAll("*").forEach(c => {
            if (c.closest && c.closest('button[class*="opacity-0"]')) return;
            c.style.setProperty("color", SB_TEXT, "important");
          });
        }
      });
    });

    // 7. Borders
    sb.querySelectorAll("[class*='border']").forEach(el => {
      if (el.classList.contains("ag-sb-blob")) return;
      el.style.setProperty("border-color", SB_BORDER, "important");
    });

    // 8. Ensure all sidebar content sits above blobs
    sb.querySelectorAll(":scope > *").forEach(el => {
      if (!el.classList.contains("ag-sb-blob")) {
        el.style.setProperty("position", "relative", "important");
        el.style.setProperty("z-index", "1", "important");
      }
    });
  }

  function isLightBg(bg) {
    const m = bg.match(/(\d+),\s*(\d+),\s*(\d+)/);
    if (!m) return false;
    return (+m[1] + +m[2] + +m[3]) / 3 > 150;
  }

  // Detect bg-blue-50 / bg-blue-100 style (active chat highlight)
  function isBlueTinted(bg) {
    const m = bg.match(/(\d+),\s*(\d+),\s*(\d+)/);
    if (!m) return false;
    const [r, g, b] = [+m[1], +m[2], +m[3]];
    const avg = (r + g + b) / 3;
    return avg > 150 && b > r && (b - r) > 6;
  }

  function isLightColor(col) {
    const m = col.match(/(\d+),\s*(\d+),\s*(\d+)/);
    if (!m) return false;
    return (+m[1] + +m[2] + +m[3]) / 3 > 150;
  }

  /* ── 4. Main area gradient blobs ── */
  /* Injected INSIDE the main content container (not body) so they
     live within ChainLit's opaque wrapper stack and are actually visible.
     Uses position:absolute relative to the container.                    */
  function injectMainBlobs() {
    if (document.getElementById("ag-main-blob-1")) return;

    // Find the main content area — the scrollable chat column.
    // ChainLit structure: body > div.flex.h-screen > div.flex-1 > main
    const mainEl = document.querySelector("main");
    if (!mainEl) return;  // retry via boot()

    // The container that holds main — this is the flex-1 column
    const container = mainEl.parentElement || mainEl;
    container.style.setProperty("position", "relative", "important");
    container.style.setProperty("overflow", "hidden", "important");

    const defs = [
      {
        id: "ag-main-blob-1",
        css: `position:absolute;width:560px;height:560px;top:-120px;right:-80px;border-radius:50%;
              background:radial-gradient(ellipse at center,rgba(22,87,203,0.32) 0%,rgba(99,149,235,0.14) 55%,transparent 80%);
              filter:blur(52px);pointer-events:none;z-index:0;
              animation:agMainB1 22s ease-in-out infinite alternate;`
      },
      {
        id: "ag-main-blob-2",
        css: `position:absolute;width:440px;height:440px;bottom:60px;left:-60px;border-radius:50%;
              background:radial-gradient(ellipse at center,rgba(22,87,203,0.26) 0%,rgba(96,165,250,0.11) 55%,transparent 80%);
              filter:blur(58px);pointer-events:none;z-index:0;
              animation:agMainB2 28s ease-in-out infinite alternate;animation-delay:-12s;`
      },
      {
        id: "ag-main-blob-3",
        css: `position:absolute;width:340px;height:340px;top:38%;right:15%;border-radius:50%;
              background:radial-gradient(ellipse at center,rgba(56,189,248,0.20) 0%,rgba(14,165,233,0.08) 60%,transparent 80%);
              filter:blur(64px);pointer-events:none;z-index:0;
              animation:agMainB1 34s ease-in-out infinite alternate;animation-delay:-7s;`
      }
    ];

    defs.forEach(({ id, css }) => {
      const el = document.createElement("div");
      el.id = id;
      el.className = "ag-main-blob";
      el.style.cssText = css;
      container.appendChild(el);
    });

    // Ensure all real content inside container sits above blobs
    Array.from(container.children).forEach(child => {
      if (!child.classList.contains("ag-main-blob")) {
        const pos = window.getComputedStyle(child).position;
        if (pos === "static") {
          child.style.setProperty("position", "relative", "important");
        }
        child.style.setProperty("z-index", "1", "important");
      }
    });

    if (!document.getElementById("ag-main-kf")) {
      const s = document.createElement("style");
      s.id = "ag-main-kf";
      s.textContent = `
        @keyframes agMainB1 {
          0%   { transform: translate(0,0) scale(1); }
          40%  { transform: translate(28px,-22px) scale(1.05); }
          100% { transform: translate(-12px,14px) scale(0.97); }
        }
        @keyframes agMainB2 {
          0%   { transform: translate(0,0) scale(1); }
          45%  { transform: translate(-22px,-28px) scale(1.06); }
          100% { transform: translate(16px,12px) scale(0.96); }
        }
        @keyframes msgSlideIn {
          from { opacity:0; transform:translateY(10px); }
          to   { opacity:1; transform:translateY(0); }
        }
      `;
      document.head.appendChild(s);
    }
  }

  /* ── 5. Chat header — constrain width ── */
  function constrainChatHeader() {
    // Look for the top bar (sticky header) in main content
    const candidates = Array.from(document.querySelectorAll(
      "header, [class*='sticky'][class*='top'], [class*='border-b']"
    )).filter(el => {
      const rect = el.getBoundingClientRect();
      return rect.top < 80 && rect.width > 400 && !el.closest("[data-ag-sidebar]");
    });

    candidates.forEach(el => {
      if (el.dataset.agHeader) return;
      el.dataset.agHeader = "1";
      el.style.setProperty("max-width", "900px", "important");
      el.style.setProperty("margin-left", "auto", "important");
      el.style.setProperty("margin-right", "auto", "important");
      el.style.setProperty("border-radius", "0 0 14px 14px", "important");
      el.style.setProperty("box-shadow", "0 2px 12px rgba(0,0,0,0.06)", "important");
    });
  }

  /* â”€â”€ 6. Input bar glow â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  function enhanceInputBar() {
    document.addEventListener("focusin", e => {
      const ta = e.target.closest("textarea");
      if (!ta) return;
      const form = ta.closest("form") || ta.parentElement?.parentElement;
      if (form) {
        form.style.boxShadow = "0 0 0 3px rgba(22,87,203,0.15), 0 2px 12px rgba(0,0,0,0.07)";
        form.style.borderColor = "rgba(22,87,203,0.35)";
        form.style.transition = "box-shadow 0.2s ease, border-color 0.2s ease";
      }
    });
    document.addEventListener("focusout", e => {
      const ta = e.target.closest("textarea");
      if (!ta) return;
      const form = ta.closest("form") || ta.parentElement?.parentElement;
      if (form) {
        form.style.boxShadow = "0 2px 12px rgba(0,0,0,0.07)";
        form.style.borderColor = "#e2e8f0";
      }
    });
  }

  /* â”€â”€ 7. User message bubble fixer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  let _fixingBubbles = false;
  function fixUserBubbles() {
    if (_fixingBubbles) return;
    _fixingBubbles = true;
    const chat = document.querySelector("main") || document.body;

    chat.querySelectorAll('[class*="justify-end"]').forEach(row => {
      if (row.closest("[data-ag-sidebar]")) return;
      if (row.dataset.agUserRow) return;

      const bubble = row.firstElementChild;
      if (!bubble) return;

      // â”€â”€ Exclusions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
      if (bubble.querySelector("textarea, input, form")) return;
      if (bubble.querySelector("table, pre, code, td, th")) return;
      if (row.querySelector("table, td")) return;
      const txt = bubble.textContent?.trim() || "";
      if (txt.length < 3) return;
      // Skip action button rows (Copy Table, Copy, Download, etc.)
      if (/^(copy|copy table|copy all|download|export|clear|cancel|close|send)$/i.test(txt)) return;
      // Skip rows where ALL visible children are buttons or icons
      const meaningfulChildren = Array.from(bubble.querySelectorAll("*")).filter(
        c => c.children.length === 0 && c.tagName !== "SVG" && c.tagName !== "PATH" &&
             c.tagName !== "BUTTON" && (c.textContent?.trim().length || 0) > 0
      );
      if (meaningfulChildren.length === 0 && bubble.querySelectorAll("button, svg").length > 0) return;
      if (bubble.children.length > 6) return;
      // â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

      row.dataset.agUserRow = "1";
      row.setAttribute("data-ag-user-row", "true");
      bubble.setAttribute("data-ag-user-bubble", "true");

      bubble.style.setProperty("background", "linear-gradient(135deg, #1d4ed8, #2563eb)", "important");
      bubble.style.setProperty("color", "#ffffff", "important");
      bubble.style.setProperty("border-radius", "18px 18px 4px 18px", "important");
      bubble.style.setProperty("padding", "10px 16px", "important");
      bubble.style.setProperty("max-width", "72%", "important");
      bubble.style.setProperty("width", "fit-content", "important");
      bubble.style.setProperty("box-shadow", "0 2px 12px rgba(29,78,216,0.3)", "important");
      bubble.style.setProperty("word-break", "break-word", "important");
      bubble.style.setProperty("display", "block", "important");

      bubble.querySelectorAll("*").forEach(c => {
        c.style.setProperty("color", "#ffffff", "important");
        c.style.setProperty("background", "transparent", "important");
      });
    });
    _fixingBubbles = false;
  }

  /* â”€â”€ 7b. Chat header â€” narrow + centered â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  function constrainChatHeader() {
    if (document.querySelector('[data-ag-header-done]')) return;

    // Find any element whose text is exactly "ATCO Genie" or contains it
    // (handles split spans like <span>ATCO</span><span> Genie</span>)
    let headerBar = null;
    const allEls = Array.from(document.querySelectorAll("header, [class*='border-b'], [class*='sticky'], [class*='top-0']"));
    for (const el of allEls) {
      if (el.closest("[data-ag-sidebar]")) continue;
      const rect = el.getBoundingClientRect();
      if (rect.top < 5 && rect.height > 0 && rect.height < 100 && rect.width > 400) {
        headerBar = el;
        break;
      }
    }
    if (!headerBar) return;
    headerBar.setAttribute("data-ag-header-done", "true");

    // Center the header content within its full-width parent
    const parent = headerBar.parentElement;
    if (parent) {
      parent.style.setProperty("display", "flex", "important");
      parent.style.setProperty("justify-content", "center", "important");
    }
    headerBar.style.setProperty("max-width", "900px", "important");
    headerBar.style.setProperty("width", "100%", "important");
    headerBar.style.setProperty("padding-top", "6px", "important");
    headerBar.style.setProperty("padding-bottom", "6px", "important");
    headerBar.style.setProperty("min-height", "unset", "important");
  }

  /* â”€â”€ 8. Message entrance animation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  function observeMessages() {
    fixUserBubbles(); // Run on existing messages
    let _msgDebounce = null;
    new MutationObserver(mutations => {
      for (const m of mutations) {
        for (const n of m.addedNodes) {
          if (n.nodeType !== 1) continue;
          if (n.className?.includes?.("group") || n.querySelector?.('[class*="rounded-2xl"]')) {
            n.style.animation = "msgSlideIn 0.25s cubic-bezier(0.16,1,0.3,1) both";
          }
        }
      }
      // Debounce: SSE streaming causes rapid DOM updates
      if (_msgDebounce) clearTimeout(_msgDebounce);
      _msgDebounce = setTimeout(fixUserBubbles, 200);
      // NOTE: do NOT call hideInputChips here â€” it runs at document level and can hide the sidebar
    }).observe(document.body, { childList: true, subtree: true });

  }

  /* -- Hide theme toggle button -- */
  function hideThemeToggle() {
    document.querySelectorAll('button').forEach(btn => {
      const label = (btn.getAttribute('aria-label') || btn.getAttribute('title') || '').toLowerCase();
      if (/dark|light|theme|mode/.test(label)) { btn.style.setProperty('display','none','important'); return; }
      const svgText = btn.querySelector('svg')?.innerHTML || '';
      if (/moon|sun|brightness/i.test(svgText)) { btn.style.setProperty('display','none','important'); }
    });
  }

  /* -- Hide file chips from the input bar -- */
  function hideInputChips() {
    document.querySelectorAll('textarea').forEach(ta => {
      const parent = ta.parentElement;
      if (!parent) return;
      Array.from(parent.children).forEach(child => {
        if (child === ta || child.contains(ta)) return;
        if (child.tagName === 'TEXTAREA' || child.tagName === 'BUTTON') return;
        if (child.offsetWidth > 400 || child.offsetHeight > 200) return;
        const hasCloseBtn = !!child.querySelector('button');
        const txt = child.textContent?.trim() || '';
        if (!hasCloseBtn || txt.length < 3 || txt.length > 100) return;
        child.style.setProperty('display','none','important');
      });
    });
  }

  /* ── Fix 3-dot dropdown: portal to body for correct positioning ── */
  function fixDropdownMenus() {
    if (!document.getElementById("ag-dropdown-fix")) {
      const style = document.createElement("style");
      style.id = "ag-dropdown-fix";
      style.textContent = `
        /* Hide original misplaced dropdown (we portal a clone to body) */
        [data-ag-sidebar] div[class*="z-[200]"][class*="shadow"] {
          visibility: hidden !important;
          pointer-events: none !important;
          width: 0 !important; height: 0 !important;
          overflow: hidden !important;
        }
        .ag-dropdown-portal {
          position: fixed !important; z-index: 99999 !important;
          background: #1e293b !important;
          border: 1px solid rgba(255,255,255,0.12) !important;
          border-radius: 8px !important;
          box-shadow: 0 8px 30px rgba(0,0,0,0.4) !important;
          padding: 4px 0 !important; min-width: 120px !important;
        }
        .ag-dropdown-portal button {
          color: #e2e8f0 !important; background: transparent !important;
          display: flex !important; width: 100% !important;
          text-align: left !important; padding: 6px 12px !important;
          font-size: 12px !important; align-items: center !important;
          gap: 8px !important; cursor: pointer !important;
          border: none !important; outline: none !important;
        }
        .ag-dropdown-portal button:hover { background: rgba(255,255,255,0.1) !important; }
        .ag-dropdown-portal button:last-child { color: #fca5a5 !important; }
        .ag-dropdown-portal button:last-child:hover { background: rgba(220,38,38,0.15) !important; }
        .ag-dropdown-portal svg {
          color: #94a3b8 !important; stroke: #94a3b8 !important;
          width: 12px !important; height: 12px !important; flex-shrink: 0 !important;
        }
        .ag-dropdown-backdrop { position: fixed; inset: 0; z-index: 99998; background: transparent; }

        /* ── 3-dot trigger: visible on hover ── */
        .group:hover > div > button[class*="opacity-0"],
        .group:hover button[class*="group-hover"],
        [data-ag-sidebar] .group:hover button[class*="opacity-0"] { opacity: 1 !important; }
        [data-ag-sidebar] .group:hover button[class*="opacity-0"] svg,
        [data-ag-sidebar] .group:hover button[class*="opacity-0"] svg path {
          stroke: rgba(255,255,255,0.7) !important; color: rgba(255,255,255,0.7) !important;
        }
        [data-ag-sidebar] .group:hover button[class*="opacity-0"]:hover {
          background: rgba(255,255,255,0.15) !important; border-radius: 6px !important;
        }
        [data-ag-sidebar] .group:hover button[class*="opacity-0"]:hover svg,
        [data-ag-sidebar] .group:hover button[class*="opacity-0"]:hover svg path {
          stroke: #fff !important; color: #fff !important;
        }

        /* ── Sidebar spacing + readability ── */
        [data-ag-sidebar] .group,
        [data-ag-sidebar] button[class*="text-left"],
        [data-ag-sidebar] div[class*="relative group"] {
          padding-top: 8px !important; padding-bottom: 8px !important; margin-bottom: 2px !important;
        }
        [data-ag-sidebar] .group span, [data-ag-sidebar] .group p,
        [data-ag-sidebar] button[class*="text-left"] span,
        [data-ag-sidebar] button[class*="truncate"] {
          font-weight: 400 !important; font-size: 13px !important;
          letter-spacing: 0.01em !important; line-height: 1.4 !important;
        }
        [data-ag-sidebar] div[class*="ml-5"],
        [data-ag-sidebar] div[class*="pl-2"] { border-left-color: rgba(255,255,255,0.06) !important; }
        [data-ag-sidebar] button[class*="font-medium"] { font-weight: 500 !important; font-size: 12.5px !important; }
        [data-ag-sidebar] .group svg:not([class*="h-3"]) { opacity: 0.5 !important; width: 14px !important; height: 14px !important; }
      `;
      document.head.appendChild(style);
    }

    // Portal system: clone dropdown to body for correct positioning
    let activePortal = null, activeBackdrop = null;
    function closePortal() {
      if (activePortal) { activePortal.remove(); activePortal = null; }
      if (activeBackdrop) { activeBackdrop.remove(); activeBackdrop = null; }
    }
    function portalDropdown(original) {
      closePortal();
      const wrapper = original.closest(".relative") || original.parentElement;
      const trigger = wrapper?.querySelector('button[class*="opacity-0"]') || wrapper?.querySelector("button");
      const rect = trigger ? trigger.getBoundingClientRect() : { bottom: 200, right: 260 };

      activeBackdrop = document.createElement("div");
      activeBackdrop.className = "ag-dropdown-backdrop";
      activeBackdrop.addEventListener("mousedown", (e) => {
        e.stopPropagation(); closePortal();
        window.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });
      document.body.appendChild(activeBackdrop);

      activePortal = original.cloneNode(true);
      activePortal.className = "ag-dropdown-portal";
      activePortal.removeAttribute("style");
      activePortal.style.top = (rect.bottom + 4) + "px";
      activePortal.style.left = Math.max(8, rect.right - 130) + "px";

      const clonedBtns = activePortal.querySelectorAll("button");
      const originalBtns = original.querySelectorAll("button");
      clonedBtns.forEach((btn, i) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault(); e.stopPropagation(); closePortal();
          if (originalBtns[i]) setTimeout(() => originalBtns[i].click(), 10);
        });
      });
      document.body.appendChild(activePortal);
    }

    // Scope to sidebar only (not body) to avoid triggering on SSE tokens
    let _portalDebounce = null;
    function startPortalObserver() {
      const sb = document.querySelector("[data-ag-sidebar]");
      if (!sb) { setTimeout(startPortalObserver, 500); return; }
      new MutationObserver(() => {
        if (_portalDebounce) return;
        _portalDebounce = setTimeout(() => {
          _portalDebounce = null;
          const dd = sb.querySelector('div[class*="z-[200]"][class*="shadow"]');
          if (dd && !dd.dataset.agPortaled) {
            dd.dataset.agPortaled = "1";
            requestAnimationFrame(() => portalDropdown(dd));
          } else if (!dd && activePortal) { closePortal(); }
        }, 50);
      }).observe(sb, { childList: true, subtree: true });
    }
    startPortalObserver();
  }

  function boot() {
    fixDropdownMenus();
    injectMainBlobs();
    enhanceInputBar();
    observeMessages();

    // Retry sidebar until React mounts it
    let sbAttempts = 0;
    function trySidebar() {
      const sb = findSidebar();
      if (sb) {
        styleSidebar(sb);
        setTimeout(fixUserBubbles, 600);
        setTimeout(fixUserBubbles, 2000);
        setTimeout(hideThemeToggle, 800);
        setTimeout(hideThemeToggle, 2500);
        setTimeout(hideInputChips, 1000);
        setTimeout(hideInputChips, 3000);
        return;
      }
      if (++sbAttempts < 30) setTimeout(trySidebar, 400);
    }
    trySidebar();

    // Retry header every 1s for up to 10s (React may lazy-render it)
    let hdAttempts = 0;
    function tryHeader() {
      constrainChatHeader();
      if (!document.querySelector("[data-ag-header-done]") && ++hdAttempts < 10) {
        setTimeout(tryHeader, 1000);
      }
    }
    setTimeout(tryHeader, 800);
  }


  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

