/**
 * AtcoGenie — Excel Upload Handler v8
 *
 * Session-scoped uploads (SPA-aware):
 *  - Detects the active chat by intercepting fetch() calls to /api/chats/{id}
 *  - Files can ONLY be uploaded inside a chat (not from homepage)
 *  - Files persist across refreshes by fetching from the server on chat load
 *
 * v8 changes:
 *  - Fixed "ready" chip: dark-green bg + bright text (legible)
 *  - Added "Uploaded Files" collapsible panel in the left sidebar
 */

(function () {
  "use strict";

  const MAX_BYTES = 25 * 1024 * 1024; // 25 MB

  /* ── State ──────────────────────────────────────────────────────────────── */
  let uploads = [];   // { id, filename, status, sheetNames, rowCount, error }
  const pollers = {};   // upload_id → intervalId
  let pillBar   = null;
  let patched   = false;
  let activeSessionId = null;  // numeric chat ID, detected from SPA interactions

  /* ── Session detection via fetch interception ───────────────────────────── */
  // The React SPA calls GET /api/chats/<id> whenever a chat is selected.
  // We intercept window.fetch to detect the active chat session.
  const _origFetch = window.fetch;
  window.fetch = function (...args) {
    const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
    // Match: /api/chats/123 (GET to load a chat) — but not /api/chats/search etc.
    const chatLoad = url.match(/\/api\/chats\/(\d+)$/);
    if (chatLoad) {
      const newId = chatLoad[1];
      if (newId !== activeSessionId) {
        activeSessionId = newId;
        // Clear previous uploads state and reload for new session
        clearState();
        setTimeout(() => loadSessionUploads(newId), 300);
      }
    }
    // Detect new chat creation: POST /api/chats (returns {id: ...})
    const result = _origFetch.apply(this, args);
    if (url.match(/\/api\/chats\/?$/) && args[1]?.method?.toUpperCase() === "POST") {
      result.then(resp => {
        if (resp.ok) {
          // Clone to read without consuming the body
          resp.clone().json().then(data => {
            if (data?.id) {
              activeSessionId = String(data.id);
              clearState();
            }
          }).catch(() => {});
        }
      }).catch(() => {});
    }
    return result;
  };

  function clearState() {
    Object.values(pollers).forEach(clearInterval);
    Object.keys(pollers).forEach(k => delete pollers[k]);
    uploads = [];
    renderPills();
  }

  /* ── Fetch persisted uploads for this chat from server ───────────────────── */
  async function loadSessionUploads(sessionId) {
    if (!sessionId) return; // no session = show nothing
    await _fetchUploads(sessionId);
    // NOTE: we intentionally do NOT fall back to all-user uploads here.
    // Files are strictly session-scoped: they belong to the chat they were
    // uploaded in and should NOT appear in other chats.
  }

  async function _fetchUploads(sessionId) {
    try {
      const headers = { credentials: "include" };
      if (sessionId) headers.headers = { "X-Session-Id": sessionId };
      console.log("[AtcoGenie] 📂 Fetching uploads", sessionId ? `for session: ${sessionId}` : "(all user uploads)");
      const resp = await _origFetch("/api/data/uploads", headers);
      console.log("[AtcoGenie] 📂 /api/data/uploads response status:", resp.status);
      if (!resp.ok) {
        console.log("[AtcoGenie] 📂 Non-OK response, aborting.");
        return;
      }
      const data = await resp.json();
      console.log("[AtcoGenie] 📂 Raw server data:", JSON.stringify(data));
      const serverUploads = (data.uploads || []).map(u => ({
        id: u.id,
        filename: u.filename,
        status: "ready",
        sheetNames: u.sheet_names || [],
        rowCount: u.row_count || 0,
        error: null,
      }));
      console.log("[AtcoGenie] 📂 Mapped uploads:", serverUploads.length, serverUploads.map(u => u.filename));
      // Merge: keep in-progress local uploads, add server ones not already tracked.
      // Deduplicate by BOTH id AND filename to avoid showing accidental re-uploads.
      const localIds = new Set(uploads.map(u => u.id).filter(Boolean));
      const localFilenames = new Set(uploads.map(u => u.filename));
      for (const su of serverUploads) {
        if (!localIds.has(su.id) && !localFilenames.has(su.filename)) {
          uploads.push(su);
          localFilenames.add(su.filename); // prevent duplicates within server results
        }
      }
      console.log("[AtcoGenie] 📂 Total uploads after merge:", uploads.length, "— calling renderPills()");
      renderPills();
    } catch (err) {
      console.log("[AtcoGenie] 📂 Error fetching uploads:", err);
    }
  }

  /* ── Upload flow ─────────────────────────────────────────────────────────── */
  async function handleFiles(files) {
    if (!activeSessionId) {
      toast("📁 Please open or create a chat first, then upload your file there.", "error");
      return;
    }

    const valid = Array.from(files).filter(f => {
      if (!f.name.match(/\.(xlsx|xls)$/i)) {
        toast(`❌ "${f.name}" — only .xlsx / .xls files are supported.`, "error");
        return false;
      }
      if (f.size > MAX_BYTES) {
        toast(`❌ "${f.name}" exceeds the 25 MB limit.`, "error");
        return false;
      }
      return true;
    });
    for (const file of valid) await uploadFile(file);
  }

  async function uploadFile(file) {
    if (!activeSessionId) return;

    const entry = { id: null, filename: file.name, status: "uploading",
                    sheetNames: [], rowCount: 0, error: null };
    uploads.push(entry);
    renderPills();
    toast(`📤 Uploading "${file.name}"…`, "info");

    const fd = new FormData();
    fd.append("file", file);

    let resp;
    try {
      resp = await _origFetch("/api/data/uploads", {
        method: "POST",
        headers: { "X-Session-Id": activeSessionId },
        body: fd,
        credentials: "include",
      });
    } catch (e) {
      entry.status = "error"; entry.error = "Network error";
      renderPills();
      toast("❌ Upload failed: network error", "error");
      return;
    }

    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try { detail = (await resp.json()).detail || detail; } catch (_) {}
      entry.status = "error"; entry.error = detail;
      renderPills();
      toast(`❌ Upload failed: ${detail}`, "error");
      return;
    }

    const data = await resp.json();
    entry.id     = data.upload_id;
    entry.status = "processing";
    renderPills();
    toast(`⏳ Converting "${file.name}"…`, "info");
    startPoller(entry);
  }

  function startPoller(entry) {
    const id = entry.id;
    const t = setInterval(async () => {
      try {
        const resp = await _origFetch(`/api/data/uploads/${id}/status`, {
          credentials: "include"
        });
        if (!resp.ok) {
          if (resp.status === 404 || resp.status >= 500) {
            entry.status = "error";
            entry.error  = `Status check failed (${resp.status})`;
            clearInterval(t); delete pollers[id];
            renderPills();
          }
          return;
        }
        const d = await resp.json();
        entry.status = d.status;

        if (d.status === "ready") {
          entry.sheetNames = d.sheet_names || [];
          entry.rowCount   = d.row_count   || 0;
          clearInterval(t); delete pollers[id];
          renderPills();
          const note = entry.sheetNames.length > 1
            ? ` (${entry.sheetNames.length} sheets)` : "";
          toast(`✅ "${entry.filename}"${note} — ${entry.rowCount.toLocaleString()} rows ready. Ask me about it!`, "success");
        } else if (d.status === "error") {
          entry.error = d.error || "Conversion failed.";
          clearInterval(t); delete pollers[id];
          renderPills();
          toast(`❌ "${entry.filename}": ${entry.error}`, "error");
        }
      } catch (_) {}
    }, 2000);
    pollers[id] = t;
  }

  async function removeUpload(id) {
    if (pollers[id]) { clearInterval(pollers[id]); delete pollers[id]; }
    const i = uploads.findIndex(u => u.id === id);
    if (i !== -1) uploads.splice(i, 1);
    renderPills();
    if (id) _origFetch(`/api/data/uploads/${id}`, { method: "DELETE", credentials: "include" }).catch(() => {});
  }

  /* ── Pill UI ─────────────────────────────────────────────────────────────── */
  const CSS = `
    /* ── Input-bar upload chips ── */
    #genie-pills {
      display:flex; flex-wrap:wrap; gap:6px; padding:6px 14px 2px;
      font-family:system-ui,-apple-system,sans-serif;
    }
    #genie-pills:empty { display:none; }
    .gp {
      display:inline-flex; align-items:center; gap:5px;
      padding:3px 10px 3px 8px; border-radius:20px;
      font-size:12px; font-weight:500; max-width:260px;
      animation:gpIn .2s ease; cursor:default;
    }
    @keyframes gpIn { from{opacity:0;transform:translateY(4px) scale(.95)} to{opacity:1;transform:translateY(0) scale(1)} }
    .gp.uploading,.gp.processing { background:rgba(99,102,241,.18); color:#c7d2fe; border:1px solid rgba(99,102,241,.35); }
    /* ✅ FIXED: was near-invisible rgba(34,197,94,.12) — now solid dark-green with bright text */
    .gp.ready  { background:#14532d; color:#dcfce7; border:1px solid #16a34a; }
    .gp.error  { background:#7f1d1d; color:#fecaca; border:1px solid rgba(239,68,68,.5); }
    .gp-label  { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .gp-rows   { opacity:.75; font-size:11px; flex-shrink:0; color:#86efac; }
    .gp.error .gp-rows { color:#fca5a5; }
    .gp-spin   { display:inline-block; animation:gpSpin .85s linear infinite; }
    @keyframes gpSpin { to{transform:rotate(360deg)} }
    .gp-x { background:none; border:none; cursor:pointer; color:inherit; opacity:.5;
             font-size:15px; line-height:1; padding:0; margin-left:2px; flex-shrink:0; transition:opacity .15s; }
    .gp-x:hover { opacity:1; }

    /* ── Toasts ── */
    #genie-toasts {
      position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
      z-index:99999; display:flex; flex-direction:column; gap:8px;
      align-items:center; pointer-events:none;
    }
    .gt {
      padding:10px 18px; border-radius:10px; font-size:13px; font-weight:500;
      font-family:system-ui,-apple-system,sans-serif;
      white-space:nowrap; max-width:480px; overflow:hidden; text-overflow:ellipsis;
      backdrop-filter:blur(8px); opacity:0; transform:translateY(10px);
      transition:opacity .22s, transform .22s;
    }
    .gt.show    { opacity:1; transform:translateY(0); }
    .gt.success { background:rgba(20,83,45,.92);  color:#bbf7d0; border:1px solid rgba(34,197,94,.4);  }
    .gt.error   { background:rgba(127,29,29,.92); color:#fecaca; border:1px solid rgba(239,68,68,.4);  }
    .gt.info    { background:rgba(30,27,75,.92);  color:#c7d2fe; border:1px solid rgba(99,102,241,.4); }

    #genie-file-panel {
      margin: 12px 8px 4px;
      border-radius: 10px;
      background: rgba(99,102,241,0.08);
      border: 1px solid rgba(99,102,241,0.22);
      overflow: hidden;
      font-family: system-ui,-apple-system,sans-serif;
      transition: opacity .2s;
    }
    #genie-file-panel.gfp-hidden { display:none; }
    #genie-file-panel-header {
      display: flex;
      align-items: center;
      gap: 7px;
      padding: 9px 12px;
      cursor: pointer;
      user-select: none;
      background: rgba(99,102,241,0.13);
    }
    #genie-file-panel-header:hover { background: rgba(99,102,241,0.22); }
    #genie-file-panel-title {
      flex: 1;
      font-size: 11px;
      font-weight: 700;
      color: #3730a3;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
    #genie-file-panel-count {
      font-size: 10.5px;
      background: rgba(99,102,241,0.25);
      color: #3730a3;
      border-radius: 999px;
      padding: 1px 7px;
      font-weight: 700;
    }
    #genie-file-panel-caret {
      font-size: 9px;
      color: #4f46e5;
      transition: transform 0.18s ease;
      display: inline-block;
    }
    #genie-file-panel.gfp-collapsed #genie-file-panel-caret { transform: rotate(-90deg); }
    #genie-file-panel-body {
      padding: 6px 8px 8px;
      display: flex;
      flex-direction: column;
      gap: 5px;
      max-height: 260px;
      overflow-y: auto;
    }
    #genie-file-panel.gfp-collapsed #genie-file-panel-body { display: none; }
    .gfp-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 9px;
      border-radius: 8px;
      background: rgba(255,255,255,0.65);
      border: 1px solid rgba(99,102,241,0.15);
      transition: background 0.15s;
    }
    .gfp-item:hover { background: rgba(255,255,255,0.90); }
    .gfp-item-icon { font-size: 16px; flex-shrink: 0; line-height: 1; }
    .gfp-item-body { flex: 1; min-width: 0; }
    .gfp-item-name {
      font-size: 12px;
      font-weight: 600;
      color: #1e293b;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .gfp-item-meta {
      font-size: 10.5px;
      color: #64748b;
      margin-top: 2px;
    }
    .gfp-item.gfp-ready  .gfp-item-meta { color: #15803d; font-weight: 500; }
    .gfp-item.gfp-processing .gfp-item-name { color: #4f46e5; }
    .gfp-item.gfp-error  .gfp-item-meta { color: #dc2626; }
    .gfp-item-del {
      background: none; border: none; cursor: pointer;
      color: #94a3b8; font-size: 14px; line-height: 1;
      padding: 2px 4px; border-radius: 4px;
      transition: color .15s, background .15s;
      flex-shrink: 0;
    }
    .gfp-item-del:hover { color: #dc2626; background: rgba(239,68,68,0.10); }
    .gfp-spin { display:inline-block; animation:gpSpin .85s linear infinite; }
  `;

  function injectStyles() {
    if (document.getElementById("genie-upload-css")) return;
    const s = document.createElement("style");
    s.id = "genie-upload-css"; s.textContent = CSS;
    document.head.appendChild(s);
  }

  function renderPills() {
    if (!pillBar) return;
    pillBar.innerHTML = "";
    uploads.forEach(u => {
      const pill = document.createElement("div");
      pill.className = `gp ${u.status}`;
      pill.title = u.sheetNames.length > 1
        ? `Sheets: ${u.sheetNames.join(", ")}` : (u.error || u.filename);

      const icon    = u.status === "ready" ? "📊" : u.status === "error" ? "❌" : `<span class="gp-spin">⏳</span>`;
      const rowsTag = (u.status === "ready" && u.rowCount)
        ? `<span class="gp-rows">${u.rowCount.toLocaleString()} rows</span>` : "";
      const closeBtn = u.id
        ? `<button class="gp-x" data-id="${u.id}" title="Remove">×</button>` : "";

      pill.innerHTML = `${icon}<span class="gp-label">${u.filename}</span>${rowsTag}${closeBtn}`;
      pillBar.appendChild(pill);
    });
    pillBar.querySelectorAll(".gp-x").forEach(btn => {
      btn.onclick = e => { e.stopPropagation(); removeUpload(btn.dataset.id); };
    });
    renderFilePanel();
  }

  /* ── Sidebar file panel ───────────────────────────────────────────────────── */
  let filePanelCollapsed = false;

  function renderFilePanel() {
    let panel = document.getElementById("genie-file-panel");

    // Hide entirely when no uploads
    if (uploads.length === 0) {
      if (panel) panel.classList.add("gfp-hidden");
      return;
    }

    // Create panel if it doesn't exist
    if (!panel) {
      panel = buildFilePanel();
      const sidebar = findSidebar();
      if (sidebar) {
        // Insert after the "Recent" section or the folder list, before the bottom user profile
        const profile = sidebar.querySelector('[class*="profile"], [class*="user"], [class*="avatar"]');
        if (profile && profile.closest("div")) {
          sidebar.insertBefore(panel, profile.closest("div"));
        } else {
          sidebar.appendChild(panel);
        }
      }
    }

    if (!panel) return; // couldn't find sidebar
    panel.classList.remove("gfp-hidden");
    if (filePanelCollapsed) {
      panel.classList.add("gfp-collapsed");
    } else {
      panel.classList.remove("gfp-collapsed");
    }

    // Update count badge
    const countEl = panel.querySelector("#genie-file-panel-count");
    if (countEl) countEl.textContent = uploads.length;

    // Re-render body items
    const body = panel.querySelector("#genie-file-panel-body");
    if (!body) return;
    body.innerHTML = "";

    uploads.forEach(u => {
      const statusClass = `gfp-${u.status === "uploading" || u.status === "processing" ? "processing" : u.status}`;
      const icon = u.status === "ready" ? "📊" : u.status === "error" ? "❌" : `<span class="gfp-spin">⏳</span>`;
      const meta = u.status === "ready"
        ? `${u.rowCount.toLocaleString()} rows${u.sheetNames.length > 1 ? " · " + u.sheetNames.length + " sheets" : ""}`
        : u.status === "error" ? (u.error || "Failed")
        : "Processing…";
      const delBtn = u.id
        ? `<button class="gfp-item-del" data-id="${u.id}" title="Remove">🗑</button>` : "";

      const item = document.createElement("div");
      item.className = `gfp-item ${statusClass}`;
      item.innerHTML = `
        <span class="gfp-item-icon">${icon}</span>
        <div class="gfp-item-body">
          <div class="gfp-item-name" title="${u.filename}">${u.filename}</div>
          <div class="gfp-item-meta">${meta}</div>
        </div>
        ${delBtn}
      `;
      body.appendChild(item);
    });

    body.querySelectorAll(".gfp-item-del").forEach(btn => {
      btn.onclick = e => { e.stopPropagation(); removeUpload(btn.dataset.id); };
    });
  }

  function buildFilePanel() {
    const panel = document.createElement("div");
    panel.id = "genie-file-panel";
    panel.innerHTML = `
      <div id="genie-file-panel-header">
        <span style="font-size:14px">📁</span>
        <span id="genie-file-panel-title">Uploaded Files</span>
        <span id="genie-file-panel-count">0</span>
        <span id="genie-file-panel-caret">▾</span>
      </div>
      <div id="genie-file-panel-body"></div>
    `;
    panel.querySelector("#genie-file-panel-header").addEventListener("click", () => {
      filePanelCollapsed = !filePanelCollapsed;
      panel.classList.toggle("gfp-collapsed", filePanelCollapsed);
    });
    return panel;
  }

  /* ── Find the real sidebar ───────────────────────────────────────────────── */
  function findSidebar() {
    // Strategy 1: Find the "+ New Chat" button — it ALWAYS lives in the sidebar.
    // Walk up from it to find a narrow tall ancestor (the sidebar container).
    const allButtons = Array.from(document.querySelectorAll("button, a, div[role='button']"));
    const newChatBtn = allButtons.find(el => /new\s*chat/i.test(el.textContent?.trim() || ""));
    if (newChatBtn) {
      // Walk up until we find a container that has a sidebar-like aspect ratio
      let el = newChatBtn.parentElement;
      let depth = 0;
      while (el && depth < 10) {
        if (el.offsetWidth > 40 && el.offsetWidth < 350 && el.offsetHeight > 300) {
          return el;
        }
        el = el.parentElement;
        depth++;
      }
    }

    // Strategy 2: Semantic class selectors
    const semantic = [
      '[class*="sidebar"]', '[class*="Sidebar"]',
      '[class*="side-bar"]', '[class*="drawer"]',
    ];
    for (const sel of semantic) {
      const el = document.querySelector(sel);
      if (el && el.offsetWidth > 40 && el.offsetWidth < 350 && el.offsetHeight > 300) return el;
    }

    // Strategy 3: Narrow tall div fallback
    const allDivs = Array.from(document.querySelectorAll("div"));
    return allDivs.find(d =>
      d.offsetWidth > 100 && d.offsetWidth < 300 &&
      d.offsetHeight > 400 &&
      d.children.length > 1
    ) || null;
  }

  /* ── Detect session ID from the sidebar's active/selected chat link ──────── */
  // On page refresh the SPA re-fetches the chat before our defer script loads,
  // so the fetch interceptor misses it. We fall back to scanning the DOM.
  function detectSessionFromDOM() {
    if (activeSessionId) return; // already set by fetch interceptor

    // Strategy 1: look for an anchor/button in the sidebar whose href or
    // data attribute contains a numeric chat ID and is visually "active".
    const sidebar = findSidebar();
    const root    = sidebar || document.body;

    // Find all links that look like chat links: href ends in /chats/123 or /chat/123
    const links = Array.from(root.querySelectorAll("a[href], [data-id], [data-chat-id]"));
    for (const el of links) {
      // Check href pattern
      const href = el.getAttribute("href") || "";
      const hrefMatch = href.match(/\/(?:chats?|conversations?|c)\/(\d+)/i);
      if (hrefMatch) {
        // Prefer the one that looks selected (has aria-current, active class, etc.)
        const isActive =
          el.getAttribute("aria-current") ||
          el.getAttribute("aria-selected") === "true" ||
          /active|selected|current/i.test(el.className || "") ||
          el.closest("[aria-current]") ||
          el.closest("[class*='active']") ||
          el.closest("[class*='selected']");
        if (isActive) {
          activeSessionId = hrefMatch[1];
          console.log("[AtcoGenie] 🔍 Session from DOM (active link):", activeSessionId);
          return;
        }
        // Keep last match as fallback (will be overwritten if better found)
        activeSessionId = hrefMatch[1];
      }
      // Check data attributes
      const dataId = el.getAttribute("data-id") || el.getAttribute("data-chat-id");
      if (dataId && /^\d+$/.test(dataId)) {
        activeSessionId = dataId;
      }
    }
    if (activeSessionId) {
      console.log("[AtcoGenie] 🔍 Session from DOM (fallback):", activeSessionId);
      return;
    }

    // Strategy 2: The SPA's React state stores the last-opened chat.
    // Try fetching /api/uploads to see what was uploaded to the most
    // recently active session — we probe each chat from the chat list.
    // This is a best-effort async fallback that resolves in background.
    console.log("[AtcoGenie] 🔍 No session ID in DOM, trying API fallback...");
    _origFetch("/api/chats", { credentials: "include" })
      .then(r => r.ok ? r.json() : [])
      .then(chats => {
        if (!activeSessionId && Array.isArray(chats) && chats.length > 0) {
          // Use the most recent chat (first in list, as they're ordered newest-first)
          activeSessionId = String(chats[0].id);
          console.log("[AtcoGenie] 🔍 Session from API (most recent chat):", activeSessionId);
          loadSessionUploads(activeSessionId);
        }
      })
      .catch(() => {});
  }

  function toast(msg, type = "info") {
    let wrap = document.getElementById("genie-toasts");
    if (!wrap) {
      wrap = document.createElement("div"); wrap.id = "genie-toasts";
      document.body.appendChild(wrap);
    }
    const el = document.createElement("div");
    el.className = `gt ${type}`; el.textContent = msg;
    wrap.appendChild(el);
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("show")));
    const dur = type === "success" ? 5500 : 4000;
    setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 300); }, dur);
  }

  /* ── DOM injection ───────────────────────────────────────────────────────── */
  function intercept() {
    if (patched) return true;

    const textarea = document.querySelector('textarea[placeholder*="Ask anything"]');
    if (!textarea) {
      // console.log("[AtcoGenie] Upload panel: textarea not found yet.");
      return false;
    }

    const form = textarea.closest("form") || textarea.parentElement?.parentElement;
    if (!form) {
      console.log("[AtcoGenie] Upload panel: textarea found but no parent container.");
      return false;
    }

    const fileInput = form.querySelector('input[type="file"]');
    if (!fileInput) {
      console.log("[AtcoGenie] Upload panel: file input not found in form.");
      return false;
    }

    console.log("[AtcoGenie] ✅ Upload panel injected successfully.");
    patched = true;
    fileInput.accept   = ".xlsx,.xls";
    fileInput.multiple = true;

    fileInput.addEventListener("change", () => {
      if (!fileInput.files?.length) return;
      const snapshot = Array.from(fileInput.files);
      fileInput.value = "";
      handleFiles(snapshot);
    });

    // Pill bar — live INSIDE the form as the first child so it is always
    // constrained to exactly the input bar width and can never escape sideways.
    if (!document.getElementById("genie-pills")) {
      pillBar = document.createElement("div");
      pillBar.id = "genie-pills";
      // Prepend into the form so it appears above the textarea row
      form.prepend(pillBar);
    } else {
      pillBar = document.getElementById("genie-pills");
    }

    // Drag & drop on the main content area
    const main = document.querySelector("main") || document.body;
    if (!main.dataset.genieDrop) {
      main.dataset.genieDrop = "1";
      main.addEventListener("dragover", e => {
        e.preventDefault();
        main.style.outline       = "2px dashed rgba(99,102,241,.45)";
        main.style.outlineOffset = "-4px";
      });
      main.addEventListener("dragleave", () => { main.style.outline = ""; });
      main.addEventListener("drop", e => {
        e.preventDefault(); main.style.outline = "";
        const xl = Array.from(e.dataTransfer.files).filter(f => f.name.match(/\.(xlsx|xls)$/i));
        if (xl.length) handleFiles(xl);
      });
    }

    // Load persisted uploads if we already know the session
    if (activeSessionId) loadSessionUploads(activeSessionId);

    return true;
  }

  /* ── Boot ────────────────────────────────────────────────────────────────── */
  function tryIntercept() {
    injectStyles();
    if (intercept()) {
      detectSessionFromDOM();
      if (activeSessionId) {
        loadSessionUploads(activeSessionId);
      }
      return;
    }
    let n = 0;
    const t = setInterval(() => {
      n++;
      if (intercept()) {
        detectSessionFromDOM();
        if (activeSessionId) loadSessionUploads(activeSessionId);
        clearInterval(t);
      } else if (n > 80) {
        console.log("[AtcoGenie] ❌ Upload panel failed to initialize after 32 seconds.");
        clearInterval(t);
      }
    }, 400);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tryIntercept);
  } else {
    setTimeout(tryIntercept, 600);
  }

})();
