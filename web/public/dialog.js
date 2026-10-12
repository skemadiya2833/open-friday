/* In-app HUD dialogs — replaces window.alert / confirm with Friday-styled modals. */
(function () {
  "use strict";

  let host = null;
  let resolveFn = null;
  let lastFocus = null;

  function ensureHost() {
    if (host) return host;
    host = document.getElementById("fridayDialog");
    if (!host) {
      host = document.createElement("div");
      host.id = "fridayDialog";
      host.className = "fd-overlay";
      host.hidden = true;
      document.body.appendChild(host);
    }
    host.addEventListener("click", (e) => {
      if (e.target === host) close(false);
    });
    document.addEventListener("keydown", (e) => {
      if (host.hidden) return;
      if (e.key === "Escape") {
        e.preventDefault();
        close(false);
      }
    });
    return host;
  }

  function close(value) {
    const el = ensureHost();
    el.hidden = true;
    el.innerHTML = "";
    el.className = "fd-overlay";
    const fn = resolveFn;
    resolveFn = null;
    if (lastFocus && typeof lastFocus.focus === "function") {
      try { lastFocus.focus(); } catch (_) {}
    }
    lastFocus = null;
    if (fn) fn(value);
  }

  function open(opts) {
    const {
      eyebrow = "FRIDAY",
      title = "",
      body = "",
      tone = "info", // info | ok | warn | danger
      confirmLabel = "OK",
      cancelLabel = null,
      code = null,
      mono = false,
    } = opts || {};

    lastFocus = document.activeElement;
    const el = ensureHost();
    el.className = `fd-overlay fd-${tone}`;
    el.hidden = false;

    const box = document.createElement("div");
    box.className = "fd-box";
    box.setAttribute("role", cancelLabel ? "alertdialog" : "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-labelledby", "fdTitle");

    const eye = document.createElement("p");
    eye.className = "eyebrow";
    eye.textContent = eyebrow;

    const h = document.createElement("h2");
    h.id = "fdTitle";
    h.textContent = title;

    const p = document.createElement("p");
    p.className = mono ? "fd-body fd-mono" : "fd-body muted";
    p.textContent = body;

    box.append(eye, h, p);

    if (code) {
      const pre = document.createElement("pre");
      pre.className = "fd-code";
      pre.textContent = code;
      box.append(pre);
      const copyRow = document.createElement("div");
      copyRow.className = "fd-actions fd-actions-start";
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "ghost";
      copyBtn.textContent = "Copy token";
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(code);
          copyBtn.textContent = "Copied";
          setTimeout(() => { copyBtn.textContent = "Copy token"; }, 1600);
        } catch (_) {
          copyBtn.textContent = "Select & copy manually";
        }
      });
      copyRow.append(copyBtn);
      box.append(copyRow);
    }

    const actions = document.createElement("div");
    actions.className = "fd-actions";

    if (cancelLabel) {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "ghost";
      cancel.textContent = cancelLabel;
      cancel.addEventListener("click", () => close(false));
      actions.append(cancel);
    }

    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = tone === "danger" ? "danger" : "";
    ok.textContent = confirmLabel;
    ok.addEventListener("click", () => close(true));
    actions.append(ok);

    box.append(actions);
    el.replaceChildren(box);
    queueMicrotask(() => ok.focus());

    return new Promise((resolve) => {
      resolveFn = resolve;
    });
  }

  const Dialog = {
    /** Info / error / success notice — one OK button. */
    async alert(opts) {
      if (typeof opts === "string") opts = { body: opts, title: "Notice" };
      await open({
        eyebrow: opts.eyebrow || "COMMS",
        title: opts.title || "Notice",
        body: opts.body || "",
        tone: opts.tone || "info",
        confirmLabel: opts.okLabel || "Got it",
        code: opts.code || null,
        mono: !!opts.mono,
      });
    },
    /** Confirm / cancel — resolves true if confirmed. */
    async confirm(opts) {
      if (typeof opts === "string") opts = { body: opts, title: "Confirm" };
      return open({
        eyebrow: opts.eyebrow || "CONFIRM",
        title: opts.title || "Confirm",
        body: opts.body || "",
        tone: opts.tone || "warn",
        confirmLabel: opts.confirmLabel || "Confirm",
        cancelLabel: opts.cancelLabel || "Cancel",
        code: opts.code || null,
      });
    },
    /** Success with optional copyable code block (e.g. enrollment token). */
    async notice(opts) {
      await open({
        eyebrow: opts.eyebrow || "SECURE LINK",
        title: opts.title || "Done",
        body: opts.body || "",
        tone: opts.tone || "ok",
        confirmLabel: opts.okLabel || "Continue",
        code: opts.code || null,
      });
    },
  };

  window.FridayDialog = Dialog;
})();
