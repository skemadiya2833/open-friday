const API = "";
const SPEAK_KEY = "friday.speakReplies";
const SESSION_KEY = "friday.sessionId";
const pauseMs = () => (window.FridayVoice ? FridayVoice.pauseMs() : 1200); // legacy fallback if turn.js missing

let turnDetector = null;
let lastHoldReason = "";

function ensureTurnDetector() {
  if (turnDetector || !window.FridayTurn) return turnDetector;
  turnDetector = new FridayTurn.TurnDetector({
    getEagerness: () => (window.FridayVoice && FridayVoice.eagerness ? FridayVoice.eagerness() : "medium"),
    onHold: (info) => {
      if (!voiceMode || voiceBusy) return;
      // Stay on listening — never flash thinking / toast while we are still deciding the turn.
      if (uiState !== "listening") setState("listening");
      lastHoldReason = info.reason || "";
    },
    onCommit: (info) => {
      lastHoldReason = "";
      const text = (info.text || "").trim();
      if (!text || voiceBusy) return;
      // Lock the turn immediately so a late interim cannot double-commit.
      finalBuffer = "";
      interimText = "";
      if (turnDetector) turnDetector.reset();
      setListeningLine(text, { interim: false });
      sendMessage(text, { fromVoice: true });
    },
  });
  return turnDetector;
}

let sessionId = localStorage.getItem(SESSION_KEY) || null;
let mediaRecorder = null;
let audioChunks = [];
let currentAudio = null;
let voiceMode = false;
let voiceBusy = false; // processing / speaking — don't re-trigger
let micSuspended = false; // Hold mode: recognition stopped so speakers can't re-enter
let listenCooldownUntil = 0;
let uiState = "idle";
let recognition = null;
let pauseTimer = null;
let interimText = "";
let finalBuffer = "";
let speakWasForced = false;
let turnEpoch = 0;
let chatAbort = null;
let fridayReply = "";
let releaseMicTimer = null;

const $ = (sel) => document.querySelector(sel);
const orb = $("#orb");
const statusLabel = $("#statusLabel");

function voiceHoldMode() {
  return !(window.FridayVoice && FridayVoice.duplex && FridayVoice.duplex() === "interrupt");
}

/** Show / hide global "CAMERA LIVE" while Friday is looking through the webcam. */
function setCameraLooking(on, phase) {
  const hud = $("#cameraHudPill");
  const voice = $("#cameraVoiceBadge");
  const settings = $("#cameraLivePill");
  const show = !!on;
  if (hud) {
    hud.classList.toggle("hidden", !show);
    if (show && phase === "describe") hud.textContent = "CAMERA · LOOKING";
    else if (show) hud.textContent = "CAMERA LIVE";
  }
  if (voice) {
    voice.classList.toggle("hidden", !show);
    if (show && phase === "describe") voice.textContent = "CAMERA · LOOKING";
    else if (show) voice.textContent = "CAMERA LIVE";
  }
  if (settings) settings.style.display = show ? "inline-flex" : "none";
  document.body.classList.toggle("camera-looking", show);
}

function setState(state, { force = false } = {}) {
  // During a turn, never flash back to listening/idle (yellow↔blue flicker).
  if (!force && voiceMode && voiceBusy && (state === "listening" || state === "idle")) return;
  if (!force && state === uiState) return;
  // Once speaking, stay green until the turn ends (ignore stray "thinking" from stream status).
  if (!force && uiState === "speaking" && state === "thinking") return;
  const prev = uiState;
  uiState = state;
  window.FridayLive && FridayLive.state(state);
  if (orb) orb.dataset.state = state;
  if (statusLabel) statusLabel.textContent = String(state || "standby").toUpperCase();
  syncZenChips();
  const core = $("#coreState");
  if (core) {
    const map = {
      idle: "STANDBY",
      thinking: "COMPUTE",
      listening: "AUDIO IN",
      speaking: "AUDIO OUT",
      acting: "AGENCY",
    };
    core.textContent = map[state] || String(state).toUpperCase();
  }
  const voiceEl = $("#voiceState");
  if (voiceEl) voiceEl.textContent = voiceMode ? "ENGAGED" : "READY";
  document.dispatchEvent(new CustomEvent("friday:state", { detail: { state, prev } }));
}

function suspendMic() {
  micSuspended = true;
  clearPauseTimer();
  if (releaseMicTimer) {
    clearTimeout(releaseMicTimer);
    releaseMicTimer = null;
  }
  finalBuffer = "";
  interimText = "";
  setListeningLine("");
  try { recognition?.stop(); } catch (_) {}
}

/** Chrome SpeechRecognition often ends after silence/errors; restart with retries. */
function kickRecognition(retries = 6) {
  if (!voiceMode || !recognition || micSuspended) return;
  if (voiceBusy && voiceHoldMode()) return;
  try {
    recognition.start();
  } catch (_) {
    if (retries <= 0) return;
    setTimeout(() => kickRecognition(retries - 1), 140);
  }
}

function armMicNow() {
  micSuspended = false;
  listenCooldownUntil = 0;
  finalBuffer = "";
  interimText = "";
  setState("listening", { force: true });
  // Chrome often needs a beat after stop() before start() sticks.
  kickRecognition(6);
  pushActivity("Listening", { live: false });
}

function releaseMicAfter(cooldownMs) {
  micSuspended = true; // stay deaf through cool-down
  listenCooldownUntil = Date.now() + Math.max(0, cooldownMs);
  if (releaseMicTimer) clearTimeout(releaseMicTimer);
  releaseMicTimer = setTimeout(() => {
    releaseMicTimer = null;
    if (!voiceMode) return;
    // Still in a turn — retry shortly instead of leaving the mic dead forever.
    if (voiceBusy) {
      releaseMicAfter(300);
      return;
    }
    armMicNow();
  }, Math.max(0, cooldownMs));
}

function tickClock() {
  const now = new Date();
  const clock = $("#clockReadout");
  const date = $("#dateReadout");
  const timeStr = now.toLocaleTimeString("en-US", {
    hour12: true,
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
  if (clock) clock.textContent = timeStr;
  if (date) {
    date.textContent = now.toLocaleDateString("en-US", {
      weekday: "short",
      day: "numeric",
      month: "short",
    }).toUpperCase();
  }
  const zenTime = $("#zenChipTime");
  if (zenTime) zenTime.textContent = timeStr.replace(/:\d{2}(?=\s)/, "");
}

const ZEN_KEY = "friday_zen_mode";

function zenEnabled() {
  return localStorage.getItem(ZEN_KEY) === "1";
}

function setZenMode(on) {
  localStorage.setItem(ZEN_KEY, on ? "1" : "0");
  document.body.classList.toggle("zen-mode", !!on);
  const btn = $("#btnZen");
  if (btn) {
    btn.classList.toggle("on", !!on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }
  if (on) showView("chat");
}

function syncZenChips() {
  const st = $("#zenChipStatus");
  const link = $("#zenChipLink");
  if (st) st.textContent = (uiState || "standby").toUpperCase();
  if (link) {
    const up = ($("#uplinkStatus")?.textContent || "").includes("LOST") ? "LOST" : "LOCAL";
    link.textContent = up;
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

async function apiFetch(url, opts = {}) {
  try {
    const res = await fetch(`${API}${url}`, {
      credentials: "same-origin",
      ...opts,
      headers: { ...(opts.headers || {}) },
    });
    if (res.status === 401 && !String(url).startsWith("/api/auth/")) {
      showAuthGate("Sign in required — API returned 401. Register this PC or Sign in on the Devices page.");
    }
    return res;
  } catch (err) {
    const msg = "Friday server is offline. Start it with: python main.py --server";
    pushActivity(msg, { live: false });
    throw new Error(msg);
  }
}

function showAuthGate(message) {
  let gate = document.getElementById("authGate");
  if (!gate) {
    gate = document.createElement("div");
    gate.id = "authGate";
    gate.className = "auth-gate";
    gate.innerHTML = `
      <div class="auth-gate-card">
        <h2>Authentication required</h2>
        <p class="muted" id="authGateMsg"></p>
        <p class="muted">Open <strong>http://localhost:${location.port || "8787"}/</strong> (not 127.0.0.1) so the session cookie sticks.</p>
        <div class="top-actions" style="margin-top:12px;gap:8px;display:flex;flex-wrap:wrap">
          <button type="button" id="authGateBootstrap">Register this PC</button>
          <button type="button" class="ghost" id="authGateLogin">Sign in</button>
          <button type="button" class="ghost" id="authGateDevices">Open Devices</button>
        </div>
      </div>`;
    document.body.appendChild(gate);
    gate.querySelector("#authGateBootstrap")?.addEventListener("click", () => {
      window.FridayAuth?.bootstrapPc?.();
    });
    gate.querySelector("#authGateLogin")?.addEventListener("click", () => {
      window.FridayAuth?.login?.();
    });
    gate.querySelector("#authGateDevices")?.addEventListener("click", () => {
      showView("devices");
      gate.classList.add("hidden");
    });
  }
  const msg = gate.querySelector("#authGateMsg");
  if (msg) msg.textContent = message || "";
  gate.classList.remove("hidden");
}

function hideAuthGate() {
  document.getElementById("authGate")?.classList.add("hidden");
}
window.hideAuthGate = hideAuthGate;
window.showAuthGate = showAuthGate;

function isLocalBrowserHost() {
  const h = (location.hostname || "").toLowerCase();
  return h === "localhost" || h === "127.0.0.1" || h === "[::1]" || h === "::1";
}

async function ensureAuthSession() {
  // This PC's browser is always trusted — never show an auth wall here.
  if (isLocalBrowserHost()) {
    hideAuthGate();
    return true;
  }
  try {
    const st = await (await fetch("/api/auth/status", { credentials: "same-origin" })).json();
    if (st.authenticated || st.loopback) {
      hideAuthGate();
      return true;
    }
    if (st.mode === "lan") {
      showAuthGate(
        "Scan the QR on the PC (Devices → Show QR), or use advanced code pairing.",
      );
      return false;
    }
    if (st.mode === "remote") {
      showAuthGate(
        st.device_count
          ? "Sign in with your passkey, or pair a new device from Devices."
          : "Pair this device from Devices (PC must approve).",
      );
      return false;
    }
    hideAuthGate();
    return true;
  } catch (_) {
    return true;
  }
}

async function refreshCalendar() {
  const status = $("#calendarStatus");
  const list = $("#calendarAgenda");
  if (!status || !list) return;
  try {
    const res = await apiFetch("/api/calendar/agenda?range=today");
    if (!res.ok) {
      const msg = res.status === 400
        ? "Calendar not configured — add iCal URL in docs/design/calendar.md."
        : "Could not load agenda.";
      status.textContent = msg;
      list.replaceChildren();
      return;
    }
    const data = await res.json();
    const events = data.events || data.items || [];
    status.textContent = events.length
      ? `${events.length} event(s) today`
      : "No events today (or calendar empty).";
    list.replaceChildren();
    events.slice(0, 12).forEach((ev) => {
      const li = document.createElement("li");
      const when = document.createElement("span");
      when.className = "cal-time";
      const start = ev.start || ev.dtstart || ev.when || "";
      if (typeof start === "string") {
        try {
          when.textContent = new Date(start).toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit",
            hour12: true,
          });
        } catch (_) {
          when.textContent = start.slice(11, 16) || start.slice(0, 16);
        }
      } else {
        when.textContent = "—";
      }
      const title = document.createElement("span");
      title.textContent = ev.summary || ev.title || "(untitled)";
      li.appendChild(when);
      li.appendChild(title);
      list.appendChild(li);
    });
    if (window.FridayMotion && FridayMotion.restagger) FridayMotion.restagger(list);
  } catch (_) {
    status.textContent = "Calendar offline.";
    list.replaceChildren();
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
    refreshCalendar();
  }
  if (name === "settings") refreshSettings();
  if (name === "reports" && window.FridayReports) FridayReports.refreshHistory();
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

function addBubble(role, text, meta = "") {
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  const rid = `r-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  el.dataset.replyId = rid;
  let feedback = "";
  if (role === "assistant") {
    feedback = `<div class="feedback" data-reply-id="${rid}">
      <button type="button" class="fb-up" title="Thumbs up" aria-label="Thumbs up">▲</button>
      <button type="button" class="fb-down" title="Thumbs down" aria-label="Thumbs down">▼</button>
    </div>`;
  }
  el.innerHTML = `${meta ? `<div class="meta">${meta}</div>` : ""}<div class="body">${escapeHtml(text)}</div>${feedback}`;
  $("#messages").appendChild(el);
  el.querySelector(".fb-up")?.addEventListener("click", () => sendFeedback(el, "up"));
  el.querySelector(".fb-down")?.addEventListener("click", () => sendFeedback(el, "down"));
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

async function sendFeedback(bubble, vote) {
  const text = bubble.querySelector(".body")?.textContent || "";
  const replyId = bubble.dataset.replyId || "";
  const paras = text.split(/\n\n+/);
  const kind = paras.length >= 2 && paras[paras.length - 1].split(/\s+/).length <= 20 ? "quip" : "reply";
  try {
    await apiFetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vote, kind, text: kind === "quip" ? paras[paras.length - 1] : text.slice(0, 400), reply_id: replyId }),
    });
    bubble.querySelector(".feedback")?.classList.add(vote === "up" ? "voted-up" : "voted-down");
  } catch (err) {
    console.warn("[Friday] feedback failed", err);
  }
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

/** Pipeline chatter that makes voice mode feel broken — keep off the live HUD. */
function isVoiceNoise(message) {
  return /^(Processing speech|Thinking|Voice mode|Figuring out|Intent ·|Mode ·|Turn ready|Still listening|Go on —|Chatting|Done|Spoken|Speaking reply|Voice on|Voice mode off|Pause detected|Listening|Scheduling|Researching|Working with files|Checking memory|Running |Controlling the desktop)\b/i.test(
    String(message || "").trim(),
  );
}

/** Live HUD may show look/act/errors only — never skill-run labels like Scheduling… */
function isLiveHudWorthy(message) {
  const m = String(message || "").trim();
  if (!m || isVoiceNoise(m)) return false;
  // Skip long "Acting · create a dashboard…" noise; desktop agent still surfaces Agent/Shell.
  if (/^Acting\b/i.test(m)) return false;
  return /^(Looking|Webcam|Camera|Agent |Shell |⚠|Error|Opened |Desktop agent)/i.test(m);
}

function pushActivity(message, { live = true, detail = "" } = {}) {
  const feed = $("#activityFeed");
  if (!feed || !message) return;
  const voiceOpen = window.FridayLive && FridayLive.isOpen && FridayLive.isOpen();
  // During live voice, don't dump classify/intent chips into the desktop feed either.
  if (voiceOpen && isVoiceNoise(message)) return;
  feed.querySelectorAll(".step.live").forEach((el) => el.classList.remove("live"));
  const step = document.createElement("span");
  step.className = `step${live ? " live" : ""}`;
  step.textContent = message;
  if (detail) step.title = detail;
  feed.appendChild(step);
  while (feed.children.length > 6) feed.removeChild(feed.firstChild);
  if (voiceOpen && isLiveHudWorthy(message)) {
    FridayLive.activity(message, { live });
  }
}

function setListeningLine(text, { interim = false } = {}) {
  window.FridayLive && FridayLive.user(text, interim);
  if (text && text !== "…") window.FridayLive && FridayLive.nudge(interim ? 0.4 : 0.7);
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

function normSpeech(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
}

function looksLikeFridayPrompt(heard) {
  return /when should i remind|say something like|still waiting on a time|sure boss when/i.test(
    String(heard || ""),
  );
}

function looksLikeEcho(heard) {
  const a = normSpeech(heard);
  if (!a) return true;
  if (looksLikeFridayPrompt(a)) return true;
  // Short user replies ("yes", "ok", "boss") often appear inside Friday's last line —
  // only treat as echo when the heard phrase is substantial.
  if (a.length < 12 && a.split(" ").filter(Boolean).length < 3) return false;
  const trail = (window.FridayLive && FridayLive._spokenTrail) || [];
  const refs = [
    window.FridayLive && FridayLive.lastSpoken && FridayLive.lastSpoken(),
    fridayReply,
    ...trail,
  ];
  for (const r of refs) {
    const b = normSpeech(r);
    if (!b || b.length < 12) continue;
    if (b.includes(a) && a.length >= 16) return true;
    if (a.includes(b.slice(0, Math.min(48, b.length))) && b.length >= 24) return true;
    const aw = a.split(" ").filter((w) => w.length > 2);
    const bw = new Set(b.split(" ").filter((w) => w.length > 2));
    if (aw.length < 3) continue;
    let n = 0;
    for (const w of aw) if (bw.has(w)) n++;
    if (n / aw.length >= 0.75) return true;
  }
  return false;
}

function interruptTurn() {
  turnEpoch += 1;
  try { chatAbort && chatAbort.abort(); } catch (_) {}
  window.FridayLive && FridayLive.interrupt();
  stopSpeech();
  voiceBusy = false;
  micSuspended = false;
  listenCooldownUntil = 0;
  if (releaseMicTimer) {
    clearTimeout(releaseMicTimer);
    releaseMicTimer = null;
  }
  finalBuffer = "";
  interimText = "";
  setState(voiceMode ? "listening" : "idle", { force: true });
  if (voiceMode) resumeRecognition();
  pushActivity("Interrupted · listening", { live: false });
}

window.onFridayLiveInterrupt = () => {
  if (voiceBusy || voiceMode) interruptTurn();
};

/** Voice pace commands — say "speak slower / faster / normally" instead of a slider. */
function handleVoicePaceCommand(text) {
  const t = String(text || "").trim().toLowerCase();
  if (!window.FridayVoice || !FridayVoice.setPace) return null;
  let pace = null;
  if (/\b(speak|talk|read)\s+(slower|more slowly)\b|\bslow\s+down\b|\bslower\b/.test(t) && t.split(/\s+/).length <= 8) {
    pace = "slow";
  } else if (/\b(speak|talk|read)\s+(faster|quicker|more quickly)\b|\bspeed\s+up\b|\bfaster\b/.test(t) && t.split(/\s+/).length <= 8) {
    pace = "fast";
  } else if (/\b(speak|talk)\s+(normally|normal|natural)\b|\bnormal\s+speed\b|\breset\s+(speech|voice)\s+speed\b/.test(t)) {
    pace = "normal";
  }
  if (!pace) return null;
  FridayVoice.setPace(pace);
  const label = pace === "slow" ? "slower" : pace === "fast" ? "faster" : "normal";
  return `Got it — I'll speak at a ${label} pace.`;
}

async function sendMessage(text, { fromVoice = false } = {}) {
  if (!text.trim() || voiceBusy) return;
  const paceReply = handleVoicePaceCommand(text);
  if (paceReply) {
    addBubble("user", text);
    $("#input").value = "";
    setListeningLine("");
    addBubble("assistant", paceReply);
    if (fromVoice || voiceMode) {
      voiceBusy = true;
      if (voiceHoldMode()) suspendMic();
      setState("speaking", { force: true });
      try {
        await speak(paceReply);
      } finally {
        voiceBusy = false;
        if (voiceMode) releaseMicAfter(750);
        else setState("idle", { force: true });
      }
    }
    return;
  }
  await ensureSession();
  addBubble("user", text);
  $("#input").value = "";
  setListeningLine("");
  clearActivity();
  if (window.FridayLive && FridayLive.isOpen && FridayLive.isOpen()) {
    FridayLive.clearResult();
    FridayLive.clearHint && FridayLive.clearHint();
  }
  if (!(fromVoice || voiceMode)) pushActivity("Thinking…");
  const skillOverride = $("#skillOverride").value || null;
  const chip = $("#skillChip");
  const useVoice = fromVoice || voiceMode;
  const epoch = ++turnEpoch;
  chatAbort = new AbortController();

  if (useVoice) {
    voiceBusy = true;
    clearPauseTimer();
    if (turnDetector) turnDetector.reset();
    // Hold (default): mute mic for the whole turn so speaker audio can't re-trigger.
    if (voiceHoldMode()) suspendMic();
    setState("thinking", { force: true });
  } else {
    setState("thinking", { force: true });
  }

  // live voice: sentence-pipelined speech. Hold = mic muted; Interrupt = barge-in allowed.
  const vcfg = window.FridayVoice ? FridayVoice.cfg() : { streamSpeech: true };
  const speaker = useVoice && speakEnabled() && window.FridayLive
    ? FridayLive.speaker({ onFirst: () => setState("speaking", { force: true }) })
    : null;
  const filler = useVoice && speakEnabled() && window.FridayLive
    ? FridayLive.fillers(speaker)
    : null;
  filler && filler.start();
  let fillerCleared = false;
  const clearFillerForReply = () => {
    if (fillerCleared || !filler) return;
    fillerCleared = true;
    // Abort spoken filler immediately — never wait on it before reply TTS.
    if (typeof filler.abort === "function") filler.abort();
    else filler.stop();
  };

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
        humor: humorSetting(),
      }),
      signal: chatAbort.signal,
    });
    if (!res.ok) throw new Error(`Chat failed (${res.status})`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalReply = null;
    let skillId = null;
    let streamed = "";

    const handleStreamEvent = async (ev) => {
      if (ev.type === "activity") {
        if (filler && /search|web|look|memory|recall/i.test(ev.message || "")) filler.lookup();
        pushActivity(ev.message || ev.step || "…", { detail: ev.detail || "" });
        if (ev.message && !useVoice) liveMeta.textContent = ev.message;
      }
      if (ev.type === "intent") {
        if (!useVoice) {
          pushActivity(`Intent · ${ev.mode} → ${ev.skill_id}`, {
            detail: ev.reason || "",
          });
          liveMeta.textContent = `${ev.mode} · ${ev.skill_id}`;
        }
      }
      if (ev.type === "skill_selected") {
        skillId = ev.skill_id;
        chip.textContent = `Skill · ${ev.skill_id}${ev.mode ? ` · ${ev.mode}` : ""}`;
        chip.classList.remove("hidden");
        liveMeta.textContent = `skill:${ev.skill_id}`;
        if (ev.skill_id === "computer_use") setState("acting");
        if (ev.skill_id === "camera") {
          setCameraLooking(true, "capture");
          filler && filler.looking && filler.looking();
        }
      }
      if (ev.type === "camera") {
        setCameraLooking(!!ev.live, ev.phase || (ev.live ? "capture" : ""));
        if (ev.live) {
          pushActivity(
            ev.phase === "describe" ? "Looking through camera…" : "Webcam open…",
            { live: true },
          );
        }
      }
      if (ev.type === "status" && ev.status) {
        // Don't let stream status yank us back to listening mid-turn.
        if (!(useVoice && voiceBusy && (ev.status === "listening" || ev.status === "idle"))) {
          setState(ev.status);
        }
      }
      if (ev.type === "camera_frame" && ev.jpeg_b64) {
        const wrap = document.createElement("div");
        wrap.className = "bubble assistant camera-frame";
        wrap.innerHTML = `<div class="meta">camera</div>`;
        const img = document.createElement("img");
        img.src = `data:image/jpeg;base64,${ev.jpeg_b64}`;
        img.alt = "Webcam frame";
        img.style.cssText = "display:block;max-width:100%;max-height:280px;margin-top:8px;border:1px solid var(--line);background:#000;border-radius:4px";
        wrap.appendChild(img);
        $("#messages").appendChild(wrap);
        $("#messages").scrollTop = $("#messages").scrollHeight;
        pushActivity("Camera frame shown", { live: false });
      }
      if (ev.type === "observation") {
        if (ev.source === "camera") {
          const sz = Array.isArray(ev.size) ? `${ev.size[0]}×${ev.size[1]}` : "";
          pushActivity(`Webcam frame${sz ? ` · ${sz}` : ""}`);
        } else {
          const size = ev.native_size ? `${ev.native_size[0]}×${ev.native_size[1]}` : "";
          pushActivity(`Screenshot captured${size ? ` · ${size}` : ""}`);
        }
      }
      if (ev.type === "memory_saved") pushActivity(`Remembered · ${(ev.text || "").slice(0, 80)}`, { live: false });
      if (ev.type === "chat_cleared") {
        $("#messages").innerHTML = "";
        $("#messages").appendChild(live);
      }
      if (ev.type === "reminder_set") {
        pushActivity(`Reminder set · ${ev.title || ""} (${ev.when || ""})`, { live: false });
        refreshBell();
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
        pushActivity(`Shell ► ${ev.command || "…"}`);
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
        if (epoch !== turnEpoch) return;
        streamed += ev.text;
        fridayReply = streamed;
        liveBody.textContent = streamed;
        if (window.FridayLive && FridayLive.isOpen()) {
          FridayLive.result(streamed);
          if (!(speaker && vcfg.streamSpeech)) FridayLive.friday(streamed);
        }
        if (speaker && vcfg.streamSpeech) {
          clearFillerForReply();
          speaker.push(ev.text);
        }
        $("#messages").scrollTop = $("#messages").scrollHeight;
      }
      if (ev.type === "warning" && ev.message) {
        pushActivity(`⚠ ${ev.message}`, { live: false });
      }
      if (ev.type === "done") {
        setCameraLooking(false);
        finalReply = (ev.reply || "").trim() || finalReply;
        skillId = ev.skill_id || skillId;
        sessionId = ev.session_id || sessionId;
        if (sessionId) persistSession(sessionId);
        pushActivity("Done", { live: false });
        document.dispatchEvent(new CustomEvent("friday:task", { detail: { kind: "complete" } }));
        const openId =
          ev.open_report ||
          (ev.metadata && ev.metadata.open_report) ||
          (ev.result && ev.result.metadata && ev.result.metadata.open_report);
        if (openId && window.FridayReports) {
          FridayReports.open(openId);
        }
      }
      if (ev.type === "error") {
        setCameraLooking(false);
        liveBody.textContent = ev.message || "Error";
        pushActivity(`Error · ${ev.message || "failed"}`, { live: false });
        document.dispatchEvent(new CustomEvent("friday:task", { detail: { kind: "error" } }));
      }
    };

    const flushSseParts = async (chunk, { stream = true } = {}) => {
      buffer += decoder.decode(chunk || new Uint8Array(), { stream });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        let ev;
        try {
          ev = JSON.parse(line.slice(line.indexOf(":") + 1).trim());
        } catch {
          continue;
        }
        await handleStreamEvent(ev);
        if (epoch !== turnEpoch) return false;
      }
      return true;
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!(await flushSseParts(value, { stream: true }))) return;
    }
    // Critical: last SSE frame (usually `done`) can sit in the buffer without a trailing read.
    if (!(await flushSseParts(undefined, { stream: false }))) return;
    if (buffer.trim()) {
      // Tolerate a final event missing the blank-line terminator.
      const orphan = buffer.trim();
      buffer = "";
      if (orphan.startsWith("data:")) {
        try {
          await handleStreamEvent(JSON.parse(orphan.slice(orphan.indexOf(":") + 1).trim()));
        } catch (_) { /* ignore */ }
      }
    }

    if (epoch !== turnEpoch) return;
    const textOut = (finalReply || streamed || "").trim()
      || (useVoice ? "I didn't catch a reply — say that once more." : "No reply.");
    fridayReply = textOut;
    liveBody.textContent = textOut;
    if (window.FridayLive && FridayLive.isOpen()) {
      FridayLive.result(textOut);
      FridayLive.clearHint && FridayLive.clearHint();
    }
    if (!live.querySelector(".feedback")) {
      live.dataset.replyId = `r-${Date.now()}`;
      const fb = document.createElement("div");
      fb.className = "feedback";
      fb.innerHTML = `<button type="button" class="fb-up" title="Thumbs up" aria-label="Thumbs up">▲</button>
        <button type="button" class="fb-down" title="Thumbs down" aria-label="Thumbs down">▼</button>`;
      live.appendChild(fb);
      fb.querySelector(".fb-up")?.addEventListener("click", () => sendFeedback(live, "up"));
      fb.querySelector(".fb-down")?.addEventListener("click", () => sendFeedback(live, "down"));
    }
    if (skillId) liveMeta.textContent = `skill:${skillId}`;
    clearFillerForReply();
    if (speaker && vcfg.streamSpeech && speaker.spoken() > 0) {
      speaker.finish();
      await speaker.done();
    } else if (speakEnabled() && textOut && !/^No reply\.?$/i.test(textOut)) {
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
    if (err.name === "AbortError" || /abort/i.test(err.message || "")) {
      liveMeta.textContent = "interrupted";
      return;
    }
    liveBody.textContent = `Error: ${err.message}`;
    pushActivity(`Error · ${err.message}`, { live: false });
  } finally {
    filler && filler.stop();
    if (epoch !== turnEpoch) return;
    voiceBusy = false;
    finalBuffer = "";
    interimText = "";
    if (voiceMode) {
      // Brief echo-tail so speaker bleed doesn't re-trigger STT; keep it snappy.
      const cool = voiceHoldMode() ? 220 : 120;
      releaseMicAfter(cool);
    } else {
      setState("idle", { force: true });
    }
  }
}

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage($("#input").value, { fromVoice: false });
});
window.sendMessage = sendMessage;

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

async function clearThisChat() {
  const ok = await (window.FridayDialog
    ? FridayDialog.confirm({
        eyebrow: "COMMS",
        title: "Clear this conversation?",
        body: "Friday will forget the messages in this chat. Saved memories stay intact.",
        tone: "warn",
        confirmLabel: "Clear chat",
        cancelLabel: "Keep it",
      })
    : Promise.resolve(window.confirm("Clear this conversation?")));
  if (!ok) return;
  try {
    if (sessionId) await apiFetch(`/api/sessions/${sessionId}/clear`, { method: "POST" });
  } catch (_) {}
  $("#messages").innerHTML = "";
  $("#skillChip").classList.add("hidden");
  clearActivity();
  addBubble("assistant", "Chat cleared, boss. Fresh page.");
}
$("#btnClearChat")?.addEventListener("click", clearThisChat);
$("#btnClearChat2")?.addEventListener("click", clearThisChat);

$("#speakToggle")?.addEventListener("change", (e) => {
  setSpeakEnabled(e.target.checked);
});

function setAgentStopVisible(on) {
  const btn = $("#btnStopAgent");
  if (!btn) return;
  btn.classList.toggle("hidden", !on);
  btn.classList.toggle("hot", !!on);
  document.dispatchEvent(new CustomEvent("friday:agent", { detail: { running: !!on } }));
  window.FridayMotion && FridayMotion.setWorkload(!!on || uiState === "thinking" || uiState === "acting");
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
  if (turnDetector) turnDetector.cancel();
}

function scheduleProcess(delay) {
  // Prefer semantic + mic-energy turn detector (turn.js). delay only used for barge-in / stop words.
  const det = ensureTurnDetector();
  if (det && delay == null) {
    det.noteResult({ finalText: finalBuffer, interimText: interimText });
    return;
  }
  // Legacy / forced-delay path (interrupt stop-words, or turn.js not loaded).
  clearPauseTimer();
  const textNow = (finalBuffer || interimText || "").trim();
  const wait = Math.max(300, delay != null ? delay : pauseMs());
  pauseTimer = setTimeout(() => {
    const text = (finalBuffer || interimText || "").trim();
    if (!text || voiceBusy) return;
    if (interimText && interimText.trim()) {
      scheduleProcess();
      return;
    }
    pushActivity("Pause detected · processing…");
    setListeningLine(text, { interim: false });
    sendMessage(text, { fromVoice: true });
  }, wait);
}

function pauseRecognition() {
  clearPauseTimer();
  try {
    recognition?.stop();
  } catch (_) {}
}

function resumeRecognition() {
  kickRecognition(4);
}

function stopVoiceMode() {
  voiceMode = false;
  voiceBusy = false;
  micSuspended = false;
  listenCooldownUntil = 0;
  lastHoldReason = "";
  if (releaseMicTimer) {
    clearTimeout(releaseMicTimer);
    releaseMicTimer = null;
  }
  clearPauseTimer();
  if (turnDetector) {
    turnDetector.stopEnergyWatch();
    turnDetector.reset();
  }
  pauseRecognition();
  recognition = null;
  $("#btnMic").classList.remove("hot");
  $("#composer").classList.remove("voice-on");
  window.FridayLive && FridayLive.close();
  stopSpeech();
  setListeningLine("");
  setState("idle", { force: true });
  document.dispatchEvent(new CustomEvent("friday:voice", { detail: { on: false } }));
  pushActivity("Voice mode off", { live: false });
  if (speakWasForced) {
    setSpeakEnabled(false);
    speakWasForced = false;
  }
  syncSpeakToggles();
}

function micNeedsHttps() {
  const host = location.hostname;
  if (host === "localhost" || host === "127.0.0.1" || host === "[::1]") return false;
  return !window.isSecureContext || location.protocol !== "https:";
}

async function phoneHttpsUrl() {
  let port = 8788;
  try {
    const h = await (await apiFetch("/api/health")).json();
    if (h.tls_port) port = h.tls_port;
  } catch (_) {}
  return `https://${location.hostname}:${port}/`;
}

async function fillHttpsBanner() {
  const bar = $("#httpsBanner");
  if (!bar) return "";
  const url = await phoneHttpsUrl();
  bar.classList.remove("hidden");
  bar.replaceChildren();
  bar.append("Mic needs HTTPS. Open ");
  const a = document.createElement("a");
  a.href = url;
  a.textContent = url;
  bar.append(a);
  bar.append(" — tap Advanced, then Proceed, then Allow microphone.");
  return url;
}

async function showHttpsMicHint() {
  const url = await fillHttpsBanner();
  addBubble(
    "assistant",
    `Mic needs a secure page. Open ${url || await phoneHttpsUrl()} — tap Advanced, then Proceed, then Allow microphone.`,
  );
}

async function ensureMicPermission() {
  if (micNeedsHttps()) {
    await showHttpsMicHint();
    return false;
  }
  const md = navigator.mediaDevices;
  if (!md || !md.getUserMedia) {
    addBubble("assistant", "This browser has no microphone API. Use Chrome.");
    return false;
  }
  try {
    const stream = await md.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    return true;
  } catch (err) {
    const name = err && err.name;
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      addBubble("assistant", "Mic permission was denied. Chrome → site settings → Microphone → Allow.");
    } else if (name === "NotFoundError") {
      addBubble("assistant", "No microphone found on this device.");
    } else {
      addBubble("assistant", `Mic error: ${(err && err.message) || name || "unavailable"}`);
    }
    return false;
  }
}

async function startVoiceMode() {
  const allowed = await ensureMicPermission();
  if (!allowed) return;
  const Rec = SpeechRec();
  if (!Rec) {
    // Fallback: classic click-to-record MediaRecorder path
    startFallbackRecord();
    return;
  }

  voiceMode = true;
  voiceBusy = false;
  micSuspended = false;
  listenCooldownUntil = 0;
  if (releaseMicTimer) {
    clearTimeout(releaseMicTimer);
    releaseMicTimer = null;
  }
  finalBuffer = "";
  interimText = "";
  $("#btnMic").classList.add("hot");
  $("#composer").classList.add("voice-on");
  window.FridayLive && FridayLive.open();
  setState("listening", { force: true });
  document.dispatchEvent(new CustomEvent("friday:voice", { detail: { on: true } }));
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
  ensureTurnDetector();
  if (turnDetector) turnDetector.reset();

  // Browser speech lifecycle — use as hints, never as hard commits (Chrome finals ≠ end of thought).
  recognition.onspeechstart = () => {
    if (micSuspended || voiceBusy) return;
    ensureTurnDetector()?.noteSpeechStart();
    if (uiState !== "listening") setState("listening");
  };
  recognition.onspeechend = () => {
    if (micSuspended || voiceBusy) return;
    ensureTurnDetector()?.noteSpeechEnd();
  };

  recognition.onresult = (event) => {
    // Hold mode / cool-down: ignore everything — speaker bleed must not open a turn.
    if (micSuspended || Date.now() < listenCooldownUntil) return;
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
    if (voiceBusy) {
      // Interrupt mode only: mic is still live. Hold mode never reaches here (mic suspended).
      if (voiceHoldMode()) return;
      if (looksLikeEcho(shown) || looksLikeFridayPrompt(shown)) return;
      const stopWord = /^(stop|wait|hold on|hang on|enough|cancel)\b/i.test(shown.trim());
      const longEnough = !interim && finalBuffer
        && (shown.trim().split(/\s+/).filter(Boolean).length >= 4 || shown.trim().length >= 18);
      if (stopWord || longEnough) {
        interruptTurn();
        finalBuffer = shown;
        setListeningLine(shown, { interim: false });
        scheduleProcess(stopWord ? 80 : 220);
      }
      return;
    }
    if (shown) {
      if (looksLikeEcho(shown) || looksLikeFridayPrompt(shown)) {
        finalBuffer = "";
        interimText = "";
        if (turnDetector) turnDetector.reset();
        return;
      }
      setListeningLine(shown, { interim: !finalBuffer || !!interim });
      // Stay on listening visually — don't poke setState every interim (flicker source).
      if (uiState !== "listening") setState("listening");
      // Semantic + energy turn detector — Chrome isFinal alone never commits.
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
    // network / service-not-allowed: onend will re-kick; surface once.
    pushActivity(`Mic · ${event.error}`, { live: false });
  };

  recognition.onend = () => {
    // Hold: stay stopped while suspended. Interrupt: keep recognition alive for barge-in.
    if (!voiceMode || micSuspended) return;
    if (voiceBusy && voiceHoldMode()) return;
    // Single failed start() used to leave UI on "listening" with a dead mic.
    kickRecognition(8);
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
  const allowed = await ensureMicPermission();
  if (!allowed) return;
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

let memFilter = "all";
const MEM_KINDS = [
  ["all", "Everything"], ["learned", "Learned about you"], ["note", "Notes"], ["desktop", "Desktop"],
  ["experience", "Experience"], ["plan", "Plan"], ["reminder", "Reminders"],
];
let memItems = [];

async function refreshMemory() {
  try {
    const data = await (await apiFetch("/api/memory/overview")).json();
    memItems = data.items || [];
    const counts = data.counts || {};
    $("#memStats").textContent = `${memItems.length} things remembered`;
    const bar = $("#memFilters");
    if (bar) {
      bar.innerHTML = MEM_KINDS.map(([k, label]) => {
        const n = k === "all" ? memItems.length : counts[k] || 0;
        return `<button type="button" class="chip${memFilter === k ? " on" : ""}" data-k="${k}">${label} · ${n}</button>`;
      }).join("");
      bar.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => { memFilter = b.dataset.k; refreshMemory(); }));
    }
    renderMemCards(memItems.filter((m) => memFilter === "all" || m.kind === memFilter));
  } catch (_) {
    $("#memStats").textContent = "server offline";
  }
}

function renderMemCards(items) {
  const list = $("#memList");
  list.innerHTML = "";
  if (!items.length) list.innerHTML = `<div class="muted">Nothing here yet.</div>`;
  for (const m of items) {
    const card = document.createElement("div");
    card.className = "card";
    const when = m.created_at
      ? new Date(m.created_at * 1000).toLocaleString([], {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
          hour12: true,
        })
      : "";
    card.innerHTML = `
      <div><p>${escapeHtml(m.text)}</p><p class="muted"><span class="tag">${escapeHtml(m.source || m.kind || "")}</span> ${when}</p></div>
      <div class="actions">${m.id ? `<button class="ghost" data-del="${escapeHtml(m.id)}" data-coll="${escapeHtml(m.collection || "memories")}">Forget</button>` : ""}</div>`;
    list.appendChild(card);
  }
  list.querySelectorAll("[data-del]").forEach((b) => {
    b.addEventListener("click", async () => {
      await apiFetch(`/api/memory/${encodeURIComponent(b.dataset.del)}?collection=${encodeURIComponent(b.dataset.coll || "memories")}`, { method: "DELETE" });
      refreshMemory();
    });
  });
}

$("#btnMemSearch").addEventListener("click", async () => {
  const q = $("#memSearch").value;
  try {
    if (!q.trim()) return refreshMemory();
    const items = await (await apiFetch(`/api/memory/search?q=${encodeURIComponent(q)}`)).json();
    renderMemCards(items.map((m) => ({ ...m, kind: "note", source: (m.metadata && m.metadata.source) || "memory", deletable: true, collection: "memories", created_at: (m.metadata && m.metadata.created_at) || 0 })));
  } catch (_) {}
});

$("#btnForgetAll")?.addEventListener("click", async () => {
  const ok = await (window.FridayDialog
    ? FridayDialog.confirm({
        eyebrow: "MEMORY CORE",
        title: "Forget everything?",
        body: "Learned facts, notes, plan items, and reminders in Memory Core will be permanently deleted. Chat history is separate.",
        tone: "danger",
        confirmLabel: "Forget all",
        cancelLabel: "Keep memories",
      })
    : Promise.resolve(window.confirm("Forget everything Friday remembers?")));
  if (!ok) return;
  try {
    await apiFetch("/api/memory/forget-all", { method: "POST" });
  } catch (_) {}
  refreshMemory();
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
        <div class="plan-check ${it.done ? "on" : ""}" data-id="${it.id}" title="Toggle done">${it.done ? "âœ“" : ""}</div>
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


/* Systems / camera UI lives in systems-ui.js (loaded after this file). */
function humorSetting() {
  return localStorage.getItem("friday_humor") || "dry";
}

function pickFemaleBrowserVoice() {
  try {
    const voices = window.speechSynthesis?.getVoices?.() || [];
    if (!voices.length) return null;
    const rank = (v) => {
      const n = `${v.name} ${v.lang}`.toLowerCase();
      let s = 0;
      if (/en(-|_)?ie/i.test(v.lang) || /irish|moira/.test(n)) s += 6;
      if (/en(-|_)?(gb|uk)/i.test(v.lang) || /hazel|susan|sonia|libby/.test(n)) s += 4;
      if (/en(-|_)?us/i.test(v.lang)) s += 2;
      if (/zira|hazel|susan|eva|samantha|karen|moira|tessa|fiona|jenny|aria|natasha|linda|female/.test(n)) s += 8;
      if (/microsoft.*(zira|hazel)/.test(n)) s += 4;
      if (/male|david|mark|george|james|daniel|ravi|richard|guy|tony|christopher/.test(n)) s -= 12;
      return s;
    };
    const sorted = voices.slice().sort((a, b) => rank(b) - rank(a));
    // Never fall through to a clearly male top hit — skip those.
    return sorted.find((v) => rank(v) > 0) || sorted[0] || null;
  } catch (_) {
    return null;
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
    const voice = pickFemaleBrowserVoice();
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang || "en-IE";
    } else {
      u.lang = "en-IE";
    }
    // Natural rate only — speeding browser TTS is what sounded robotic.
    u.rate = window.FridayVoice && FridayVoice.pace() === "fast" ? 1.08
      : window.FridayVoice && FridayVoice.pace() === "slow" ? 0.92
      : 1.0;
    u.pitch = 1.0;
    u.onend = () => resolve(true);
    u.onerror = () => resolve(false);
    // Voices often load async on Chromium.
    const go = () => {
      if (!u.voice) {
        const v = pickFemaleBrowserVoice();
        if (v) { u.voice = v; u.lang = v.lang || "en-IE"; }
      }
      window.speechSynthesis.speak(u);
    };
    if (!voice && speechSynthesis.getVoices().length === 0) {
      let started = false;
      const once = () => { if (started) return; started = true; go(); };
      speechSynthesis.addEventListener("voiceschanged", once, { once: true });
      setTimeout(once, 280);
      return;
    }
    go();
  });
}

// Fetch synthesized audio for one piece of text; resolves to an object URL, or null when the server TTS is unavailable.
async function ttsFetchUrl(text) {
  const clean = String(text || "").replace(/\*\*/g, "").trim();
  if (!clean) return null;
  try {
    const rate = window.FridayVoice && FridayVoice.edgeRate ? FridayVoice.edgeRate() : "+0%";
    const res = await apiFetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean.slice(0, 500), rate }),
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
    // Always 1× — rate is baked into Edge synthesis so it stays natural.
    audio.playbackRate = 1;
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

/** Split spoken text on sentence endings so TTS never truncates mid-thought. */
function speakSentences(text) {
  const clean = String(text || "").replace(/\*\*/g, "").replace(/\s+/g, " ").trim();
  if (!clean) return [];
  const parts = [];
  const re = /[^.!?\u2026]+[.!?\u2026]+["')\]]*(?:\s+|$)|[^.!?\u2026]+$/g;
  let m;
  while ((m = re.exec(clean))) {
    const p = m[0].trim();
    if (p) parts.push(p);
  }
  return parts.length ? parts : [clean];
}

async function speak(text) {
  const parts = speakSentences(text);
  if (!parts.length) return;
  stopSpeech();
  window.FridayLive && FridayLive.state("speaking");
  // Prefetch sentence N+1 while N plays — cuts the gap between Edge fetches.
  let next = ttsFetchUrl(parts[0]);
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    const urlP = next;
    if (i + 1 < parts.length) next = ttsFetchUrl(parts[i + 1]);
    const url = await urlP;
    if (url) {
      await playUrl(url);
      continue;
    }
    window.FridayLive && FridayLive.synthSpeaking(true);
    const ok = await speakBrowser(part);
    if (!ok) console.warn("[Friday] browser TTS unavailable");
  }
}

/** Pause-line TTS for voice mode. Does not cancel an in-flight reply. */
async function speakFiller(text) {
  const clean = String(text || "").replace(/[*_`#>]/g, "").trim();
  if (!clean) return;
  window.FridayLive && FridayLive.state("speaking");
  try {
    const url = await ttsFetchUrl(clean);
    if (url) {
      await playUrl(url);
      return;
    }
    window.FridayLive && FridayLive.synthSpeaking(true);
    await speakBrowser(clean);
  } catch (err) {
    console.warn("[Friday] filler TTS failed:", err);
  }
}

// live.js speaks via window.* — classic scripts usually hoist, but set explicitly.
window.ttsFetchUrl = ttsFetchUrl;
window.playUrl = playUrl;
window.speakBrowser = speakBrowser;
window.stopSpeech = stopSpeech;
window.speak = speak;
window.speakFiller = speakFiller;

// ---------------------------------------------------------------- reminders + notifications
const shownReminders = new Set(JSON.parse(sessionStorage.getItem("friday.shownReminders") || "[]"));
function rememberShown(id) {
  shownReminders.add(id);
  sessionStorage.setItem("friday.shownReminders", JSON.stringify([...shownReminders].slice(-100)));
}

function showReminderPopup(n, { fromToast = false } = {}) {
  const host = $("#remPopup");
  if (!host || host.querySelector(`[data-nid="${n.id}"]`)) return;
  document.dispatchEvent(new CustomEvent("friday:reminder", { detail: { id: n.id, kind: n.kind } }));
  const card = document.createElement("div");
  card.className = "rem-card";
  card.dataset.nid = n.id;
  const late = n.body && /missed/.test(n.body) ? ` <span class="tag">${escapeHtml(n.body)}</span>` : "";
  card.innerHTML = `
    <div class="rem-eyebrow">${n.kind === "task" ? "TASK UPDATE" : "REMINDER"}${fromToast ? " · FROM NOTIFICATION" : ""}</div>
    <div class="rem-title">${escapeHtml(n.title)}${late}</div>
    ${n.kind === "task" && n.body ? `<div class="rem-body">${escapeHtml(n.body)}</div>` : ""}
    <div class="rem-actions">
      <button data-a="done">Got it</button>
      <button class="ghost" data-a="snooze">Snooze 10 min</button>
    </div>`;
  host.appendChild(card);
  card.querySelector('[data-a="done"]').addEventListener("click", async () => {
    await apiFetch(`/api/notifications/${n.id}/seen`, { method: "POST" });
    card.remove();
    refreshBell();
  });
  card.querySelector('[data-a="snooze"]').addEventListener("click", async () => {
    await apiFetch(`/api/notifications/${n.id}/snooze?minutes=10`, { method: "POST" });
    card.remove();
    refreshBell();
  });
  if (!fromToast || !shownReminders.has(n.id)) {
    showView("chat");
    const say = n.kind === "task"
      ? `Task update, boss: ${n.title}${n.body ? ". " + n.body : ""}`
      : `Reminder, boss: ${n.title}${n.body ? ". " + n.body : ""}`;
    addBubble("assistant", say, n.kind === "task" ? "task" : "reminder");
    if (speakEnabled() || voiceMode) speak(say);
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("Friday", { body: n.title, tag: n.id });
    }
  }
  rememberShown(n.id);
}

async function pollNotifications() {
  try {
    const list = await (await apiFetch("/api/notifications?unseen=1")).json();
    for (const n of list.slice().reverse()) if (!shownReminders.has(n.id)) showReminderPopup(n);
  } catch (_) {}
  refreshBell();
}

async function refreshBell() {
  try {
    const [unseen, upcoming] = await Promise.all([
      apiFetch("/api/notifications?unseen=1").then((r) => r.json()),
      apiFetch("/api/reminders/upcoming").then((r) => r.json()),
    ]);
    const badge = $("#bellCount");
    if (badge) {
      badge.textContent = unseen.length || "";
      badge.classList.toggle("hidden", !unseen.length);
    }
    const panel = $("#remList");
    if (panel) {
      const rows = [];
      for (const n of unseen) rows.push(`<div class="rem-row new"><b>${escapeHtml(n.title)}</b><span class="muted">due now</span></div>`);
      for (const j of upcoming.slice(0, 8)) {
        const when = j.cron
          ? `repeats · ${j.cron}`
          : new Date(j.run_at * 1000).toLocaleString([], {
              weekday: "short",
              hour: "numeric",
              minute: "2-digit",
              hour12: true,
            });
        rows.push(`<div class="rem-row"><b>${escapeHtml(j.title)}</b><span class="muted">${when}</span><button class="ghost" data-cancel-job="${j.id}">×</button></div>`);
      }
      panel.innerHTML = rows.join("") || `<div class="muted">No reminders. Say “remind me to … in 20 minutes”.</div>`;
      panel.querySelectorAll("[data-cancel-job]").forEach((b) => b.addEventListener("click", async () => {
        await apiFetch(`/api/tasks/${b.dataset.cancelJob}`, { method: "DELETE" });
        refreshBell();
      }));
    }
  } catch (_) {}
}

$("#btnBell")?.addEventListener("click", () => {
  const p = $("#remPanel");
  p.classList.toggle("hidden");
  if (!p.classList.contains("hidden")) {
    refreshBell();
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  }
});
$("#btnRemAllSeen")?.addEventListener("click", async () => {
  await apiFetch("/api/notifications/all/seen", { method: "POST" });
  $("#remPopup").innerHTML = "";
  refreshBell();
});

async function openReminderFromUrl() {
  const id = new URLSearchParams(location.search).get("reminder");
  if (!id) return;
  try {
    const n = await (await apiFetch(`/api/notifications/${id}`)).json();
    shownReminders.delete(n.id);
    showReminderPopup(n, { fromToast: true });
    history.replaceState(null, "", location.pathname);
  } catch (_) {}
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden || !voiceMode || micSuspended || voiceBusy) return;
  // Chromium often kills SpeechRecognition while the tab is backgrounded.
  kickRecognition(8);
});

(async function init() {
  const link = $("#linkHost");
  if (link) link.textContent = location.hostname || "local";
  // Warm speechSynthesis voice list early (Realtime female picker needs it).
  try {
    if (window.speechSynthesis) {
      speechSynthesis.getVoices();
      speechSynthesis.addEventListener("voiceschanged", () => speechSynthesis.getVoices(), { once: true });
    }
  } catch (_) {}
  // Phone scanned PC QR (?pair=TOKEN) — redeem before the auth gate.
  if (typeof window.FridayAuth?.consumePairQuery === "function") {
    const paired = await window.FridayAuth.consumePairQuery();
    if (paired) return; // reload after session cookie is set
  }
  const authed = await ensureAuthSession();
  if (!authed) return; // redirected to localhost, or waiting on Register / Sign in
  if (micNeedsHttps()) {
    fillHttpsBanner().catch(() => {});
  }
  syncSpeakToggles();
  openReminderFromUrl();
  pollNotifications();
  setInterval(pollNotifications, 5000);
  tickClock();
  setInterval(tickClock, 1000);
  setZenMode(zenEnabled());
  $("#btnZen")?.addEventListener("click", () => setZenMode(!zenEnabled()));
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === "b" || e.key === "B") && !e.altKey) {
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || e.target?.isContentEditable) return;
      e.preventDefault();
      setZenMode(!zenEnabled());
    }
  });
  syncZenChips();
  await refreshSkills();
  await refreshSettings();
  await restoreChat();
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }
})();

window.FridayApp = {
  voiceMode: () => voiceMode,
  voiceBusy: () => voiceBusy,
  uiState: () => uiState,
};
