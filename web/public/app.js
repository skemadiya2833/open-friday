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

/** Desktop screen look — Control Center pill (orange edge glow is on the real desktop). */
function setScreenLooking(on) {
  const pill = $("#screenLookPill");
  if (pill) pill.classList.toggle("hidden", !on);
  document.body.classList.toggle("screen-looking", !!on);
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

/** Presence working bubble — Systems `presence_orb` (default on). */
let presenceOrbEnabled = true;

let avatarTalkRaf = 0;
let avatarTalkingUrl = null; // uploaded talking-head clip for active callsign
let avatarMouthAtlasUrl = null; // kept for presence snap; no mid-clip seeking
let avatarVideoToken = 0;
let avatarSpeakStartedAt = 0;
let avatarTalkSmooth = 0; // smoothed TTS energy
let avatarClipDuration = 0;
let avatarUtteranceDur = 0;
let avatarVideoReady = false;
let avatarGazeOn = false;
let avatarGazeRaf = 0;
let avatarGazeTx = 0;
let avatarGazeTy = 0;
let avatarGazeX = 0;
let avatarGazeY = 0;
let avatarGazeBored = 0;
let avatarGazeLast = 0;
let avatarGazeWanderAt = 0;
let avatarGazeWanderX = 0;
let avatarGazeWanderY = 0;

function hideAvatarVideo() {
  const panel = $("#avatarPanel");
  const video = $("#avatarVideo");
  if (panel) {
    panel.classList.remove("lipsync", "mouth-blend");
    panel.style.removeProperty("--talk");
  }
  if (video) {
    video.classList.remove("show");
    video.onended = null;
    video.ontimeupdate = null;
    video.onloadeddata = null;
    video.onplaying = null;
    video.onerror = null;
    try { video.pause(); } catch (_) {}
    try {
      video.removeAttribute("src");
      video.load();
    } catch (_) {}
  }
  avatarVideoReady = false;
  avatarClipDuration = 0;
}

function restoreAvatarStill() {
  const panel = $("#avatarPanel");
  hideAvatarVideo();
  if (panel) {
    panel.classList.remove("speaking", "mouth-blend");
    panel.style.removeProperty("--mouth");
    panel.style.removeProperty("--speak");
    panel.style.removeProperty("--talk");
  }
  const still = $("#avatarStill");
  if (still) still.classList.remove("hidden");
  avatarTalkSmooth = 0;
  avatarUtteranceDur = 0;
}

/**
 * Single continuous talking clip — no mouth-slice seeks / dual-buffer fades.
 * Research + practice: face crossfades ghost; mid-clip seeking looks like skipped frames.
 * Keep one muted loop under TTS; energy only nudges rate + glow, not hard cuts.
 */
function playTalkingVideoWithSpeech() {
  const panel = $("#avatarPanel");
  const video = $("#avatarVideo");
  if (!panel || !video || !avatarTalkingUrl) return;
  const token = ++avatarVideoToken;
  const url = avatarTalkingUrl;
  const reveal = () => {
    if (token !== avatarVideoToken) return;
    if (!video.videoWidth || video.readyState < 2) return;
    avatarVideoReady = true;
    if (Number.isFinite(video.duration) && video.duration > 0) {
      avatarClipDuration = video.duration;
    }
    video.classList.add("show");
    panel.classList.add("lipsync");
    // Stay visible for the whole utterance — energy flicker reads as blur/strobe.
    panel.style.setProperty("--talk", "1");
  };
  const fail = () => {
    if (token !== avatarVideoToken) return;
    hideAvatarVideo();
  };
  panel.classList.add("lipsync");
  video.muted = true;
  video.defaultMuted = true;
  video.loop = true;
  video.playsInline = true;
  video.playbackRate = 1;
  video.onerror = fail;
  video.onloadeddata = reveal;
  video.onplaying = reveal;
  let needLoad = true;
  try {
    const abs = new URL(url, location.origin).href;
    if (video.src === abs && video.readyState >= 2) needLoad = false;
    else if (video.src !== abs) video.src = url;
  } catch (_) {
    video.src = url;
  }
  if (!needLoad) reveal();
  try {
    if (!Number.isFinite(video.currentTime) || video.currentTime < 0.02) {
      video.currentTime = 0.04;
    }
  } catch (_) {}
  const p = video.play();
  if (p && p.then) p.then(reveal).catch(fail);
}

/** New TTS phrase — keep the loop going; only soft-rewind if the clip is about to end. */
function nudgeTalkingVideoForUtterance(durationSec, _text) {
  if (Number.isFinite(durationSec) && durationSec > 0) avatarUtteranceDur = durationSec;
  const video = $("#avatarVideo");
  if (!video || !avatarTalkingUrl) return;
  if (!avatarVideoReady) {
    video.addEventListener("loadeddata", () => {
      nudgeTalkingVideoForUtterance(avatarUtteranceDur, _text);
    }, { once: true });
    return;
  }
  try {
    if (avatarClipDuration > 0.8 && video.currentTime > avatarClipDuration - 0.35) {
      video.currentTime = 0.05;
    }
  } catch (_) {}
  if (video.paused) video.play().catch(() => {});
}

function setAvatarSpeaking(on) {
  const panel = $("#avatarPanel");
  if (!panel) return;
  if (!on) {
    avatarVideoToken += 1;
    if (avatarTalkRaf) {
      cancelAnimationFrame(avatarTalkRaf);
      avatarTalkRaf = 0;
    }
    restoreAvatarStill();
    return;
  }
  if (panel.classList.contains("hidden")) return;
  panel.classList.add("speaking");
  const still = $("#avatarStill");
  if (still) still.classList.remove("hidden");
  avatarSpeakStartedAt = performance.now();
  ensureAvatarGaze();
  if (avatarTalkingUrl) {
    const video = $("#avatarVideo");
    const live = panel.classList.contains("lipsync") && video && video.classList.contains("show");
    if (!live) playTalkingVideoWithSpeech();
    else if (video && video.paused) video.play().catch(() => {});
  } else {
    hideAvatarVideo();
  }
  if (!avatarTalkRaf) {
    const tick = () => {
      const raw = (window.FridayLive && FridayLive.outLevel) ? FridayLive.outLevel() : 0;
      const target = Number.isFinite(raw) ? Math.max(0, Math.min(1, raw)) : 0;
      const k = target > avatarTalkSmooth ? 0.5 : 0.18;
      avatarTalkSmooth += (target - avatarTalkSmooth) * k;
      const lvl = avatarTalkSmooth;
      panel.style.setProperty("--speak", lvl.toFixed(3));

      if (avatarTalkingUrl) {
        // Solid opaque clip for the whole speaking turn — energy opacity /
        // pause/rate breathes read as blur + skipped frames. Tool waits clear
        // speaking via setAvatarSpeaking(false), so no silent mocking.
        panel.style.setProperty("--talk", "1");
        const video = $("#avatarVideo");
        if (video && avatarVideoReady) {
          try {
            if (video.playbackRate !== 1) video.playbackRate = 1;
          } catch (_) {}
          if (video.paused) video.play().catch(() => {});
        }
      } else {
        panel.style.setProperty("--mouth", Math.pow(lvl, 0.7).toFixed(3));
      }
      avatarTalkRaf = requestAnimationFrame(tick);
    };
    avatarTalkRaf = requestAnimationFrame(tick);
  }
}

/** Idle presence: whole portrait parallax toward cursor / typing; soft wander when bored. */
function ensureAvatarGaze() {
  if (avatarGazeOn) return;
  avatarGazeOn = true;
  avatarGazeLast = performance.now();
  const poke = () => { avatarGazeLast = performance.now(); };
  window.addEventListener("pointermove", (e) => {
    poke();
    const panel = $("#avatarPanel");
    if (!panel || panel.classList.contains("hidden")) return;
    const r = panel.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return;
    const cx = r.left + r.width * 0.5;
    const cy = r.top + r.height * 0.42;
    const nx = (e.clientX - cx) / Math.max(120, r.width * 0.85);
    const ny = (e.clientY - cy) / Math.max(120, r.height * 0.85);
    avatarGazeTx = Math.max(-1, Math.min(1, nx));
    avatarGazeTy = Math.max(-1, Math.min(1, ny));
  }, { passive: true });
  const lookComposer = () => {
    poke();
    avatarGazeTx = 0.55;
    avatarGazeTy = 0.7;
  };
  document.addEventListener("keydown", lookComposer, { passive: true });
  $("#input")?.addEventListener("input", lookComposer, { passive: true });
  $("#input")?.addEventListener("focus", lookComposer, { passive: true });
  const tickGaze = () => {
    const panel = $("#avatarPanel");
    const now = performance.now();
    const idleMs = now - avatarGazeLast;
    const speaking = !!(panel && panel.classList.contains("speaking"));
    const boredTarget = (!speaking && idleMs > 2800) ? Math.min(1, (idleMs - 2800) / 5000) : 0;
    avatarGazeBored += (boredTarget - avatarGazeBored) * 0.04;
    if (!speaking && idleMs > 2200) {
      if (now >= avatarGazeWanderAt) {
        avatarGazeWanderAt = now + 1600 + Math.random() * 2800;
        avatarGazeWanderX = (Math.random() * 2 - 1) * (0.35 + avatarGazeBored * 0.45);
        avatarGazeWanderY = 0.2 + Math.random() * 0.45 + avatarGazeBored * 0.3;
      }
      avatarGazeTx += (avatarGazeWanderX - avatarGazeTx) * 0.03;
      avatarGazeTy += (avatarGazeWanderY - avatarGazeTy) * 0.03;
    }
    const damp = speaking ? 0.28 : 1;
    const tx = avatarGazeTx * damp;
    const ty = avatarGazeTy * damp;
    avatarGazeX += (tx - avatarGazeX) * (speaking ? 0.08 : 0.14);
    avatarGazeY += (ty - avatarGazeY) * (speaking ? 0.08 : 0.14);
    if (panel && !panel.classList.contains("hidden")) {
      panel.style.setProperty("--gaze-x", avatarGazeX.toFixed(3));
      panel.style.setProperty("--gaze-y", avatarGazeY.toFixed(3));
    }
    avatarGazeRaf = requestAnimationFrame(tickGaze);
  };
  avatarGazeRaf = requestAnimationFrame(tickGaze);
}

/**
 * Text shown in chat stays as-written; this is what TTS hears.
 * Fixes em-dash eager cuts sounding like "— I'm Piegi…" and misread callsigns.
 */
function forSpokenText(text) {
  let s = String(text || "");
  s = s.replace(/[*_`#>]+/g, "");
  s = s.replace(/\s*[—–―]+\s*/g, ", ");
  s = s.replace(/\s+-\s+/g, ", ");
  s = s.replace(/\bPiegi\b/gi, "Peegee");
  s = s.replace(/\bPIEGI\b/g, "Peegee");
  s = s.replace(/\s+/g, " ").trim();
  return s;
}

function applyPresenceSnap(snap) {
  if (!snap || !snap.skin) return;
  const skin = snap.skin;
  const themes = ["skin-friday", "skin-jarvis", "skin-ultron", "skin-vision", "skin-karen", "skin-edith", "skin-custom"];
  document.body.classList.remove(...themes);
  document.body.classList.add(skin.css_theme || "skin-friday");
  if (skin.accent && /^#[0-9a-fA-F]{6}$/.test(skin.accent)) {
    document.body.style.setProperty("--accent", skin.accent);
    document.body.style.setProperty("--accent-2", skin.accent);
    document.body.style.setProperty("--cyan", skin.accent);
    document.body.style.setProperty("--line-hot", `${skin.accent}88`);
  } else if (skin.css_theme !== "skin-custom") {
    document.body.style.removeProperty("--accent");
    document.body.style.removeProperty("--accent-2");
    document.body.style.removeProperty("--cyan");
    document.body.style.removeProperty("--line-hot");
  }
  window.__fridayVoiceProfile = skin.voice_profile || "female_us";
  window.__fridayTtsVoice = skin.tts_voice || "";
  window.__fridayTtsRate = skin.tts_rate || "+0%";
  const nameEl = $("#brandName");
  const tagEl = $("#brandTag");
  const sysEl = $("#sysId");
  if (nameEl) nameEl.textContent = skin.callsign || "FRIDAY";
  if (tagEl) tagEl.textContent = skin.hud_title || "LOCAL PROTOCOL";
  if (sysEl) sysEl.textContent = `${skin.callsign || "FRIDAY"} // LOCAL HUD`;
  document.title = `${skin.callsign || "FRIDAY"} — HUD`;
  const panel = $("#avatarPanel");
  const still = $("#avatarStill");
  const talkOn = snap.avatar_lipsync !== false;
  avatarTalkingUrl = talkOn
    ? (snap.talking_video_url || snap.video_url || null)
    : null;
  avatarMouthAtlasUrl = talkOn ? (snap.mouth_atlas_url || null) : null;
  if (panel && still) {
    if (snap.portrait_url || avatarTalkingUrl) {
      if (snap.portrait_url) {
        const next = `${snap.portrait_url}?t=${Date.now()}`;
        if (!still.getAttribute("src") || !String(still.src || "").includes(snap.portrait_url)) {
          still.src = next;
        }
      }
      if (!panel.classList.contains("speaking")) restoreAvatarStill();
      else still.classList.remove("hidden");
      panel.classList.remove("hidden");
      panel.setAttribute("aria-hidden", "false");
      ensureAvatarGaze();
    } else {
      panel.classList.add("hidden");
      panel.setAttribute("aria-hidden", "true");
    }
  }
}

async function refreshPresence() {
  try {
    const res = await apiFetch("/api/presence");
    if (!res.ok) return;
    const snap = await res.json();
    applyPresenceSnap(snap);
  } catch (_) {
    /* keep defaults */
  }
}

async function refreshPresenceOrbPref() {
  try {
    const res = await apiFetch("/api/systems/prefs");
    if (!res.ok) return;
    const snap = await res.json();
    const it = (snap.items || []).find((x) => x.key === "presence_orb");
    if (it) presenceOrbEnabled = !!it.value;
  } catch (_) {
    /* keep default */
  }
}

function syncOrbWorkBubble(state) {
  const bubble = $("#orbWorkBubble");
  if (!bubble) return;
  const working = presenceOrbEnabled && (state === "acting" || state === "thinking");
  bubble.classList.toggle("hidden", !working);
  if (working) bubble.textContent = state === "acting" ? "working" : "thinking";
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
  // Live.speaker → playUrl starts the talking clip; nothing cleared it when we
  // flipped back to listening — HUD kept mouthing and felt deaf.
  if (state === "listening" || state === "idle") {
    try { setAvatarSpeaking(false); } catch (_) {}
  }
  syncOrbWorkBubble(state);
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

let voiceWatchIv = null;
let lastSpeechActivityAt = 0;
let recognitionAlive = false;
let recreateBusy = false;
let ignoreRecognitionEnd = false;

/** Hold mode: deaf to results, but do NOT stop() — Chrome often refuses to restart the same instance. */
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
}

function wireRecognition(rec) {
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = "en-US";
  rec.onspeechstart = () => {
    lastSpeechActivityAt = Date.now();
    recognitionAlive = true;
    if (micSuspended || voiceBusy) return;
    ensureTurnDetector()?.noteSpeechStart();
    if (uiState !== "listening") setState("listening");
  };
  rec.onspeechend = () => {
    if (micSuspended || voiceBusy) return;
    ensureTurnDetector()?.noteSpeechEnd();
  };
  rec.onresult = onRecognitionResult;
  rec.onerror = onRecognitionError;
  rec.onend = onRecognitionEnd;
}

function _bootRecognition(Rec) {
  if (!voiceMode) {
    recreateBusy = false;
    ignoreRecognitionEnd = false;
    return false;
  }
  try {
    recognition = new Rec();
    wireRecognition(recognition);
    recognition.start();
    recognitionAlive = true;
    lastSpeechActivityAt = Date.now();
    recreateBusy = false;
    ignoreRecognitionEnd = false;
    return true;
  } catch (_) {
    recognition = null;
    recognitionAlive = false;
    recreateBusy = false;
    ignoreRecognitionEnd = false;
    setTimeout(() => { if (voiceMode) recreateRecognition(); }, 280);
    return false;
  }
}

/** Fresh SpeechRecognition instance. Sync when idle; brief delay only when replacing a live one. */
function recreateRecognition() {
  if (!voiceMode || recreateBusy) return;
  const Rec = SpeechRec();
  if (!Rec) return;
  recreateBusy = true;
  const had = !!recognition;
  if (had) {
    ignoreRecognitionEnd = true;
    try { recognition?.abort?.(); } catch (_) {}
    try { recognition?.stop?.(); } catch (_) {}
    recognitionAlive = false;
    recognition = null;
    setTimeout(() => _bootRecognition(Rec), 60);
    return;
  }
  _bootRecognition(Rec);
}

/** Restart recognition; recreate immediately if start() fails (Chrome InvalidState / dead session). */
function kickRecognition(retries = 4) {
  if (!voiceMode) return;
  if (!recognition) {
    recreateRecognition();
    return;
  }
  try {
    recognition.start();
    recognitionAlive = true;
    lastSpeechActivityAt = Date.now();
  } catch (_) {
    if (retries <= 0) {
      pushActivity("Mic stalled · fresh session…", { live: false });
      recreateRecognition();
      return;
    }
    setTimeout(() => kickRecognition(retries - 1), 120);
  }
}

function startVoiceWatchdog() {
  if (voiceWatchIv) return;
  voiceWatchIv = setInterval(() => {
    if (!voiceMode) return;
    const now = Date.now();
    // Turn finished but HUD left on SPEAKING / talking clip (Live.speaker path).
    if (!voiceBusy && (uiState === "speaking" || uiState === "thinking" || uiState === "acting")) {
      pushActivity("Mic re-arm…", { live: false });
      armMicNow();
      return;
    }
    // Stuck deaf after a turn (timer lost / missed arm).
    if (micSuspended && !voiceBusy && now > listenCooldownUntil + 500) {
      if (!releaseMicTimer) {
        pushActivity("Mic re-arm…", { live: false });
        armMicNow();
      }
      return;
    }
    // Chrome died mid-listen — recreate, don't just start() the corpse.
    if (!micSuspended && !voiceBusy && uiState === "listening"
        && now - (lastSpeechActivityAt || now) > 4500) {
      recreateRecognition();
      lastSpeechActivityAt = now;
    }
  }, 1200);
}

function stopVoiceWatchdog() {
  if (voiceWatchIv) {
    clearInterval(voiceWatchIv);
    voiceWatchIv = null;
  }
}

function armMicNow() {
  micSuspended = false;
  listenCooldownUntil = 0;
  finalBuffer = "";
  interimText = "";
  try { setAvatarSpeaking(false); } catch (_) {}
  setState("listening", { force: true });
  // Always fresh SpeechRecognition after a turn — reuse-after-stop is the halt bug.
  recreateRecognition();
  pushActivity("Listening", { live: false });
}

function releaseMicAfter(cooldownMs) {
  micSuspended = true; // ignore results through cool-down (engine may stay running)
  listenCooldownUntil = Date.now() + Math.max(0, cooldownMs);
  if (releaseMicTimer) clearTimeout(releaseMicTimer);
  releaseMicTimer = setTimeout(() => {
    releaseMicTimer = null;
    if (!voiceMode) return;
    if (voiceBusy) {
      releaseMicAfter(250);
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

/** Strip model theater / raw JSON before chat bubbles or captions. Never invent "try again" copy. */
function sanitizeAssistantText(text) {
  let t = String(text || "").trim();
  if (!t) return "";
  // Raw JSON / tool payload dumps — prefer embedded message if present.
  if (/^\s*[\{\[]/.test(t) && /"ok"\s*:|"tool"\s*:|"message"\s*:/.test(t)) {
    try {
      const obj = JSON.parse(t);
      if (obj && typeof obj.message === "string" && obj.message.trim()) return obj.message.trim();
      if (obj && typeof obj.reply === "string" && obj.reply.trim()) return obj.reply.trim();
    } catch (_) { /* fall through */ }
    return "";
  }
  // Prompt / identity / optics theater — hide until a clean final reply arrives.
  if (
    /\buser'?s?\s+goal\s*:/i.test(t)
    || /\bconstraint\s*\d+\s*:/i.test(t)
    || /\*{1,2}\s*correction\s*\*{0,2}/i.test(t)
    || /\bthe prompt says\b/i.test(t)
    || /\btell the user you could not reach search\b/i.test(t)
    || /\bhere'?s a thinking process\b/i.test(t)
    || /\bthinking process that leads\b/i.test(t)
    || /\banalyze the request\b/i.test(t)
    || /\bthe user\s*\(\s*boss\s*\)\s*says\b/i.test(t)
    || /\bthe user is (asking|questioning|describing|challenging)\b/i.test(t)
    || /\bquestioning my identity\b/i.test(t)
    || /\bdidn'?t automatically capture\b/i.test(t)
    || /\*\s*friday\s*:\s*calm/i.test(t)
    || /\bcalm,\s*precise,\s*a step ahead\b/i.test(t)
    || /\bsystem instructions?\b/i.test(t)
    || (/\b\*\s*goal\s*:/i.test(t) && /\b\*\s*constraint\b/i.test(t))
  ) {
    return "";
  }
  return t;
}

function scrollMessagesToEnd(force = true) {
  const box = $("#messages");
  if (!box) return;
  const stick = () => {
    box.scrollTop = box.scrollHeight;
    const last = box.lastElementChild;
    if (last && typeof last.scrollIntoView === "function") {
      try { last.scrollIntoView({ block: "end", behavior: "auto" }); } catch (_) {}
    }
  };
  stick();
  // Layout / fonts / streaming tokens often grow after the first paint.
  requestAnimationFrame(() => {
    stick();
    if (force) requestAnimationFrame(stick);
  });
}

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
  const body = role === "assistant" ? sanitizeAssistantText(text) : text;
  el.innerHTML = `${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ""}<div class="body">${escapeHtml(body)}</div>${feedback}`;
  $("#messages").appendChild(el);
  el.querySelector(".fb-up")?.addEventListener("click", () => sendFeedback(el, "up"));
  el.querySelector(".fb-down")?.addEventListener("click", () => sendFeedback(el, "down"));
  scrollMessagesToEnd(true);
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

/** Pipeline / chat chrome — never dump into the activity feed or live HUD. */
function isFeedNoise(message) {
  return /^(Processing speech|Thinking|Voice mode|Figuring out|Intent ·|Skill ·|Mode ·|Turn ready|Still listening|Go on —|Chatting|Done|Spoken|Speaking reply|Voice on|Voice mode off|Pause detected|Listening|Scheduling|Researching|Working with files|Working on a reply|Working…|working…|Checking memory|Running |Controlling the desktop|Looking at your screen|Looking through (the )?camera|Mic ·|Mic stalled|Mic re-arm|Transcribing|Recording)\b/i.test(
    String(message || "").trim(),
  );
}

/** Live HUD may show act/errors only — never skill-run labels like "Looking at your screen…". */
function isLiveHudWorthy(message) {
  const m = String(message || "").trim();
  if (!m || isFeedNoise(m)) return false;
  // Skip long "Acting · create a dashboard…" noise; desktop agent still surfaces Agent/Shell.
  if (/^Acting\b/i.test(m)) return false;
  // Skill-run "Looking…" banners are noise — orb state already shows THINKING.
  if (/^Looking\b/i.test(m)) return false;
  return /^(Webcam|Camera|Agent |Shell |⚠|Error|Opened |Desktop agent)/i.test(m);
}

function pushActivity(message, { live = true, detail = "" } = {}) {
  const feed = $("#activityFeed");
  if (!feed || !message) return;
  if (isFeedNoise(message)) return;
  const voiceOpen = window.FridayLive && FridayLive.isOpen && FridayLive.isOpen();
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
        "Systems online. Comms persist across refresh. Tell me what we're doing today and I'll lock it into the mission board.",
      );
      return;
    }
    for (const t of turns) {
      addBubble(t.role === "user" ? "user" : "assistant", t.content || "", t.skill_id || "");
    }
    scrollMessagesToEnd(true);
  } catch (_) {
    persistSession(null);
    addBubble(
      "assistant",
      "Systems online. Comms channel open — engage the mic for voice, or transmit text.",
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
  if (releaseMicTimer) {
    clearTimeout(releaseMicTimer);
    releaseMicTimer = null;
  }
  finalBuffer = "";
  interimText = "";
  if (voiceMode) {
    armMicNow();
  } else {
    micSuspended = false;
    setState("idle", { force: true });
  }
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
  const skillOverride = $("#skillOverride").value || null;
  const chip = $("#skillChip");
  chip.classList.add("hidden");
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
  // Typed chat still gets caption/progress fillers when Live HUD is open — audio only with voice TTS.
  const vcfg = window.FridayVoice ? FridayVoice.cfg() : { streamSpeech: true };
  // Stream speech whenever TTS is on — don't wait for the full reply (Jarvis-style).
  const speaker = speakEnabled() && window.FridayLive && (useVoice || vcfg.streamSpeech)
    ? FridayLive.speaker({ onFirst: () => setState("speaking", { force: true }) })
    : null;
  const filler = window.FridayLive
    ? FridayLive.fillers(useVoice && speakEnabled() ? speaker : null)
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
  live.innerHTML = `<div class="meta hidden"></div><span class="body"></span>`;
  const liveBody = live.querySelector(".body");
  const liveMeta = live.querySelector(".meta");
  const setLiveMeta = (text) => {
    if (!liveMeta) return;
    const t = String(text || "").trim();
    if (!t || isFeedNoise(t) || /^(thinking…|working…|skill:chat|talk\s*·\s*chat|chat)$/i.test(t)) {
      liveMeta.textContent = "";
      liveMeta.classList.add("hidden");
      return;
    }
    liveMeta.textContent = t;
    liveMeta.classList.remove("hidden");
  };
  $("#messages").appendChild(live);
  scrollMessagesToEnd(true);

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
        const msg = ev.message || ev.step || "";
        if (!isFeedNoise(msg)) {
          pushActivity(msg || "…", { detail: ev.detail || "" });
          if (ev.message) setLiveMeta(ev.message);
        }
      }
      if (ev.type === "thinking_token" && (ev.token || ev.text)) {
        const scrap = String(ev.token || ev.text || "").trim();
        if (scrap) {
          if (filler && typeof filler.thinking === "function") filler.thinking(scrap);
          else if (window.FridayLive) FridayLive.friday(scrap.slice(0, 160), { filler: true });
        }
      }
      if (ev.type === "thinking_set" && ev.text) {
        const scrap = String(ev.text).trim();
        if (scrap && filler && typeof filler.thinking === "function") filler.thinking(scrap);
      }
      if (ev.type === "intent") {
        // Chat classify noise — never show Skill/Intent chips for ordinary talk.
        if (ev.skill_id && ev.skill_id !== "chat") {
          pushActivity(`Intent · ${ev.mode} → ${ev.skill_id}`, {
            detail: ev.reason || "",
          });
          setLiveMeta(`${ev.mode} · ${ev.skill_id}`);
        }
      }
      if (ev.type === "skill_selected") {
        skillId = ev.skill_id;
        if (ev.skill_id && ev.skill_id !== "chat") {
          chip.textContent = `Skill · ${ev.skill_id}${ev.mode ? ` · ${ev.mode}` : ""}`;
          chip.classList.remove("hidden");
          setLiveMeta(`${ev.skill_id}`);
        } else {
          chip.classList.add("hidden");
          setLiveMeta("");
        }
        if (ev.skill_id === "computer_use") {
          try { setAvatarSpeaking(false); } catch (_) {}
          setState("acting");
          // Status stays in the quiet hint — never open the RESULT card for pipeline chatter.
        }
        if (ev.skill_id === "observe") {
          try { setAvatarSpeaking(false); } catch (_) {}
        }
        if (ev.skill_id === "camera") {
          try { setAvatarSpeaking(false); } catch (_) {}
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
        scrollMessagesToEnd(true);
        pushActivity("Camera frame shown", { live: false });
      }
      if (ev.type === "screen_looking") {
        try { setAvatarSpeaking(false); } catch (_) {}
        setScreenLooking(!!ev.on);
      }
      if (ev.type === "observation") {
        try { setAvatarSpeaking(false); } catch (_) {}
        if (ev.source === "camera") {
          const sz = Array.isArray(ev.size) ? `${ev.size[0]}×${ev.size[1]}` : "";
          pushActivity(`Webcam frame${sz ? ` · ${sz}` : ""}`);
        } else {
          setScreenLooking(true);
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
        try { setAvatarSpeaking(false); } catch (_) {}
        // Caption-only presence during desktop work — no silent mouthing clip.
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
        const shown = sanitizeAssistantText(streamed);
        fridayReply = shown;
        liveBody.textContent = shown;
        if (window.FridayLive && FridayLive.isOpen()) {
          FridayLive.result(shown);
          if (!(speaker && vcfg.streamSpeech)) FridayLive.friday(shown);
        }
        if (speaker && vcfg.streamSpeech) {
          clearFillerForReply();
          if (shown === streamed || !/^\s*[\{\[]/.test(streamed)) speaker.push(ev.text);
        }
        scrollMessagesToEnd(false);
      }
      if (ev.type === "warning" && ev.message) {
        pushActivity(`⚠ ${ev.message}`, { live: false });
      }
      if (ev.type === "presence") {
        applyPresenceSnap(ev);
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
        const turnId =
          ev.turn_id ||
          (ev.metadata && ev.metadata.turn_id) ||
          (ev.result && ev.result.metadata && ev.result.metadata.turn_id) ||
          "";
        if (turnId) live.dataset.replyId = turnId;
      }
      if (ev.type === "error") {
        setCameraLooking(false);
        const errText = (ev.message || "Error").trim();
        liveBody.textContent = errText;
        // So the post-stream fallback does not overwrite with the voice "blanked" line.
        finalReply = errText;
        pushActivity(`Error · ${errText}`, { live: false });
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
    const textOut = sanitizeAssistantText((finalReply || streamed || "").trim())
      || (useVoice
        // Never ask them to resend — that loop is worse than a short stand-by.
        ? "That turn came back empty on my side. Standing by — what's next?"
        : "No reply came back from the model.");
    fridayReply = textOut;
    liveBody.textContent = textOut;
    if (window.FridayLive && FridayLive.isOpen()) {
      FridayLive.result(textOut);
      FridayLive.clearHint && FridayLive.clearHint();
    }
    if (!live.querySelector(".feedback")) {
      if (!live.dataset.replyId) live.dataset.replyId = `r-${Date.now()}`;
      const fb = document.createElement("div");
      fb.className = "feedback";
      fb.innerHTML = `<button type="button" class="fb-up" title="Good for training" aria-label="Thumbs up">▲</button>
        <button type="button" class="fb-down" title="Bad for training" aria-label="Thumbs down">▼</button>`;
      live.appendChild(fb);
      fb.querySelector(".fb-up")?.addEventListener("click", () => sendFeedback(live, "up"));
      fb.querySelector(".fb-down")?.addEventListener("click", () => sendFeedback(live, "down"));
    }
    if (skillId && skillId !== "chat") setLiveMeta(skillId);
    else setLiveMeta("");
    clearFillerForReply();
    const awaitSpeak = async (p) => {
      // Absolute cap so a stuck TTS chain cannot leave voiceBusy / SPEAKING forever.
      await Promise.race([
        Promise.resolve(p).catch(() => {}),
        new Promise((r) => setTimeout(r, 90000)),
      ]);
    };
    if (speaker && vcfg.streamSpeech && speaker.spoken() > 0) {
      speaker.finish();
      await awaitSpeak(speaker.done());
    } else if (speakEnabled() && textOut && !/^No reply\.?$/i.test(textOut)) {
      if (speaker) {
        speaker.push(String(textOut).slice(0, 700) + " ");
        speaker.finish();
        await awaitSpeak(speaker.done());
      } else {
        await awaitSpeak(speak(textOut));
      }
    }
  } catch (err) {
    if (err.name === "AbortError" || /abort/i.test(err.message || "")) {
      setLiveMeta("");
      return;
    }
    liveBody.textContent = `Error: ${err.message}`;
    pushActivity(`Error · ${err.message}`, { live: false });
  } finally {
    filler && filler.stop();
    setScreenLooking(false);
    // Always clear busy — even if interrupted (epoch mismatch). Skipping this left the mic deaf.
    voiceBusy = false;
    finalBuffer = "";
    interimText = "";
    // Speaker path uses playUrl (talking video on) without speak()'s finally — clear here.
    try { setAvatarSpeaking(false); } catch (_) {}
    if (!voiceMode) {
      setState("idle", { force: true });
      return;
    }
    if (epoch !== turnEpoch) {
      // Newer turn owns the mic; still ensure we are not stuck suspended without a timer.
      if (micSuspended && !releaseMicTimer) armMicNow();
      return;
    }
    setState("listening", { force: true });
    releaseMicAfter(voiceHoldMode() ? 200 : 120);
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
  addBubble("assistant", "New link established. What are we working today?");
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
  addBubble("assistant", "Chat cleared. Fresh page.");
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
  try { recognition?.abort?.(); } catch (_) {}
  try { recognition?.stop?.(); } catch (_) {}
  recognitionAlive = false;
}

function resumeRecognition() {
  recreateRecognition();
}

function onRecognitionResult(event) {
  lastSpeechActivityAt = Date.now();
  recognitionAlive = true;
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
  if (!shown) return;
  if (looksLikeEcho(shown) || looksLikeFridayPrompt(shown)) {
    finalBuffer = "";
    interimText = "";
    if (turnDetector) turnDetector.reset();
    return;
  }
  setListeningLine(shown, { interim: !finalBuffer || !!interim });
  if (uiState !== "listening") setState("listening");
  scheduleProcess();
}

function onRecognitionError(event) {
  if (event.error === "aborted" || event.error === "no-speech") return;
  if (event.error === "not-allowed") {
    addBubble("assistant", "Mic permission blocked. Allow microphone access for this site.");
    stopVoiceMode();
    return;
  }
  pushActivity(`Mic · ${event.error}`, { live: false });
  // network / no-speech aftermath: force a fresh engine on next end.
  recognitionAlive = false;
}

function onRecognitionEnd() {
  recognitionAlive = false;
  if (!voiceMode || ignoreRecognitionEnd || recreateBusy) return;
  // Natural Chrome end — try start() first; recreate only if the instance is dead.
  setTimeout(() => {
    if (!voiceMode || ignoreRecognitionEnd || recreateBusy) return;
    kickRecognition(2);
  }, 100);
}

function stopVoiceMode() {
  voiceMode = false;
  voiceBusy = false;
  micSuspended = false;
  listenCooldownUntil = 0;
  lastHoldReason = "";
  stopVoiceWatchdog();
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

  ensureTurnDetector();
  if (turnDetector) turnDetector.reset();
  lastSpeechActivityAt = Date.now();
  startVoiceWatchdog();
  recreateRecognition();
  // recreateRecognition boots sync on first start; only fail if the API is missing.
  if (!SpeechRec()) {
    addBubble("assistant", "Mic error: speech recognition is not available in this browser.");
    stopVoiceMode();
  } else if (!recognition && !recreateBusy) {
    // Immediate sync boot failed — one more try, then surface.
    recreateRecognition();
    if (!recognition) {
      addBubble("assistant", "Mic error: speech recognition failed to start. Allow the mic and try again.");
      stopVoiceMode();
    }
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
  ["experience", "Experience"], ["plan", "Plan"],
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
    const mapped = (items || []).map((m) => ({
      ...m,
      kind: "note",
      source: (m.metadata && m.metadata.source) || "memory",
      deletable: true,
      collection: "memories",
      created_at: (m.metadata && m.metadata.created_at) || 0,
    }));
    if (!mapped.length) {
      const list = $("#memList");
      if (list) {
        list.innerHTML = `<div class="muted">No memory hits for “${escapeHtml(q.trim())}”. This is vector memory — not web research. Use Reports → Run report for topics like that.</div>`;
      }
      $("#memStats").textContent = "0 matches";
      return;
    }
    renderMemCards(mapped);
  } catch (_) {
    const list = $("#memList");
    if (list) list.innerHTML = `<div class="muted">Memory search failed.</div>`;
  }
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
        <button type="button" class="plan-del" data-del="${it.id}" title="Remove from today's plan">Delete</button>`;
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
    const active = (jobs || []).filter((j) => j.status === "scheduled" || j.status === "paused");
    if (!active.length) {
      list.innerHTML = `<div class="muted">No queued jobs. Morning briefing / weekly review live in Systems if enabled — one-off reminders show here.</div>`;
      return;
    }
    for (const j of active) {
      const when = j.cron
        ? `repeats ${j.cron}`
        : j.run_at
          ? new Date(j.run_at * 1000).toLocaleString([], {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
              hour12: true,
            })
          : "queued";
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <div>
          <h3>${escapeHtml(j.title || "Task")}</h3>
          <p>${escapeHtml(j.prompt || "")}</p>
          <p class="muted">${escapeHtml(j.status)} · ${escapeHtml(j.skill_id || "")} · ${escapeHtml(when)}</p>
        </div>
        <div class="actions">
          <button class="ghost" data-run="${j.id}">Run now</button>
          <button class="ghost danger" data-cancel="${j.id}">Delete</button>
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
    const profile = (window.__fridayVoiceProfile || "female_us").toLowerCase();
    const wantMale = profile.startsWith("male");
    const wantGb = profile.endsWith("_gb");
    const rank = (v) => {
      const n = `${v.name} ${v.lang}`.toLowerCase();
      let s = 0;
      if (wantGb && (/en(-|_)?(gb|uk)/i.test(v.lang) || /george|ryan|thomas|hazel|susan|sonia|libby/.test(n))) s += 10;
      if (!wantGb && /en(-|_)?us/i.test(v.lang)) s += 4;
      if (wantMale) {
        if (/male|david|mark|george|james|daniel|ravi|richard|guy|tony|christopher|ryan|davis|brian|eric|arthur/.test(n)) s += 12;
        if (/zira|hazel|susan|eva|samantha|karen|moira|tessa|fiona|jenny|aria|natasha|linda|female|hazel/.test(n)) s -= 14;
      } else {
        if (/zira|hazel|susan|eva|samantha|karen|moira|tessa|fiona|jenny|aria|natasha|linda|female/.test(n)) s += 10;
        if (/microsoft.*(zira|hazel)/.test(n)) s += 4;
        if (/male|david|mark|george|james|daniel|ravi|richard|guy|tony|christopher/.test(n)) s -= 12;
      }
      return s;
    };
    const sorted = voices.slice().sort((a, b) => rank(b) - rank(a));
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
    const slice = forSpokenText(text).slice(0, 800);
    if (!slice.trim()) {
      resolve(false);
      return;
    }
    // Chrome: cancel → immediate speak often stays silent; pause briefly + resume.
    try { window.speechSynthesis.cancel(); } catch (_) {}
    const u = new SpeechSynthesisUtterance(slice);
    const voice = pickFemaleBrowserVoice();
    const profile = (window.__fridayVoiceProfile || "female_us").toLowerCase();
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang || (profile.endsWith("_gb") ? "en-GB" : "en-US");
    } else {
      u.lang = profile.endsWith("_gb") ? "en-GB" : "en-US";
    }
    u.rate = window.FridayVoice && FridayVoice.pace() === "fast" ? 1.08
      : window.FridayVoice && FridayVoice.pace() === "slow" ? 0.92
      : (profile.startsWith("male") ? 0.94 : 1.0);
    u.pitch = profile.startsWith("male") ? 0.85 : 1.0;
    const maxMs = Math.min(45000, 2500 + slice.length * 90);
    // Rough duration so the talking clip can restart with the phrase.
    const words = slice.trim().split(/\s+/).filter(Boolean).length;
    nudgeTalkingVideoForUtterance(Math.max(0.7, words / 2.5), slice);
    let settled = false;
    let safety = 0;
    const done = (ok) => {
      if (settled) return;
      settled = true;
      if (safety) clearTimeout(safety);
      resolve(ok);
    };
    safety = setTimeout(() => {
      try { window.speechSynthesis.cancel(); } catch (_) {}
      done(false);
    }, maxMs);
    u.onend = () => done(true);
    u.onerror = () => done(false);
    const go = () => {
      if (!u.voice) {
        const v = pickFemaleBrowserVoice();
        if (v) { u.voice = v; u.lang = v.lang || "en-US"; }
      }
      try {
        window.speechSynthesis.speak(u);
        // Chromium bug: synth can stick in paused state and produce no audio.
        window.speechSynthesis.resume();
      } catch (err) {
        console.warn("[Friday] browser TTS speak failed:", err);
        done(false);
      }
    };
    if (!voice && speechSynthesis.getVoices().length === 0) {
      let started = false;
      const once = () => { if (started) return; started = true; setTimeout(go, 60); };
      speechSynthesis.addEventListener("voiceschanged", once, { once: true });
      setTimeout(once, 280);
      return;
    }
    setTimeout(go, 60);
  });
}

/** Server TTS (Edge). Hard 8s abort so a 403/hang never freezes the voice HUD. */
async function ttsFetchUrl(text) {
  const clean = forSpokenText(text);
  if (!clean) return null;
  const ac = new AbortController();
  // Edge is fast; local SAPI can take a few seconds per sentence.
  const timer = setTimeout(() => ac.abort(), 20000);
  try {
    const rate = (window.__fridayTtsRate)
      || (window.FridayVoice && FridayVoice.edgeRate ? FridayVoice.edgeRate() : "+0%");
    const voice = window.__fridayTtsVoice || undefined;
    const res = await apiFetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean.slice(0, 500), rate, voice }),
      signal: ac.signal,
    });
    if (!res.ok) throw new Error(`TTS HTTP ${res.status}`);
    const blob = await res.blob();
    if ((blob.type || "").startsWith("audio") || blob.size > 1000) return URL.createObjectURL(blob);
  } catch (err) {
    if (err && err.name !== "AbortError") {
      console.warn("[Friday] server TTS failed, using browser voice:", err);
    }
  } finally {
    clearTimeout(timer);
  }
  return null;
}

function playUrl(url, text) {
  return new Promise((resolve) => {
    try { window.FridaySfx && FridaySfx.unlock && FridaySfx.unlock(); } catch (_) {}
    const audio = new Audio(url);
    currentAudio = audio;
    audio.preservesPitch = true;
    // Always 1× — rate is baked into Edge synthesis so it stays natural.
    audio.playbackRate = 1;
    window.FridayLive && FridayLive.attachAudio(audio);
    setAvatarSpeaking(true);
    const phrase = text != null ? String(text) : String(window.__fridayLastSpeakText || "");
    window.__fridayLastSpeakText = phrase;
    const syncMouth = () => {
      const d = audio.duration;
      nudgeTalkingVideoForUtterance(Number.isFinite(d) && d > 0 ? d : 0, phrase);
    };
    if (audio.readyState >= 1) syncMouth();
    else audio.addEventListener("loadedmetadata", syncMouth, { once: true });
    let settled = false;
    let safety = 0;
    const fin = () => {
      if (settled) return;
      settled = true;
      if (safety) clearTimeout(safety);
      try { URL.revokeObjectURL(url); } catch (_) {}
      resolve();
    };
    safety = setTimeout(() => {
      try { audio.pause(); } catch (_) {}
      fin();
    }, 45000);
    audio.onended = fin;
    audio.onerror = () => {
      console.warn("[Friday] audio playback error");
      fin();
    };
    audio._cancel = fin;
    audio.play().catch((err) => {
      console.warn("[Friday] audio.play blocked:", err);
      fin();
    });
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
  setAvatarSpeaking(false);
}

/** Split spoken text on sentence endings so TTS never truncates mid-thought. */
function speakSentences(text) {
  const clean = forSpokenText(text);
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
  setAvatarSpeaking(true);
  try {
    // Prefetch N+1 while N plays. First sentence: fall to browser fast so voice starts now.
    let next = ttsFetchUrl(parts[0]);
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const urlP = next;
      if (i + 1 < parts.length) next = ttsFetchUrl(parts[i + 1]);
      let url = null;
      try {
        url = await Promise.race([
          Promise.resolve(urlP).catch(() => null),
          new Promise((r) => setTimeout(() => r(null), 4500)),
        ]);
      } catch (_) { url = null; }
      if (url) {
        await playUrl(url, part);
        continue;
      }
      window.FridayLive && FridayLive.synthSpeaking(true);
      setAvatarSpeaking(true);
      const ok = await speakBrowser(part);
      if (!ok) console.warn("[Friday] browser TTS unavailable");
    }
  } catch (err) {
    console.warn("[Friday] speak failed:", err);
  } finally {
    setAvatarSpeaking(false);
    window.FridayLive && FridayLive.synthSpeaking(false);
  }
}

/** Pause-line TTS for voice mode. Does not cancel an in-flight reply. */
async function speakFiller(text) {
  const clean = forSpokenText(text);
  if (!clean) return;
  window.FridayLive && FridayLive.state("speaking");
  setAvatarSpeaking(true);
  try {
    const url = await ttsFetchUrl(clean);
    if (url) {
      await playUrl(url, clean);
      return;
    }
    window.FridayLive && FridayLive.synthSpeaking(true);
    await speakBrowser(clean);
  } catch (err) {
    console.warn("[Friday] filler TTS failed:", err);
  } finally {
    setAvatarSpeaking(false);
    window.FridayLive && FridayLive.synthSpeaking(false);
  }
}

// live.js speaks via window.* — classic scripts usually hoist, but set explicitly.
window.ttsFetchUrl = ttsFetchUrl;
window.playUrl = playUrl;
window.speakBrowser = speakBrowser;
window.stopSpeech = stopSpeech;
window.speak = speak;
window.speakFiller = speakFiller;
window.forSpokenText = forSpokenText;
window.setAvatarSpeaking = setAvatarSpeaking;
window.nudgeTalkingVideoForUtterance = nudgeTalkingVideoForUtterance;
window.sanitizeAssistantText = sanitizeAssistantText;

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
      ? `Task update: ${n.title}${n.body ? ". " + n.body : ""}`
      : `Reminder: ${n.title}${n.body ? ". " + n.body : ""}`;
    addBubble("assistant", say, n.kind === "task" ? "task" : "reminder");
    if (speakEnabled() || voiceMode) speak(say);
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("Friday", { body: n.title, tag: n.id });
    }
  }
  rememberShown(n.id);
}

let _lastUnseen = [];
let _notifPollTimer = null;

async function pollNotifications() {
  if (document.hidden) return;
  try {
    const list = await (await apiFetch("/api/notifications?unseen=1")).json();
    _lastUnseen = Array.isArray(list) ? list : [];
    for (const n of _lastUnseen.slice().reverse()) {
      if (!shownReminders.has(n.id)) showReminderPopup(n);
    }
    const badge = $("#bellCount");
    if (badge) {
      badge.textContent = _lastUnseen.length || "";
      badge.classList.toggle("hidden", !_lastUnseen.length);
    }
    // Only hit reminders/upcoming when the panel is open — not every poll.
    if ($("#remPanel") && !$("#remPanel").classList.contains("hidden")) {
      await refreshBell({ reuseUnseen: true });
    }
  } catch (_) {}
}

function scheduleNotifPoll() {
  clearTimeout(_notifPollTimer);
  const ms = document.hidden ? 60000 : 20000;
  _notifPollTimer = setTimeout(async () => {
    await pollNotifications();
    scheduleNotifPoll();
  }, ms);
}

async function refreshBell(opts = {}) {
  try {
    const unseen = opts.reuseUnseen
      ? _lastUnseen
      : await apiFetch("/api/notifications?unseen=1").then((r) => r.json());
    _lastUnseen = Array.isArray(unseen) ? unseen : [];
    const upcoming = await apiFetch("/api/reminders/upcoming").then((r) => r.json());
    const badge = $("#bellCount");
    if (badge) {
      badge.textContent = _lastUnseen.length || "";
      badge.classList.toggle("hidden", !_lastUnseen.length);
    }
    const panel = $("#remList");
    if (panel) {
      const rows = [];
      for (const n of _lastUnseen) rows.push(`<div class="rem-row new"><b>${escapeHtml(n.title)}</b><span class="muted">due now</span></div>`);
      for (const j of (upcoming || []).slice(0, 8)) {
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
      panel.innerHTML = rows.join("") || `<div class="muted">No reminders.</div>`;
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
  if (document.hidden || !voiceMode) return;
  // Chromium kills SpeechRecognition while backgrounded — always fresh instance.
  setTimeout(() => { if (voiceMode) recreateRecognition(); }, 150);
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
  scheduleNotifPoll();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      pollNotifications();
      scheduleNotifPoll();
    }
  });
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
  await refreshPresenceOrbPref();
  await refreshPresence();
  ensureAvatarGaze();
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
