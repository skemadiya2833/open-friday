/* Friday Systems UI — settings grid, camera controls, morning briefing.
 * Loaded after app.js; uses globals: $, apiFetch, escapeHtml, setSpeakEnabled,
 * syncSpeakToggles, addBubble, setCameraLooking.
 */

function bindVoiceControls() {
  document.querySelectorAll("#settingsGrid [data-voice-style]").forEach((b) =>
    b.addEventListener("click", () => window.FridayVoice && FridayVoice.setStyle(b.dataset.voiceStyle)));
  document.querySelectorAll("#settingsGrid [data-voice-duplex]").forEach((b) =>
    b.addEventListener("click", () => window.FridayVoice && FridayVoice.setDuplex(b.dataset.voiceDuplex)));
  window.FridayLive && FridayLive.syncControls();
}

function humorSetting() {
  return localStorage.getItem("friday_humor") || "dry";
}

async function patchPrefs(values) {
  const res = await apiFetch("/api/systems/prefs", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
  if (!res.ok) throw new Error("prefs save failed");
  return res.json();
}

function prefsPanelHtml(snap) {
  if (!snap || !snap.items) {
    return `<div class="setting"><label>Preferences</label><p class="muted">Could not load prefs.</p></div>`;
  }
  const byGroup = {};
  for (const it of snap.items) {
    (byGroup[it.group] || (byGroup[it.group] = [])).push(it);
  }
  const groups = snap.groups || [];
  let body = "";
  for (const g of groups) {
    const items = byGroup[g.id];
    if (!items || !items.length) continue;
    body += `<div class="prefs-group"><h3 class="prefs-group-title">${escapeHtml(g.label)}</h3>`;
    for (const it of items) {
      body += prefItemHtml(it);
    }
    body += `</div>`;
  }
  return `
    <div class="setting ops-panel prefs-panel">
      <label>Preferences</label>
      <div class="prefs-actions" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
        <button type="button" class="ghost" id="prefsOptimaBtn">Reset to optima</button>
        <button type="button" class="ghost" id="prefsClearBtn">Clear overrides</button>
        <span class="muted" id="prefsSaveHint" style="align-self:center"></span>
      </div>
      ${body}
    </div>`;
}

function prefItemHtml(it) {
  const src = it.source === "ui" ? "Systems" : it.source === "env" ? ".env" : "optima";
  const restart = it.restart ? ` <span class="muted">(restart recommended)</span>` : "";
  let control = "";
  if (it.kind === "bool") {
    control = `<label class="speak-toggle" style="margin-top:8px">
      <input type="checkbox" data-pref="${escapeHtml(it.key)}" ${it.value ? "checked" : ""} />
      <span>${escapeHtml(it.label)}</span>
    </label>`;
  } else if (it.kind === "choice") {
    const opts = (it.choices || []).map((c) =>
      `<button type="button" data-pref="${escapeHtml(it.key)}" data-val="${escapeHtml(c)}" class="${c === it.value ? "on" : ""}">${escapeHtml(String(c))}</button>`
    ).join("");
    control = `<div class="seg pref-seg" style="margin-top:8px;flex-wrap:wrap">${opts}</div>`;
  } else {
    control = `<input type="text" data-pref="${escapeHtml(it.key)}" value="${escapeHtml(String(it.value ?? ""))}" style="margin-top:8px;width:min(280px,100%);padding:6px 8px;background:transparent;border:1px solid var(--line);color:var(--text);font-family:var(--mono)" />`;
  }
  return `<div class="pref-item" data-pref-key="${escapeHtml(it.key)}">
    <div class="pref-label"><strong>${escapeHtml(it.label)}</strong>
      <span class="muted pref-src"> · ${escapeHtml(src)}${restart}</span></div>
    ${control}
  </div>`;
}

function bindPrefsControls(snap) {
  const hint = $("#prefsSaveHint");
  const setHint = (t) => { if (hint) hint.textContent = t; };
  const afterSave = (next) => {
    if (next && typeof next.humor === "string") {
      localStorage.setItem("friday_humor", next.humor);
    } else if (next && next.items) {
      const h = next.items.find((x) => x.key === "humor");
      if (h) localStorage.setItem("friday_humor", h.value);
    }
    setHint("Saved");
    setTimeout(() => setHint(""), 1500);
  };
  document.querySelectorAll("#settingsGrid [data-pref][type=checkbox]").forEach((el) => {
    el.addEventListener("change", async () => {
      try {
        const snap2 = await patchPrefs({ [el.getAttribute("data-pref")]: el.checked });
        afterSave(snap2);
        const item = snap2.items?.find((x) => x.key === el.getAttribute("data-pref"));
        const row = el.closest(".pref-item");
        const src = row?.querySelector(".pref-src");
        if (src && item) src.textContent = ` · ${item.source === "ui" ? "Systems" : item.source}`;
      } catch (_) {
        el.checked = !el.checked;
        setHint("Save failed");
      }
    });
  });
  document.querySelectorAll("#settingsGrid .pref-seg button[data-pref]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const key = btn.getAttribute("data-pref");
      const val = btn.getAttribute("data-val");
      try {
        const snap2 = await patchPrefs({ [key]: val });
        afterSave(snap2);
        document.querySelectorAll(`#settingsGrid .pref-seg button[data-pref="${key}"]`).forEach((b) => {
          b.classList.toggle("on", b.getAttribute("data-val") === val);
        });
        const row = btn.closest(".pref-item");
        const src = row?.querySelector(".pref-src");
        if (src) src.textContent = " · Systems";
      } catch (_) {
        setHint("Save failed");
      }
    });
  });
  document.querySelectorAll("#settingsGrid input[type=text][data-pref]").forEach((el) => {
    let timer = null;
    const save = async () => {
      try {
        const snap2 = await patchPrefs({ [el.getAttribute("data-pref")]: el.value });
        afterSave(snap2);
      } catch (_) {
        setHint("Save failed");
      }
    };
    el.addEventListener("change", save);
    el.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(save, 500);
    });
  });
  $("#prefsOptimaBtn")?.addEventListener("click", async () => {
    try {
      await apiFetch("/api/systems/prefs/optima", { method: "POST" });
      setHint("Optima applied");
      refreshSettings();
    } catch (_) {
      setHint("Failed");
    }
  });
  $("#prefsClearBtn")?.addEventListener("click", async () => {
    try {
      await apiFetch("/api/systems/prefs/clear", { method: "POST" });
      setHint("Cleared");
      refreshSettings();
    } catch (_) {
      setHint("Failed");
    }
  });
  // Seed local humor from server so chat requests match Systems.
  const humor = (snap.items || []).find((x) => x.key === "humor");
  if (humor) localStorage.setItem("friday_humor", humor.value);
}

function opsSummaryHtml(ops) {
  if (!ops || !ops.counts) return "";
  const c = ops.counts;
  const oll = (ops.subsystems && ops.subsystems.ollama) || {};
  const ollLabel = oll.up ? `up${oll.version ? " · " + oll.version : ""}` : "down";
  const drift = (ops.health && ops.health.drift_keys && ops.health.drift_keys.length)
    ? ops.health.drift_keys.join(", ")
    : "none";
  const memCols = (ops.subsystems && ops.subsystems.memory_collections) || {};
  const memDetail = Object.keys(memCols).length
    ? Object.entries(memCols).map(([k, v]) => `${k}:${v}`).join(" · ")
    : "";
  return `
      <div class="setting ops-panel"><label>Ops</label>
        <table class="ops-table"><tbody>
          <tr><td>Sessions</td><td>${c.sessions ?? "—"}</td><td>Active runs</td><td>${c.active_runs ?? "—"}</td></tr>
          <tr><td>Skills</td><td>${c.skills_enabled ?? "—"} / ${c.skills_total ?? "—"}</td><td>SKILL.md</td><td>${c.skillmd_installed ?? "—"} · ${c.skillmd_quarantine ?? "—"} Q</td></tr>
          <tr><td>Memory</td><td>${c.memory_docs ?? "—"}${memDetail ? `<br><span class="muted">${escapeHtml(memDetail)}</span>` : ""}</td><td>Reports</td><td>${c.reports ?? "—"}</td></tr>
          <tr><td>Tasks</td><td>${c.tasks_enabled ?? "—"} / ${c.scheduled_tasks ?? "—"}</td><td>Approvals</td><td>${c.approvals_pending ?? "—"}</td></tr>
          <tr><td>Ollama</td><td colspan="3">${escapeHtml(ollLabel)} · drift ${escapeHtml(drift)}</td></tr>
        </tbody></table>
      </div>`;
}

function ownerProfileHtml(profile) {
  const about = (profile && profile.about) || "";
  const ups = (profile && profile.upgrades) || [];
  const list = ups.length
    ? ups.map((u, i) => {
        const text = typeof u === "string" ? u : (u.text || "");
        const src = typeof u === "object" && u.source ? ` · ${u.source}` : "";
        return `<li data-idx="${i}"><span>${escapeHtml(text)}${src ? `<span class="muted">${escapeHtml(src)}</span>` : ""}</span>
          <button type="button" class="ghost danger" data-upgrade-del="${i}" title="Remove">×</button></li>`;
      }).join("")
    : `<li class="muted" style="border:0;background:transparent;padding:0">None yet</li>`;
  return `
    <div class="setting ops-panel owner-profile-panel">
      <label>About you</label>
      <textarea id="ownerAbout" placeholder="Who you are, preferences, how Friday should work with you…">${escapeHtml(about)}</textarea>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button type="button" class="ghost" id="ownerAboutSave">Save profile</button>
        <span class="muted" id="ownerProfileHint"></span>
      </div>
      <label style="margin-top:16px">Upgrade notes</label>
      <ul class="upgrade-list" id="ownerUpgradeList">${list}</ul>
      <div class="upgrade-add">
        <input id="ownerUpgradeInput" maxlength="280" placeholder="Idea for a future upgrade…" />
        <button type="button" class="ghost" id="ownerUpgradeAdd">Add</button>
      </div>
    </div>`;
}

async function loadOwnerProfile() {
  try {
    const res = await apiFetch("/api/systems/profile");
    if (!res.ok) return { about: "", upgrades: [] };
    return res.json();
  } catch (_) {
    return { about: "", upgrades: [] };
  }
}

function bindOwnerProfile() {
  const hint = $("#ownerProfileHint");
  const setHint = (t) => { if (hint) hint.textContent = t || ""; };
  $("#ownerAboutSave")?.addEventListener("click", async () => {
    try {
      const about = $("#ownerAbout")?.value || "";
      const res = await apiFetch("/api/systems/profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ about }),
      });
      if (!res.ok) throw new Error("save failed");
      setHint("Saved");
      setTimeout(() => setHint(""), 1600);
    } catch (_) {
      setHint("Save failed");
    }
  });
  $("#ownerUpgradeAdd")?.addEventListener("click", async () => {
    const input = $("#ownerUpgradeInput");
    const text = (input?.value || "").trim();
    if (!text) return;
    try {
      const res = await apiFetch("/api/systems/profile/upgrades", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, source: "manual" }),
      });
      if (!res.ok) throw new Error("add failed");
      if (input) input.value = "";
      const profile = await res.json();
      const panel = document.querySelector(".owner-profile-panel");
      if (panel) {
        const wrap = document.createElement("div");
        wrap.innerHTML = ownerProfileHtml(profile);
        panel.replaceWith(wrap.firstElementChild);
        bindOwnerProfile();
      }
    } catch (_) {
      setHint("Could not add");
    }
  });
  document.querySelectorAll("[data-upgrade-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const idx = Number(btn.getAttribute("data-upgrade-del"));
      if (!Number.isFinite(idx)) return;
      try {
        const res = await apiFetch(`/api/systems/profile/upgrades/${idx}`, { method: "DELETE" });
        if (!res.ok) throw new Error("delete failed");
        const profile = await res.json();
        const panel = document.querySelector(".owner-profile-panel");
        if (panel) {
          const wrap = document.createElement("div");
          wrap.innerHTML = ownerProfileHtml(profile);
          panel.replaceWith(wrap.firstElementChild);
          bindOwnerProfile();
        }
      } catch (_) {
        setHint("Could not remove");
      }
    });
  });
}

async function refreshSettings() {
  try {
    const [hRes, opsRes, prefsRes, profile] = await Promise.all([
      apiFetch("/api/health"),
      apiFetch("/api/ops/summary").catch(() => null),
      apiFetch("/api/systems/prefs").catch(() => null),
      loadOwnerProfile(),
    ]);
    const h = await hRes.json();
    let ops = null;
    if (opsRes && opsRes.ok) ops = await opsRes.json();
    let prefs = null;
    if (prefsRes && prefsRes.ok) prefs = await prefsRes.json();
    $("#modelPill").textContent = h.chat_model || h.vision_model || "local";
    const uplink = $("#uplinkStatus");
    if (uplink) uplink.textContent = "UPLINK · SECURE";
    $("#settingsGrid").innerHTML = `
      ${ownerProfileHtml(profile)}
      ${opsSummaryHtml(ops)}
      ${prefsPanelHtml(prefs)}
      <div class="setting"><label>Models</label>
        <div><span class="muted">Vision</span> <strong>${escapeHtml(h.vision_model || "—")}</strong></div>
        <div><span class="muted">Chat</span> <strong>${escapeHtml(h.chat_model || "—")}</strong></div>
        <div><span class="muted">Embed</span> <strong>${escapeHtml(h.embed_model || "—")}</strong></div>
      </div>
      <div class="setting"><label>Voice</label><strong>${h.voice ? "enabled" : "disabled"}</strong>
        <label class="speak-toggle" style="margin-top:12px">
          <input type="checkbox" id="speakToggleSettings" />
          <span>Audio Out</span>
        </label>
      </div>
      <div class="setting"><label>Voice pacing</label>
        <div class="seg">
          <button type="button" data-voice-style="realtime">Realtime</button>
          <button type="button" data-voice-style="relaxed">Relaxed</button>
        </div>
        <div class="seg" style="margin-top:8px">
          <button type="button" data-voice-duplex="hold">Hold</button>
          <button type="button" data-voice-duplex="interrupt">Interrupt</button>
        </div>
      </div>
      <div class="setting"><label>Briefings</label>
        <label class="speak-toggle" style="margin-top:8px">
          <input type="checkbox" id="morningBriefingToggle" />
          <span>Morning (≈08:00)</span>
        </label>
        <label class="speak-toggle" style="margin-top:8px">
          <input type="checkbox" id="eodBriefingToggle" />
          <span>End of day (≈18:00)</span>
        </label>
        <label class="speak-toggle" style="margin-top:8px">
          <input type="checkbox" id="weeklyBriefingToggle" />
          <span>Weekly review</span>
        </label>
        <button type="button" class="ghost" id="morningBriefingRun" style="margin-top:8px">Run morning</button>
      </div>
      <div class="setting"><label>Camera</label>
        <p class="muted" id="cameraStatusLine" style="margin:0 0 8px">Checking…</p>
        <label class="speak-toggle">
          <input type="checkbox" id="cameraEnableToggle" />
          <span>Enable</span>
        </label>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0">
          <label for="cameraDeviceSelect" class="muted" style="margin:0">Device</label>
          <select id="cameraDeviceSelect" style="min-width:220px;max-width:100%">
            <option value="">Scanning…</option>
          </select>
          <button type="button" class="ghost" id="cameraScanBtn" title="Re-scan">Scan</button>
          <button type="button" class="ghost" id="cameraUseRecommendedBtn" title="Use recommended" style="display:none">Recommended</button>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0">
          <label for="cameraResSelect" class="muted" style="margin:0">Resolution</label>
          <select id="cameraResSelect" style="min-width:180px">
            <option value="720p">720p</option>
            <option value="480p">480p</option>
            <option value="1080p">1080p</option>
            <option value="auto">Auto</option>
          </select>
        </div>
        <p class="muted" id="cameraDeviceHint" style="margin:0 0 8px"></p>
        <label class="speak-toggle">
          <input type="checkbox" id="cameraArmToggle" />
          <span>Arm</span>
        </label>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <button type="button" class="ghost" id="cameraSnapBtn">Snap</button>
          <button type="button" class="ghost" id="cameraPreviewBtn">Preview</button>
          <span class="pill" id="cameraLivePill" style="display:none">CAMERA LIVE</span>
        </div>
        <img id="cameraPreviewImg" alt="Camera preview" class="hidden" style="margin-top:10px;max-width:100%;max-height:240px;border:1px solid var(--line);background:#000" />
      </div>`;
    bindOwnerProfile();
    bindVoiceControls();
    syncSpeakToggles();
    bindPrefsControls(prefs || { items: [] });
    bindMorningBriefing();
    bindCameraControls();
    $("#speakToggleSettings")?.addEventListener("change", (e) => {
      setSpeakEnabled(e.target.checked);
    });
  } catch (_) {
    $("#settingsGrid").innerHTML = `<div class="setting"><strong>Uplink lost</strong></div>`;
    const uplink = $("#uplinkStatus");
    if (uplink) uplink.textContent = "UPLINK · LOST";
  }
}

async function refreshCameraStatus() {
  const line = $("#cameraStatusLine");
  const armToggle = $("#cameraArmToggle");
  const enableToggle = $("#cameraEnableToggle");
  try {
    const st = await (await apiFetch("/api/camera/status")).json();
    if (line) {
      const cam = st.index_label || (typeof st.index === "number" ? `Camera ${st.index}` : "");
      const base = st.detail || (st.enabled ? (st.armed ? "Armed" : "Disarmed") : "Disabled");
      line.textContent = cam && st.enabled ? `${base} · ${cam}` : base;
    }
    if (enableToggle) enableToggle.checked = !!st.enabled;
    if (armToggle) {
      armToggle.checked = !!st.armed;
      armToggle.disabled = !st.enabled;
    }
    if (st && typeof st.live === "boolean") setCameraLooking(!!st.live);
    return st;
  } catch (_) {
    if (line) line.textContent = "Camera status unavailable";
    return null;
  }
}

async function saveCameraSelection(extra = {}) {
  const sel = $("#cameraDeviceSelect");
  const resSel = $("#cameraResSelect");
  if (!sel) return null;
  const raw = String(sel.value || "");
  let backend = "";
  let idx = Number(raw);
  if (raw.includes(":")) {
    const [be, ix] = raw.split(":");
    backend = (be || "").trim();
    idx = Number(ix);
  }
  if (!Number.isFinite(idx)) return null;
  const opt = sel.options[sel.selectedIndex];
  const name = (opt?.dataset?.name || opt?.textContent || "").trim();
  const resolution = (extra.resolution != null)
    ? extra.resolution
    : (resSel?.value || "720p");
  const res = await apiFetch("/api/camera/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index: idx, backend, name, resolution }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Could not save camera selection.");
  }
  return res.json();
}

async function refreshCameraDevices() {
  const sel = $("#cameraDeviceSelect");
  const resSel = $("#cameraResSelect");
  const hint = $("#cameraDeviceHint");
  const recBtn = $("#cameraUseRecommendedBtn");
  if (!sel) return null;
  sel.disabled = true;
  if (hint) hint.textContent = "Scanning connected cameras…";
  try {
    const data = await (await apiFetch("/api/camera/devices")).json();
    const devices = Array.isArray(data.devices) ? data.devices : [];
    const selectedIdx = typeof data.selected_index === "number" ? data.selected_index : 0;
    const selectedBe = (data.selected_backend || "").trim();
    sel.innerHTML = "";
    if (resSel && data.resolution) resSel.value = data.resolution;
    if (!data.opencv) {
      sel.innerHTML = `<option value="">OpenCV missing</option>`;
      if (hint) hint.textContent = data.error || "Install camera extras to list devices.";
      if (recBtn) recBtn.style.display = "none";
      return data;
    }
    if (!devices.length) {
      sel.innerHTML = `<option value="">No cameras found</option>`;
      if (hint) hint.textContent = "Plug in a webcam and hit Scan. Close other apps that lock the camera.";
      if (recBtn) recBtn.style.display = "none";
      return data;
    }
    let matched = false;
    const savedName = String(data.selected_name || "").trim().toLowerCase();
    const selectedKey = String(data.selected_key || "").trim();
    for (const d of devices) {
      const opt = document.createElement("option");
      const key = `${d.backend || "default"}:${d.index}`;
      opt.value = key;
      opt.dataset.name = d.name || "";
      opt.textContent = d.label || d.name || `Camera ${d.index}`;
      if (d.virtual) opt.dataset.virtual = "1";
      // Prefer match by DirectShow name, then by key — never trust index alone.
      const byName = savedName && String(d.name || "").trim().toLowerCase() === savedName;
      const byKey = selectedKey && key === selectedKey;
      const exact = selectedBe && key === `${selectedBe}:${selectedIdx}`;
      const loose = !selectedBe && !matched && d.index === selectedIdx;
      if (!matched && (byName || byKey || exact || loose)) {
        opt.selected = true;
        matched = true;
      }
      sel.appendChild(opt);
    }
    if (!matched) {
      const opt = document.createElement("option");
      opt.value = selectedBe ? `${selectedBe}:${selectedIdx}` : `default:${selectedIdx}`;
      opt.textContent = `Camera ${selectedIdx}${selectedBe ? ` · ${selectedBe}` : ""} (saved · not detected now)`;
      opt.selected = true;
      sel.appendChild(opt);
    }
    if (recBtn) {
      const showRec = !!(data.recommended_key && data.warning);
      recBtn.style.display = showRec ? "" : "none";
      recBtn.dataset.key = data.recommended_key || "";
      recBtn.title = data.recommended_label || "Use recommended desk camera";
    }
    if (hint) {
      if (data.warning) hint.textContent = data.warning;
      else {
        const virt = devices.filter((d) => d.virtual).length;
        hint.textContent = data.enabled
          ? `${devices.length} device(s)${virt ? ` · ${virt} virtual` : ""}`
          : `${devices.length} found · enable to use`;
      }
    }
    return data;
  } catch (_) {
    sel.innerHTML = `<option value="">Scan failed</option>`;
    if (hint) hint.textContent = "Could not list cameras (server offline?).";
    return null;
  } finally {
    sel.disabled = false;
  }
}

async function bindCameraControls() {
  const toggle = $("#cameraArmToggle");
  const enableToggle = $("#cameraEnableToggle");
  const snapBtn = $("#cameraSnapBtn");
  const scanBtn = $("#cameraScanBtn");
  const sel = $("#cameraDeviceSelect");
  if (!toggle) return;
  await refreshCameraStatus();
  await refreshCameraDevices();
  enableToggle?.addEventListener("change", async () => {
    try {
      const res = await apiFetch("/api/camera/enable", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !!enableToggle.checked }),
      });
      if (!res.ok) {
        enableToggle.checked = !enableToggle.checked;
        const err = await res.json().catch(() => ({}));
        addBubble("assistant", err.detail || "Could not update camera enable.");
      }
    } catch (_) {
      enableToggle.checked = !enableToggle.checked;
    }
    await refreshCameraStatus();
    if (enableToggle?.checked) await refreshCameraDevices();
  });
  scanBtn?.addEventListener("click", async () => {
    await refreshCameraDevices();
    await refreshCameraStatus();
  });
  $("#cameraUseRecommendedBtn")?.addEventListener("click", async () => {
    const btn = $("#cameraUseRecommendedBtn");
    const key = btn?.dataset.key;
    if (!key || !sel) return;
    sel.value = key;
    try {
      await saveCameraSelection();
      await refreshCameraDevices();
      await refreshCameraStatus();
      addBubble("assistant", `Camera set to ${sel.options[sel.selectedIndex]?.textContent || key}.`);
    } catch (err) {
      addBubble("assistant", err.message || "Could not apply recommended camera.");
    }
  });
  $("#cameraResSelect")?.addEventListener("change", async () => {
    try {
      await saveCameraSelection();
      await refreshCameraStatus();
    } catch (err) {
      addBubble("assistant", err.message || "Could not save resolution.");
    }
  });
  sel?.addEventListener("change", async () => {
    try {
      await saveCameraSelection();
      await refreshCameraStatus();
      await refreshCameraDevices();
    } catch (err) {
      addBubble("assistant", err.message || "Could not save camera selection.");
      await refreshCameraDevices();
    }
  });
  toggle.addEventListener("change", async () => {
    try {
      if (toggle.checked) {
        const res = await apiFetch("/api/camera/arm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (!res.ok) {
          toggle.checked = false;
          const err = await res.json().catch(() => ({}));
          addBubble("assistant", err.detail || "Could not arm camera — enable it first.");
        }
      } else {
        await apiFetch("/api/camera/disarm", { method: "POST" });
      }
    } catch (_) {
      toggle.checked = false;
    }
    await refreshCameraStatus();
  });
  snapBtn?.addEventListener("click", async () => {
    setCameraLooking(true, "capture");
    try {
      const res = await apiFetch("/api/camera/snap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: "What do you see in front of the camera?" }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        addBubble("assistant", data.detail || "Camera snap failed — arm the camera first.");
      } else {
        addBubble("assistant", data.reply || "(no description)");
      }
    } catch (_) {
      addBubble("assistant", "Camera snap failed (offline).");
    } finally {
      setCameraLooking(false);
      await refreshCameraStatus();
    }
  });
  const previewBtn = $("#cameraPreviewBtn");
  const previewImg = $("#cameraPreviewImg");
  previewBtn?.addEventListener("click", async () => {
    if (!previewImg) return;
    const hint = $("#cameraDeviceHint");
    const armToggleEl = toggle; // cameraArmToggle
    setCameraLooking(true, "capture");
    if (hint) hint.textContent = "Opening preview…";
    previewImg.classList.add("hidden");
    try {
      // Persist the dropdown pick first — MSMF/DSHOW indices are not interchangeable.
      try {
        await saveCameraSelection();
      } catch (err) {
        if (hint) hint.textContent = err.message || "Could not save camera selection.";
        addBubble("assistant", err.message || "Could not save camera selection.");
        return;
      }
      const picked = (sel?.options[sel.selectedIndex]?.textContent || "").toLowerCase();
      if (/snap camera|obs virtual|virtual/.test(picked) && !/snap u2/.test(picked)) {
        if (hint) {
          hint.textContent = "Heads-up: that looks like a virtual camera. Use recommended / pick SNAP U2 for desk look.";
        }
      }
      if (enableToggle) enableToggle.checked = true;
      const en = await apiFetch("/api/camera/enable", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: true }),
      });
      if (!en.ok) {
        const detail = "Could not enable the camera.";
        if (hint) hint.textContent = detail;
        addBubble("assistant", detail);
        return;
      }
      const armRes = await apiFetch("/api/camera/arm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ttl_seconds: 120 }),
      });
      if (!armRes.ok) {
        let detail = "Could not arm the camera.";
        try {
          const err = await armRes.json();
          detail = err.detail || detail;
        } catch (_) { /* keep default */ }
        if (hint) hint.textContent = detail;
        addBubble("assistant", detail);
        return;
      }
      if (armToggleEl) armToggleEl.checked = true;
      const res = await apiFetch("/api/camera/preview");
      if (!res.ok) {
        let detail = "Preview failed.";
        try {
          const err = await res.json();
          detail = err.detail || detail;
        } catch (_) {
          detail = `Preview failed (HTTP ${res.status}).`;
        }
        if (hint) hint.textContent = detail;
        addBubble("assistant", detail);
        return;
      }
      const blob = await res.blob();
      if (!blob || blob.size < 100 || !(blob.type || "").includes("image")) {
        const detail = "Preview returned no image — try another device in the list.";
        if (hint) hint.textContent = detail;
        addBubble("assistant", detail);
        return;
      }
      const url = URL.createObjectURL(blob);
      if (previewImg.dataset.url) URL.revokeObjectURL(previewImg.dataset.url);
      previewImg.dataset.url = url;
      await new Promise((resolve, reject) => {
        previewImg.onload = () => resolve();
        previewImg.onerror = () => reject(new Error("image decode failed"));
        previewImg.src = url;
      });
      previewImg.classList.remove("hidden");
      if (hint) hint.textContent = "Preview frame below — pick another device if this is the wrong camera.";
    } catch (err) {
      const detail = err && err.message && !/offline/i.test(err.message)
        ? `Preview failed: ${err.message}`
        : "Preview failed (offline or camera busy).";
      if (hint) hint.textContent = detail;
      addBubble("assistant", detail);
      previewImg.classList.add("hidden");
    } finally {
      setCameraLooking(false);
      await refreshCameraStatus();
    }
  });
}

async function bindBriefingToggle(id, getPath, postPath) {
  const toggle = $(id);
  if (!toggle) return;
  try {
    const st = await (await apiFetch(getPath)).json();
    toggle.checked = !!st.enabled;
  } catch (_) { /* offline */ }
  toggle.addEventListener("change", async () => {
    try {
      await apiFetch(postPath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: toggle.checked }),
      });
    } catch (_) {
      toggle.checked = !toggle.checked;
    }
  });
}

async function bindMorningBriefing() {
  await Promise.all([
    bindBriefingToggle("#morningBriefingToggle", "/api/briefing/morning", "/api/briefing/morning"),
    bindBriefingToggle("#eodBriefingToggle", "/api/briefing/eod", "/api/briefing/eod"),
    bindBriefingToggle("#weeklyBriefingToggle", "/api/briefing/weekly", "/api/briefing/weekly"),
  ]);
  const runBtn = $("#morningBriefingRun");
  runBtn?.addEventListener("click", async () => {
    try {
      const r = await (await apiFetch("/api/briefing/morning/run", { method: "POST" })).json();
      if (r.script) {
        addBubble("assistant", r.script);
        if (speakEnabled()) speak(r.script);
      }
    } catch (err) {
      addBubble("assistant", "Could not run morning briefing.");
    }
  });
}




