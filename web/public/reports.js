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
    const kind = chart.kind || "bar";
    if (kind === "heatmap" && chart.grid && (chart.grid.cells || []).length) {
      const rows = Number(chart.grid.rows) || 7;
      const cols = Number(chart.grid.cols) || 24;
      const cw = (w - pad * 2) / cols;
      const ch = (h - pad * 2) / rows;
      const cells = chart.grid.cells || [];
      const max = Math.max(0.01, ...cells.map((c) => Number(c.value) || 0));
      cells.forEach((c) => {
        const v = Number(c.value) || 0;
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", String(pad + (Number(c.col) || 0) * cw));
        rect.setAttribute("y", String(pad + (Number(c.row) || 0) * ch));
        rect.setAttribute("width", String(Math.max(1, cw - 1)));
        rect.setAttribute("height", String(Math.max(1, ch - 1)));
        const t = v / max;
        rect.setAttribute("fill", `color-mix(in srgb, var(--cyan) ${Math.round(t * 85 + 10)}%, transparent)`);
        svg.appendChild(rect);
      });
      return;
    }
    if (kind === "timeline" && (chart.blocks || []).length) {
      const blocks = chart.blocks.slice(0, 24);
      const laneH = Math.max(8, (h - pad * 2) / Math.max(1, blocks.length));
      const t0 = Date.parse(blocks[0].start) || 0;
      const t1 = Date.parse(blocks[blocks.length - 1].end || blocks[blocks.length - 1].start) || t0 + 1;
      const span = Math.max(1, t1 - t0);
      blocks.forEach((b, i) => {
        const a = Date.parse(b.start) || t0;
        const z = Date.parse(b.end) || a + 1;
        const x = pad + ((a - t0) / span) * (w - pad * 2);
        const bw = Math.max(2, ((z - a) / span) * (w - pad * 2));
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", String(x));
        rect.setAttribute("y", String(pad + i * laneH));
        rect.setAttribute("width", String(bw));
        rect.setAttribute("height", String(laneH - 2));
        rect.setAttribute("fill", "var(--accent, var(--cyan))");
        rect.setAttribute("opacity", "0.85");
        svg.appendChild(rect);
      });
      return;
    }
    const max = Math.max(1, ...series.map((p) => Number(p.value) || 0));
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

  function safeImgUrl(u) {
    const href = safeHttpUrl(u);
    if (!href) return null;
    // Only allow http(s) images — never javascript: or data: from untrusted pages.
    return href;
  }

  function renderReport(doc) {
    currentReport = doc;
    const root = $("#reportCanvas");
    if (!root) return;
    clear(root);
    root.classList.add("report-dossier");

    const hero = el("div", "report-hero");
    hero.appendChild(el("div", "report-kicker", "FRIDAY · RESEARCH BRIEF"));
    hero.appendChild(el("h2", null, doc.query || "Report"));
    const meta = el("p", "report-meta");
    const nSrc = (doc.sources || []).length;
    const nImg = (doc.images || []).length;
    meta.textContent = `${(doc.mode || "quick").toUpperCase()} · ${nSrc} sources · ${nImg} visuals · ${doc.created_at || ""}`;
    hero.appendChild(meta);
    root.appendChild(hero);

    const sum = doc.summary || {};
    const brief = el("div", "report-brief");
    brief.appendChild(el("h3", null, doc.kind === "productivity" ? "Summary" : "Executive brief"));
    const bodyText = sum.tldr || doc.commentary || "";
    (String(bodyText).split(/\n+/).filter(Boolean) || [""]).forEach((para) => {
      brief.appendChild(el("p", null, para));
    });
    if (sum.confidence != null || sum.rationale) {
      brief.appendChild(
        el("p", "muted", `Confidence ${sum.confidence ?? "—"} · ${sum.rationale || ""}`),
      );
    }
    root.appendChild(brief);

    const gallery = (doc.images || []).filter((im) => safeImgUrl(im.image || im.url));
    if (gallery.length) {
      const g = el("div", "report-gallery");
      g.appendChild(el("h3", null, "Visuals from the web"));
      const strip = el("div", "report-gallery-strip");
      gallery.slice(0, 8).forEach((im) => {
        const fig = el("figure", "report-figure");
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = im.title || "Research visual";
        img.src = safeImgUrl(im.image || im.url);
        fig.appendChild(img);
        const cap = el("figcaption");
        if (im.url && safeHttpUrl(im.url)) {
          cap.appendChild(linkEl(im.url, im.title || domainOf(im.url) || "Open"));
        } else {
          cap.textContent = im.title || "";
        }
        fig.appendChild(cap);
        strip.appendChild(fig);
      });
      g.appendChild(strip);
      root.appendChild(g);
    }

    if (doc.metrics && typeof doc.metrics === "object") {
      const mbox = el("div", "report-card");
      mbox.appendChild(el("h3", null, "Computed metrics"));
      mbox.appendChild(el("pre", "muted", JSON.stringify(doc.metrics, null, 2)));
      root.appendChild(mbox);
    }
    if ((doc.open_loops || []).length) {
      const ob = el("div", "report-card");
      ob.appendChild(el("h3", null, "Open loops"));
      (doc.open_loops || []).forEach((t) => ob.appendChild(el("p", null, t)));
      root.appendChild(ob);
    }

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

    if ((doc.claims || []).length) {
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
        claimsHost.appendChild(row);
      });
      root.appendChild(claimsHost);
    }

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

    const srcBox = el("div", "report-sources");
    srcBox.appendChild(el("h3", null, "Sources & articles"));
    const grid = el("div", "report-source-grid");
    (doc.sources || []).forEach((s) => {
      const card = el("article", "report-source-card");
      if (safeImgUrl(s.image)) {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = "";
        img.src = safeImgUrl(s.image);
        card.appendChild(img);
      }
      const body = el("div", "report-source-body");
      body.appendChild(el("div", "report-source-domain", s.domain || domainOf(s.url) || "web"));
      body.appendChild(linkEl(s.url, s.title || s.url));
      const snip = (s.snippet || s.text || "").slice(0, 220);
      if (snip) body.appendChild(el("p", null, snip + (snip.length >= 220 ? "…" : "")));
      const cred = (s.credibility || {}).label || "";
      if (cred) body.appendChild(el("p", "muted", cred));
      card.appendChild(body);
      grid.appendChild(card);
    });
    srcBox.appendChild(grid);
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
    const google = el("a", "ghost", "Open Google");
    google.href = "https://www.google.com/search?q=" + encodeURIComponent(doc.query || "");
    google.target = "_blank";
    google.rel = "noopener noreferrer";
    actions.appendChild(google);
    const ddg = el("a", "ghost", "Open DuckDuckGo");
    ddg.href = "https://duckduckgo.com/?q=" + encodeURIComponent(doc.query || "");
    ddg.target = "_blank";
    ddg.rel = "noopener noreferrer";
    actions.appendChild(ddg);
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
    const list = (doc.findings || []).filter((f) => (f.confidence ?? 0) >= confFilter);
    if (!list.length) {
      host.appendChild(el("p", "muted", "No findings above this confidence — lower the filter or dig deeper."));
      return;
    }
    list.forEach((f) => {
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
      if (!Array.isArray(rows) || !rows.length) {
        host.appendChild(el("p", "report-empty", "No reports yet."));
        return;
      }
      rows.forEach((r) => {
        const when = r.created_at
          ? new Date(r.created_at).toLocaleString([], {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
              hour12: true,
            })
          : "";
        const label = when ? `${r.query || r.id} · ${when}` : (r.query || r.id);
        const btn = el("button", "ghost report-hist", label);
        btn.type = "button";
        btn.addEventListener("click", async () => {
          const res = await apiFetch(`/api/reports/${r.id}`);
          if (!res.ok) {
            setLive("Could not open report.");
            return;
          }
          const doc = await res.json();
          renderReport(doc);
          showReportsView();
        });
        host.appendChild(btn);
      });
      if (window.FridayMotion && FridayMotion.restagger) FridayMotion.restagger(host);
    } catch (_) {
      host.appendChild(el("p", "report-empty", "History unavailable."));
    }
  }

  function showReportsView() {
    if (typeof showView === "function") {
      showView("reports");
      return;
    }
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
      setLive(res.status === 403 ? "Tools role required." : res.status === 409 ? "Another run is active." : "Could not start.");
      clearInterval(timerIv);
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
        document.dispatchEvent(new CustomEvent("friday:report", { detail: { ready: true, reportId } }));
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
