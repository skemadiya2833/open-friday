/* Friday live voice mode: pacing settings, animated orb, captions, spoken fillers, sentence-streamed speech.
 * Loaded before app.js. app.js calls into window.FridayVoice / window.FridayLive; everything degrades to the old
 * behaviour when this file is missing (app.js guards every call). No dependencies, no network. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ settings
  const K_STYLE = "friday.voiceStyle"; // "realtime" | "relaxed"
  const K_PACE = "friday.voicePace"; // "slow" | "normal" | "fast" — Edge rate, not warped playback
  const K_DUPLEX = "friday.voiceDuplex"; // "hold" | "interrupt"
  const STYLES = {
    // Monitor speakers + desk mic: industry default is half-duplex (Hold) + echo tail.
    // Realtime streams Edge neural sentence-by-sentence; Relaxed speaks after the full reply.
    // eagerness mirrors OpenAI semantic_vad bands (ideas only) — see turn.js + docs/design/voice_turntaking.md
    // pauseMs kept as a legacy fallback if turn.js fails to load.
    // Realtime: speak the first phrase ASAP (eager cut + caption-only thinking fillers).
    realtime: { pauseMs: 450, fillerMs: 0, streamSpeech: true, label: "Realtime", eagerness: "high" },
    relaxed: { pauseMs: 1400, fillerMs: 700, streamSpeech: false, label: "Relaxed", eagerness: "low" },
  };
  const PACE_RATE = { slow: "-18%", normal: "+0%", fast: "+18%" };
  const Voice = {
    styles: STYLES,
    style() {
      const s = localStorage.getItem(K_STYLE);
      return STYLES[s] ? s : "realtime";
    },
    setStyle(s) {
      if (!STYLES[s]) return;
      localStorage.setItem(K_STYLE, s);
      window.FridayLive && FridayLive.syncControls();
    },
    // hold (default): mic gated while Friday talks — required for speaker+mic desks.
    duplex() {
      const d = localStorage.getItem(K_DUPLEX);
      return d === "interrupt" ? "interrupt" : "hold";
    },
    setDuplex(d) {
      if (d !== "hold" && d !== "interrupt") return;
      localStorage.setItem(K_DUPLEX, d);
      window.FridayLive && FridayLive.syncControls();
    },
    isHold() { return Voice.duplex() === "hold"; },
    cfg() { return STYLES[Voice.style()]; },
    pauseMs() { return Voice.cfg().pauseMs; },
    eagerness() { return Voice.cfg().eagerness || "medium"; },
    // Natural 1× playback; pace adjusts Edge synthesis rate (say "speak slower/faster").
    pace() {
      const p = localStorage.getItem(K_PACE);
      return p === "slow" || p === "fast" ? p : "normal";
    },
    setPace(p) {
      if (p !== "slow" && p !== "normal" && p !== "fast") return;
      localStorage.setItem(K_PACE, p);
      window.FridayLive && FridayLive.syncControls();
    },
    edgeRate() { return PACE_RATE[Voice.pace()] || "+0%"; },
    // Compat for older call sites — always natural playback (no chipmunk slider).
    speed() { return 1; },
    setSpeed() { /* slider removed — use setPace / voice commands */ },
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
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      micAnalyser = c.createAnalyser();
      micAnalyser.fftSize = 512;
      micAnalyser.smoothingTimeConstant = 0.22; // snappier orb reaction to speech
      c.createMediaStreamSource(micStream).connect(micAnalyser); // analysis only: never routed to the speakers
    } catch (_) { micAnalyser = null; }
  }

  function closeMic() {
    try { micStream && micStream.getTracks().forEach((t) => t.stop()); } catch (_) {}
    micStream = null; micAnalyser = null;
  }

  // ------------------------------------------------------------------ orb
  const $ = (s) => document.querySelector(s);
  let overlay, canvas, g, raf = 0, state = "idle", t0 = 0, speakingSynth = false, open = false;
  const COLORS_DEFAULT = {
    listening: ["#3ecbff", "#9be7ff"],
    thinking: ["#ffb347", "#ffd9a0"],
    acting: ["#ff6a2b", "#ffb347"],
    speaking: ["#7dffb2", "#c9ffe0"],
    idle: ["#3ecbff", "#9be7ff"],
  };
  function skinColors() {
    try {
      const s = getComputedStyle(document.body);
      const a = (s.getPropertyValue("--accent") || "").trim();
      const a2 = (s.getPropertyValue("--accent-2") || "").trim();
      const c = (s.getPropertyValue("--cyan") || "").trim();
      if (!a || !a2 || !c) return COLORS_DEFAULT;
      return {
        listening: [c, a2],
        thinking: [a2, a],
        acting: [a, a2],
        speaking: [a2, c],
        idle: [c, a2],
      };
    } catch (_) {
      return COLORS_DEFAULT;
    }
  }
  const COLORS = COLORS_DEFAULT;

  // Real spectrum -> radial bars. Per-bar attack/decay smoothing + automatic gain, so quiet and loud voices both move the orb.
  const NB = 72, freq = new Uint8Array(256), bars = new Float32Array(NB);
  let peak = 60, lastTs = 0, level = 0, kick = 0;

  function spectrum(an, out) {
    an.getByteFrequencyData(freq);
    let fmax = 0;
    for (let i = 1; i < 56; i++) if (freq[i] > fmax) fmax = freq[i];
    peak = Math.max(60, peak * 0.992, fmax);                 // slow-decaying auto gain
    const half = NB / 2;
    for (let i = 0; i < half; i++) {
      const bin = 1 + Math.floor(Math.pow(i / half, 1.35) * 54); // low bins get more bars: that is where voice energy is
      const v = Math.min(1, (freq[bin] / peak) * 1.15);
      out[i] = v; out[NB - 1 - i] = v;                       // mirror so the ring is symmetric
    }
  }

  function drawOrb(ts) {
    raf = requestAnimationFrame(drawOrb);
    if (!g) return;
    const dt = Math.min(0.05, Math.max(0.001, (ts - (lastTs || ts)) / 1000));
    lastTs = ts;
    const t = (ts - t0) / 1000;
    const W = canvas.width, H = canvas.height, cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.2;
    const target = new Float32Array(NB);
    const an = state === "listening" ? micAnalyser : state === "speaking" && !speakingSynth ? outAnalyser : null;
    if (an) spectrum(an, target);
    else if (state === "speaking") {          // browser voice (no audio tap): plausible speech-like motion
      for (let i = 0; i < NB; i++) target[i] = Math.max(0, 0.55 * Math.sin(i * 0.5 + t * 9) * Math.sin(t * 3.3 + i * 0.12) + 0.3 * Math.sin(t * 6)) * 0.9;
    } else {                                   // thinking / acting / idle: slow travelling wave
      const amp = state === "idle" ? 0.05 : 0.2;
      for (let i = 0; i < NB; i++) target[i] = amp * (0.5 + 0.5 * Math.sin(i * 0.35 - t * (state === "acting" ? 5 : 3)));
    }
    let sum = 0;
    // Faster attack/release so the orb tracks speech instead of lagging a beat behind.
    const a = 1 - Math.exp(-dt * 48), d = 1 - Math.exp(-dt * 14);
    for (let i = 0; i < NB; i++) {
      bars[i] += (target[i] - bars[i]) * (target[i] > bars[i] ? a : d);
      sum += bars[i];
    }
    level += (sum / NB - level) * (1 - Math.exp(-dt * 22));
    kick += (level - kick) * (1 - Math.exp(-dt * 10));
    const pal = skinColors();
    const [c1, c2] = pal[state] || pal.idle;
    g.clearRect(0, 0, W, H);

    const gl = g.createRadialGradient(cx, cy, R * 0.3, cx, cy, R * (1.9 + level * 0.9));
    gl.addColorStop(0, c1 + "77"); gl.addColorStop(0.55, c1 + "1f"); gl.addColorStop(1, "transparent");
    g.fillStyle = gl; g.beginPath(); g.arc(cx, cy, Math.min(cx, R * (1.9 + level * 0.9)), 0, Math.PI * 2); g.fill();

    // radial voice bars
    const r0 = R * (1.12 + kick * 0.18);
    g.lineCap = "round"; g.lineWidth = Math.max(2.5, (W / 420) * 3.4);
    const rot = t * (state === "thinking" ? 0.5 : state === "acting" ? 0.9 : 0.12);
    for (let i = 0; i < NB; i++) {
      const ang = (i / NB) * Math.PI * 2 + rot - Math.PI / 2;
      const len = R * (0.07 + bars[i] * 0.95);
      g.strokeStyle = i % 3 === 0 ? c2 : c1;
      g.globalAlpha = 0.55 + 0.45 * Math.min(1, bars[i] * 1.6);
      g.beginPath();
      g.moveTo(cx + Math.cos(ang) * r0, cy + Math.sin(ang) * r0);
      g.lineTo(cx + Math.cos(ang) * (r0 + len), cy + Math.sin(ang) * (r0 + len));
      g.stroke();
    }
    g.globalAlpha = 1;

    // HUD arcs (speed up while thinking / working)
    const spin = state === "thinking" ? 1.8 : state === "acting" ? 2.8 : 0.3;
    for (let k = 0; k < 2; k++) {
      const rr = R * (2.05 + k * 0.22), dir = k ? -1 : 1, a0 = t * spin * dir + k * 2;
      g.strokeStyle = k ? c2 : c1; g.globalAlpha = 0.5; g.lineWidth = 2;
      g.beginPath(); g.arc(cx, cy, rr, a0, a0 + Math.PI * 0.6); g.stroke();
      g.beginPath(); g.arc(cx, cy, rr, a0 + Math.PI, a0 + Math.PI * 1.35); g.stroke();
    }
    g.globalAlpha = 1;

    // core: swells with the voice
    const cr = R * (0.8 + kick * 0.5) * (1 + 0.025 * Math.sin(t * 2.2));
    const core = g.createRadialGradient(cx - cr * 0.3, cy - cr * 0.3, cr * 0.1, cx, cy, cr);
    core.addColorStop(0, "#ffffff"); core.addColorStop(0.35, c2); core.addColorStop(1, c1);
    g.fillStyle = core; g.beginPath(); g.arc(cx, cy, cr, 0, Math.PI * 2); g.fill();
  }

  // ------------------------------------------------------------------ overlay + captions
  const LABELS = { listening: "LISTENING", thinking: "THINKING", acting: "WORKING ON IT", speaking: "SPEAKING", idle: "READY" };
  const Live = {
    _sizeCanvas() {
      canvas = canvas || $("#liveOrb");
      if (!canvas) return;
      const css = Math.max(48, Math.round(canvas.getBoundingClientRect().width || 58));
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(css * dpr);
      canvas.height = Math.round(css * dpr);
    },
    /** Keep the left-rail Friday circle alive even when voice mode is closed. */
    ensurePresence() {
      canvas = canvas || $("#liveOrb");
      if (!canvas) return;
      if (!g) g = canvas.getContext("2d");
      Live._sizeCanvas();
      if (!raf) {
        t0 = performance.now();
        raf = requestAnimationFrame(drawOrb);
      }
    },
    open() {
      overlay = overlay || $("#liveOverlay");
      if (!overlay) return;
      Live.ensurePresence();
      overlay.classList.remove("hidden");
      document.body.classList.add("live-open");
      open = true; t0 = performance.now();
      Live.user("");
      const cap = $("#capFriday");
      if (cap) { cap.textContent = ""; cap.classList.add("faded"); }
      Live.clearResult();
      Live.state("listening");
      requestAnimationFrame(() => Live._sizeCanvas());
      openMic();
      Live.syncControls();
      // Prefetch browser voices so Realtime picks a female voice on first utterance.
      try { window.speechSynthesis && speechSynthesis.getVoices(); } catch (_) {}
    },
    close() {
      if (!overlay) return;
      open = false;
      overlay.classList.add("hidden");
      overlay.classList.remove("has-result", "show-type");
      document.body.classList.remove("live-open");
      closeMic();
      // Orb stays on the left rail — keep a quiet idle pulse.
      Live.state("idle");
      Live.ensurePresence();
    },
    isOpen() { return open; },
    isSpeaking() { return state === "speaking"; },
    stateName() { return state; },
    lastSpoken() { return Live._lastSpoken || ""; },
    /** RMS mic level 0..1 for turn-taking (Web Audio Analyser). */
    micLevel() {
      if (!micAnalyser) return 0;
      return levelOf(micAnalyser);
    },
    state(s) {
      const m = { thinking: "thinking", acting: "acting", listening: "listening", idle: open ? "listening" : "idle", speaking: "speaking", running: "acting" };
      const next = m[s] || state;
      if (next === state) return; // avoid yellow/blue thrash from redundant updates
      state = next;
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
      const clean = typeof window.sanitizeAssistantText === "function"
        ? window.sanitizeAssistantText(text)
        : String(text || "");
      const t = String(clean || "").replace(/\s+/g, " ").trim();
      // Full spoken line — CSS wraps/scrolls; never clip mid-word in the rail.
      el.textContent = t;
      el.classList.toggle("filler", filler);
      el.classList.toggle("faded", !t);
      el.scrollTop = el.scrollHeight;
    },
    activity(message, { live = true } = {}) {
      // Never open the RESULT panel for pipeline chatter — that panel is for the reply.
      // Keep at most one quiet hint under the captions.
      const hint = $("#liveHint");
      if (!hint || !message) return;
      const t = String(message).trim();
      if (!t) return;
      hint.textContent = t;
      hint.classList.toggle("live", !!live);
      hint.classList.remove("hidden");
    },
    clearHint() {
      const hint = $("#liveHint");
      if (!hint) return;
      hint.textContent = "";
      hint.classList.add("hidden");
      hint.classList.remove("live");
    },
    result(text, { append = false } = {}) {
      const reply = $("#liveReply");
      const box = $("#liveResults");
      overlay = overlay || $("#liveOverlay");
      if (!reply) return;
      const t = String(text || "");
      if (!t.trim() && !append) return;
      // Short spoken replies live in the caption — RESULT docks at the bottom for long output only.
      const short = !append && t.replace(/\s+/g, " ").trim().length <= 420;
      if (short) {
        this.friday(t);
        if (box) box.hidden = true;
        if (overlay) overlay.classList.remove("has-result");
        reply.textContent = "";
        return;
      }
      if (box) box.hidden = false;
      if (overlay) overlay.classList.add("has-result");
      if (append) reply.textContent += t;
      else reply.textContent = t;
      reply.scrollTop = reply.scrollHeight;
    },
    clearResult() {
      const reply = $("#liveReply");
      const feed = $("#liveActivity");
      const box = $("#liveResults");
      overlay = overlay || $("#liveOverlay");
      if (reply) reply.textContent = "";
      if (feed) feed.replaceChildren();
      if (box) box.hidden = true;
      if (overlay) overlay.classList.remove("has-result");
      this.clearHint();
    },
    attachAudio(audio) {
      try {
        const c = ctx();
        if (!c) return;
        if (!outAnalyser) { outAnalyser = c.createAnalyser(); outAnalyser.fftSize = 512; outAnalyser.smoothingTimeConstant = 0.55; outAnalyser.connect(c.destination); }
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
      const st = Voice.style(), dx = Voice.duplex(), pace = Voice.pace();
      document.querySelectorAll("[data-voice-style]").forEach((b) => b.classList.toggle("on", b.dataset.voiceStyle === st));
      document.querySelectorAll("[data-voice-duplex]").forEach((b) => b.classList.toggle("on", b.dataset.voiceDuplex === dx));
      document.querySelectorAll("[data-voice-pace]").forEach((b) => b.classList.toggle("on", b.dataset.voicePace === pace));
      document.querySelectorAll("[data-voice-speed-wrap]").forEach((el) => { el.hidden = true; });
      const orb = $("#liveOrb");
      if (orb) {
        orb.title = Voice.isHold()
          ? "Speaker-safe Hold — mic muted while Friday talks. Click to stop her."
          : "Interrupt — speak to barge in (echo risk with open speakers). Click to stop.";
      }
    },
    nudge(amt) {
      const v = Math.max(0.15, Math.min(1, Number(amt) || 0.45));
      kick = Math.max(kick, v);
      for (let i = 0; i < NB; i++) bars[i] = Math.max(bars[i], v * (0.35 + 0.65 * Math.abs(Math.sin(i * 0.4 + performance.now() / 90))));
    },
    interrupt() { // barge-in: stop talking immediately
      Live._speaker && Live._speaker.abort();
      if (window.stopSpeech) window.stopSpeech();
      if (open) Live.state("listening");
    },

    // ---------------------------------------------------------------- fillers (spoken + captions)
    FILLERS: {
      thinking: [
        "Hold on boss, let me look into that.",
        "One moment.",
        "Give me a second.",
        "Let me check on that.",
        "On it — thinking.",
      ],
      // Soft beats while the model is still cold / generating — keep presence, not chatter.
      progress: [
        "Still working on it.",
        "Hang on — almost there.",
        "Still thinking that through.",
        "One more beat.",
      ],
      acting: [
        "On it. I'll take care of that on your screen.",
        "Okay boss, working on that now.",
        "Sure — give me a moment while I do that.",
      ],
      lookup: [
        "Let me look that up.",
        "Checking that now.",
        "Hold on, pulling that up.",
      ],
      looking: [
        "Hold on boss, let me look into that.",
        "One sec — checking the camera.",
        "Alright, eyes on your desk.",
        "Lemme take a look.",
      ],
    },
    fillers(speaker, kind) {
      let timer = 0, beat = 0, spoken = 0, stopped = false;
      let idx = Math.floor(Math.random() * 5);
      let progIdx = Math.floor(Math.random() * 4);
      let audioChain = Promise.resolve();
      // Realtime: captions only for thinking — audio fillers steal the TTS queue from the answer.
      const speakAudio = !!speaker && !Voice.cfg().streamSpeech;
      const say = (type, { audio = speakAudio } = {}) => {
        if (stopped || spoken >= 4) return;
        const list = Live.FILLERS[type] || Live.FILLERS.thinking;
        const pick = type === "progress" ? (progIdx++ % list.length) : (idx++ % list.length);
        const text = list[pick];
        spoken++;
        Live.friday(text, { filler: true });
        Live.activity(text, { live: true });
        if (!audio) return;
        audioChain = audioChain.then(async () => {
          if (stopped) return;
          if (typeof window.speakFiller === "function") {
            await window.speakFiller(text);
          } else if (speaker && typeof speaker.say === "function") {
            speaker.say(text, { filler: true });
            if (typeof speaker.done === "function") await speaker.done();
          }
        }).catch(() => {});
      };
      const clearBeat = () => { if (beat) { clearInterval(beat); beat = 0; } };
      const armBeat = () => {
        clearBeat();
        // Long Ollama warmups leave dead air after the first filler — keep a soft pulse.
        beat = setInterval(() => {
          if (stopped || spoken >= 4) { clearBeat(); return; }
          // Later beats: caption always; speak at most every other so it doesn't nag.
          say("progress", { audio: speakAudio && spoken < 3 && spoken % 2 === 1 });
        }, Voice.cfg().streamSpeech ? 4500 : 6000);
      };
      return {
        // Realtime: speak sooner so "hold on boss" lands before a fast reply.
        start() {
          // Realtime: no spoken/caption thinking fillers — they add delay before the answer.
          if (Voice.cfg().streamSpeech) return;
          const ms = Voice.cfg().fillerMs || 900;
          timer = setTimeout(() => {
            say(kind || "thinking");
            armBeat();
          }, ms);
        },
        agent() { clearTimeout(timer); clearBeat(); say("acting"); armBeat(); },
        lookup() { if (!spoken) { clearTimeout(timer); timer = setTimeout(() => { say("lookup"); armBeat(); }, 400); } },
        looking() { clearTimeout(timer); clearBeat(); say("looking"); armBeat(); },
        // Caption-only thinking scraps from the model (never spoken — too long / raw).
        thinking(snippet) {
          if (stopped || !snippet) return;
          const t = String(snippet).replace(/\s+/g, " ").trim();
          if (!t) return;
          Live.friday(t.length > 160 ? t.slice(0, 157) + "…" : t, { filler: true });
          Live.activity("Thinking…", { live: true });
        },
        stop() { stopped = true; clearTimeout(timer); clearBeat(); },
        abort() {
          stopped = true;
          clearTimeout(timer);
          clearBeat();
          try { window.stopSpeech && window.stopSpeech(); } catch (_) {}
          audioChain = Promise.resolve();
        },
        ready() { return audioChain; },
        count() { return spoken; },
      };
    },

    // ---------------------------------------------------------------- sentence-streamed speech
    /* Neural TTS when ready; first phrase falls through to browser fast so speech starts now.
     * Realtime: eager first cut (clause / ~28 chars) — Jarvis-style talk-as-you-think. */
    speaker({ onFirst } = {}) {
      let pending = "", chain = Promise.resolve(), aborted = false, first = true, spokenReal = 0;
      let eagerFirst = false;
      const trail = [];
      const sp = {
        spoken() { return spokenReal; },
        say(text, { filler = false } = {}) {
          const clean = String(text || "").replace(/[*_`#>]/g, "").trim();
          if (!clean || aborted) return;
          if (first) { first = false; onFirst && onFirst(); }
          // One engine for the whole reply — neural first, browser only if neural fails.
          // (Browser-first on phrase 1 caused two different voices mid-answer.)
          const pre = window.ttsFetchUrl ? window.ttsFetchUrl(clean) : Promise.resolve(null);
          chain = chain.then(async () => {
            if (aborted) return;
            Live.state("speaking");
            if (!filler) {
              Live.friday(clean);
              spokenReal++;
              Live._lastSpoken = clean;
              trail.push(clean);
              if (trail.length > 6) trail.shift();
              Live._spokenTrail = trail.slice();
            }
            const url = await Promise.race([
              Promise.resolve(pre).catch(() => null),
              new Promise((r) => setTimeout(() => r(null), 4500)),
            ]);
            if (aborted) return;
            const play = url && window.playUrl
              ? window.playUrl(url)
              : (window.speakBrowser
                ? (Live.synthSpeaking(true), window.speakBrowser(clean))
                : Promise.resolve());
            await Promise.race([
              Promise.resolve(play).catch(() => {}),
              new Promise((r) => setTimeout(r, 45000)),
            ]);
          }).catch(() => {});
        },
        push(chunk) {
          pending += chunk;
          for (;;) {
            // Full sentence endings.
            const re = /[.!?\u2026]+["')\]]*(?:\s+|$)|(?:\r?\n){2,}/g;
            let m, cut = -1;
            while ((m = re.exec(pending))) {
              const end = m.index + m[0].length;
              if (end >= 4 || m[0].includes("\n")) { cut = end; break; }
            }
            // First utterance: start ASAP on a short phrase — don't wait for a period.
            if (cut < 0 && spokenReal === 0 && !eagerFirst) {
              const clause = /[,:;]\s+| — | – | - /g;
              let cm;
              while ((cm = clause.exec(pending))) {
                const end = cm.index + cm[0].length;
                if (end >= 12) { cut = end; eagerFirst = true; break; }
              }
              if (cut < 0 && pending.length >= 16) {
                const space = pending.lastIndexOf(" ", Math.min(40, pending.length));
                if (space >= 10) { cut = space + 1; eagerFirst = true; }
              }
            }
            // Soft overflow at a word boundary if a sentence never arrived.
            if (cut < 0 && pending.length > 80) {
              const space = pending.lastIndexOf(" ", 72);
              if (space >= 16) cut = space + 1;
            }
            if (cut < 0) break;
            sp.say(pending.slice(0, cut));
            pending = pending.slice(cut);
          }
        },
        finish() { if (pending.trim()) sp.say(pending); pending = ""; },
        // App owns listening after echo-tail cool-down (half-duplex re-arm).
        done() {
          return Promise.race([
            chain.then(() => {}),
            new Promise((r) => setTimeout(r, 90000)),
          ]);
        },
        abort() { aborted = true; pending = ""; },
      };
      Live._speaker = sp;
      Live._spokenTrail = trail;
      return sp;
    },
  };

  window.FridayVoice = Voice;
  window.FridayLive = Live;

  document.addEventListener("DOMContentLoaded", () => {
    Live.ensurePresence();
    window.addEventListener("resize", () => Live._sizeCanvas());
    $("#liveClose")?.addEventListener("click", () => document.getElementById("btnMic")?.click());
    $("#liveOrb")?.addEventListener("click", () => {
      if (!open) {
        document.getElementById("btnMic")?.click();
        return;
      }
      Live.interrupt();
      if (typeof window.onFridayLiveInterrupt === "function") window.onFridayLiveInterrupt();
    });
    $("#liveTypeToggle")?.addEventListener("click", () => {
      overlay = overlay || $("#liveOverlay");
      if (!overlay) return;
      overlay.classList.toggle("show-type");
      const on = overlay.classList.contains("show-type");
      $("#liveTypeToggle").textContent = on ? "Hide type" : "Type";
      if (on) {
        const ta = $("#liveInput");
        try { ta?.focus(); } catch (_) {}
      }
    });
    $("#liveResultsClear")?.addEventListener("click", () => Live.clearResult());
    $("#liveCompose")?.addEventListener("submit", (e) => {
      e.preventDefault();
      const ta = $("#liveInput");
      const text = (ta?.value || "").trim();
      if (!text) return;
      if (ta) ta.value = "";
      if (typeof window.sendMessage === "function") {
        window.sendMessage(text, { fromVoice: false });
      } else {
        const main = document.getElementById("input");
        if (main) {
          main.value = text;
          document.getElementById("composer")?.requestSubmit?.();
        }
      }
    });
    $("#liveInput")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        $("#liveCompose")?.requestSubmit?.();
      }
    });
    document.querySelectorAll("[data-voice-style]").forEach((b) => b.addEventListener("click", () => Voice.setStyle(b.dataset.voiceStyle)));
    document.querySelectorAll("[data-voice-duplex]").forEach((b) => b.addEventListener("click", () => Voice.setDuplex(b.dataset.voiceDuplex)));
    document.querySelectorAll("[data-voice-pace]").forEach((b) => b.addEventListener("click", () => Voice.setPace(b.dataset.voicePace)));
    Live.syncControls();
  });
})();
