/* Tools & MCP Control Center page and approval dialog.
 * All dynamic strings (tool args, MCP descriptions, server errors) are untrusted:
 * they are written with textContent, never innerHTML.
 */
(function () {
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const jget = async (url) => (await apiFetch(url)).json();
  const jpost = async (url, body) =>
    (await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    })).json();

  function card(title, lines, actions) {
    const c = el("div", "card");
    const row = el("div", "card-row");
    const left = el("div");
    left.appendChild(el("h3", "", title));
    lines.forEach((t) => left.appendChild(el("p", "", t)));
    row.appendChild(left);
    if (actions && actions.length) {
      const a = el("div", "actions");
      actions.forEach((b) => a.appendChild(b));
      row.appendChild(a);
    }
    c.appendChild(row);
    return c;
  }
  function button(label, fn, cls) {
    const b = el("button", cls || "", label);
    b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      try { await fn(); } finally { b.disabled = false; }
      refreshTools();
    });
    return b;
  }

  async function refreshTools() {
    try {
      const [pol, mcp, tools, audit] = await Promise.all([
        jget("/api/policy"), jget("/api/mcp/servers"), jget("/api/tools"), jget("/api/audit?n=40"),
      ]);
      $("#toolsPolicyLine").textContent =
        `Policy: safe=${pol.tiers.safe}, confirm=${pol.tiers.confirm}, dangerous=${pol.tiers.dangerous}. ` +
        `Shell tool ${pol.shell.enabled ? "enabled" : "disabled"} (mode ${pol.shell.mode}).` +
        (mcp.config_error ? ` MCP config error: ${mcp.config_error}` : "");

      const sv = $("#mcpServers");
      sv.replaceChildren();
      if (!mcp.servers.length) sv.appendChild(card("No MCP servers configured", ["Edit config/mcp_servers.yaml."], []));
      mcp.servers.forEach((s) => {
        const running = ["ready", "starting"].includes(s.status);
        const lines = [
          `State: ${s.status}${s.error ? " (" + s.error + ")" : ""}${s.enabled ? "" : " [disabled in config]"}`,
          `Command: ${s.command || ""}`,
          `Tools: ${(s.tools || []).length}, calls: ${s.calls || 0}`,
        ];
        const acts = [running ? button("Stop", () => jpost(`/api/mcp/servers/${encodeURIComponent(s.name)}/stop`))
                              : button("Start", () => jpost(`/api/mcp/servers/${encodeURIComponent(s.name)}/start`))];
        sv.appendChild(card(s.name, lines, acts));
      });

      $("#toolsCount").textContent = `${tools.tools.length} tools, registry v${tools.version}`;
      const tl = $("#toolList");
      tl.replaceChildren();
      tools.tools.forEach((t) => {
        tl.appendChild(card(t.name, [`${t.risk} | ${t.source}`, (t.description || "").slice(0, 200)], []));
      });

      $("#auditChain").textContent = audit.chain_ok ? "hash chain verified" : `CHAIN PROBLEM: ${audit.chain_message}`;
      const al = $("#auditList");
      al.replaceChildren();
      audit.records.slice().reverse().forEach((r) => {
        al.appendChild(card(`${r.tool || r.event || "event"} -> ${r.outcome || r.decision || ""}`,
          [`${r.ts || ""} | caller ${r.caller || "?"} | approver ${r.approver || "-"}`], []));
      });
    } catch (e) {
      $("#toolsPolicyLine").textContent = "Could not load: " + e.message;
    }
  }

  // --- view hook -----------------------------------------------------------
  const baseShowView = showView;
  showView = function (name) {
    baseShowView(name);
    if (name === "tools") refreshTools();
  };

  $("#mcpKill").addEventListener("click", async () => {
    const r = await jpost("/api/mcp/kill");
    pushActivity(`Kill switch: ${r.servers_stopped} MCP server(s) stopped, ${r.approvals_denied} approval(s) denied.`, { live: false });
    refreshTools();
  });
  $("#mcpReload").addEventListener("click", async () => { await jpost("/api/mcp/reload"); refreshTools(); });

  // --- approvals -----------------------------------------------------------
  let current = null;
  const overlay = $("#approvalOverlay");

  async function answer(ok) {
    if (!current) return;
    const id = current.id;
    current = null;
    overlay.hidden = true;
    try { await jpost(`/api/approvals/${encodeURIComponent(id)}`, { approved: ok }); } catch (_) {}
  }
  $("#approvalAllow").addEventListener("click", () => answer(true));
  $("#approvalDeny").addEventListener("click", () => answer(false));

  async function pollApprovals() {
    try {
      const res = await fetch("/api/approvals");
      if (res.ok) {
        const { pending } = await res.json();
        if (pending.length && !current) {
          current = pending[0];
          $("#approvalTitle").textContent = `${current.tool} (${current.risk || "confirm"})`;
          $("#approvalMeta").textContent = `Requested by ${current.caller || "unknown"}. Expires automatically.`;
          $("#approvalArgs").textContent = JSON.stringify(current.args, null, 2);
          overlay.hidden = false;
        } else if (!pending.length && current) {
          current = null;
          overlay.hidden = true;
        }
      }
    } catch (_) { /* server offline: the main UI already reports it */ }
    setTimeout(pollApprovals, 1000);
  }
  pollApprovals();
})();
