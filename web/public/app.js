const API = "";
const SPEAK_KEY = "friday.speakReplies";
const SESSION_KEY = "friday.sessionId";
const pauseMs = () => (window.FridayVoice ? FridayVoice.pauseMs() : 1100); // silence before we process speech

let sessionId = localStorage.getItem(SESSION_KEY) || null;
let mediaRecorder = null;
let audioChunks = [];
let currentAudio = null;
let voiceMode = false;
let voiceBusy = false; // processing / speaking — don't re-trigger
let recognition = null;
let pauseTimer = null;
let interimText = "";
let finalBuffer = "";
let speakWasForced = false;

const $ = (sel) => document.querySelector(sel);
const orb = $("#orb");
const statusLabel = $("#statusLabel");

function setState(state) {
  window.FridayLive && FridayLive.state(state);
  if (orb) orb.dataset.state = state;
  if (statusLabel) statusLabel.textContent = state;
  const core = $("#coreState");
  if (core) {
    const map = {
      idle: "STANDBY",
      thinking: "COMPUTE",
      listening: "AUDIO IN",
      acting: "AGENCY",
    };
    core.textContent = map[state] || String(state).toUpperCase();
  }
  const voiceEl = $("#voiceState");
  if (voiceEl) voiceEl.textContent = voiceMode ? "ENGAGED" : "READY";
}

function tickClock() {
  const now = new Date();
  const clock = $("#clockReadout");
  const date = $("#dateReadout");
  if (clock) {
    clock.textContent = now.toLocaleTimeString("en-GB", { hour12: false });
  }
  if (date) {
    date.textContent = now.toLocaleDateString("en-GB", {
      weekday: "short",
      day: "2-digit",
      month: "short",
    }).toUpperCase();
  }
}


function speakEnabled() {
  return localStorage.getItem(SPEAK_KEY) === "1" || voiceMode;
}

function setSpeakEnabled(on) {
  localStorage.setItem(SPEAK_KEY, on ? "1" : "0");
  syncSpeakToggles();
}

function syncSpeakToggles() {
  const on = localStorage.getItem(SPEAK_KEY) === "1";
  document.querySelectorAll("#speakToggle, #speakToggleSettings").forEach((el) => {
    if (el) el.checked = on || voiceMode;
  });
}

async function apiFetch(url, opts) {
  try {
    const res = await fetch(`${API}${url}`, opts);
    return res;
  } catch (err) {
    const msg = "Friday server is offline. Start it with: python main.py --server";
    pushActivity(msg, { live: false });
    throw new Error(msg);
  }
}

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $(`#view-${name}`).classList.add("active");
  if (name === "memory") refreshMemory();
  if (name === "skills") refreshSkills();
  if (name === "tasks") {
    refreshPlan();
    refreshTasks();
  }
  if (name === "settings") refreshSettings();
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

function addBubble(role, text, meta = "") {
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  el.innerHTML = `${meta ? `<div class="meta">${meta}</div>` : ""}${escapeHtml(text)}`;
  $("#messages").appendChild(el);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function clearActivity() {
  const feed = $("#activityFeed");
  if (feed) feed.innerHTML = "";
}

function pushActivity(message, { live = true, detail = "" } = {}) {
  const feed = $("#activityFeed");
  if (!feed || !message) return;
  feed.querySelectorAll(".step.live").forEach((el) => el.classList.remove("live"));
  const step = document.createElement("span");
  step.className = `step${live ? " live" : ""}`;
  step.textContent = message;
  if (detail) step.title = detail;
  feed.appendChild(step);
  while (feed.children.length > 6) feed.removeChild(feed.firstChild);
}

function setListeningLine(text, { interim = false } = {}) {
  window.FridayLive && FridayLive.user(text, interim);
  const line = $("#listeningLine");
  if (!line) return;
  if (!text) {
    line.classList.add("hidden");
    line.innerHTML = "";
    return;
  }
  line.classList.remove("hidden");
  const prefix = interim ? "Listening" : "Heard";
  line.innerHTML = `<span class="prefix">${prefix}:</span>${escapeHtml(text)}`;
  $("#input").value = text;
}

function persistSession(id) {
  sessionId = id;
  if (id) localStorage.setItem(SESSION_KEY, id);
  else localStorage.removeItem(SESSION_KEY);
}

async function ensureSession() {
  if (sessionId) {
    // Verify it still exists on the server.
    try {
      const res = await apiFetch(`/api/sessions/${sessionId}`);
      if (res.ok) return sessionId;
    } catch (_) {}
    persistSession(null);
  }
  // Resume most recent chat if available.
  try {
    const list = await (await apiFetch("/api/sessions")).json();
    if (Array.isArray(list) && list.length) {
      persistSession(list[0].id);
      return sessionId;
    }
  } catch (_) {}
  const res = await apiFetch("/api/sessions", { method: "POST" });
  const data = await res.json();
  persistSession(data.id);
  return sessionId;
}

async function restoreChat() {
  try {
    await ensureSession();
    const res = await apiFetch(`/api/sessions/${sessionId}`);
    if (!res.ok) throw new Error("session missing");
    const data = await res.json();
    const turns = data.turns || [];
    $("#messages").innerHTML = "";
    if (!turns.length) {
      addBubble(
        "assistant",
        "Systems online, boss. Comms persist across refresh. Tell me what we're doing today and I'll lock it into the mission board.",
      );
      return;
    }
    for (const t of turns) {
      addBubble(t.role === "user" ? "user" : "assistant", t.content || "", t.skill_id || "");
    }
    $("#messages").scrollTop = $("#messages").scrollHeight;
  } catch (_) {
    persistSession(null);
    addBubble(
      "assistant",
      "Systems online, boss. Comms channel open — engage the mic for voice, or transmit text.",
    );
  }
}

async function sendMessage(text, { fromVoice = false } = {}) {
  if (!text.trim() || voiceBusy) return;
  await ensureSession();
  addBubble("user", text);
  $("#input").value = "";
  setListeningLine("");
  setState("thinking");
  clearActivity();
  pushActivity(fromVoice ? "Processing speech…" : "Thinking…");
  const skillOverride = $("#skillOverride").value || null;
  const chip = $("#skillChip");
  const useVoice = fromVoice || voiceMode;

  if (useVoice) voiceBusy = true;

  // live voice: sentence-pipelined speech + spoken/shown fillers while the reply is being prepared
  const vcfg = window.FridayVoice ? FridayVoice.cfg() : { streamSpeech: false };
  const speaker = useVoice && speakEnabled() && window.FridayLive ? FridayLive.speaker({ onFirst: pauseRecognition }) : null;
  const filler = useVoice && window.FridayLive ? FridayLive.fillers(speaker) : null;
  filler && filler.start();

  const live = document.createElement("div");
  live.className = "bubble assistant";
  live.innerHTML = `<div class="meta">working…</div><span class="body"></span>`;
  const liveBody = live.querySelector(".body");
  const liveMeta = live.querySelector(".meta");
  $("#messages").appendChild(live);

  try {
    const res = await apiFetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        skill_override: skillOverride,
        voice_mode: useVoice,
      }),
    });
    if (!res.ok) throw new Error(`Chat failed (${res.status})`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalReply = null;
    let skillId = null;
    let streamed = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        let ev;
        try {
          ev = JSON.parse(part.slice(6));
        } catch {
          continue;
        }

        if (ev.type === "activity") {
          if (filler && /search|web|look|memory|recall/i.test(ev.message || "")) filler.lookup();
          pushActivity(ev.message || ev.step || "…", { detail: ev.detail || "" });
          if (ev.message) liveMeta.textContent = ev.message;
        }
        if (ev.type === "intent") {
          pushActivity(`Intent · ${ev.mode} → ${ev.skill_id}`, {
            detail: ev.reason || "",
          });
          liveMeta.textContent = `${ev.mode} · ${ev.skill_id}`;
        }
        if (ev.type === "skill_selected") {
          skillId = ev.skill_id;
          chip.textContent = `Skill · ${ev.skill_id}${ev.mode ? ` · ${ev.mode}` : ""}`;
          chip.classList.remove("hidden");
          liveMeta.textContent = `skill:${ev.skill_id}`;
          if (ev.skill_id === "computer_use") setState("acting");
        }
        if (ev.type === "status" && ev.status) setState(ev.status);
        if (ev.type === "observation") {
          const size = ev.native_size ? `${ev.native_size[0]}×${ev.native_size[1]}` : "";
          pushActivity(`Screenshot captured${size ? ` · ${size}` : ""}`);
        }
        if (ev.type === "computer_use_start") {
          filler && filler.agent();
          setState("acting");
          setAgentStopVisible(true);
          pushActivity(`Acting · ${ev.objective || "desktop task"}`);
        }
        if (ev.type === "computer_use_end") {
          setAgentStopVisible(false);
          pushActivity(`Agent finished · ${ev.status || "done"}`, { live: false });
        }
        if (ev.type === "shell_start") {
          pushActivity(`Shell ▸ ${ev.command || "…"}`);
          addBubble("assistant", `Running command:\n${ev.command || ""}`, "shell");
        }
        if (ev.type === "shell_end") {
          const out = (ev.output || "").trim();
          pushActivity(`Shell exit ${ev.exit_code}`, { live: false });
          if (out) addBubble("assistant", out.slice(0, 1200), `shell · exit ${ev.exit_code}`);
        }
        if (ev.type === "action_start" && ev.step) {
          const s = ev.step;
          pushActivity(`${s.action}${s.description ? " · " + s.description : ""}`);
        }
        if (ev.type === "focus" && ev.box) {
          pushActivity(`Focus crop · [${ev.box.join(", ")}]`);
        }
        if (ev.type === "skill_token" && ev.text) {
          streamed += ev.text;
          liveBody.textContent = streamed;
          if (speaker && vcfg.streamSpeech) { filler && filler.stop(); speaker.push(ev.text); }
          else if (window.FridayLive && FridayLive.isOpen()) FridayLive.friday(streamed);
          $("#messages").scrollTop = $("#messages").scrollHeight;
        }
        if (ev.type === "warning" && ev.message) {
          pushActivity(`⚠ ${ev.message}`, { live: false });
        }
        if (ev.type === "done") {
          finalReply = ev.reply;
          skillId = ev.skill_id || skillId;
          sessionId = ev.session_id || sessionId;
          if (sessionId) persistSession(sessionId);
          pushActivity("Done", { live: false });
        }
        if (ev.type === "error") {
          liveBody.textContent = ev.message || "Error";
          pushActivity(`Error · ${ev.message || "failed"}`, { live: false });
        }
      }
    }

    const textOut = finalReply || streamed || "(no reply)";
    liveBody.textContent = textOut;
    if (skillId) liveMeta.textContent = `skill:${skillId}`;
    filler && filler.stop();
    if (speaker && vcfg.streamSpeech && speaker.spoken() > 0) {
      speaker.finish();
      await speaker.done();
    } else if (speakEnabled() && textOut && textOut !== "(no reply)") {
      // Pause mic recognition while speaking to avoid echo loops.
      pauseRecognition();
      pushActivity("Speaking reply…");
      if (speaker) {
        speaker.push(String(textOut).slice(0, 700) + " ");
        speaker.finish();
        await speaker.done();
      } else {
        await speak(textOut);
      }
      pushActivity("Spoken", { live: false });
    }
  } catch (err) {
    liveBody.textContent = `Error: ${err.message}`;
    pushActivity(`Error · ${err.message}`, { live: false });
  } finally {
    filler && filler.stop();
    setState(voiceMode ? "listening" : "idle");
    voiceBusy = false;
    finalBuffer = "";
    interimText = "";
    if (voiceMode) resumeRecognition();
  }
}

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage($("#input").value, { fromVoice: false });
});

$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage($("#input").value, { fromVoice: false });
  }
});

$("#btnNewChat").addEventListener("click", async () => {
  try {
    const res = await apiFetch("/api/sessions", { method: "POST" });
    const data = await res.json();
    persistSession(data.id);
  } catch (_) {
    persistSession(null);
  }
  $("#messages").innerHTML = "";
  $("#skillChip").classList.add("hidden");
  clearActivity();
  addBubble("assistant", "New link established, boss. What are we working today?");
});

$("#speakToggle")?.addEventListener("change", (e) => {
  setSpeakEnabled(e.target.checked);
});

function setAgentStopVisible(on) {
  const btn = $("#btnStopAgent");
  if (!btn) return;
  btn.classList.toggle("hidden", !on);
  btn.classList.toggle("hot", !!on);
}

$("#btnStopAgent")?.addEventListener("click", async () => {
  pushActivity("Halt requested…");
  try {
    const res = await apiFetch("/api/agent/cancel", { method: "POST" });
    const data = await res.json();
    pushActivity(
      data.cancelled ? "Agent halt sent" : "No agent running",
      { live: false },
    );
  } catch (err) {
    pushActivity(`Halt failed · ${err.message}`, { live: false });
  }
  setAgentStopVisible(false);
  setState("idle");
});

function SpeechRec() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function clearPauseTimer() {
  if (pauseTimer) {
    clearTimeout(pauseTimer);
    pauseTimer = null;
  }
}

function scheduleProcess() {
  clearPauseTimer();
  pauseTimer = setTimeout(() => {
    const text = (finalBuffer || interimText || "").trim();
    if (!text || voiceBusy) return;
    pushActivity("Pause detected · processing…");
    setListeningLine(text, { interim: false });
    sendMessage(text, { fromVoice: true });
  }, pauseMs());
}

function pauseRecognition() {
  clearPauseTimer();
  try {
    recognition?.stop();
  } catch (_) {}
}

function resumeRecognition() {
  if (!voiceMode || !recognition) return;
  try {
    recognition.start();
  } catch (_) {
    // Already started is fine.
  }
}

function stopVoiceMode() {
  voiceMode = false;
  clearPauseTimer();
  pauseRecognition();
  recognition = null;
  $("#btnMic").classList.remove("hot");
  $("#composer").classList.remove("voice-on");
  window.FridayLive && FridayLive.close();
  stopSpeech();
  setListeningLine("");
  setState("idle");
  pushActivity("Voice mode off", { live: false });
  if (speakWasForced) {
    setSpeakEnabled(false);
    speakWasForced = false;
  }
  syncSpeakToggles();
}

function startVoiceMode() {
  const Rec = SpeechRec();
  if (!Rec) {
    // Fallback: classic click-to-record MediaRecorder path
    startFallbackRecord();
    return;
  }

  voiceMode = true;
  $("#btnMic").classList.add("hot");
  $("#composer").classList.add("voice-on");
  window.FridayLive && FridayLive.open();
  setState("listening");
  pushActivity("Voice on · speak, pause to send");
  setListeningLine("…", { interim: true });

  // Auto-enable speak for voice conversations
  if (localStorage.getItem(SPEAK_KEY) !== "1") {
    speakWasForced = true;
    setSpeakEnabled(true);
  }

  recognition = new Rec();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onresult = (event) => {
    if (voiceBusy) return;
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const piece = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalBuffer = `${finalBuffer} ${piece}`.trim();
      } else {
        interim += piece;
      }
    }
    interimText = interim;
    const shown = `${finalBuffer} ${interim}`.trim();
    if (shown) {
      setListeningLine(shown, { interim: !finalBuffer || !!interim });
      setState("listening");
      scheduleProcess();
    }
  };

  recognition.onerror = (event) => {
    if (event.error === "aborted" || event.error === "no-speech") return;
    if (event.error === "not-allowed") {
      addBubble("assistant", "Mic permission blocked. Allow microphone access for this site.");
      stopVoiceMode();
      return;
    }
    pushActivity(`Mic · ${event.error}`, { live: false });
  };

  recognition.onend = () => {
    // Chrome stops after silence — restart while voice mode is on.
    if (voiceMode && !voiceBusy) {
      try { recognition.start(); } catch (_) {}
    }
  };

  try {
    recognition.start();
  } catch (err) {
    addBubble("assistant", `Mic error: ${err.message}`);
    stopVoiceMode();
  }
}

async function startFallbackRecord() {
  // One-shot record for browsers without SpeechRecognition
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "";
    mediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      setState("idle");
      $("#btnMic").classList.remove("hot");
      pushActivity("Transcribing…");
      setListeningLine("Transcribing…", { interim: true });
      const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
      const fd = new FormData();
      fd.append("file", blob, "speech.webm");
      try {
        const res = await apiFetch("/api/voice/transcribe", { method: "POST", body: fd });
        stream.getTracks().forEach((t) => t.stop());
        if (!res.ok) {
          let detail = "Voice transcription failed.";
          try {
            const err = await res.json();
            detail = err.detail || detail;
          } catch (_) {}
          addBubble("assistant", detail);
          setListeningLine("");
          return;
        }
        const data = await res.json();
        if (data.text) {
          setListeningLine(data.text, { interim: false });
          sendMessage(data.text, { fromVoice: true });
        } else {
          addBubble("assistant", "I heard silence — try speaking closer to the mic.");
          setListeningLine("");
        }
      } catch (err) {
        stream.getTracks().forEach((t) => t.stop());
        addBubble("assistant", err.message);
        setListeningLine("");
      }
    };
    mediaRecorder.start();
    setState("listening");
    $("#btnMic").classList.add("hot");
    setListeningLine("Recording… click mic again when done", { interim: true });
    pushActivity("Recording… click mic to finish");
  } catch (err) {
    addBubble("assistant", `Mic error: ${err.message}`);
  }
}

$("#btnMic").addEventListener("click", () => {
  if (voiceMode) {
    stopVoiceMode();
    return;
  }
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }
  startVoiceMode();
});

async function refreshSkills() {
  try {
    const skills = await (await apiFetch("/api/skills")).json();
    const list = $("#skillList");
    const override = $("#skillOverride");
    const taskSkill = $("#taskSkill");
    override.innerHTML = `<option value="">Auto skill</option>`;
    taskSkill.innerHTML = "";
    list.innerHTML = "";
    for (const s of skills) {
      override.innerHTML += `<option value="${s.id}">${s.name}</option>`;
      taskSkill.innerHTML += `<option value="${s.id}">${s.name}</option>`;
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <div>
          <h3>${escapeHtml(s.name)} <span class="muted">${s.id}</span></h3>
          <p>${escapeHtml(s.description)}</p>
          <p class="muted">triggers: ${(s.triggers || []).join(", ") || "—"}</p>
        </div>
        <div class="actions">
          <div class="toggle ${s.enabled ? "on" : ""}" data-id="${s.id}" title="Enable"></div>
        </div>`;
      list.appendChild(card);
    }
    list.querySelectorAll(".toggle").forEach((t) => {
      t.addEventListener("click", async () => {
        const enabled = !t.classList.contains("on");
        await apiFetch(`/api/skills/${t.dataset.id}/enabled?enabled=${enabled}`, { method: "POST" });
        refreshSkills();
      });
    });
  } catch (_) {}
}

async function refreshMemory() {
  try {
    const stats = await (await apiFetch("/api/memory/stats")).json();
    $("#memStats").textContent = Object.entries(stats).map(([k, v]) => `${k}:${v}`).join(" · ");
    const items = await (await apiFetch("/api/memory?limit=50")).json();
    renderMemCards(items);
  } catch (_) {
    $("#memStats").textContent = "server offline";
  }
}

function renderMemCards(items) {
  const list = $("#memList");
  list.innerHTML = "";
  for (const m of items) {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div><p>${escapeHtml(m.text)}</p><p class="muted">${m.id.slice(0, 8)} · score ${(m.score || 0).toFixed(2)}</p></div>
      <div class="actions"><button class="ghost" data-del="${m.id}">Delete</button></div>`;
    list.appendChild(card);
  }
  list.querySelectorAll("[data-del]").forEach((b) => {
    b.addEventListener("click", async () => {
      await apiFetch(`/api/memory/${b.dataset.del}`, { method: "DELETE" });
      refreshMemory();
    });
  });
}

$("#btnMemSearch").addEventListener("click", async () => {
  const q = $("#memSearch").value;
  try {
    const items = await (await apiFetch(`/api/memory/search?q=${encodeURIComponent(q)}`)).json();
    renderMemCards(items);
  } catch (_) {}
});

$("#memAddForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#memText").value.trim();
  if (!text) return;
  await apiFetch("/api/memory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  $("#memText").value = "";
  refreshMemory();
});

async function refreshPlan() {
  try {
    const data = await (await apiFetch("/api/plan/today")).json();
    const dateEl = $("#planDate");
    if (dateEl) dateEl.textContent = data.date || "";
    const list = $("#planList");
    if (!list) return;
    list.innerHTML = "";
    const items = data.items || [];
    if (!items.length) {
      list.innerHTML = `<div class="muted">No agenda yet — add what we're doing today.</div>`;
      return;
    }
    for (const it of items) {
      const row = document.createElement("div");
      row.className = `plan-item${it.done ? " done" : ""}`;
      row.innerHTML = `
        <div class="plan-check ${it.done ? "on" : ""}" data-id="${it.id}" title="Toggle done">${it.done ? "✓" : ""}</div>
        <div class="plan-text">${escapeHtml(it.text || "")}${it.note ? `<div class="muted">${escapeHtml(it.note)}</div>` : ""}</div>
        <button type="button" data-del="${it.id}">DEL</button>`;
      list.appendChild(row);
    }
    list.querySelectorAll(".plan-check").forEach((el) => {
      el.addEventListener("click", async () => {
        const done = !el.classList.contains("on");
        await apiFetch(`/api/plan/today/${el.dataset.id}/done?done=${done}`, { method: "POST" });
        refreshPlan();
      });
    });
    list.querySelectorAll("[data-del]").forEach((el) => {
      el.addEventListener("click", async () => {
        await apiFetch(`/api/plan/today/${el.dataset.del}`, { method: "DELETE" });
        refreshPlan();
      });
    });
  } catch (_) {
    const list = $("#planList");
    if (list) list.innerHTML = `<div class="muted">Plan offline</div>`;
  }
}

$("#planForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#planText")?.value.trim();
  if (!text) return;
  await apiFetch("/api/plan/today", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  $("#planText").value = "";
  refreshPlan();
});

async function refreshTasks() {
  try {
    const jobs = await (await apiFetch("/api/tasks")).json();
    const list = $("#taskList");
    list.innerHTML = "";
    for (const j of jobs) {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <div>
          <h3>${escapeHtml(j.title || "Task")}</h3>
          <p>${escapeHtml(j.prompt || "")}</p>
          <p class="muted">${j.status} · ${j.skill_id} · ${j.id.slice(0, 8)}</p>
        </div>
        <div class="actions">
          <button class="ghost" data-run="${j.id}">Run</button>
          <button class="ghost" data-cancel="${j.id}">Cancel</button>
        </div>`;
      list.appendChild(card);
    }
    list.querySelectorAll("[data-run]").forEach((b) =>
      b.addEventListener("click", async () => {
        await apiFetch(`/api/tasks/${b.dataset.run}/run`, { method: "POST" });
        refreshTasks();
      })
    );
    list.querySelectorAll("[data-cancel]").forEach((b) =>
      b.addEventListener("click", async () => {
        await apiFetch(`/api/tasks/${b.dataset.cancel}`, { method: "DELETE" });
        refreshTasks();
      })
    );
  } catch (_) {}
}

$("#taskForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    title: $("#taskTitle").value || "Friday task",
    prompt: $("#taskPrompt").value,
    skill_id: $("#taskSkill").value || "chat",
    delay_seconds: $("#taskDelay").value ? Number($("#taskDelay").value) : null,
  };
  await apiFetch("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  $("#taskPrompt").value = "";
  refreshTasks();
});

function bindVoiceControls() {
  document.querySelectorAll("#settingsGrid [data-voice-style]").forEach((b) =>
    b.addEventListener("click", () => window.FridayVoice && FridayVoice.setStyle(b.dataset.voiceStyle)));
  document.querySelectorAll("#settingsGrid input[data-voice-speed]").forEach((i) =>
    i.addEventListener("input", () => window.FridayVoice && FridayVoice.setSpeed(i.value)));
  window.FridayLive && FridayLive.syncControls();
}

async function refreshSettings() {
  try {
    const h = await (await apiFetch("/api/health")).json();
    $("#modelPill").textContent = h.chat_model || h.vision_model || "local";
    const uplink = $("#uplinkStatus");
    if (uplink) uplink.textContent = "UPLINK · SECURE";
    $("#settingsGrid").innerHTML = `
      <div class="setting"><label>Vision model</label><strong>${escapeHtml(h.vision_model || "—")}</strong></div>
      <div class="setting"><label>Chat model</label><strong>${escapeHtml(h.chat_model || "—")}</strong></div>
      <div class="setting"><label>Embed model</label><strong>${escapeHtml(h.embed_model || "—")}</strong></div>
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
        <p class="muted" style="margin:8px 0 0">Realtime answers sooner: shorter pause, speaks sentence by sentence while the reply is written. Relaxed waits longer before sending and speaks after the reply.</p>
        <label style="margin-top:12px">Speech speed <strong data-voice-speed-label></strong></label>
        <input type="range" min="0.8" max="1.4" step="0.05" data-voice-speed style="width:100%" />
      </div>`;
    bindVoiceControls();
    syncSpeakToggles();
    $("#speakToggleSettings")?.addEventListener("change", (e) => {
      setSpeakEnabled(e.target.checked);
    });
  } catch (_) {
    $("#settingsGrid").innerHTML = `<div class="setting"><strong>Uplink lost — server offline</strong></div>`;
    const uplink = $("#uplinkStatus");
    if (uplink) uplink.textContent = "UPLINK · LOST";
  }
}

function speakBrowser(text) {
  return new Promise((resolve) => {
    if (!window.speechSynthesis) {
      resolve(false);
      return;
    }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.slice(0, 800));
    u.rate = 0.92 * (window.FridayVoice ? FridayVoice.speed() : 1);
    u.onend = () => resolve(true);
    u.onerror = () => resolve(false);
    window.speechSynthesis.speak(u);
  });
}

// Fetch synthesized audio for one piece of text; resolves to an object URL, or null when the server TTS is unavailable.
async function ttsFetchUrl(text) {
  const clean = String(text || "").replace(/\*\*/g, "").trim();
  if (!clean) return null;
  try {
    const res = await apiFetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean.slice(0, 500) }),
    });
    if (!res.ok) throw new Error(`TTS HTTP ${res.status}`);
    const blob = await res.blob();
    if ((blob.type || "").startsWith("audio") || blob.size > 1000) return URL.createObjectURL(blob);
  } catch (err) {
    console.warn("[Friday] server TTS failed, using browser voice:", err);
  }
  return null;
}

function playUrl(url) {
  return new Promise((resolve) => {
    const audio = new Audio(url);
    currentAudio = audio;
    audio.preservesPitch = true;
    audio.playbackRate = window.FridayVoice ? FridayVoice.speed() : 1;
    window.FridayLive && FridayLive.attachAudio(audio);
    const fin = () => {
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.onended = fin;
    audio.onerror = fin;
    audio._cancel = fin;
    audio.play().catch(fin);
  });
}

function stopSpeech() {
  try {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio._cancel && currentAudio._cancel();
    }
  } catch (_) {}
  currentAudio = null;
  try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (_) {}
}

async function speak(text) {
  const clean = String(text || "").replace(/\*\*/g, "").trim();
  if (!clean) return;
  stopSpeech();
  window.FridayLive && FridayLive.state("speaking");
  const url = await ttsFetchUrl(clean);
  if (url) {
    await playUrl(url);
    return;
  }
  window.FridayLive && FridayLive.synthSpeaking(true);
  const ok = await speakBrowser(clean);
  if (!ok) console.warn("[Friday] browser TTS unavailable");
}

(async function init() {
  syncSpeakToggles();
  tickClock();
  setInterval(tickClock, 1000);
  await refreshSkills();
  await refreshSettings();
  await restoreChat();
})();
