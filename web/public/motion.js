/* Stage 4 motion system — View Transitions, panel assemble, decipher, stagger */
(function () {
  "use strict";

  const K_LOW = "friday_low_effects";
  const VT = typeof document.startViewTransition === "function";

  function prefersReduced() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function lowEffects() {
    return localStorage.getItem(K_LOW) === "1";
  }

  function motionAllowed() {
    return !document.hidden && !prefersReduced() && !lowEffects();
  }

  function syncBodyClasses() {
    document.body.classList.toggle("hud-low-effects", lowEffects());
    document.body.classList.toggle("hud-paused", document.hidden);
    if (window.innerWidth <= 960) document.body.classList.add("hud-bg-lite");
    else document.body.classList.remove("hud-bg-lite");
  }

  function markAmbientClasses() {
    const grid = document.querySelector(".hud-grid");
    const scan = document.querySelector(".hud-scan");
    document.querySelectorAll(".hud-glow-a, .hud-glow-b").forEach((el) => el.classList.add("hud-glow-drift"));
    if (grid) grid.classList.add("hud-grid-drift");
    if (scan) scan.classList.add("hud-scan-flicker");
    const spin = document.querySelector(".hud-rings .ring-spin");
    if (spin) spin.classList.add("hud-rings-spin");
  }

  function assemblePanels() {
    // CSS already draws panel-frame corners (::before/::after). Do not inject a
    // second SVG bracket layer — that stacked and looked "assembled twice".
    document.querySelectorAll(".panel-frame").forEach((panel) => {
      if (panel.dataset.hudAssembled === "1") return;
      panel.dataset.hudAssembled = "1";
      // Strip any leftover SVG brackets from older motion.js builds.
      panel.querySelectorAll(".hud-bracket-svg").forEach((el) => el.remove());
      panel.classList.remove("hud-bracket");
      if (!motionAllowed()) {
        panel.classList.add("hud-assembled");
        return;
      }
      panel.classList.add("hud-panel-enter");
      requestAnimationFrame(() => {
        panel.classList.add("hud-assembled");
      });
    });
  }

  function decipherHeading(h1) {
    if (!h1 || h1.dataset.hudDeciphered === "1") return;
    const raw = h1.textContent || "";
    h1.textContent = "";
    h1.classList.add("hud-decipher");
    const chars = [...raw];
    chars.forEach((ch, i) => {
      const span = document.createElement("span");
      span.className = "hud-char";
      span.textContent = ch === " " ? "\u00a0" : ch;
      if (motionAllowed()) span.style.animationDelay = `${Math.min(i * 18, 400)}ms`;
      else span.style.opacity = "1";
      h1.appendChild(span);
    });
    h1.dataset.hudDeciphered = "1";
  }

  function staggerContainer(root) {
    if (!root || root.dataset.hudStagger === "1") return;
    root.dataset.hudStagger = "1";
    root.classList.add("hud-stagger");
    const kids = [...root.children];
    kids.forEach((el, i) => {
      if (motionAllowed()) el.style.animationDelay = `${i * 45}ms`;
    });
    if (motionAllowed()) {
      requestAnimationFrame(() => root.classList.add("hud-stagger-go"));
    } else {
      kids.forEach((el) => {
        el.style.opacity = "1";
        el.style.transform = "none";
      });
    }
  }

  function refreshStaggerForView(viewEl) {
    if (!viewEl) return;
    staggerContainer(viewEl.querySelector(".cards"));
    staggerContainer(viewEl.querySelector(".plan-list"));
    staggerContainer(viewEl.querySelector(".calendar-agenda"));
    staggerContainer(viewEl.querySelector(".nav"));
    const h1 = viewEl.querySelector(".top h1");
    if (h1) {
      delete h1.dataset.hudDeciphered;
      h1.classList.remove("hud-decipher");
      decipherHeading(h1);
    }
  }

  function transitionView(fromEl, toEl, fn) {
    if (!motionAllowed()) {
      fn();
      refreshStaggerForView(toEl);
      return;
    }
    const run = () => {
      fn();
      refreshStaggerForView(toEl);
    };
    if (VT) {
      document.startViewTransition(run);
      return;
    }
    if (fromEl) fromEl.classList.add("hud-view-out");
    setTimeout(() => {
      run();
      if (toEl) {
        toEl.classList.add("hud-view-in");
        setTimeout(() => toEl.classList.remove("hud-view-in"), 220);
      }
      if (fromEl) fromEl.classList.remove("hud-view-out");
    }, 120);
  }

  function hookShowView() {
    if (typeof showView !== "function") return;
    const base = showView;
    window.showView = function (name) {
      const prev = document.querySelector(".view.active");
      const next = document.querySelector(`#view-${name}`);
      if (!prev || prev === next) {
        base(name);
        refreshStaggerForView(next);
        document.dispatchEvent(new CustomEvent("friday:view", { detail: { from: prev?.id, to: name } }));
        return;
      }
      transitionView(prev, next, () => {
        base(name);
        document.dispatchEvent(new CustomEvent("friday:view", { detail: { from: prev?.id, to: name } }));
      });
    };
  }

  function hookPanels() {
    const rem = document.getElementById("remPanel");
    if (rem) {
      const obs = new MutationObserver(() => {
        const open = !rem.classList.contains("hidden");
        document.dispatchEvent(new CustomEvent("friday:panel", { detail: { id: "reminders", open } }));
      });
      obs.observe(rem, { attributes: true, attributeFilter: ["class"] });
    }
    const approval = document.getElementById("approvalOverlay");
    if (approval) {
      const obs = new MutationObserver(() => {
        const open = !approval.hidden;
        if (open) document.dispatchEvent(new CustomEvent("friday:approval", { detail: { open: true } }));
      });
      obs.observe(approval, { attributes: true, attributeFilter: ["hidden"] });
    }
  }

  function setWorkload(heavy) {
    document.body.dataset.workload = heavy ? "heavy" : "normal";
  }

  function listenStatus() {
    document.addEventListener("friday:state", (ev) => {
      const st = ev.detail && ev.detail.state;
      const heavy = st === "acting" || st === "thinking";
      setWorkload(heavy);
    });
    document.addEventListener("friday:agent", (ev) => {
      if (ev.detail && ev.detail.running != null) setWorkload(!!ev.detail.running);
    });
  }

  function bindVisibility() {
    document.addEventListener("visibilitychange", syncBodyClasses);
    window.addEventListener("resize", syncBodyClasses);
  }

  function injectSettingsBlock() {
    const grid = document.getElementById("settingsGrid");
    if (!grid || grid.querySelector(".hud-settings-block")) return;
    const block = document.createElement("div");
    block.className = "hud-settings-block setting";
    block.innerHTML = `
      <h3>HUD &amp; MOTION</h3>
      <div class="hud-settings-row">
        <label><input type="checkbox" id="hudLowEffects" /> Low effects (lighter motion)</label>
        <a class="ghost" href="/health" style="padding:6px 10px;font-size:0.8rem">Open health / perf</a>
      </div>
      <p class="muted" style="margin:0">Honors <code>prefers-reduced-motion</code>. Pauses ambient loops when the tab is hidden.</p>`;
    grid.appendChild(block);
    const cb = block.querySelector("#hudLowEffects");
    cb.checked = lowEffects();
    cb.addEventListener("change", () => {
      localStorage.setItem(K_LOW, cb.checked ? "1" : "0");
      syncBodyClasses();
    });
  }

  const mo = new MutationObserver(() => injectSettingsBlock());
  mo.observe(document.documentElement, { childList: true, subtree: true });

  function init() {
    syncBodyClasses();
    markAmbientClasses();
    assemblePanels();
    hookShowView();
    hookPanels();
    listenStatus();
    bindVisibility();
    refreshStaggerForView(document.querySelector(".view.active"));
    injectSettingsBlock();
  }

  window.FridayMotion = {
    refreshStaggerForView,
    motionAllowed,
    setLowEffects(on) {
      localStorage.setItem(K_LOW, on ? "1" : "0");
      syncBodyClasses();
    },
    setWorkload,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
