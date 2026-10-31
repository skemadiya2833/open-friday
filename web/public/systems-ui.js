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

/** Fill chat/vision <select>s from installed Ollama tags. */
async function bindModelPrefSelects(setHint, afterSave) {
  const selects = [...document.querySelectorAll("#settingsGrid select[data-model-pref]")];
  if (!selects.length) return;
  let catalog = { ok: false, models: [] };
  try {
    const res = await apiFetch("/api/systems/models");
    if (res.ok) catalog = await res.json();
  } catch (_) {}
  const names = (catalog.models || []).map((m) => m.name).filter(Boolean);
  for (const sel of selects) {
    const key = sel.getAttribute("data-model-pref");
    const current = sel.value || "";
    const opts = new Set(names);
    if (current) opts.add(current);
    const list = [...opts].sort((a, b) => a.localeCompare(b));
    sel.innerHTML = list.length
      ? list.map((n) => {
          const meta = (catalog.models || []).find((m) => m.name === n);
          const label = meta && meta.size_gb != null ? `${n} · ${meta.size_gb} GB` : n;
          return `<option value="${escapeHtml(n)}" ${n === current ? "selected" : ""}>${escapeHtml(label)}</option>`;
        }).join("")
      : `<option value="${escapeHtml(current)}">${escapeHtml(current || "No Ollama models found")}</option>`;
    sel.addEventListener("change", async () => {
      try {
        const snap2 = await patchPrefs({ [key]: sel.value });
        afterSave(snap2);
        const row = sel.closest(".pref-item");
        const src = row?.querySelector(".pref-src");
        if (src) src.textContent = " · Systems";
        const mh = $("#modelPrefHint");
        if (mh) mh.textContent = "Applied — next reply uses this tag";
        setTimeout(() => { if (mh && mh.textContent.startsWith("Applied")) mh.textContent = ""; }, 2200);
      } catch (_) {
        setHint("Save failed");
      }
    });
  }
  $("#matchVisionToChatBtn")?.addEventListener("click", async () => {
    const chatSel = document.querySelector('#settingsGrid select[data-model-pref="chat_model"]');
    const visSel = document.querySelector('#settingsGrid select[data-model-pref="vision_model"]');
    const tag = chatSel?.value;
    if (!tag || !visSel) return;
    try {
      const snap2 = await patchPrefs({ vision_model: tag });
      afterSave(snap2);
      visSel.value = tag;
      const mh = $("#modelPrefHint");
      if (mh) mh.textContent = `Vision = ${tag}`;
      setTimeout(() => { if (mh) mh.textContent = ""; }, 2200);
    } catch (_) {
      setHint("Save failed");
    }
  });
}

function prefsGroupsMarkup(snap) {
  if (!snap || !snap.items) {
    return `<p class="muted">Could not load prefs.</p>`;
  }
  const byGroup = {};
  for (const it of snap.items) {
    (byGroup[it.group] || (byGroup[it.group] = [])).push(it);
  }
  const groups = snap.groups || [];
  const chips = [];
  let body = "";
  let first = true;
  for (const g of groups) {
    const items = byGroup[g.id];
    if (!items || !items.length) continue;
    chips.push(
      `<button type="button" class="sys-chip${first ? " on" : ""}" data-prefs-group="${escapeHtml(g.id)}">${escapeHtml(g.label)}</button>`
    );
    body += `<div class="prefs-group" data-group-id="${escapeHtml(g.id)}" ${first ? "" : "hidden"}>
      <h3 class="prefs-group-title">${escapeHtml(g.label)}</h3>`;
    for (const it of items) {
      body += prefItemHtml(it);
    }
    body += `</div>`;
    first = false;
  }
  return `
    <div class="prefs-actions">
      <button type="button" class="ghost" id="prefsOptimaBtn">Reset to optima</button>
      <button type="button" class="ghost" id="prefsClearBtn">Clear overrides</button>
      <span class="muted" id="prefsSaveHint"></span>
    </div>
    <nav class="prefs-subnav" aria-label="Preference groups">${chips.join("")}</nav>
    <div class="prefs-groups">${body}</div>`;
}

function prefItemHtml(it) {
  const src = it.source === "ui" ? "Systems" : it.source === "env" ? ".env" : "optima";
  const restart = it.restart ? ` <span class="muted">(restart)</span>` : "";
  const meta = `<span class="muted pref-src"> · ${escapeHtml(src)}${restart}</span>`;
  if (it.kind === "bool") {
    return `<div class="pref-item pref-switch" data-pref-key="${escapeHtml(it.key)}">
      <div class="pref-copy">
        <strong>${escapeHtml(it.label)}</strong>${meta}
      </div>
      <label class="switch" title="${escapeHtml(it.label)}">
        <input type="checkbox" data-pref="${escapeHtml(it.key)}" ${it.value ? "checked" : ""} />
        <span class="switch-ui" aria-hidden="true"></span>
      </label>
    </div>`;
  }
  let control = "";
  if (it.kind === "choice") {
    const opts = (it.choices || []).map((c) =>
      `<button type="button" data-pref="${escapeHtml(it.key)}" data-val="${escapeHtml(c)}" class="${c === it.value ? "on" : ""}">${escapeHtml(String(c))}</button>`
    ).join("");
    control = `<div class="seg pref-seg">${opts}</div>`;
    if (it.key === "tts_voice") {
      control += `<div class="pref-inline">
        <button type="button" class="ghost" id="ttsVoicePreviewBtn" title="Hear the selected TTS voice">Preview voice</button>
        <span class="muted" id="ttsVoicePreviewHint"></span>
      </div>`;
    }
  } else if (it.key === "chat_model" || it.key === "vision_model") {
    const cur = escapeHtml(String(it.value ?? ""));
    control = `<select class="sys-select" data-pref="${escapeHtml(it.key)}" data-model-pref="${escapeHtml(it.key)}">
      <option value="${cur}">${cur || "Loading…"}</option>
    </select>`;
    if (it.key === "vision_model") {
      control += `<div class="pref-inline">
        <button type="button" class="ghost" id="matchVisionToChatBtn" title="Use the same Ollama tag for chat and screen look">Match vision to chat</button>
        <span class="muted" id="modelPrefHint"></span>
      </div>`;
    }
  } else if (it.kind === "secret" || it.secret) {
    const saved = it.has_secret
      ? `<span class="muted">saved</span>`
      : `<span class="muted">not set</span>`;
    control = `<div class="pref-inline">
      <input class="sys-input" type="password" autocomplete="new-password" data-pref="${escapeHtml(it.key)}" data-secret="1"
        placeholder="${it.has_secret ? "•••••••• (leave blank to keep)" : "paste token here"}" value="" />
      ${saved}
      ${it.has_secret ? `<button type="button" class="ghost" data-clear-secret="${escapeHtml(it.key)}" title="Clear stored token">Clear</button>` : ""}
    </div>`;
  } else {
    const wide = /path|install|repo|python|model|folder/i.test(it.key) || it.group === "cad";
    control = `<input class="sys-input${wide ? " sys-input-wide" : ""}" type="text" data-pref="${escapeHtml(it.key)}" value="${escapeHtml(String(it.value ?? ""))}" />`;
  }
  return `<div class="pref-item" data-pref-key="${escapeHtml(it.key)}">
    <div class="pref-copy"><strong>${escapeHtml(it.label)}</strong>${meta}</div>
    ${control}
  </div>`;
}

/** Sample line for Systems → TTS voice preview. */
const TTS_PREVIEW_LINE =
  "Systems online, boss. This is how I sound with the selected voice.";

let _ttsPreviewAudio = null;

function selectedPrefValue(key) {
  const on = document.querySelector(`#settingsGrid .pref-seg button[data-pref="${key}"].on`);
  return on ? on.getAttribute("data-val") : "";
}

async function previewSelectedTtsVoice() {
  const hint = $("#ttsVoicePreviewHint");
  const btn = $("#ttsVoicePreviewBtn");
  const voice = selectedPrefValue("tts_voice");
  const engine = selectedPrefValue("tts_engine") || "auto";
  if (!voice) {
    if (hint) hint.textContent = "Select a voice first";
    return;
  }
  if (btn) btn.disabled = true;
  if (hint) hint.textContent = `Synthesizing · ${voice}…`;
  try {
    if (_ttsPreviewAudio) {
      try { _ttsPreviewAudio.pause(); } catch (_) {}
      _ttsPreviewAudio = null;
    }
    const rate = window.FridayVoice && FridayVoice.edgeRate ? FridayVoice.edgeRate() : "+0%";
    const res = await apiFetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: TTS_PREVIEW_LINE,
        rate,
        voice,
        engine: engine === "auto" ? undefined : engine,
      }),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    if (!(blob.type || "").startsWith("audio") && blob.size < 1000) {
      throw new Error("No audio returned");
    }
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    _ttsPreviewAudio = audio;
    if (hint) hint.textContent = `Playing · ${voice}`;
    await new Promise((resolve) => {
      const done = () => {
        try { URL.revokeObjectURL(url); } catch (_) {}
        if (_ttsPreviewAudio === audio) _ttsPreviewAudio = null;
        resolve();
      };
      audio.onended = done;
      audio.onerror = done;
      audio.play().catch(done);
    });
    if (hint) hint.textContent = "Done";
    setTimeout(() => { if (hint && hint.textContent === "Done") hint.textContent = ""; }, 1600);
  } catch (err) {
    console.warn("[Friday] TTS preview failed:", err);
    if (hint) hint.textContent = "Preview failed — try another voice or engine";
    // Soft fallback: browser speech so the control still does something.
    if (typeof speakBrowser === "function") {
      try { await speakBrowser(TTS_PREVIEW_LINE); } catch (_) {}
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function bindPresencePanel() {
  const line = $("#presenceStatusLine");
  const grid = $("#presencePortraitGrid");
  const skinSeg = $("#presenceSkinSeg");
  const engHint = $("#avatarEngineHint");
  const form = $("#presenceCustomForm");
  const voiceSel = $("#presenceVoiceSelect");
  const delBtn = $("#presenceDeleteBtn");
  if (!grid || !skinSeg) return;
  let lastSnap = {};

  const fillVoices = (choices) => {
    if (!voiceSel) return;
    const list = (choices && choices.length) ? choices : [
      { id: "af_bella", label: "Bella (female US)" },
      { id: "bm_george", label: "George (male GB)" },
      { id: "am_adam", label: "Adam (male US)" },
    ];
    const cur = voiceSel.value;
    voiceSel.innerHTML = list.map((v) =>
      `<option value="${escapeHtml(v.id)}" data-profile="${escapeHtml(v.profile || "")}">${escapeHtml(v.label || v.id)}</option>`
    ).join("");
    if (cur) voiceSel.value = cur;
  };

  const render = async () => {
    let snap = {};
    try {
      const res = await apiFetch("/api/presence");
      if (res.ok) snap = await res.json();
    } catch (_) {}
    lastSnap = snap;
    const skins = snap.skins || [];
    const active = (snap.skin && snap.skin.id) || "friday";
    const portraits = snap.portraits || {};
    const avatar = snap.avatar || {};
    const engines = (avatar.engines) || {};
    fillVoices(snap.voice_choices);
    skinSeg.innerHTML = skins.map((s) =>
      `<button type="button" data-presence-skin="${escapeHtml(s.id)}" class="${s.id === active ? "on" : ""}">${escapeHtml(s.display_name || s.id)}${s.custom ? " ★" : ""}</button>`
    ).join("");
    grid.innerHTML = skins.map((s) => {
      const url = portraits[s.id];
      const hasTalk = !!s.talking_video;
      const thumb = url
        ? `<img src="${escapeHtml(url)}?t=${Date.now()}" alt="" class="presence-thumb" />`
        : `<div class="presence-thumb presence-thumb-empty">No image</div>`;
      return `<div class="presence-card" data-skin="${escapeHtml(s.id)}">
        <div class="presence-card-head">${escapeHtml(s.display_name || s.id)}${s.custom ? " · custom" : ""}${hasTalk ? " · talk" : ""}</div>
        ${thumb}
        <div class="presence-card-actions">
          <label class="ghost presence-upload-btn">
            Portrait
            <input type="file" accept="image/png,image/jpeg,image/webp" data-portrait-upload="${escapeHtml(s.id)}" hidden />
          </label>
          ${url ? `<button type="button" class="ghost presence-del-btn" data-portrait-delete="${escapeHtml(s.id)}">Remove image</button>` : ""}
          <label class="ghost presence-upload-btn">
            Talking video
            <input type="file" accept="video/mp4,video/webm,video/quicktime" data-talking-upload="${escapeHtml(s.id)}" hidden />
          </label>
          ${hasTalk ? `<button type="button" class="ghost presence-del-btn" data-talking-delete="${escapeHtml(s.id)}">Remove video</button>` : ""}
        </div>
      </div>`;
    }).join("");
    const lipsync = snap.avatar_lipsync !== false;
    const lipsyncEl = $("#avatarLipsyncToggle");
    if (lipsyncEl) lipsyncEl.checked = lipsync;
    const activeTalk = !!(snap.skin && snap.skin.talking_video);
    if (engHint) {
      engHint.textContent = activeTalk
        ? "Active callsign has a talking video — energy-synced (muted) with TTS."
        : "Upload a talking-head mp4 per callsign (from wav2lip.org or similar). Wav2Lip generation is retired.";
    }
    if (line) {
      line.textContent = activeTalk
        ? "Talking video on — speak and the clip plays with your voice."
        : "Upload a talking video to animate the avatar with speech (no on-device Wav2Lip).";
    }
    if (delBtn) {
      const isCustom = !!(snap.skin && snap.skin.custom);
      delBtn.hidden = !isCustom;
      delBtn.dataset.skinId = isCustom ? snap.skin.id : "";
    }
  };

  await render();

  skinSeg.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-presence-skin]");
    if (!btn) return;
    const sid = btn.getAttribute("data-presence-skin");
    try {
      await apiFetch("/api/presence/skin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skin_id: sid }),
      });
      if (typeof refreshPresence === "function") refreshPresence();
      await render();
    } catch (_) {
      if (line) line.textContent = "Could not switch callsign";
    }
  });

  $("#avatarLipsyncToggle")?.addEventListener("change", async (e) => {
    try {
      await patchPrefs({ avatar_lipsync: !!e.target.checked });
      await render();
    } catch (_) {
      e.target.checked = !e.target.checked;
    }
  });

  grid.addEventListener("change", async (ev) => {
    const input = ev.target;
    if (!(input instanceof HTMLInputElement) || input.type !== "file") return;
    const portraitSid = input.getAttribute("data-portrait-upload");
    const talkSid = input.getAttribute("data-talking-upload");
    const file = input.files && input.files[0];
    if (!file) return;
    if (portraitSid) {
      if (line) line.textContent = `Uploading portrait ${portraitSid}…`;
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        const res = await apiFetch(`/api/presence/portrait/${encodeURIComponent(portraitSid)}`, {
          method: "POST",
          body: fd,
        });
        if (!res.ok) throw new Error(await res.text());
        if (typeof refreshPresence === "function") refreshPresence();
        await render();
        if (line) line.textContent = `Portrait saved for ${portraitSid}`;
      } catch (err) {
        if (line) line.textContent = `Upload failed — ${err && err.message ? err.message : "error"}`;
      } finally {
        input.value = "";
      }
      return;
    }
    if (talkSid) {
      if (line) line.textContent = `Uploading talking video ${talkSid}…`;
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        const res = await apiFetch(`/api/presence/talking/${encodeURIComponent(talkSid)}`, {
          method: "POST",
          body: fd,
        });
        if (!res.ok) throw new Error(await res.text());
        if (typeof refreshPresence === "function") refreshPresence();
        await render();
        if (line) line.textContent = `Talking video saved for ${talkSid}`;
      } catch (err) {
        if (line) line.textContent = `Talking upload failed — ${err && err.message ? err.message : "error"}`;
      } finally {
        input.value = "";
      }
    }
  });

  grid.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-portrait-delete], [data-talking-delete]");
    if (!btn) return;
    const portraitSid = btn.getAttribute("data-portrait-delete");
    const talkSid = btn.getAttribute("data-talking-delete");
    if (portraitSid) {
      if (!window.confirm(`Remove portrait for ${portraitSid}?`)) return;
      if (line) line.textContent = `Removing portrait ${portraitSid}…`;
      try {
        const res = await apiFetch(`/api/presence/portrait/${encodeURIComponent(portraitSid)}`, {
          method: "DELETE",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (typeof refreshPresence === "function") refreshPresence();
        await render();
        if (line) line.textContent = `Portrait removed for ${portraitSid}`;
      } catch (err) {
        if (line) line.textContent = `Remove failed — ${err && err.message ? err.message : "error"}`;
      }
      return;
    }
    if (talkSid) {
      if (!window.confirm(`Remove talking video for ${talkSid}?`)) return;
      if (line) line.textContent = `Removing talking video ${talkSid}…`;
      try {
        const res = await apiFetch(`/api/presence/talking/${encodeURIComponent(talkSid)}`, {
          method: "DELETE",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (typeof refreshPresence === "function") refreshPresence();
        await render();
        if (line) line.textContent = `Talking video removed for ${talkSid}`;
      } catch (err) {
        if (line) line.textContent = `Remove failed — ${err && err.message ? err.message : "error"}`;
      }
    }
  });

  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(form);
    const name = String(fd.get("display_name") || "").trim();
    if (!name) return;
    const voice = String(fd.get("tts_voice") || "af_bella");
    const opt = voiceSel && voiceSel.selectedOptions[0];
    const profile = (opt && opt.getAttribute("data-profile")) || "female_us";
    const payload = {
      display_name: name,
      callsign: String(fd.get("callsign") || "").trim() || undefined,
      address_as: String(fd.get("address_as") || "").trim() || undefined,
      accent: String(fd.get("accent") || "#3dd6c6"),
      tts_voice: voice,
      voice_profile: profile,
      humor_level: String(fd.get("humor_level") || "dry"),
      personality: String(fd.get("personality") || "").trim() || undefined,
      lipsync: true,
      activate: true,
    };
    if (line) line.textContent = `Creating ${name}…`;
    try {
      const res = await apiFetch("/api/presence/skins", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          msg = err.detail || msg;
        } catch (_) {}
        throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
      const created = await res.json();
      const sid = (created.skin && created.skin.id) || (created.skin_id);
      const portrait = fd.get("portrait");
      if (sid && portrait && portrait instanceof File && portrait.size > 0) {
        const pfd = new FormData();
        pfd.append("file", portrait, portrait.name);
        await apiFetch(`/api/presence/portrait/${encodeURIComponent(sid)}`, {
          method: "POST",
          body: pfd,
        });
      }
      const talking = fd.get("talking");
      if (sid && talking && talking instanceof File && talking.size > 0) {
        const tfd = new FormData();
        tfd.append("file", talking, talking.name);
        await apiFetch(`/api/presence/talking/${encodeURIComponent(sid)}`, {
          method: "POST",
          body: tfd,
        });
      }
      form.reset();
      if (form.querySelector('[name="accent"]')) form.querySelector('[name="accent"]').value = "#f472b6";
      if (typeof refreshPresence === "function") refreshPresence();
      await render();
      if (line) line.textContent = `${name} ready — switched.`;
    } catch (err) {
      if (line) line.textContent = `Create failed — ${err && err.message ? err.message : "error"}`;
    }
  });

  delBtn?.addEventListener("click", async () => {
    const sid = delBtn.dataset.skinId;
    if (!sid) return;
    if (!window.confirm(`Delete custom callsign ${sid}?`)) return;
    try {
      const res = await apiFetch(`/api/presence/skins/${encodeURIComponent(sid)}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (typeof refreshPresence === "function") refreshPresence();
      await render();
      if (line) line.textContent = `Deleted ${sid}`;
    } catch (err) {
      if (line) line.textContent = `Delete failed — ${err && err.message ? err.message : "error"}`;
    }
  });
}

function bindSystemsNav() {
  const nav = document.querySelector("#settingsGrid .systems-nav");
  if (!nav) return;
  nav.querySelectorAll("[data-sys-panel]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-sys-panel");
      nav.querySelectorAll("[data-sys-panel]").forEach((b) => {
        b.classList.toggle("on", b === btn);
      });
      document.querySelectorAll("#settingsGrid .systems-panel").forEach((panel) => {
        const match = panel.getAttribute("data-panel") === id;
        panel.hidden = !match;
      });
    });
  });
}

function bindPrefsGroupNav() {
  const sub = document.querySelector("#settingsGrid .prefs-subnav");
  if (!sub) return;
  sub.querySelectorAll("[data-prefs-group]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const gid = btn.getAttribute("data-prefs-group");
      sub.querySelectorAll("[data-prefs-group]").forEach((b) => {
        b.classList.toggle("on", b === btn);
      });
      document.querySelectorAll("#settingsGrid .prefs-group").forEach((g) => {
        g.hidden = g.getAttribute("data-group-id") !== gid;
      });
    });
  });
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
        if (key === "presence_skin") {
          await apiFetch("/api/presence/skin", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ skin_id: val }),
          });
          if (typeof refreshPresence === "function") refreshPresence();
        }
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
  document.querySelectorAll("#settingsGrid input[type=password][data-pref][data-secret]").forEach((el) => {
    el.addEventListener("change", async () => {
      const key = el.getAttribute("data-pref");
      const val = (el.value || "").trim();
      if (!val) return; // blank = keep existing (server also ignores mask)
      try {
        const snap2 = await patchPrefs({ [key]: val });
        el.value = "";
        afterSave(snap2);
        refreshSettings();
      } catch (_) {
        setHint("Save failed");
      }
    });
  });
  document.querySelectorAll("#settingsGrid [data-clear-secret]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const key = btn.getAttribute("data-clear-secret");
      try {
        const snap2 = await patchPrefs({ [key]: "" });
        afterSave(snap2);
        refreshSettings();
      } catch (_) {
        setHint("Clear failed");
      }
    });
  });
  bindModelPrefSelects(setHint, afterSave);
  $("#prefsOptimaBtn")?.addEventListener("click", async () => {
    try {
      await apiFetch("/api/systems/prefs/optima", { method: "POST" });
      setHint("Optima applied");
      refreshSettings();
    } catch (_) {
      setHint("Failed");
    }
  });
  $("#ttsVoicePreviewBtn")?.addEventListener("click", () => {
    previewSelectedTtsVoice();
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
      <div class="ops-embed">
        <h3 class="prefs-group-title">Ops</h3>
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
      <div class="systems-shell">
        <nav class="systems-nav" aria-label="Systems sections">
          <button type="button" class="sys-chip on" data-sys-panel="prefs">Preferences</button>
          <button type="button" class="sys-chip" data-sys-panel="presence">Presence</button>
          <button type="button" class="sys-chip" data-sys-panel="about">About you</button>
          <button type="button" class="sys-chip" data-sys-panel="voice">Voice</button>
          <button type="button" class="sys-chip" data-sys-panel="camera">Camera</button>
          <button type="button" class="sys-chip" data-sys-panel="cad">CAD</button>
          <button type="button" class="sys-chip" data-sys-panel="status">Status</button>
        </nav>

        <section class="systems-panel setting" id="sys-prefs" data-panel="prefs">
          <label>Preferences</label>
          ${prefsGroupsMarkup(prefs)}
        </section>

        <section class="systems-panel setting" id="sys-presence" data-panel="presence" hidden>
          <label>Presence / talking head</label>
          <p class="muted sys-status-line" id="presenceStatusLine">Loading callsigns…</p>
          <div class="pref-item">
            <div class="pref-copy"><strong>Active callsign</strong><span class="muted"> · skin + voice</span></div>
            <div class="seg" id="presenceSkinSeg"></div>
          </div>
          <div class="pref-item pref-switch">
            <div class="pref-copy"><strong>Play talking video with speech</strong><span class="muted"> · fades/paces your clip to TTS energy</span></div>
            <label class="switch" title="Talking video">
              <input type="checkbox" id="avatarLipsyncToggle" />
              <span class="switch-ui" aria-hidden="true"></span>
            </label>
          </div>
          <div class="pref-item">
            <div class="pref-copy"><strong>Portraits &amp; talking videos</strong><span class="muted"> · still image + optional talk clip per callsign</span></div>
            <div class="presence-portrait-grid" id="presencePortraitGrid"></div>
            <p class="muted" id="avatarEngineHint" style="margin:8px 0 0"></p>
          </div>
          <div class="pref-item" id="presenceCustomBox">
            <div class="pref-copy"><strong>Create your callsign</strong><span class="muted"> · inherits tools &amp; safety; customize voice, talk style, avatar</span></div>
            <form id="presenceCustomForm" class="presence-custom-form" autocomplete="off">
              <div class="presence-custom-row">
                <label>Name<input name="display_name" required maxlength="40" placeholder="Piegi" /></label>
                <label>Callsign<input name="callsign" maxlength="32" placeholder="PIEGI" /></label>
              </div>
              <div class="presence-custom-row">
                <label>Address them as<input name="address_as" maxlength="48" placeholder="boss (optional)" /></label>
                <label>Accent<input name="accent" type="color" value="#f472b6" /></label>
              </div>
              <div class="presence-custom-row">
                <label>Voice
                  <select name="tts_voice" id="presenceVoiceSelect"></select>
                </label>
                <label>Humor
                  <select name="humor_level">
                    <option value="dry">dry</option>
                    <option value="full">full</option>
                    <option value="off">off</option>
                  </select>
                </label>
              </div>
              <label class="presence-custom-full">Personality / way of talking
                <textarea name="personality" rows="3" maxlength="800" placeholder="Warm, playful, short answers."></textarea>
              </label>
              <label class="presence-custom-full">Portrait (optional)
                <input type="file" name="portrait" accept="image/png,image/jpeg,image/webp" />
              </label>
              <label class="presence-custom-full">Talking video (optional)
                <input type="file" name="talking" accept="video/mp4,video/webm,video/quicktime" />
              </label>
              <div class="presence-custom-actions">
                <button type="submit" class="primary" id="presenceCreateBtn">Create &amp; switch</button>
                <button type="button" class="ghost" id="presenceDeleteBtn" hidden>Delete active custom</button>
              </div>
            </form>
          </div>
        </section>

        <section class="systems-panel" id="sys-about" data-panel="about" hidden>
          ${ownerProfileHtml(profile)}
        </section>

        <section class="systems-panel setting" id="sys-voice" data-panel="voice" hidden>
          <label>Voice</label>
          <div class="pref-item pref-switch">
            <div class="pref-copy"><strong>Audio out</strong><span class="muted"> · speak replies</span></div>
            <label class="switch" title="Audio out">
              <input type="checkbox" id="speakToggleSettings" />
              <span class="switch-ui" aria-hidden="true"></span>
            </label>
          </div>
          <p class="muted sys-status-line">Pipeline: <strong>${h.voice ? "enabled" : "disabled"}</strong></p>
          <div class="pref-item">
            <div class="pref-copy"><strong>Pacing</strong></div>
            <div class="seg">
              <button type="button" data-voice-style="realtime">Realtime</button>
              <button type="button" data-voice-style="relaxed">Relaxed</button>
            </div>
          </div>
          <div class="pref-item">
            <div class="pref-copy"><strong>Duplex</strong></div>
            <div class="seg">
              <button type="button" data-voice-duplex="hold">Hold</button>
              <button type="button" data-voice-duplex="interrupt">Interrupt</button>
            </div>
          </div>
          <div class="pref-item">
            <div class="pref-copy"><strong>Briefings</strong></div>
            <div class="pref-stack">
              <label class="switch-inline"><span>Morning ≈08:00</span>
                <span class="switch"><input type="checkbox" id="morningBriefingToggle" /><span class="switch-ui" aria-hidden="true"></span></span>
              </label>
              <label class="switch-inline"><span>End of day ≈18:00</span>
                <span class="switch"><input type="checkbox" id="eodBriefingToggle" /><span class="switch-ui" aria-hidden="true"></span></span>
              </label>
              <label class="switch-inline"><span>Weekly review</span>
                <span class="switch"><input type="checkbox" id="weeklyBriefingToggle" /><span class="switch-ui" aria-hidden="true"></span></span>
              </label>
              <button type="button" class="ghost" id="morningBriefingRun">Run morning now</button>
            </div>
          </div>
        </section>

        <section class="systems-panel setting" id="sys-camera" data-panel="camera" hidden>
          <label>Camera</label>
          <p class="muted sys-status-line" id="cameraStatusLine">Checking…</p>
          <div class="pref-item pref-switch">
            <div class="pref-copy"><strong>Enable</strong></div>
            <label class="switch" title="Enable camera">
              <input type="checkbox" id="cameraEnableToggle" />
              <span class="switch-ui" aria-hidden="true"></span>
            </label>
          </div>
          <div class="pref-item">
            <div class="pref-copy"><strong>Device</strong></div>
            <div class="pref-inline">
              <select class="sys-select" id="cameraDeviceSelect">
                <option value="">Scanning…</option>
              </select>
              <button type="button" class="ghost" id="cameraScanBtn" title="Re-scan">Scan</button>
              <button type="button" class="ghost" id="cameraUseRecommendedBtn" title="Use recommended" style="display:none">Recommended</button>
            </div>
          </div>
          <div class="pref-item">
            <div class="pref-copy"><strong>Resolution</strong></div>
            <select class="sys-select" id="cameraResSelect">
              <option value="720p">720p</option>
              <option value="480p">480p</option>
              <option value="1080p">1080p</option>
              <option value="auto">Auto</option>
            </select>
          </div>
          <p class="muted" id="cameraDeviceHint"></p>
          <div class="pref-item pref-switch">
            <div class="pref-copy"><strong>Arm</strong><span class="muted"> · grant capture</span></div>
            <label class="switch" title="Arm camera">
              <input type="checkbox" id="cameraArmToggle" />
              <span class="switch-ui" aria-hidden="true"></span>
            </label>
          </div>
          <div class="pref-inline">
            <button type="button" class="ghost" id="cameraSnapBtn">Snap</button>
            <button type="button" class="ghost" id="cameraPreviewBtn">Preview</button>
            <span class="pill" id="cameraLivePill" style="display:none">CAMERA LIVE</span>
          </div>
          <img id="cameraPreviewImg" alt="Camera preview" class="hidden camera-preview" />
        </section>

        <section class="systems-panel setting" id="sys-cad" data-panel="cad" hidden>
          <label>CAD / FreeCAD</label>
          <p class="muted sys-status-line" id="cadStatusLine">Checking…</p>
          <div class="pref-inline">
            <button type="button" class="ghost" id="cadDetectBtn">Detect FreeCAD</button>
            <button type="button" class="ghost" id="cadSetupBtn">Setup Taiga</button>
            <button type="button" class="ghost" id="cadLaunchBtn">Launch FreeCAD server</button>
            <button type="button" class="ghost" id="cadRefreshBtn">Refresh</button>
          </div>
          <p class="muted" id="cadHint"></p>
          <p class="muted">Paths and enable live under Preferences → CAD.</p>
        </section>

        <section class="systems-panel setting" id="sys-status" data-panel="status" hidden>
          <label>Status</label>
          <div class="status-models">
            <div><span class="muted">Chat</span> <strong>${escapeHtml(h.chat_model || "—")}</strong></div>
            <div><span class="muted">Vision</span> <strong>${escapeHtml(h.vision_model || "—")}</strong></div>
            <div><span class="muted">Embed</span> <strong>${escapeHtml(h.embed_model || "—")}</strong></div>
          </div>
          ${opsSummaryHtml(ops)}
        </section>
      </div>`;
    bindSystemsNav();
    bindPrefsGroupNav();
    bindOwnerProfile();
    bindVoiceControls();
    syncSpeakToggles();
    bindPrefsControls(prefs || { items: [] });
    bindPresencePanel();
    bindMorningBriefing();
    bindCameraControls();
    bindCadControls();
    $("#speakToggleSettings")?.addEventListener("change", (e) => {
      setSpeakEnabled(e.target.checked);
    });
  } catch (_) {
    $("#settingsGrid").innerHTML = `<div class="setting"><strong>Uplink lost</strong></div>`;
    const uplink = $("#uplinkStatus");
    if (uplink) uplink.textContent = "UPLINK · LOST";
  }
}

async function refreshCadStatus() {
  const line = $("#cadStatusLine");
  const hint = $("#cadHint");
  try {
    const data = await (await apiFetch("/api/cad/status")).json();
    const st = data.status || {};
    const cfg = data.settings || {};
    if (line) {
      if (st.ready_to_build) {
        line.textContent = `Ready · FreeCAD ${cfg.freecad_install || ""} · port ${st.port || 8765}`;
      } else if (!st.enabled) {
        line.textContent = "Off — enable CAD builds in Preferences below, or Detect / Setup.";
      } else {
        line.textContent = (st.blockers && st.blockers[0]) || "Not ready";
      }
    }
    if (hint) {
      hint.textContent = st.ready_to_build
        ? "Ask Friday to build a part, or use Preferences → CAD / FreeCAD to tweak paths."
        : (st.blockers || []).slice(0, 2).join(" ");
    }
    return data;
  } catch (_) {
    if (line) line.textContent = "CAD status unavailable";
    return null;
  }
}

function bindCadControls() {
  refreshCadStatus();
  $("#cadRefreshBtn")?.addEventListener("click", () => refreshCadStatus());
  $("#cadDetectBtn")?.addEventListener("click", async () => {
    const hint = $("#cadHint");
    if (hint) hint.textContent = "Detecting FreeCAD…";
    try {
      const data = await (await apiFetch("/api/cad/detect", { method: "POST" })).json();
      if (hint) {
        hint.textContent = data.ok
          ? `Found: ${(data.found || []).join(", ") || "ok"}`
          : "No FreeCAD install found under Program Files.";
      }
      await refreshCadStatus();
      // Reload prefs panel values if present
      try {
        const prefs = await (await apiFetch("/api/systems/prefs")).json();
        bindPrefsControls(prefs || { items: [] });
      } catch (_) { /* ignore */ }
    } catch (e) {
      if (hint) hint.textContent = String(e?.message || e);
    }
  });
  $("#cadSetupBtn")?.addEventListener("click", async () => {
    const hint = $("#cadHint");
    if (hint) hint.textContent = "Setting up Taiga worker (clone + venv + torch) — can take a few minutes…";
    try {
      const data = await (await apiFetch("/api/cad/setup", { method: "POST" })).json();
      if (hint) hint.textContent = data.setup?.message || (data.ok ? "Setup done." : "Setup failed.");
      await refreshCadStatus();
    } catch (e) {
      if (hint) hint.textContent = String(e?.message || e);
    }
  });
  $("#cadLaunchBtn")?.addEventListener("click", async () => {
    const hint = $("#cadHint");
    if (hint) hint.textContent = "Launching FreeCAD…";
    try {
      const data = await (await apiFetch("/api/cad/launch", { method: "POST" })).json();
      if (hint) hint.textContent = data.launch?.message || (data.ok ? "Launched." : "Launch failed.");
      await refreshCadStatus();
    } catch (e) {
      if (hint) hint.textContent = String(e?.message || e);
    }
  });
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

async function refreshCameraDevices({ deep = false } = {}) {
  const sel = $("#cameraDeviceSelect");
  const resSel = $("#cameraResSelect");
  const hint = $("#cameraDeviceHint");
  const recBtn = $("#cameraUseRecommendedBtn");
  if (!sel) return null;
  sel.disabled = true;
  if (hint) {
    hint.textContent = deep
      ? "Scanning selected camera…"
      : "Listing cameras…";
  }
  try {
    const q = deep ? "?deep=1" : "";
    const data = await (await apiFetch(`/api/camera/devices${q}`)).json();
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
    // deep=1 opens only the currently selected device (not every virtual cam).
    await refreshCameraDevices({ deep: true });
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




