/**
 * AtcoGenie — Chart Renderer v1
 * ================================
 * Observes AI response messages for ```chart-json fenced code blocks,
 * then renders interactive Apache ECharts visualizations inline.
 *
 * Supported chart types:
 *   bar, line, pie, donut, horizontalBar, stackedBar, area
 *
 * Features:
 *  1. CHART RENDERING  — Replaces raw code block with an interactive ECharts canvas
 *  2. ACTION TOOLBAR   — Download PNG, Download SVG, Copy Image, Copy Data as CSV
 *  3. RESPONSIVE       — Charts resize with the container via ResizeObserver
 *  4. THEMED           — AtcoGenie blue palette (#1657CB) on a clean light card
 *  5. TOAST FEEDBACK   — Non-intrusive copy confirmation notifications
 */
(function () {
  "use strict";

  // Local copy — avoids CDN blocks on restricted corporate/school networks
  const ECHARTS_CDN  = "/assets/echarts.min.js";
  const CHART_HEIGHT = 320; // px

  /* AtcoGenie pastel colour palette — soft, vibrant, high-contrast on white */
  const BRAND_COLORS = [
    "#6B9EFF", "#FF8FAB", "#5DD6A8", "#FFB86B",
    "#A78BFA", "#67D4E8", "#FF7B7B", "#84D69B",
    "#F4C06E", "#7CC4FA", "#E888C8", "#9BE0B0"
  ];

  /* ── ECharts lazy loader ──────────────────────────────────────────────────── */
  let _ecLoaded   = false;
  let _ecLoading  = false;
  let _ecQueue    = [];

  function withECharts(fn) {
    if (_ecLoaded)  { fn(); return; }
    _ecQueue.push(fn);
    if (_ecLoading) return;
    _ecLoading = true;

    const s = document.createElement("script");
    s.src = ECHARTS_CDN;
    s.onload = () => {
      _ecLoaded  = true;
      _ecLoading = false;
      _ecQueue.forEach(cb => cb());
      _ecQueue = [];
    };
    s.onerror = () => {
      console.warn("[AtcoGenie Charts] Failed to load ECharts from CDN.");
      _ecLoading = false;
      _ecQueue   = [];
      // Restore hidden source elements so user still sees the raw data
      document.querySelectorAll("[data-ag-chart-hidden]").forEach(el => {
        el.classList.remove("ag-chart-src-hidden");
        el.removeAttribute("data-ag-chart-hidden");
      });
    };
    document.head.appendChild(s);
  }

  /* ── Injected CSS ─────────────────────────────────────────────────────────── */
  const CSS = `
    /* ── Card wrapper ── */
    .ag-chart-card {
      margin: 16px 0 20px;
      border-radius: 12px;
      background: #ffffff;
      border: 1px solid rgba(22, 87, 203, 0.13);
      box-shadow: 0 4px 20px rgba(22, 87, 203, 0.09), 0 1px 4px rgba(0,0,0,0.06);
      overflow: hidden;
      font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
      animation: agChartFadeIn 0.35s cubic-bezier(0.16,1,0.3,1) both;
    }
    @keyframes agChartFadeIn {
      from { opacity: 0; transform: translateY(8px); }
      to   { opacity: 1; transform: translateY(0); }
    }

    /* ── Toolbar ── */
    .ag-chart-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 14px 9px;
      background: rgba(22, 87, 203, 0.035);
      border-bottom: 1px solid rgba(22, 87, 203, 0.09);
      flex-wrap: wrap;
    }
    .ag-chart-title {
      font-size: 12.5px;
      font-weight: 600;
      color: #1e3a5f;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 55%;
      letter-spacing: 0.01em;
    }
    .ag-chart-actions {
      display: flex;
      gap: 5px;
      flex-shrink: 0;
    }

    /* ── Action buttons ── */
    .ag-chart-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 500;
      color: #1657CB;
      background: rgba(22, 87, 203, 0.07);
      border: 1px solid rgba(22, 87, 203, 0.22);
      border-radius: 6px;
      cursor: pointer;
      transition: background 0.15s, border-color 0.15s, color 0.15s, transform 0.1s;
      white-space: nowrap;
      user-select: none;
      line-height: 1;
    }
    .ag-chart-btn:hover {
      background: rgba(22, 87, 203, 0.14);
      border-color: rgba(22, 87, 203, 0.4);
      color: #0f3fa6;
      transform: translateY(-1px);
    }
    .ag-chart-btn:active { transform: translateY(0); }
    .ag-chart-btn.ag-btn-ok {
      color: #065f46;
      background: rgba(52, 211, 153, 0.12);
      border-color: rgba(52, 211, 153, 0.35);
    }

    /* ── ECharts canvas wrapper ── */
    .ag-chart-canvas-wrap {
      width: 100%;
      height: ${CHART_HEIGHT}px;
      padding: 8px 4px 4px;
      box-sizing: border-box;
    }

    /* ── Hide the raw source element (inline <code> or <pre>) ──
       ChainLit renders double-backtick inline code as:
         <code class="bg-slate-100 dark:bg-slate-900 ...">chart-json{...}</code>
       We hide it as soon as JS marks it, AND we pre-hide via CSS
       using the [data-ag-chart-hidden] attribute set synchronously.    */
    .ag-chart-src-hidden,
    [data-ag-chart-hidden] {
      display: none !important;
    }

    /* ── Toast ── */
    .ag-chart-toast {
      position: fixed;
      bottom: 28px;
      right: 28px;
      z-index: 999999;
      background: linear-gradient(135deg, #1e3a5f, #1657CB);
      color: #ffffff;
      font-size: 12.5px;
      font-weight: 500;
      padding: 10px 18px;
      border-radius: 9px;
      box-shadow: 0 6px 24px rgba(22, 87, 203, 0.35), 0 2px 8px rgba(0,0,0,0.2);
      opacity: 0;
      transform: translateY(10px);
      transition: opacity 0.22s ease, transform 0.22s ease;
      pointer-events: none;
      font-family: system-ui, -apple-system, sans-serif;
      letter-spacing: 0.01em;
    }
    .ag-chart-toast.ag-toast-visible {
      opacity: 1;
      transform: translateY(0);
    }
  `;

  function injectStyles() {
    if (document.getElementById("ag-chart-css")) return;
    const s = document.createElement("style");
    s.id = "ag-chart-css";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /* ── Toast helper ─────────────────────────────────────────────────────────── */
  let _toastTimer = null;
  function toast(msg) {
    let el = document.getElementById("ag-chart-toast-el");
    if (!el) {
      el = document.createElement("div");
      el.id = "ag-chart-toast-el";
      el.className = "ag-chart-toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add("ag-toast-visible");
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => el.classList.remove("ag-toast-visible"), 2800);
  }

  /* ── Number formatter (axis labels, tooltips) ─────────────────────────────── */
  function fmtNum(v) {
    const abs = Math.abs(+v);
    if (abs >= 1e6) return (+v / 1e6).toFixed(1) + "M";
    if (abs >= 1e3) return (+v / 1e3).toFixed(0) + "K";
    return (+v).toLocaleString();
  }

  /* ── ECharts option builder ───────────────────────────────────────────────── */
  function buildOption(spec) {
    const rawType  = (spec.type || "bar").toLowerCase().replace(/[\s_-]/g, "");
    const isPie       = rawType === "pie" || rawType === "donut";
    const isLine      = rawType === "line" || rawType === "area";
    const isArea      = rawType === "area";
    const isHoriz     = rawType === "horizontalbar";
    const isStacked   = rawType === "stackedbar" || rawType === "stacked";

    const baseText = { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: "#374151" };

    const option = {
      animation: true,
      animationDuration: 550,
      animationEasing: "cubicOut",
      backgroundColor: "transparent",
      textStyle: baseText,
      color: BRAND_COLORS,
      tooltip: {
        trigger: isPie ? "item" : "axis",
        backgroundColor: "rgba(15, 23, 42, 0.93)",
        borderColor: "rgba(22, 87, 203, 0.35)",
        borderWidth: 1,
        textStyle: { color: "#f1f5f9", fontSize: 12, fontFamily: baseText.fontFamily },
        axisPointer: {
          type: "cross",
          lineStyle: { color: "rgba(22, 87, 203, 0.25)", type: "dashed" }
        }
      },
    };

    /* ── PIE / DONUT ── */
    if (isPie) {
      const data = (spec.data || []).map((d, i) => ({
        name: d.name,
        value: d.value,
        itemStyle: { color: BRAND_COLORS[i % BRAND_COLORS.length] }
      }));
      option.legend = {
        type: "scroll", orient: "horizontal", bottom: 6,
        textStyle: { color: "#6b7280", fontSize: 11, fontFamily: baseText.fontFamily }
      };
      option.series = [{
        type: "pie",
        radius: rawType === "donut" ? ["40%", "68%"] : "65%",
        center: ["50%", "48%"],
        data,
        label: {
          show: true,
          formatter: "{b}: {d}%",
          fontSize: 11,
          color: "#374151",
          fontFamily: baseText.fontFamily
        },
        labelLine: { smooth: true, lineStyle: { color: "#9ca3af" } },
        emphasis: {
          itemStyle: { shadowBlur: 14, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.25)" }
        }
      }];
      return option;
    }

    /* ── CARTESIAN (bar, line, area, horizontal, stacked) ── */
    const labels   = spec.labels   || [];
    const datasets = spec.datasets || [];

    const axisLabelStyle = { color: "#6b7280", fontSize: 11, fontFamily: baseText.fontFamily };
    const splitLineStyle = { lineStyle: { color: "#f3f4f6", type: "dashed" } };

    option.grid = {
      top: 20, right: 20,
      bottom: labels.length > 8 ? 64 : 52,
      left: isHoriz ? 10 : 10,
      containLabel: true
    };

    if (isHoriz) {
      option.xAxis = {
        type: "value",
        name: spec.yAxis || "",
        nameTextStyle: axisLabelStyle,
        axisLine: { lineStyle: { color: "#e5e7eb" } },
        splitLine: splitLineStyle,
        axisLabel: { ...axisLabelStyle, formatter: v => fmtNum(v) }
      };
      option.yAxis = {
        type: "category",
        data: labels,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: axisLabelStyle
      };
    } else {
      option.xAxis = {
        type: "category",
        data: labels,
        name: spec.xAxis || "",
        nameTextStyle: axisLabelStyle,
        axisLine: { lineStyle: { color: "#e5e7eb" } },
        axisTick: { show: false },
        axisLabel: { ...axisLabelStyle, rotate: labels.length > 9 ? 35 : 0 }
      };
      option.yAxis = {
        type: "value",
        name: spec.yAxis || "",
        nameTextStyle: axisLabelStyle,
        nameGap: 12,
        axisLine: { show: false },
        splitLine: splitLineStyle,
        axisLabel: { ...axisLabelStyle, formatter: v => fmtNum(v) }
      };
    }

    option.legend = {
      bottom: 2, type: "scroll",
      textStyle: { color: "#6b7280", fontSize: 11, fontFamily: baseText.fontFamily }
    };

    option.series = datasets.map((ds, i) => {
      const c = ds.color || BRAND_COLORS[i % BRAND_COLORS.length];

      if (isLine) {
        return {
          name: ds.label,
          type: "line",
          data: ds.data,
          smooth: true,
          symbol: "circle",
          symbolSize: 5,
          lineStyle: { width: 2.5, color: c },
          itemStyle: { color: c },
          areaStyle: isArea ? {
            color: {
              type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: c + "4D" },
                { offset: 1, color: c + "08" }
              ]
            }
          } : undefined
        };
      }

      if (isHoriz) {
        const seriesObj = {
          name: ds.label,
          type: "bar",
          data: ds.data,
          barMaxWidth: 28,
          itemStyle: { borderRadius: [0, 5, 5, 0] },
          stack: isStacked ? "total" : undefined,
          label: datasets.length === 1 ? {
            show: true, position: "right",
            formatter: p => fmtNum(p.value),
            fontSize: 10, color: "#6b7280",
            fontFamily: baseText.fontFamily
          } : undefined
        };
        // Single dataset: color each bar differently
        if (datasets.length === 1) {
          seriesObj.colorBy = "data";
        } else {
          seriesObj.itemStyle.color = c;
        }
        return seriesObj;
      }

      const barObj = {
        name: ds.label,
        type: "bar",
        data: ds.data,
        barMaxWidth: 42,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        stack: isStacked ? "total" : undefined
      };
      // Single dataset: color each bar differently
      if (datasets.length === 1) {
        barObj.colorBy = "data";
      } else {
        barObj.itemStyle.color = c;
      }
      return barObj;
    });

    return option;
  }

  /* ── Spec → CSV ───────────────────────────────────────────────────────────── */
  function specToCSV(spec) {
    const type = (spec.type || "").toLowerCase();
    if (type === "pie" || type === "donut") {
      const rows = [["Name", "Value"], ...(spec.data || []).map(d => [d.name, d.value])];
      return rows.map(r => r.join(",")).join("\n");
    }
    const ds = spec.datasets || [];
    const header = [spec.xAxis || "Label", ...ds.map(d => d.label)];
    const rows = (spec.labels || []).map((lbl, i) => [
      lbl, ...ds.map(d => d.data[i] ?? "")
    ]);
    return [header, ...rows].map(r => r.join(",")).join("\n");
  }

  /* ── Button factory ───────────────────────────────────────────────────────── */
  function makeBtn(text) {
    const btn = document.createElement("button");
    btn.className = "ag-chart-btn";
    btn.textContent = text;
    return btn;
  }

  function flashOk(btn) {
    btn.classList.add("ag-btn-ok");
    setTimeout(() => btn.classList.remove("ag-btn-ok"), 2200);
  }

  function triggerDownload(url, filename) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  }

  /* ── Core: render one chart block ─────────────────────────────────────────── */
  function renderChart(codeEl) {
    if (codeEl.dataset.agChartDone) return;
    codeEl.dataset.agChartDone = "1";

    // Hide the raw source IMMEDIATELY (synchronous) so it disappears from view
    // the instant scan() identifies it — before any async ECharts loading.
    hideSource(codeEl, true);

    // Strip the literal 'chart-json' prefix.
    // When the LLM uses double-backticks (``) instead of triple (```),
    // the markdown renderer emits a class-less <code> whose textContent is:
    //   "chart-json{ \"type\": \"bar\", ... }"
    // We strip that prefix before parsing so both backtick styles work.
    let raw = codeEl.textContent.trim();
    if (raw.startsWith('chart-json')) {
      raw = raw.slice('chart-json'.length).trim();
    }

    let spec;
    try {
      spec = JSON.parse(raw);
    } catch (e) {
      console.warn('[AtcoGenie Charts] Invalid chart-json — skipping.', e.message, '\nRaw:', raw.slice(0, 120));
      hideSource(codeEl, false);  // restore so user still sees the data
      return;
    }

    /* ── Resolve message container (needed for dedup check) ── */
    // Walk UP from the code element to the nearest block-level ancestor.
    // This is the message body div — React does NOT recreate it during streaming,
    // so it's a stable reference we can use for dedup across re-renders.
    const pre    = codeEl.closest("pre");
    const anchor = pre || codeEl.parentElement || codeEl;

    let msgContainer = anchor.parentNode;
    while (
      msgContainer &&
      msgContainer !== document.body &&
      !["DIV", "ARTICLE", "SECTION", "LI"].includes(msgContainer.tagName)
    ) {
      msgContainer = msgContainer.parentNode;
    }
    const container = msgContainer || anchor.parentNode;

    /* ── DEDUP GUARD ── */
    // React re-creates <code> nodes on every streaming chunk, so the
    // node-level `data-ag-chart-done` guard fails for the new nodes.
    // Instead, check the stable message container: if it already contains
    // an .ag-chart-card, this is a duplicate — hide the code and bail out.
    if (container.querySelector(".ag-chart-card")) {
      hideSource(codeEl, true);   // hide the duplicate raw block too
      return;
    }

    /* ── Build card DOM ── */
    const card = document.createElement("div");
    card.className = "ag-chart-card";

    /* toolbar */
    const toolbar = document.createElement("div");
    toolbar.className = "ag-chart-toolbar";

    const titleEl = document.createElement("div");
    titleEl.className = "ag-chart-title";
    titleEl.textContent = spec.title || "Chart";

    const actions = document.createElement("div");
    actions.className = "ag-chart-actions";

    const btnPng = makeBtn("⬇ PNG");
    const btnSvg = makeBtn("⬇ SVG");
    const btnCpy = makeBtn("⎘ Copy");
    const btnCsv = makeBtn("📋 CSV");
    actions.append(btnPng, btnSvg, btnCpy, btnCsv);
    toolbar.append(titleEl, actions);

    /* canvas wrap */
    const canvasWrap = document.createElement("div");
    canvasWrap.className = "ag-chart-canvas-wrap";

    card.append(toolbar, canvasWrap);

    // Append chart at end of message container; source stays hidden.
    container.appendChild(card);


    /* ── Render with ECharts ── */
    withECharts(() => {
      const chart = window.echarts.init(canvasWrap, null, { renderer: "canvas" });
      const option = buildOption(spec);
      chart.setOption(option);

      /* responsive resize */
      const ro = new ResizeObserver(() => chart.resize());
      ro.observe(canvasWrap);

      /* ── PNG download ── */
      btnPng.addEventListener("click", () => {
        const url = chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
        triggerDownload(url, safeFileName(spec.title) + ".png");
      });

      /* ── SVG download (headless ECharts instance) ── */
      btnSvg.addEventListener("click", () => {
        const svgChart = window.echarts.init(document.createElement("div"), null, {
          renderer: "svg", width: 900, height: CHART_HEIGHT
        });
        svgChart.setOption(option);
        const svgStr = svgChart.renderToSVGString();
        svgChart.dispose();
        const blob = new Blob([svgStr], { type: "image/svg+xml" });
        const url  = URL.createObjectURL(blob);
        triggerDownload(url, safeFileName(spec.title) + ".svg");
        setTimeout(() => URL.revokeObjectURL(url), 8000);
      });

      /* ── Copy image to clipboard ── */
      btnCpy.addEventListener("click", () => {
        const url = chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
        fetch(url)
          .then(r => r.blob())
          .then(blob => {
            if (navigator.clipboard && navigator.clipboard.write) {
              return navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
            }
            throw new Error("clipboard API not available");
          })
          .then(() => { toast("✅ Chart copied to clipboard"); flashOk(btnCpy); })
          .catch(() => toast("⚠️ Copy failed — use PNG download instead"));
      });

      /* ── Copy data as CSV ── */
      btnCsv.addEventListener("click", () => {
        const csv = specToCSV(spec);
        const fallback = () => {
          const ta = document.createElement("textarea");
          ta.value = csv;
          ta.style.cssText = "position:fixed;left:-9999px;";
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand("copy"); toast("✅ Data copied as CSV"); flashOk(btnCsv); }
          catch { toast("⚠️ Copy failed"); }
          ta.remove();
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(csv)
            .then(() => { toast("✅ Data copied as CSV"); flashOk(btnCsv); })
            .catch(fallback);
        } else {
          fallback();
        }
      });
    });
  }

  function safeFileName(title) {
    return (title || "chart").replace(/[^a-z0-9\-_ ]/gi, "").replace(/\s+/g, "_").slice(0, 60);
  }

  /* ── Hide / un-hide the raw source element ──────────────────────────────── */
  function hideSource(codeEl, hidden) {
    // Walk up to find the element to hide:
    //   fenced block  → <pre>      (direct parent of <code>)
    //   inline block  → <code> itself (sits directly in a <div>/<p>)
    const pre = codeEl.closest("pre");
    const target = pre || codeEl;
    if (hidden) {
      target.classList.add("ag-chart-src-hidden");
      target.setAttribute("data-ag-chart-hidden", "1");
    } else {
      target.classList.remove("ag-chart-src-hidden");
      target.removeAttribute("data-ag-chart-hidden");
    }
  }

  /* ── DOM scanner ──────────────────────────────────────────────────────────── */
  function scan() {
    /* Strategy 1 — fenced code block (``` chart-json) :
         Markdown renderer assigns <code class="language-chart-json">
         Works when LLM uses triple backticks correctly.              */
    document.querySelectorAll(
      'code[class*="chart-json"], code[class*="language-chart-json"], code[data-language="chart-json"]'
    ).forEach(el => {
      if (!el.dataset.agChartDone) renderChart(el);
    });

    /* Strategy 2 — inline code block (`` chart-json ) :
         When LLM uses double backticks the renderer emits a class-less
         <code> whose textContent literally starts with "chart-json".
         We scan all <code> elements and match by content prefix.     */
    document.querySelectorAll('code').forEach(el => {
      if (el.dataset.agChartDone) return;
      const txt = el.textContent.trim();
      if (txt.startsWith('chart-json') && txt.length > 12) {
        renderChart(el);
      }
    });
  }

  /* ── Boot ─────────────────────────────────────────────────────────────────── */
  function boot() {
    injectStyles();
    scan();
    const obs = new MutationObserver(() => scan());
    obs.observe(document.body, { childList: true, subtree: true });
    console.log("[AtcoGenie] 📊 Chart renderer v2 ready.");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    setTimeout(boot, 800);
  }
})();
