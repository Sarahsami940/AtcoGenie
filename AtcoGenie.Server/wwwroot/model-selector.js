/**
 * AtcoGenie Model Selector v6
 * ============================
 * Injects the model picker INTO the input bar (replaces the non-functional
 * visual button already rendered by the SPA there), and removes the old
 * fixed top-right pill.
 *
 * Strategy:
 *  1. Find the existing model-button the SPA renders in the toolbar row
 *     (matches text like "Gemini … (Fast)" or "Gemini …").
 *  2. If found → hide it and insert our live button in its place.
 *  3. If not found → fall back to appending to the toolbar row.
 */
(function () {
  "use strict";

  // ── Model registry ────────────────────────────────────────────────────────
  const MODELS = [
    { id: "gemini-3.1-flash-lite-preview", label: "Gemini 3.1 Flash", sub: "Fast · Lightweight", icon: "⚡" },
    { id: "gemini-3.1-pro-preview",        label: "Gemini 3.1 Pro",   sub: "Thinking · Deep Reasoning", icon: "🧠" },
    { id: "qwen-2.5-7b",                   label: "Qwen 2.5 7B",     sub: "On-Prem · Open Source", icon: "🏠" },
  ];
  const DEFAULT_MODEL_ID = "gemini-3.1-flash-lite-preview";

  // ── State ─────────────────────────────────────────────────────────────────
  let _currentModel  = DEFAULT_MODEL_ID;
  let _dropdownOpen  = false;
  let _injected      = false;

  // ── Persist / load preference ─────────────────────────────────────────────
  async function fetchPreference() {
    try {
      const res = await fetch("/api/preferences/model");
      if (res.ok) return (await res.json()).model || DEFAULT_MODEL_ID;
    } catch (_) {}
    return DEFAULT_MODEL_ID;
  }

  async function savePreference(modelId) {
    const res = await fetch("/api/preferences/model", {
      method:  "PUT",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ model: modelId }),
    });
    if (!res.ok) {
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
        }
      } catch (_) {}
    }
    return _origFetch(input, init);
  };

  // ── Styles ────────────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("ag-ms-style")) return;
    const style = document.createElement("style");
    style.id = "ag-ms-style";
    style.textContent = `
      /* === Wrapper sits inline in the toolbar === */
      #ag-ms-wrap {
        position: relative;
        display: inline-flex;
        align-items: center;
        flex-shrink: 0;
      }

      /* === Pill button === */
      #ag-model-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px 10px 4px 8px;
        background: rgba(99,102,241,0.12);
        border: 1px solid rgba(99,102,241,0.35);
        border-radius: 999px;
        cursor: pointer;
        color: #1e293b;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 12.5px;
        font-weight: 600;
        letter-spacing: 0.01em;
        transition: background 0.18s, border-color 0.18s, color 0.18s;
        user-select: none;
        white-space: nowrap;
        line-height: 1.4;
      }
      #ag-model-pill:hover {
        background: rgba(99,102,241,0.22);
        border-color: rgba(99,102,241,0.55);
        color: #0f172a;
      }
      #ag-model-pill .ag-pill-icon  { font-size: 13px; line-height: 1; }
      #ag-model-pill .ag-pill-label { color: #1e293b; font-weight: 600; }
      #ag-model-pill .ag-pill-caret {
        color: #4f46e5;
        font-size: 8px;
        margin-left: 2px;
        transition: transform 0.18s ease;
        display: inline-block;
      }
      #ag-model-pill.ag-open .ag-pill-caret { transform: rotate(180deg); }

      /* === Dropdown panel — opens upward === */
      #ag-model-dropdown {
        position: absolute;
        bottom: calc(100% + 8px);
        left: 0;
        z-index: 99999;
        background: #141824;
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 14px;
        padding: 6px;
        min-width: 230px;
        box-shadow: 0 -8px 32px rgba(0,0,0,0.55), 0 0 0 1px rgba(99,102,241,0.08);
        display: none;
      }
      #ag-model-dropdown.ag-visible {
        display: block;
        animation: ag-slide-up 0.17s cubic-bezier(0.16, 1, 0.3, 1);
      }
      @keyframes ag-slide-up {
        from { opacity: 0; transform: translateY(8px) scale(0.97); }
        to   { opacity: 1; transform: translateY(0)  scale(1);     }
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
      .ag-option:hover   { background: rgba(255,255,255,0.06); }
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
  }

  // ── Build the pill + dropdown ─────────────────────────────────────────────
  function buildPill() {
    const wrap = document.createElement("div");
    wrap.id = "ag-ms-wrap";

    const pill = document.createElement("button");
    pill.id = "ag-model-pill";
    pill.setAttribute("aria-haspopup", "listbox");
    pill.setAttribute("aria-expanded", "false");
    pill.innerHTML = `
      <span class="ag-pill-icon">⚡</span>
      <span class="ag-pill-label">Gemini 3.1 Flash</span>
      <span class="ag-pill-caret">▼</span>
    `;

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
        if (m.id === _currentModel) { closeDropdown(); return; }
        const prevModel = _currentModel;
        _currentModel = m.id;
        window.__atcoGenieModel = m.id;
        refreshUI();
        closeDropdown();
        savePreference(m.id).catch(function () {
          _currentModel = prevModel;
          window.__atcoGenieModel = prevModel;
          refreshUI();
        });
      });
      dropdown.appendChild(opt);
    });

    pill.addEventListener("click", function (e) {
      e.stopPropagation();
      _dropdownOpen ? closeDropdown() : openDropdown();
    });

    wrap.appendChild(pill);
    wrap.appendChild(dropdown);
    return wrap;
  }

  // ── Find the SPA's existing model button row and inject ───────────────────
  function tryInject() {
    if (_injected) return true;

    // The SPA renders a toolbar row containing the file-attachment button (+)
    // and a model name button like "Gemini 3 Pro (Fast) ▾".
    // We look for a button whose text contains "Gemini" or "gemini".
    const spaBtn = Array.from(document.querySelectorAll("button")).find(b =>
      /gemini|qwen/i.test(b.textContent) && b.closest("form,footer,[class*='input'],[class*='toolbar']")
    );

    if (!spaBtn) return false;

    // Hide the SPA's non-functional button
    spaBtn.style.display = "none";

    injectStyles();
    const wrap = buildPill();
    spaBtn.parentElement.insertBefore(wrap, spaBtn);
    _injected = true;
    refreshUI();
    console.log("[AtcoGenie] ✅ Model selector v6 injected into input bar.");
    return true;
  }

  // ── UI helpers ─────────────────────────────────────────────────────────────
  function openDropdown() {
    _dropdownOpen = true;
    const dd   = document.getElementById("ag-model-dropdown");
    const pill = document.getElementById("ag-model-pill");
    if (dd)   { dd.classList.add("ag-visible"); }
    if (pill) { pill.classList.add("ag-open"); pill.setAttribute("aria-expanded", "true"); }
  }

  function closeDropdown() {
    _dropdownOpen = false;
    const dd   = document.getElementById("ag-model-dropdown");
    const pill = document.getElementById("ag-model-pill");
    if (dd)   { dd.classList.remove("ag-visible"); }
    if (pill) { pill.classList.remove("ag-open"); pill.setAttribute("aria-expanded", "false"); }
  }

  function refreshUI() {
    const model = MODELS.find(m => m.id === _currentModel) || MODELS[0];
    const pill  = document.getElementById("ag-model-pill");
    if (pill) {
      pill.querySelector(".ag-pill-icon").textContent  = model.icon;
      pill.querySelector(".ag-pill-label").textContent = model.label;
    }
    document.querySelectorAll(".ag-option").forEach(function (opt) {
      const active = opt.getAttribute("data-model-id") === _currentModel;
      opt.classList.toggle("ag-active", active);
      opt.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  // Close on outside click
  document.addEventListener("click", function (e) {
    const dd   = document.getElementById("ag-model-dropdown");
    const pill = document.getElementById("ag-model-pill");
    if (dd && !dd.contains(e.target) && pill && !pill.contains(e.target)) {
      closeDropdown();
    }
  }, true);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeDropdown();
  });

  // ── Boot ──────────────────────────────────────────────────────────────────
  function boot() {
    fetchPreference().then(function (model) {
      _currentModel = model;
      window.__atcoGenieModel = model;

      // Try immediately, then poll until the SPA renders the input bar
      if (!tryInject()) {
        let n = 0;
        const t = setInterval(() => {
          n++;
          if (tryInject() || n > 100) clearInterval(t);
        }, 300);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
