/* Friday research report canvas — vanilla JS, textContent only, SVG charts via DOM. */
(function () {
  "use strict";

  let currentReport = null;
  let confFilter = 0;
  let es = null;
  let startedAt = 0;
  let timerIv = null;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function safeHttpUrl(u) {
    try {
      const x = new URL(String(u || ""), location.origin);
      if (x.protocol !== "http:" && x.protocol !== "https:") return null;
      return x.href;
    } catch (_) {
      return null;
    }
  }

  function domainOf(u) {
    try {
      return new URL(u).hostname.replace(/^www\./, "");
    } catch (_) {
      return "";
    }
  }

  function linkEl(url, label) {
    const href = safeHttpUrl(url);
    const a = el("a", "report-link");
    if (!href) {
      a.textContent = label || "(blocked link)";
      a.removeAttribute("href");
      return a;
    }
    a.href = href;
    a.textContent = label || domainOf(href) || href;
    a.rel = "noopener noreferrer";
    a.target = "_blank";
    return a;
  }

  function drawChart(svg, chart) {
    clear(svg);
    const series = (chart.series || []).slice(0, 24);
    const w = 320, h = 160, pad = 28;
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("role", "img");
    const max = Math.max(1, ...series.map((p) => Number(p.value) || 0));
    const kind = chart.kind || "bar";
    if (kind === "pie") {
      let ang = -Math.PI / 2;
      const cx = w / 2, cy = h / 2, r = 54;
      const total = series.reduce((s, p) => s + (Number(p.value) || 0), 0) || 1;
      series.forEach((p, i) => {
        const slice = ((Number(p.value) || 0) / total) * Math.PI * 2;
        const x1 = cx + r * Math.cos(ang);
        const y1 = cy + r * Math.sin(ang);
        ang += slice;
        const x2 = cx + r * Math.cos(ang);
        const y2 = cy + r * Math.sin(ang);
        const large = slice > Math.PI ? 1 : 0;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`);
        path.setAttribute("fill", `hsl(${(i * 47) % 360} 55% 48%)`);
        svg.appendChild(path);
      });
      return;
    }
    series.forEach((p, i) => {
      const v = Number(p.value) || 0;
      const x = pad + (i * (w - pad * 2)) / Math.max(1, series.length);
      const bw = Math.max(4, (w - pad * 2) / Math.max(1, series.length) - 4);
      const bh = ((h - pad * 2) * v) / max;
      if (kind === "line") {
        // points accumulated below
      } else {
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", String(x));
        rect.setAttribute("y", String(h - pad - bh));
        rect.setAttribute("width", String(bw));
        rect.setAttribute("height", String(bh));
        rect.setAttribute("fill", "var(--cyan)");
        svg.appendChild(rect);
      }
    });
    if (kind === "line" && series.length) {
      const pts = series.map((p, i) => {
        const v = Number(p.value) || 0;
        const x = pad + (i * (w - pad * 2)) / Math.max(1, series.length - 1);
        const y = h - pad - ((h - pad * 2) * v) / max;
        return `${x},${y}`;
      }).join(" ");
      const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      poly.setAttribute("points", pts);
      poly.setAttribute("fill", "none");
      poly.setAttribute("stroke", "var(--cyan)");
      poly.setAttribute("stroke-width", "2");
      svg.appendChild(poly);
    }
  }

  function renderReport(doc) {
    currentReport = doc;
    const root = $("#reportCanvas");
    if (!root) return;
    clear(root);

    const head = el("div", "report-head");
    head.appendChild(el("h2", null, doc.query || "Report"));
    const meta = el("p", "muted");
    meta.textContent = `${doc.mode || "?"} · ${doc.created_at || ""} · id ${doc.id || ""}`;
    head.appendChild(meta);
    if (doc.fallback_plain) {
      head.appendChild(el("p", "warn", `Plain fallback: ${doc.fallback_reason || ""}`));
    }
    root.appendChild(head);

    const sum = doc.summary || {};
    const card = el("div", "report-card");
    card.appendChild(el("h3", null, "TL;DR"));
    card.appendChild(el("p", null, sum.tldr || ""));
    card.appendChild(el("p", "muted", `Confidence ${sum.confidence ?? "—"} — ${sum.rationale || ""}`));
    root.appendChild(card);

    const filt = el("div", "report-toolbar");
    filt.appendChild(el("span", "muted", "Min confidence"));
    const range = el("input");
    range.type = "range";
    range.min = "0";
    range.max = "100";
    range.value = String(Math.round(confFilter * 100));
    range.addEventListener("input", () => {
      confFilter = Number(range.value) / 100;
      renderFindings(doc);
    });
    filt.appendChild(range);
    root.appendChild(filt);

    const findingsHost = el("div", "report-findings");
    findingsHost.id = "reportFindings";
    root.appendChild(findingsHost);
    renderFindings(doc);

    const claimsHost = el("div", "report-card");
    claimsHost.appendChild(el("h3", null, "Claims & evidence"));
    (doc.claims || []).forEach((c) => {
      const row = el("details", "claim-row");
      const sumEl = el("summary");
      sumEl.textContent = c.claim || "";
      row.appendChild(sumEl);
      row.appendChild(el("p", "muted", `Evidence: ${c.evidence || ""}`));
      const src = (doc.sources || []).find((s) => s.id === c.source_id);
      if (src) {
        const p = el("p");
        p.appendChild(document.createTextNode("Source: "));
        p.appendChild(linkEl(src.url, src.domain || src.title));
        row.appendChild(p);
      }
      const copyBtn = el("button", "ghost", "Copy citation");
      copyBtn.type = "button";
      copyBtn.addEventListener("click", () => {
        const text = `${c.claim} — ${src ? src.url : c.source_id}`;
        navigator.clipboard?.writeText(text);
      });
      row.appendChild(copyBtn);
      claimsHost.appendChild(row);
    });
    root.appendChild(claimsHost);

    (doc.charts || []).forEach((ch) => {
      const box = el("div", "report-card");
      box.appendChild(el("h3", null, ch.title || "Chart"));
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.classList.add("report-chart");
      drawChart(svg, ch);
      box.appendChild(svg);
      root.appendChild(box);
    });

    const table = doc.comparison_table;
    if (table && (table.headers || []).length) {
      const box = el("div", "report-card");
      box.appendChild(el("h3", null, "Comparison"));
      const tbl = el("table", "report-table");
      const thead = el("thead");
      const hr = el("tr");
      (table.headers || []).forEach((h) => hr.appendChild(el("th", null, h)));
      thead.appendChild(hr);
      tbl.appendChild(thead);
      const tb = el("tbody");
      (table.rows || []).forEach((row) => {
        const tr = el("tr");
        row.forEach((cell) => tr.appendChild(el("td", null, cell)));
        tb.appendChild(tr);
      });
      tbl.appendChild(tb);
      box.appendChild(tbl);
      root.appendChild(box);
    }

    if ((doc.timeline || []).length) {
      const box = el("div", "report-card");
      box.appendChild(el("h3", null, "Timeline"));
      (doc.timeline || []).forEach((t) => {
        box.appendChild(el("p", null, `${t.when}: ${t.event}`));
      });
      root.appendChild(box);
    }

    const srcBox = el("div", "report-card");
    srcBox.appendChild(el("h3", null, "Sources"));
    (doc.sources || []).forEach((s) => {
      const row = el("div", "source-row");
      row.appendChild(linkEl(s.url, `${s.domain} — ${s.title}`));
      const cred = (s.credibility || {}).label || "";
      row.appendChild(el("p", "muted", `${s.fetched_at || ""} · ${cred}`));
      srcBox.appendChild(row);
    });
    root.appendChild(srcBox);

    ["uncertainties", "open_questions", "pros", "cons"].forEach((key) => {
      const items = doc[key] || [];
      if (!items.length) return;
      const box = el("div", "report-card");
      box.appendChild(el("h3", null, key.replace("_", " ")));
      items.forEach((t) => box.appendChild(el("p", null, t)));
      root.appendChild(box);
    });

    const actions = el("div", "report-toolbar");
    const rem = el("button", "ghost", "Remember findings");
    rem.type = "button";
    rem.addEventListener("click", async () => {
      await apiFetch(`/api/reports/${doc.id}/remember`, { method: "POST" });
    });
    actions.appendChild(rem);
    const md = el("a", "ghost", "Export Markdown");
    md.href = `/api/reports/${doc.id}/export.md`;
    md.rel = "noopener noreferrer";
    actions.appendChild(md);
    const ht = el("a", "ghost", "Export HTML");
    ht.href = `/api/reports/${doc.id}/export.html`;
    ht.rel = "noopener noreferrer";
    actions.appendChild(ht);
    const del = el("button", "ghost danger", "Delete");
    del.type = "button";
    del.addEventListener("click", async () => {
      await apiFetch(`/api/reports/${doc.id}`, { method: "DELETE" });
      clear(root);
      refreshHistory();
    });
    actions.appendChild(del);
    root.appendChild(actions);
  }

  function renderFindings(doc) {
    const host = $("#reportFindings");
    if (!host) return;
    clear(host);
    host.appendChild(el("h3", null, "Key findings"));
    (doc.findings || [])
      .filter((f) => (f.confidence ?? 0) >= confFilter)
      .forEach((f) => {
        const card = el("div", "report-card finding");
        card.appendChild(el("h4", null, f.title || ""));
        card.appendChild(el("p", null, f.body || ""));
        card.appendChild(el("p", "muted", `Confidence ${f.confidence ?? "—"}`));
        const dig = el("button", "ghost", "Dig deeper");
        dig.type = "button";
        dig.addEventListener("click", async () => {
          const r = await apiFetch(`/api/reports/${doc.id}/dig`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ finding_id: f.id }),
          });
          if (r.ok) {
            const sub = await r.json();
            renderReport(sub);
            refreshHistory();
          }
        });
        card.appendChild(dig);
        host.appendChild(card);
      });
  }

  async function refreshHistory() {
    const host = $("#reportHistory");
    if (!host || typeof apiFetch !== "function") return;
    clear(host);
    try {
      const rows = await (await apiFetch("/api/reports")).json();
      rows.forEach((r) => {
        const btn = el("button", "ghost report-hist", `${r.query || r.id}`);
        btn.type = "button";
        btn.addEventListener("click", async () => {
          const doc = await (await apiFetch(`/api/reports/${r.id}`)).json();
          renderReport(doc);
          showReportsView();
        });
        host.appendChild(btn);
      });
    } catch (_) { /* offline */ }
  }

  function showReportsView() {
    document.querySelectorAll(".nav-btn").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-view") === "reports");
    });
    document.querySelectorAll(".view").forEach((v) => {
      v.classList.toggle("active", v.id === "view-reports");
    });
  }

  function setLive(line) {
    const live = $("#reportLive");
    if (live) live.textContent = line;
  }

  function tickElapsed() {
    const elapse = $("#reportElapsed");
    if (!elapse || !startedAt) return;
    elapse.textContent = `${Math.round((Date.now() - startedAt) / 1000)}s`;
  }

  async function startResearch(query, mode) {
    showReportsView();
    const canvas = $("#reportCanvas");
    if (canvas) {
      clear(canvas);
      for (let i = 0; i < 3; i++) {
        const sk = el("div", "report-card skeleton");
        sk.appendChild(el("div", "sk-line"));
        sk.appendChild(el("div", "sk-line short"));
        canvas.appendChild(sk);
      }
    }
    startedAt = Date.now();
    clearInterval(timerIv);
    timerIv = setInterval(tickElapsed, 500);
    setLive("Starting…");
    const res = await apiFetch("/api/reports/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, mode: mode || "quick" }),
    });
    if (!res.ok) {
      setLive(res.status === 403 ? "Tools role required to run web research." : "Could not start.");
      return;
    }
    const { run_id } = await res.json();
    $("#reportCancel")?.setAttribute("data-run", run_id);
    if (es) es.close();
    es = new EventSource(`/api/runs/${run_id}/events`);
    let reportId = null;
    es.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch (_) { return; }
      const t = data.type || "";
      if (t === "report_plan") setLive(`Plan · ${(data.sub_questions || []).join("; ") || data.query || ""}`);
      if (t === "report_query") setLive(`Query · ${data.query || ""}`);
      if (t === "report_source_found") setLive(`Source · ${data.domain || ""} — ${data.title || ""}`);
      if (t === "report_note") setLive(`Note · ${(data.text || "").slice(0, 80)}`);
      if (t === "report_validation") setLive(`Validation · ${(data.issues || []).length} issue(s)`);
      if (t === "report_final") {
        reportId = data.report_id;
        setLive(data.fallback ? `Fallback · ${data.reason || ""}` : `Done · ${data.claims || 0} claims`);
      }
      if (t === "stream_end" || t === "run_end") {
        es.close();
        clearInterval(timerIv);
        if (reportId) {
          apiFetch(`/api/reports/${reportId}`).then((r) => r.json()).then(renderReport).then(refreshHistory);
        }
      }
    };
  }

  function wire() {
    $("#reportForm")?.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("#reportQuery")?.value?.trim();
      const mode = $("#reportMode")?.value || "quick";
      if (q) startResearch(q, mode);
    });
    $("#reportCancel")?.addEventListener("click", async () => {
      const rid = $("#reportCancel")?.getAttribute("data-run");
      if (rid) await apiFetch(`/api/runs/${rid}/cancel`, { method: "POST" });
      await apiFetch("/api/estop", { method: "POST" }).catch(() => {});
      setLive("Cancel requested");
    });
    refreshHistory();
  }

  window.FridayReports = {
    start: startResearch,
    open: async (id) => {
      showReportsView();
      const doc = await (await apiFetch(`/api/reports/${id}`)).json();
      renderReport(doc);
    },
    refreshHistory,
    show: showReportsView,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
