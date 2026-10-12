/* Procedural UI audio — no samples, no speech-like formants */
(function () {
  "use strict";

  const MASTER = 0.28;
  const MAX_VOICES = 4;
  const K_MUTE = "friday_sfx_mute";
  const K_CAT = "friday_sfx_cat"; // JSON { ui, alert, power, data }

  let ctx = null;
  let master = null;
  let unlocked = false;
  let active = 0;

  const defaultCats = { ui: true, alert: true, power: true, data: true };

  function cats() {
    try {
      return { ...defaultCats, ...JSON.parse(localStorage.getItem(K_CAT) || "{}") };
    } catch (_) {
      return { ...defaultCats };
    }
  }

  function saveCats(c) {
    localStorage.setItem(K_CAT, JSON.stringify(c));
  }

  function muted() {
    return localStorage.getItem(K_MUTE) === "1";
  }

  function prefersReduced() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function voiceActive() {
    const app = window.FridayApp;
    if (app) {
      if (app.voiceMode && app.voiceMode()) return true;
      if (app.voiceBusy && app.voiceBusy()) return true;
      const st = app.uiState && app.uiState();
      if (st === "listening" || st === "speaking") return true;
    }
    if (window.FridayLive && FridayLive.isOpen && FridayLive.isOpen()) {
      if (FridayLive.isSpeaking && FridayLive.isSpeaking()) return true;
      const s = FridayLive.stateName && FridayLive.stateName();
      if (s === "listening" || s === "speaking") return true;
    }
    return false;
  }

  function ensureCtx() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = MASTER;
    master.connect(ctx.destination);
    return ctx;
  }

  function unlock() {
    if (unlocked) return;
    const c = ensureCtx();
    if (!c) return;
    if (c.state === "suspended") c.resume().catch(() => {});
    unlocked = true;
  }

  function schedule(fn) {
    if (muted() || !unlocked) return;
    if (voiceActive()) return;
    if (active >= MAX_VOICES) return;
    const c = ensureCtx();
    if (!c) return;
    active += 1;
    try {
      fn(c, master, () => {
        active = Math.max(0, active - 1);
      });
    } catch (_) {
      active = Math.max(0, active - 1);
    }
  }

  function tone(c, dest, { f0, f1, dur, type, gain, when }) {
    const t0 = when || c.currentTime;
    const osc = c.createOscillator();
    const g = c.createGain();
    osc.type = type || "sine";
    osc.frequency.setValueAtTime(f0, t0);
    if (f1 != null) osc.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(Math.max(0.0001, gain), t0 + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g);
    g.connect(dest);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  }

  function noiseBurst(c, dest, { dur, freq, gain, when }) {
    const t0 = when || c.currentTime;
    const len = Math.floor(c.sampleRate * dur);
    const buf = c.createBuffer(1, len, c.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / len);
    const src = c.createBufferSource();
    src.buffer = buf;
    const bp = c.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = freq || 3200;
    bp.Q.value = 8;
    const g = c.createGain();
    g.gain.value = gain || 0.15;
    src.connect(bp);
    bp.connect(g);
    g.connect(dest);
    src.start(t0);
    src.stop(t0 + dur);
  }

  const cues = {
    servo(c, dest, done) {
      tone(c, dest, { f0: 180, f1: 420, dur: 0.12, type: "triangle", gain: 0.12 });
      noiseBurst(c, dest, { dur: 0.05, freq: 2800, gain: 0.06, when: c.currentTime + 0.04 });
      setTimeout(done, 140);
    },
    relay(c, dest, done) {
      tone(c, dest, { f0: 880, f1: 220, dur: 0.04, type: "square", gain: 0.05 });
      setTimeout(done, 50);
    },
    chirp(c, dest, done) {
      tone(c, dest, { f0: 1200, f1: 2400, dur: 0.07, type: "sine", gain: 0.08 });
      tone(c, dest, { f0: 900, f1: 1800, dur: 0.06, type: "sine", gain: 0.06, when: c.currentTime + 0.05 });
      setTimeout(done, 120);
    },
    powerUp(c, dest, done) {
      tone(c, dest, { f0: 120, f1: 520, dur: 0.28, type: "sine", gain: 0.1 });
      setTimeout(done, 300);
    },
    powerDown(c, dest, done) {
      tone(c, dest, { f0: 480, f1: 90, dur: 0.22, type: "sine", gain: 0.09 });
      setTimeout(done, 240);
    },
    ping(c, dest, done) {
      tone(c, dest, { f0: 880, f1: 1320, dur: 0.18, type: "sine", gain: 0.11 });
      setTimeout(done, 200);
    },
    alertSoft(c, dest, done) {
      tone(c, dest, { f0: 440, f1: 440, dur: 0.12, type: "triangle", gain: 0.09 });
      tone(c, dest, { f0: 554, f1: 554, dur: 0.14, type: "triangle", gain: 0.08, when: c.currentTime + 0.1 });
      setTimeout(done, 280);
    },
  };

  function play(name, category) {
    const cat = category || "ui";
    if (!cats()[cat]) return;
    if (prefersReduced() && cat !== "alert") return;
    const fn = cues[name];
    if (!fn) return;
    schedule((c, dest, done) => fn(c, dest, done));
  }

  function bindEvents() {
    document.addEventListener("friday:panel", (ev) => {
      const open = ev.detail && ev.detail.open;
      play(open ? "servo" : "relay", "ui");
    });
    document.addEventListener("friday:view", () => play("chirp", "data"));
    document.addEventListener("friday:state", (ev) => {
      const st = ev.detail && ev.detail.state;
      if (st === "listening") play("ping", "data");
      if (st === "thinking") play("chirp", "data");
    });
    document.addEventListener("friday:voice", (ev) => {
      if (ev.detail && ev.detail.on) play("powerUp", "power");
      else play("powerDown", "power");
    });
    document.addEventListener("friday:task", (ev) => {
      const k = ev.detail && ev.detail.kind;
      if (k === "complete") play("ping", "ui");
      if (k === "error") play("alertSoft", "alert");
    });
    document.addEventListener("friday:approval", () => play("alertSoft", "alert"));
    document.addEventListener("friday:report", (ev) => {
      if (ev.detail && ev.detail.ready) play("chirp", "data");
    });
    document.addEventListener("friday:reminder", () => play("alertSoft", "alert"));
    document.addEventListener("friday:focus", (ev) => {
      play(ev.detail && ev.detail.end ? "powerDown" : "powerUp", "power");
    });
  }

  function syncMuteBtn() {
    const btn = document.getElementById("btnSfxMute");
    if (!btn) return;
    btn.setAttribute("aria-pressed", muted() ? "true" : "false");
    btn.classList.toggle("muted", muted());
    btn.textContent = muted() ? "SFX OFF" : "SFX";
  }

  function injectHeaderMute() {
    const right = document.querySelector(".topbar-right");
    if (!right || document.getElementById("btnSfxMute")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "btnSfxMute";
    btn.className = "hud-ctl";
    btn.title = "Toggle interface sounds";
    btn.addEventListener("click", () => {
      unlock();
      localStorage.setItem(K_MUTE, muted() ? "0" : "1");
      syncMuteBtn();
    });
    right.insertBefore(btn, right.firstChild);
    syncMuteBtn();
  }

  function injectSettings() {
    const grid = document.getElementById("settingsGrid");
    if (!grid || grid.querySelector(".hud-sfx-settings")) return;
    const c = cats();
    const block = document.createElement("div");
    block.className = "hud-settings-block hud-sfx-settings setting";
    block.innerHTML = `
      <h3>UI SOUNDS (SYNTH)</h3>
      <div class="hud-settings-row">
        <label><input type="checkbox" data-sfx-cat="ui" /> Interface</label>
        <label><input type="checkbox" data-sfx-cat="data" /> Data / tabs</label>
        <label><input type="checkbox" data-sfx-cat="power" /> Power / voice</label>
        <label><input type="checkbox" data-sfx-cat="alert" /> Alerts</label>
      </div>
      <p class="muted" style="margin:0">Procedural Web Audio only. Unlocks after first click. Muted while listening or speaking.</p>`;
    grid.appendChild(block);
    block.querySelectorAll("[data-sfx-cat]").forEach((inp) => {
      const k = inp.getAttribute("data-sfx-cat");
      inp.checked = !!c[k];
      inp.addEventListener("change", () => {
        const next = cats();
        next[k] = inp.checked;
        saveCats(next);
      });
    });
  }

  const mo = new MutationObserver(() => {
    injectSettings();
  });
  mo.observe(document.documentElement, { childList: true, subtree: true });

  function init() {
    ["click", "keydown", "pointerdown"].forEach((ev) => {
      document.addEventListener(ev, unlock, { once: true, passive: true });
    });
    bindEvents();
    injectHeaderMute();
    injectSettings();
  }

  window.FridaySfx = { play, unlock, muted, setMuted(on) {
    localStorage.setItem(K_MUTE, on ? "1" : "0");
    syncMuteBtn();
  }};

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
