/**
 * AtcoGenie Model Selector v3
 * ============================
 * Injects a self-contained, styled model-picker pill into the page.
 * Does NOT rely on the React bundle's internal dropdown DOM.
 *
 * Supported model IDs (must stay in sync with Program.cs VALID_MODELS):
 *   gemini-2.5-pro        →  Gemini 2.5 Pro        (Thinking, deep reasoning)
 *   gemini-2.5-flash-lite →  Gemini 2.5 Flash Lite  (Fast, lightweight)
 */
(function () {
  "use strict";

  // ── Model registry ────────────────────────────────────────────────────────
  const MODELS = [
    { id: "gemini-3.1-flash-lite-preview", label: "Gemini 3.1 Flash Lite", sub: "Fast · Lightweight", icon: "⚡" },
    { id: "gemini-3.1-pro-preview", label: "Gemini 3.1 Pro", sub: "Thinking · Deep Reasoning", icon: "🧠" },
  ];
  const DEFAULT_MODEL_ID = "gemini-3.1-flash-lite-preview";

  // ── State ─────────────────────────────────────────────────────────────────
  let _currentModel = DEFAULT_MODEL_ID;
  let _dropdownOpen = false;

  // ── Persist / load preference ─────────────────────────────────────────────
  async function fetchPreference() {
    try {
      const res = await fetch("/api/preferences/model");
      if (res.ok) return (await res.json()).model || DEFAULT_MODEL_ID;
    } catch (_) { }
    return DEFAULT_MODEL_ID;
  }

  async function savePreference(modelId) {
    const res = await fetch("/api/preferences/model", {
      method:  "PUT",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ model: modelId }),
    });
    if (res.ok) {
      console.debug("[AtcoGenie] ✅ Model saved:", modelId);
    } else {
      const msg = `Server rejected model '${modelId}' (HTTP ${res.status})`;
      console.warn("[AtcoGenie] ⚠️", msg);
      throw new Error(msg);
    }
  }

  // ── Fetch interceptor: inject model into every /api/query POST ────────────
  const _origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    if (url.includes("/api/query") && init && init.method === "POST" && init.body && _currentModel) {
      try {
        const body = JSON.parse(init.body);
        if (!body.model) {
          body.model = _currentModel;
          init = Object.assign({}, init, { body: JSON.stringify(body) });
          console.debug("[AtcoGenie] 📤 Injected model:", _currentModel);
        }
      } catch (_) { }
    }
    return _origFetch(input, init);
  };

  // ── Build injected UI ─────────────────────────────────────────────────────
  function buildUI() {
    // ── Styles ──────────────────────────────────────────────────────────────
    const style = document.createElement("style");
    style.textContent = `
      /* === Pill button === */
      #ag-model-pill {
        position: fixed;
        top: 14px;
        right: 18px;
        z-index: 99999;
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 6px 14px 6px 10px;
        background: rgba(15, 17, 26, 0.72);
        border: 1px solid rgba(255, 255, 255, 0.13);
        border-radius: 999px;
        cursor: pointer;
        color: #cbd5e1;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 0.01em;
        backdrop-filter: blur(10px) saturate(140%);
        -webkit-backdrop-filter: blur(10px) saturate(140%);
        box-shadow: 0 2px 16px rgba(0,0,0,0.35);
        transition: background 0.2s, border-color 0.2s, box-shadow 0.2s;
        user-select: none;
        white-space: nowrap;
      }
      #ag-model-pill:hover {
        background: rgba(30, 36, 55, 0.88);
        border-color: rgba(99, 102, 241, 0.45);
        box-shadow: 0 2px 20px rgba(99, 102, 241, 0.2);
        color: #e2e8f0;
      }
      #ag-model-pill .ag-pill-icon { font-size: 15px; line-height: 1; }
      #ag-model-pill .ag-pill-label { color: #e2e8f0; }
      #ag-model-pill .ag-pill-caret {
        color: #64748b;
        font-size: 9px;
        margin-left: 1px;
        transition: transform 0.2s ease;
        display: inline-block;
      }
      #ag-model-pill.ag-open .ag-pill-caret { transform: rotate(180deg); }

      /* === Dropdown panel === */
      #ag-model-dropdown {
        position: fixed;
        top: 54px;
        right: 18px;
        z-index: 99998;
        background: #141824;
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 14px;
        padding: 6px;
        min-width: 228px;
        box-shadow: 0 12px 40px rgba(0,0,0,0.55), 0 0 0 1px rgba(99,102,241,0.08);
        display: none;
      }
      #ag-model-dropdown.ag-visible {
        display: block;
        animation: ag-slide-in 0.17s cubic-bezier(0.16, 1, 0.3, 1);
      }
      @keyframes ag-slide-in {
        from { opacity: 0; transform: translateY(-8px) scale(0.97); }
        to   { opacity: 1; transform: translateY(0)   scale(1);     }
      }

      /* === Individual option === */
      .ag-option {
        display: flex;
        align-items: center;
        gap: 11px;
        padding: 10px 12px;
        border-radius: 9px;
        cursor: pointer;
        transition: background 0.15s;
      }
      .ag-option:hover { background: rgba(255,255,255,0.06); }
      .ag-option.ag-active { background: rgba(99,102,241,0.14); }

      .ag-opt-icon {
        font-size: 18px;
        width: 26px;
        text-align: center;
        flex-shrink: 0;
        line-height: 1;
      }
      .ag-opt-body { flex: 1; min-width: 0; }
      .ag-opt-name {
        font-size: 13px;
        font-weight: 500;
        color: #e2e8f0;
        font-family: 'Inter', -apple-system, sans-serif;
      }
      .ag-opt-sub {
        font-size: 11px;
        color: #475569;
        margin-top: 2px;
        font-family: 'Inter', -apple-system, sans-serif;
      }
      .ag-option.ag-active .ag-opt-name { color: #a5b4fc; }
      .ag-option.ag-active .ag-opt-sub  { color: #6366f1; }

      .ag-check {
        color: #6366f1;
        font-size: 13px;
        font-weight: 700;
        opacity: 0;
        transition: opacity 0.15s;
        flex-shrink: 0;
      }
      .ag-option.ag-active .ag-check { opacity: 1; }

      /* === Divider label === */
      .ag-dropdown-header {
        padding: 6px 12px 4px;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #334155;
        font-family: 'Inter', -apple-system, sans-serif;
      }
    `;
    document.head.appendChild(style);

    // ── Pill ────────────────────────────────────────────────────────────────
    const pill = document.createElement("button");
    pill.id = "ag-model-pill";
    pill.setAttribute("aria-haspopup", "listbox");
    pill.setAttribute("aria-expanded", "false");
    pill.innerHTML = `
      <span class="ag-pill-icon">⚡</span>
      <span class="ag-pill-label">Gemini 2.5 Flash</span>
      <span class="ag-pill-caret">▼</span>
    `;
    document.body.appendChild(pill);

    // ── Dropdown ─────────────────────────────────────────────────────────────
    const dropdown = document.createElement("div");
    dropdown.id = "ag-model-dropdown";
    dropdown.setAttribute("role", "listbox");

    const hdr = document.createElement("div");
    hdr.className = "ag-dropdown-header";
    hdr.textContent = "AI Model";
    dropdown.appendChild(hdr);

    MODELS.forEach(function (m) {
      const opt = document.createElement("div");
      opt.className = "ag-option" + (m.id === _currentModel ? " ag-active" : "");
      opt.setAttribute("role", "option");
      opt.setAttribute("data-model-id", m.id);
      opt.setAttribute("aria-selected", m.id === _currentModel ? "true" : "false");
      opt.innerHTML = `
        <span class="ag-opt-icon">${m.icon}</span>
        <div class="ag-opt-body">
          <div class="ag-opt-name">${m.label}</div>
          <div class="ag-opt-sub">${m.sub}</div>
        </div>
        <span class="ag-check">✓</span>
      `;
      opt.addEventListener("click", function (e) {
        e.stopPropagation();
        e.preventDefault();

        if (m.id === _currentModel) { closeDropdown(); return; } // no-op if already active

        const prevModel = _currentModel;

        // Optimistic update — flip UI immediately, don’t wait for HTTP
        _currentModel          = m.id;
        window.__atcoGenieModel = m.id;
        refreshUI();
        closeDropdown();

        // Persist in background; revert if server rejects
        savePreference(m.id).catch(function () {
          _currentModel          = prevModel;
          window.__atcoGenieModel = prevModel;
          refreshUI();
          console.warn("[AtcoGenie] ↩ Reverted to:", prevModel);
        });
      });
      dropdown.appendChild(opt);
    });

    document.body.appendChild(dropdown);

    // ── Events ──────────────────────────────────────────────────────────────
    pill.addEventListener("click", function (e) {
      e.stopPropagation();
      _dropdownOpen ? closeDropdown() : openDropdown();
    });
    // Use capture phase so our handler wins over React’s own document listeners
    document.addEventListener("click", function (e) {
      const dd = document.getElementById("ag-model-dropdown");
      const pill = document.getElementById("ag-model-pill");
      if (dd && !dd.contains(e.target) && pill && !pill.contains(e.target)) {
        closeDropdown();
      }
    }, true); // capture: true
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeDropdown();
    });

  }

  // ── UI helpers ─────────────────────────────────────────────────────────────
  function openDropdown() {
    _dropdownOpen = true;
    const dd = document.getElementById("ag-model-dropdown");
    const pill = document.getElementById("ag-model-pill");
    if (dd) { dd.classList.add("ag-visible"); dd.removeAttribute("hidden"); }
    if (pill) { pill.classList.add("ag-open"); pill.setAttribute("aria-expanded", "true"); }
  }

  function closeDropdown() {
    _dropdownOpen = false;
    const dd = document.getElementById("ag-model-dropdown");
    const pill = document.getElementById("ag-model-pill");
    if (dd) { dd.classList.remove("ag-visible"); }
    if (pill) { pill.classList.remove("ag-open"); pill.setAttribute("aria-expanded", "false"); }
  }

  function refreshUI() {
    const model = MODELS.find(function (m) { return m.id === _currentModel; }) || MODELS[0];

    const pill = document.getElementById("ag-model-pill");
    if (pill) {
      pill.querySelector(".ag-pill-icon").textContent = model.icon;
      pill.querySelector(".ag-pill-label").textContent = model.label;
    }

    document.querySelectorAll(".ag-option").forEach(function (opt) {
      const active = opt.getAttribute("data-model-id") === _currentModel;
      opt.classList.toggle("ag-active", active);
      opt.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  function boot() {
    fetchPreference().then(function (model) {
      _currentModel = model;
      window.__atcoGenieModel = model;
      buildUI();
      refreshUI();
      console.log("[AtcoGenie] 🚀 Model selector v4 ready. Active model:", model);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
