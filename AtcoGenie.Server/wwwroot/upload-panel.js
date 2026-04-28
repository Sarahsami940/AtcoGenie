/**
 * AtcoGenie — Excel Upload Handler v6
 *
 * Session-scoped uploads:
 *  - Files can ONLY be uploaded inside a chat (not from homepage)
 *  - Files are tied to the chat they were uploaded in
 *  - On page/chat navigation, previously uploaded files are fetched from the
 *    server and re-rendered as pills (persistent across refreshes)
 */

(function () {
  "use strict";

  const MAX_BYTES = 25 * 1024 * 1024; // 25 MB

  /* ── State ──────────────────────────────────────────────────────────────── */
  let uploads = [];   // { id, filename, status, sheetNames, rowCount, error }
  const pollers = {};   // upload_id → intervalId
  let pillBar   = null;
  let patched   = false;

  /* ── Session ────────────────────────────────────────────────────────────── */
  function getSessionId() {
    const m = location.pathname.match(/\/chats\/(\d+)/);
    return m ? m[1] : null;
  }

  /* ── Fetch persisted uploads for this chat from server ───────────────────── */
  async function loadSessionUploads(sessionId) {
    if (!sessionId) { uploads = []; renderPills(); return; }
    try {
      const resp = await fetch("/api/data/uploads", {
        credentials: "include",
        headers: { "X-Session-Id": sessionId },
      });
      if (!resp.ok) return;
      const data = await resp.json();
      const serverUploads = (data.uploads || []).map(u => ({
        id: u.id,
        filename: u.filename,
        status: "ready",
        sheetNames: u.sheet_names || [],
        rowCount: u.row_count || 0,
        error: null,
      }));
      // Merge: keep any in-progress local uploads, add server ones that aren't already tracked
      const localIds = new Set(uploads.map(u => u.id).filter(Boolean));
      for (const su of serverUploads) {
        if (!localIds.has(su.id)) uploads.push(su);
      }
      renderPills();
    } catch (_) {}
  }

  /* ── Upload flow ─────────────────────────────────────────────────────────── */
  async function handleFiles(files) {
    const sessionId = getSessionId();
    if (!sessionId) {
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
    const sessionId = getSessionId();
    if (!sessionId) return; // guard — should never reach here

    const entry = { id: null, filename: file.name, status: "uploading",
                    sheetNames: [], rowCount: 0, error: null };
    uploads.push(entry);
    renderPills();
    toast(`📤 Uploading "${file.name}"…`, "info");

    const fd = new FormData();
    fd.append("file", file);

    let resp;
    try {
      resp = await fetch("/api/data/uploads", {
        method: "POST",
        headers: { "X-Session-Id": sessionId },
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
        const resp = await fetch(`/api/data/uploads/${id}/status`, {
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
    if (id) fetch(`/api/data/uploads/${id}`, { method: "DELETE", credentials: "include" }).catch(() => {});
  }

  /* ── Pill UI ─────────────────────────────────────────────────────────────── */
  const CSS = `
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
    .gp.uploading,.gp.processing { background:rgba(99,102,241,.15); color:#a5b4fc; border:1px solid rgba(99,102,241,.3); }
    .gp.ready  { background:rgba(34,197,94,.12);  color:#86efac; border:1px solid rgba(34,197,94,.25); }
    .gp.error  { background:rgba(239,68,68,.12);  color:#fca5a5; border:1px solid rgba(239,68,68,.25); }
    .gp-label  { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .gp-rows   { opacity:.65; font-size:11px; flex-shrink:0; }
    .gp-spin   { display:inline-block; animation:gpSpin .85s linear infinite; }
    @keyframes gpSpin { to{transform:rotate(360deg)} }
    .gp-x { background:none; border:none; cursor:pointer; color:inherit; opacity:.45;
             font-size:15px; line-height:1; padding:0; margin-left:2px; flex-shrink:0; transition:opacity .15s; }
    .gp-x:hover { opacity:1; }

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
    if (!textarea) return false;

    const form = textarea.closest("form") || textarea.parentElement?.parentElement;
    if (!form) return false;

    const fileInput = form.querySelector('input[type="file"]');
    if (!fileInput) return false;

    patched = true;
    fileInput.accept   = ".xlsx,.xls";
    fileInput.multiple = true;

    fileInput.addEventListener("change", () => {
      if (!fileInput.files?.length) return;
      const snapshot = Array.from(fileInput.files);
      fileInput.value = "";
      handleFiles(snapshot);
    });

    // Pill bar — inject once, just above the form container
    if (!document.getElementById("genie-pills")) {
      pillBar = document.createElement("div");
      pillBar.id = "genie-pills";
      const anchor = form.closest("div") || form;
      (anchor.parentElement || document.body).insertBefore(pillBar, anchor);
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

    // Load persisted uploads for this chat session from the server
    const sid = getSessionId();
    if (sid) loadSessionUploads(sid);

    return true;
  }

  /* ── Route-change cleanup ────────────────────────────────────────────────── */
  let lastPath = location.pathname;
  function onRouteChange() {
    const newPath = location.pathname;
    if (newPath === lastPath) return;
    lastPath = newPath;

    // Clear in-memory state & pollers on any navigation
    uploads = [];
    Object.values(pollers).forEach(clearInterval);
    Object.keys(pollers).forEach(k => delete pollers[k]);
    renderPills();

    // Reset patch flag so intercept re-runs after React remount
    patched = false;
    tryIntercept();
  }

  /* ── Boot ────────────────────────────────────────────────────────────────── */
  function tryIntercept() {
    injectStyles();
    if (intercept()) return;
    let n = 0;
    const t = setInterval(() => {
      n++;
      if (intercept() || n > 80) clearInterval(t);
    }, 400);
  }

  const _push = history.pushState.bind(history);
  history.pushState = (...args) => {
    _push(...args); setTimeout(onRouteChange, 120); setTimeout(tryIntercept, 700);
  };
  window.addEventListener("popstate", () => {
    setTimeout(onRouteChange, 120); setTimeout(tryIntercept, 700);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tryIntercept);
  } else {
    setTimeout(tryIntercept, 600);
  }

})();
