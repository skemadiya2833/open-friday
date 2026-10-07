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
let turnEpoch = 0;
let chatAbort = null;
let fridayReply = "";

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

function looksLikeEcho(heard) {
  const a = normSpeech(heard);
  if (!a) return true;
  const refs = [window.FridayLive && FridayLive.lastSpoken && FridayLive.lastSpoken(), fridayReply];
  for (const r of refs) {
    const b = normSpeech(r);
    if (!b) continue;
    if (b.includes(a) || a.includes(b.slice(0, Math.min(48, b.length)))) return true;
    const aw = a.split(" ").filter((w) => w.length > 2);
    const bw = new Set(b.split(" ").filter((w) => w.length > 2));
    if (!aw.length) continue;
    let n = 0;
    for (const w of aw) if (bw.has(w)) n++;
    if (n / aw.length >= 0.65) return true;
  }
  return false;
}

function interruptTurn() {
  turnEpoch += 1;
  try { chatAbort && chatAbort.abort(); } catch (_) {}
  window.FridayLive && FridayLive.interrupt();
  stopSpeech();
  voiceBusy = false;
  setState(voiceMode ? "listening" : "idle");
  if (voiceMode) resumeRecognition();
  pushActivity("Interrupted · listening", { live: false });
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
  const epoch = ++turnEpoch;
  chatAbort = new AbortController();

  if (useVoice) voiceBusy = true;

  // live voice: sentence-pipelined speech. Mic stays live so the owner can interrupt.
  const vcfg = window.FridayVoice ? FridayVoice.cfg() : { streamSpeech: true };
  const speaker = useVoice && speakEnabled() && window.FridayLive ? FridayLive.speaker() : null;
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
      signal: chatAbort.signal,
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
          if (epoch !== turnEpoch) return;
          streamed += ev.text;
          fridayReply = streamed;
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

    if (epoch !== turnEpoch) return;
    const textOut = finalReply || streamed || "(no reply)";
    fridayReply = textOut;
    liveBody.textContent = textOut;
    if (skillId) liveMeta.textContent = `skill:${skillId}`;
    filler && filler.stop();
    if (speaker && vcfg.streamSpeech && speaker.spoken() > 0) {
      speaker.finish();
      await speaker.done();
    } else if (speakEnabled() && textOut && textOut !== "(no reply)") {
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

async function clearThisChat() {
  if (!confirm("Clear this conversation? Friday will forget the messages in it (saved memories stay).")) return;
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

function scheduleProcess(delay) {
  clearPauseTimer();
  pauseTimer = setTimeout(() => {
    const text = (finalBuffer || interimText || "").trim();
    if (!text || voiceBusy) return;
    pushActivity("Pause detected · processing…");
    setListeningLine(text, { interim: false });
    sendMessage(text, { fromVoice: true });
  }, delay || pauseMs());
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
      const stopWord = /^(stop|wait|hold on|hang on|enough|no|friday|hey)\b/i.test(shown.trim());
      const longEnough = shown.trim().split(/\s+/).filter(Boolean).length >= 3 || shown.trim().length >= 14;
      if ((stopWord || longEnough) && !looksLikeEcho(shown)) {
        interruptTurn();
        finalBuffer = shown;
        setListeningLine(shown, { interim: !!interim });
        scheduleProcess(stopWord ? 80 : 220);
      }
      return;
    }
    if (shown) {
      setListeningLine(shown, { interim: !finalBuffer || !!interim });
      setState("listening");
      const quick = window.FridayVoice && FridayVoice.style() === "realtime" && finalBuffer && !interim;
      scheduleProcess(quick ? 140 : undefined);
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
    // Keep the mic live during replies so the owner can interrupt.
    if (voiceMode) {
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
  ["all", "Everything"], ["learned", "Learned about you"], ["note", "Notes you added"], ["desktop", "Desktop tasks"],
  ["experience", "Agent experience"], ["plan", "Today's plan"], ["reminder", "Reminders"], ["chat", "Chat snippets"],
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
    const when = m.created_at ? new Date(m.created_at * 1000).toLocaleString() : "";
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
  if (!confirm("Forget everything Friday remembers? Notes, learned facts, chat snippets, plan items and reminders in Memory Core will be deleted.")) return;
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
        <input type="range" min="0.85" max="1.6" step="0.05" data-voice-speed style="width:100%" />
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
    u.rate = 1.18 * (window.FridayVoice ? FridayVoice.speed() : 1.2);
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

// ---------------------------------------------------------------- reminders + notifications
const shownReminders = new Set(JSON.parse(sessionStorage.getItem("friday.shownReminders") || "[]"));
function rememberShown(id) {
  shownReminders.add(id);
  sessionStorage.setItem("friday.shownReminders", JSON.stringify([...shownReminders].slice(-100)));
}

function showReminderPopup(n, { fromToast = false } = {}) {
  const host = $("#remPopup");
  if (!host || host.querySelector(`[data-nid="${n.id}"]`)) return;
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
        const when = j.cron ? `repeats · ${j.cron}` : new Date(j.run_at * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
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

(async function init() {
  const link = $("#linkHost");
  if (link) link.textContent = location.hostname || "local";
  if (micNeedsHttps()) {
    fillHttpsBanner().catch(() => {});
  }
  syncSpeakToggles();
  openReminderFromUrl();
  pollNotifications();
  setInterval(pollNotifications, 5000);
  tickClock();
  setInterval(tickClock, 1000);
  await refreshSkills();
  await refreshSettings();
  await restoreChat();
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }
})();
