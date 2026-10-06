/* Friday live voice mode: pacing settings, animated orb, captions, spoken fillers, sentence-streamed speech.
 * Loaded before app.js. app.js calls into window.FridayVoice / window.FridayLive; everything degrades to the old
 * behaviour when this file is missing (app.js guards every call). No dependencies, no network. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ settings
  const K_STYLE = "friday.voiceStyle"; // "realtime" | "relaxed"
  const K_SPEED = "friday.voiceSpeed"; // 0.8 .. 1.4
  const STYLES = {
    // pauseMs: silence before a spoken turn is sent. fillerMs: how long a reply may take before Friday says a filler.
    realtime: { pauseMs: 550, fillerMs: 1300, streamSpeech: true, label: "Realtime" },
    relaxed: { pauseMs: 1100, fillerMs: 2400, streamSpeech: false, label: "Relaxed" },
  };
  const Voice = {
    styles: STYLES,
    style() {
      const s = localStorage.getItem(K_STYLE);
      return STYLES[s] ? s : "relaxed"; // relaxed = the previous behaviour, so nothing changes until the owner opts in
    },
    setStyle(s) {
      if (!STYLES[s]) return;
      localStorage.setItem(K_STYLE, s);
      window.FridayLive && FridayLive.syncControls();
    },
    cfg() { return STYLES[Voice.style()]; },
    pauseMs() { return Voice.cfg().pauseMs; },
    speed() {
      const v = parseFloat(localStorage.getItem(K_SPEED) || "1");
      return isFinite(v) ? Math.min(1.4, Math.max(0.8, v)) : 1;
    },
    setSpeed(v) {
      localStorage.setItem(K_SPEED, String(Math.min(1.4, Math.max(0.8, Number(v) || 1))));
      window.FridayLive && FridayLive.syncControls();
    },
  };

  // ------------------------------------------------------------------ audio levels
  let ac = null, micAnalyser = null, micStream = null, outAnalyser = null;
  const outSources = new WeakMap();
  const buf = new Uint8Array(256);

  function ctx() {
    if (!ac) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ac = new AC();
    }
    if (ac.state === "suspended") ac.resume().catch(() => {});
    return ac;
  }

  function levelOf(an) {
    if (!an) return 0;
    an.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < an.fftSize && i < buf.length; i++) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    return Math.min(1, Math.sqrt(sum / Math.min(an.fftSize, buf.length)) * 3.2);
  }

  async function openMic() {
    try {
      const c = ctx();
      if (!c || !navigator.mediaDevices) return;
      micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      micAnalyser = c.createAnalyser();
      micAnalyser.fftSize = 256;
      c.createMediaStreamSource(micStream).connect(micAnalyser); // analysis only: never routed to the speakers
    } catch (_) { micAnalyser = null; }
  }

  function closeMic() {
    try { micStream && micStream.getTracks().forEach((t) => t.stop()); } catch (_) {}
    micStream = null; micAnalyser = null;
  }

  // ------------------------------------------------------------------ orb
  const $ = (s) => document.querySelector(s);
  let overlay, canvas, g, raf = 0, state = "idle", t0 = 0, smooth = 0, speakingSynth = false, open = false;
  const COLORS = {
    listening: ["#3ecbff", "#9be7ff"],
    thinking: ["#ffb347", "#ffd9a0"],
    acting: ["#ff6a2b", "#ffb347"],
    speaking: ["#7dffb2", "#c9ffe0"],
    idle: ["#3ecbff", "#9be7ff"],
  };

  function drawOrb(ts) {
    raf = requestAnimationFrame(drawOrb);
    if (!g) return;
    const t = (ts - t0) / 1000;
    const W = canvas.width, H = canvas.height, cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.24;
    let target = 0;
    if (state === "listening") target = levelOf(micAnalyser);
    else if (state === "speaking") target = outAnalyser && !speakingSynth ? levelOf(outAnalyser) : 0.35 + 0.3 * Math.abs(Math.sin(t * 7.3) * Math.sin(t * 3.1));
    else if (state === "thinking" || state === "acting") target = 0.18 + 0.1 * Math.sin(t * 2.4);
    smooth += (target - smooth) * (target > smooth ? 0.45 : 0.12);
    const [c1, c2] = COLORS[state] || COLORS.idle;
    g.clearRect(0, 0, W, H);

    // soft glow
    const glow = g.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * (1.7 + smooth * 0.3));
    glow.addColorStop(0, c1 + "88"); glow.addColorStop(0.5, c1 + "22"); glow.addColorStop(1, "transparent");
    g.fillStyle = glow; g.fillRect(0, 0, W, H);

    // reactive radial waveform (the "voice")
    const N = 120;
    g.lineWidth = 2.2; g.strokeStyle = c2; g.beginPath();
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * Math.PI * 2 + t * 0.15;
      const wob = Math.sin(a * 5 + t * 3) * 0.5 + Math.sin(a * 9 - t * 2.1) * 0.5;
      const r = R * (1.08 + smooth * 0.55 * wob * (0.5 + 0.5 * Math.sin(a * 3 + t))) + (state === "thinking" ? Math.sin(a * 6 + t * 5) * 2 : 0);
      const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
      i ? g.lineTo(x, y) : g.moveTo(x, y);
    }
    g.closePath(); g.stroke();

    // rotating arcs (HUD rings); thinking/acting spin faster
    const spin = state === "thinking" ? 2.2 : state === "acting" ? 3.2 : 0.5;
    for (let k = 0; k < 3; k++) {
      g.strokeStyle = k === 1 ? c2 : c1; g.globalAlpha = 0.85 - k * 0.2; g.lineWidth = 2 + (k === 0 ? 1.5 : 0);
      const rr = R * (1.55 + k * 0.22), dir = k % 2 ? -1 : 1, a0 = t * spin * dir + k;
      g.beginPath(); g.arc(cx, cy, rr, a0, a0 + Math.PI * (0.55 + 0.15 * k)); g.stroke();
      g.beginPath(); g.arc(cx, cy, rr, a0 + Math.PI, a0 + Math.PI * (1.35 + 0.1 * k)); g.stroke();
    }
    g.globalAlpha = 1;

    // core
    const cr = R * (0.78 + smooth * 0.25 + 0.03 * Math.sin(t * 2));
    const core = g.createRadialGradient(cx - cr * 0.3, cy - cr * 0.3, cr * 0.1, cx, cy, cr);
    core.addColorStop(0, "#ffffff"); core.addColorStop(0.35, c2); core.addColorStop(1, c1);
    g.fillStyle = core; g.beginPath(); g.arc(cx, cy, cr, 0, Math.PI * 2); g.fill();
  }

  // ------------------------------------------------------------------ overlay + captions
  const LABELS = { listening: "LISTENING", thinking: "THINKING", acting: "WORKING ON IT", speaking: "SPEAKING", idle: "READY" };
  const Live = {
    open() {
      overlay = overlay || $("#liveOverlay");
      if (!overlay) return;
      canvas = $("#liveOrb");
      g = canvas.getContext("2d");
      const dpr = Math.min(2, window.devicePixelRatio || 1), size = 420;
      canvas.width = size * dpr; canvas.height = size * dpr;
      canvas.style.width = canvas.style.height = size + "px";
      overlay.classList.remove("hidden");
      document.body.classList.add("live-open");
      open = true; t0 = performance.now();
      Live.user(""); Live.friday("");
      Live.state("listening");
      cancelAnimationFrame(raf); raf = requestAnimationFrame(drawOrb);
      openMic();
      Live.syncControls();
    },
    close() {
      if (!overlay) return;
      open = false;
      overlay.classList.add("hidden");
      document.body.classList.remove("live-open");
      cancelAnimationFrame(raf);
      closeMic();
    },
    isOpen() { return open; },
    state(s) {
      const m = { thinking: "thinking", acting: "acting", listening: "listening", idle: open ? "listening" : "idle", speaking: "speaking", running: "acting" };
      state = m[s] || state;
      const el = $("#liveState");
      if (el) el.textContent = LABELS[state] || state.toUpperCase();
      if (overlay) overlay.dataset.state = state;
    },
    user(text, interim) {
      const el = $("#capUser");
      if (!el) return;
      el.textContent = text && text !== "…" ? text : "";
      el.classList.toggle("interim", !!interim);
      if (text && text !== "…") { const f = $("#capFriday"); if (f) f.classList.add("faded"); }
    },
    friday(text, { filler = false } = {}) {
      const el = $("#capFriday");
      if (!el) return;
      const t = String(text || "").replace(/\s+/g, " ").trim();
      el.textContent = t.length > 300 ? "…" + t.slice(-300) : t;
      el.classList.toggle("filler", filler);
      el.classList.toggle("faded", !t);
    },
    attachAudio(audio) {
      try {
        const c = ctx();
        if (!c) return;
        if (!outAnalyser) { outAnalyser = c.createAnalyser(); outAnalyser.fftSize = 256; outAnalyser.connect(c.destination); }
        if (!outSources.has(audio)) {
          const src = c.createMediaElementSource(audio);
          src.connect(outAnalyser);
          outSources.set(audio, src);
        }
        speakingSynth = false;
      } catch (_) { speakingSynth = true; }
    },
    synthSpeaking(on) { speakingSynth = !!on; },
    syncControls() {
      const st = Voice.style(), sp = Voice.speed();
      document.querySelectorAll("[data-voice-style]").forEach((b) => b.classList.toggle("on", b.dataset.voiceStyle === st));
      document.querySelectorAll("input[data-voice-speed]").forEach((i) => { if (Number(i.value) !== sp) i.value = sp; });
      document.querySelectorAll("[data-voice-speed-label]").forEach((l) => { l.textContent = sp.toFixed(2) + "×"; });
    },
    interrupt() { // barge-in: stop talking immediately
      Live._speaker && Live._speaker.abort();
      if (window.stopSpeech) window.stopSpeech();
    },

    // ---------------------------------------------------------------- fillers
    FILLERS: {
      thinking: ["Let me think about that.", "One moment.", "Let me grab a few details.", "Give me a second.", "Let me check on that."],
      acting: ["On it. I'll take care of that on your screen.", "Okay, working on that now.", "Sure. Give me a moment while I do that."],
      lookup: ["Let me look that up.", "Checking that now."],
    },
    fillers(speaker, kind) {
      let timer = 0, spoken = 0, stopped = false, idx = Math.floor(Math.random() * 5);
      const say = (type) => {
        if (stopped || spoken >= 2) return;
        const list = Live.FILLERS[type] || Live.FILLERS.thinking;
        const text = list[idx++ % list.length];
        spoken++;
        Live.friday(text, { filler: true });
        if (speaker) speaker.say(text, { filler: true });
      };
      return {
        start() { timer = setTimeout(() => say(kind || "thinking"), Voice.cfg().fillerMs); },
        agent() { clearTimeout(timer); say("acting"); },  // desktop work starts: announce it right away
        lookup() { if (!spoken) { clearTimeout(timer); timer = setTimeout(() => say("lookup"), 400); } },
        stop() { stopped = true; clearTimeout(timer); },
        count() { return spoken; },
      };
    },

    // ---------------------------------------------------------------- sentence-streamed speech
    /* speaker.push(textChunk) as tokens arrive; speaker.finish() flushes; await speaker.done().
     * Audio for sentence N+1 is fetched while N plays, so there is no gap and the first words start early. */
    speaker({ onFirst } = {}) {
      let pending = "", chain = Promise.resolve(), aborted = false, first = true, spokenReal = 0;
      const fetches = [];
      const sp = {
        spoken() { return spokenReal; },
        say(text, { filler = false } = {}) {
          const clean = String(text || "").replace(/[*_`#>]/g, "").trim();
          if (!clean || aborted) return;
          if (first) { first = false; onFirst && onFirst(); }
          const pre = window.ttsFetchUrl ? window.ttsFetchUrl(clean) : Promise.resolve(null);
          fetches.push(pre);
          chain = chain.then(async () => {
            if (aborted) return;
            Live.state("speaking");
            if (!filler) { Live.friday(clean); spokenReal++; }
            const url = await pre;
            if (aborted) return;
            if (url) await window.playUrl(url);
            else { Live.synthSpeaking(true); await window.speakBrowser(clean); }
          }).catch(() => {});
        },
        push(chunk) {
          pending += chunk;
          for (;;) {
            const re = /[.!?\u2026]+["')\]]*\s+|\n+/g;
            let m, cut = -1;
            while ((m = re.exec(pending))) {
              const end = m.index + m[0].length;
              if (end >= 18 || m[0].includes("\n")) { cut = end; break; } // "3.5" has no space after the dot: never split there
            }
            if (cut < 0) break;
            sp.say(pending.slice(0, cut));
            pending = pending.slice(cut);
          }
        },
        finish() { if (pending.trim()) sp.say(pending); pending = ""; },
        done() { return chain.then(() => { if (open) Live.state("listening"); }); },
        abort() { aborted = true; pending = ""; },
      };
      Live._speaker = sp;
      return sp;
    },
  };

  window.FridayVoice = Voice;
  window.FridayLive = Live;

  document.addEventListener("DOMContentLoaded", () => {
    $("#liveClose")?.addEventListener("click", () => document.getElementById("btnMic")?.click());
    $("#liveOrb")?.addEventListener("click", () => Live.interrupt());
    document.querySelectorAll("[data-voice-style]").forEach((b) => b.addEventListener("click", () => Voice.setStyle(b.dataset.voiceStyle)));
    document.querySelectorAll("input[data-voice-speed]").forEach((i) => i.addEventListener("input", () => Voice.setSpeed(i.value)));
    Live.syncControls();
  });
})();
