/* Passkey pairing / login UI. Soft signals only — never used as an authenticator. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);

  async function dlgAlert(opts) {
    if (window.FridayDialog) return FridayDialog.alert(opts);
    window.alert(typeof opts === "string" ? opts : (opts.body || opts.title || ""));
  }
  async function dlgConfirm(opts) {
    if (window.FridayDialog) return FridayDialog.confirm(opts);
    return window.confirm(typeof opts === "string" ? opts : (opts.body || opts.title || ""));
  }
  async function dlgNotice(opts) {
    if (window.FridayDialog) return FridayDialog.notice(opts);
    window.alert((opts.body || "") + (opts.code ? "\n\n" + opts.code : ""));
  }

  function b64urlToBuf(s) {
    const pad = "=".repeat((4 - (s.length % 4)) % 4);
    const b64 = (s + pad).replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out.buffer;
  }
  function bufToB64url(buf) {
    const bytes = new Uint8Array(buf);
    let s = "";
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function reviveCreate(opts) {
    opts.challenge = b64urlToBuf(opts.challenge);
    opts.user.id = b64urlToBuf(opts.user.id);
    return opts;
  }
  function reviveGet(opts) {
    opts.challenge = b64urlToBuf(opts.challenge);
    if (opts.allowCredentials) {
      opts.allowCredentials = opts.allowCredentials.map((c) => ({ ...c, id: b64urlToBuf(c.id) }));
    }
    return opts;
  }
  function serializeCred(cred) {
    return {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        attestationObject: cred.response.attestationObject
          ? bufToB64url(cred.response.attestationObject)
          : undefined,
        authenticatorData: cred.response.authenticatorData
          ? bufToB64url(cred.response.authenticatorData)
          : undefined,
        signature: cred.response.signature ? bufToB64url(cred.response.signature) : undefined,
        userHandle: cred.response.userHandle ? bufToB64url(cred.response.userHandle) : undefined,
      },
      clientExtensionResults: cred.getClientExtensionResults?.() || {},
    };
  }

  async function refreshStatus() {
    const line = $("#authStatusLine");
    try {
      const st = await (await fetch("/api/auth/status")).json();
      if (line) {
        const gate = st.passkeys_required ? "passkeys required" : "no login on this PC";
        line.textContent = `Mode ${st.mode} (${gate}) · RP ${st.rp_id} · ${st.authenticated ? "signed in (" + (st.role || "?") + ")" : "signed out"} · ${st.device_count} device(s). Phone: set FRIDAY_AUTH=remote + FRIDAY_PUBLIC_HOST — docs/PHONE_SETUP.md.`;
      }
      if (st.authenticated && st.role === "admin") {
        await refreshDevices();
        await refreshPending();
      }
    } catch (e) {
      if (line) line.textContent = "Auth status unavailable: " + e.message;
    }
  }

  async function refreshDevices() {
    const box = $("#deviceList");
    if (!box) return;
    try {
      const data = await (await fetch("/api/auth/devices")).json();
      box.replaceChildren();
      for (const d of data.devices || []) {
        const el = document.createElement("div");
        el.className = "card";
        el.innerHTML = `<div><h3></h3><p class="muted"></p></div><div class="actions"></div>`;
        el.querySelector("h3").textContent = d.label;
        el.querySelector("p").textContent = `${d.role} · last ${new Date(d.last_used * 1000).toLocaleString()}`;
        const rev = document.createElement("button");
        rev.type = "button";
        rev.className = "ghost danger";
        rev.textContent = "Revoke";
        rev.onclick = async () => {
          await fetch("/api/auth/stepup/options", { method: "POST" }).catch(() => {});
          const ok = await dlgConfirm({
            eyebrow: "DEVICES",
            title: `Revoke “${d.label}”?`,
            body: "This needs a fresh passkey step-up. The device will lose access until re-enrolled.",
            tone: "danger",
            confirmLabel: "Revoke device",
            cancelLabel: "Cancel",
          });
          if (!ok) return;
          const r = await fetch("/api/auth/devices/" + d.id, { method: "DELETE" });
          if (!r.ok) {
            const detail = (await r.json().catch(() => ({}))).detail || "Revoke failed — complete step-up first.";
            await dlgAlert({
              eyebrow: "DEVICES",
              title: "Couldn’t revoke",
              body: String(detail),
              tone: "danger",
            });
          }
          refreshStatus();
        };
        el.querySelector(".actions").append(rev);
        box.append(el);
      }
    } catch (_) {
      box.textContent = "Sign in as admin to manage devices.";
    }
  }

  async function refreshPending() {
    const box = $("#pairPending");
    if (!box) return;
    try {
      const data = await (await fetch("/api/auth/pair/pending")).json();
      box.replaceChildren();
      for (const p of data.pending || []) {
        const el = document.createElement("div");
        el.className = "card";
        el.innerHTML = `<div><h3></h3><p class="muted"></p></div>`;
        el.querySelector("h3").textContent = p.device_name + " · code " + p.code;
        el.querySelector("p").textContent = JSON.stringify(p.soft || {});
        box.append(el);
        const id = $("#pairPendingId");
        if (id && !id.value) id.value = p.id;
      }
    } catch (_) {
      box.textContent = "";
    }
  }

  async function bootstrapPc() {
    if (!window.PublicKeyCredential) {
      await dlgAlert({
        eyebrow: "PASSKEYS",
        title: "WebAuthn unavailable",
        body: "This browser doesn’t support passkeys. Try a current Chrome, Edge, or Safari build.",
        tone: "warn",
      });
      return;
    }
    const optRes = await fetch("/api/auth/register/options", { method: "POST" });
    const body = await optRes.json();
    if (!optRes.ok) {
      await dlgAlert({
        eyebrow: "PASSKEYS",
        title: "Couldn’t start registration",
        body: String(body.detail || "Options request failed."),
        tone: "danger",
      });
      return;
    }
    const challenge = body.options.challenge;
    const cred = await navigator.credentials.create({ publicKey: reviveCreate(body.options) });
    const ver = await fetch("/api/auth/register/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enrollment_token: body.enrollment_token,
        challenge,
        credential: serializeCred(cred),
      }),
    });
    const out = await ver.json();
    if (!ver.ok) {
      await dlgAlert({
        eyebrow: "PASSKEYS",
        title: "Registration failed",
        body: String(out.detail || "Verify step failed."),
        tone: "danger",
      });
      return;
    }
    await dlgNotice({
      eyebrow: "PASSKEYS",
      title: "Device registered",
      body: `${out.label} is on the roster as ${out.role}. Reloading secure session.`,
      tone: "ok",
      okLabel: "Continue",
    });
    refreshStatus();
    window.hideAuthGate?.();
    location.reload();
  }

  async function login() {
    const optRes = await fetch("/api/auth/login/options", { method: "POST" });
    const body = await optRes.json();
    if (!optRes.ok) {
      await dlgAlert({
        eyebrow: "PASSKEYS",
        title: "Couldn’t start sign-in",
        body: String(body.detail || "Login options failed."),
        tone: "danger",
      });
      return;
    }
    const challenge = body.options.challenge;
    const cred = await navigator.credentials.get({ publicKey: reviveGet(body.options) });
    const ver = await fetch("/api/auth/login/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge, credential: serializeCred(cred) }),
    });
    const out = await ver.json();
    if (!ver.ok) {
      await dlgAlert({
        eyebrow: "PASSKEYS",
        title: "Sign-in failed",
        body: String(out.detail || "Verify step failed."),
        tone: "danger",
      });
      return;
    }
    refreshStatus();
    window.hideAuthGate?.();
    location.reload();
  }

  window.FridayAuth = {
    bootstrapPc: () =>
      bootstrapPc().catch((e) =>
        dlgAlert({ eyebrow: "PASSKEYS", title: "Registration error", body: e.message || String(e), tone: "danger" })),
    login: () =>
      login().catch((e) =>
        dlgAlert({ eyebrow: "PASSKEYS", title: "Sign-in error", body: e.message || String(e), tone: "danger" })),
    refreshStatus,
  };

  $("#btnAuthBootstrap")?.addEventListener("click", () => window.FridayAuth.bootstrapPc());
  $("#btnAuthLogin")?.addEventListener("click", () => window.FridayAuth.login());
  $("#btnAuthRefresh")?.addEventListener("click", () => refreshStatus());
  $("#btnPairApprove")?.addEventListener("click", async () => {
    const pending_id = $("#pairPendingId")?.value?.trim();
    const code = $("#pairCode")?.value?.trim();
    const r = await fetch("/api/auth/pair/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pending_id, code }),
    });
    const out = await r.json();
    if (!r.ok) {
      await dlgAlert({
        eyebrow: "PAIRING",
        title: "Approve failed",
        body: String(out.detail || "Press a physical key, then retry."),
        tone: "danger",
      });
      return;
    }
    await dlgNotice({
      eyebrow: "PAIRING",
      title: "Enrollment token ready",
      body: "Valid for 5 minutes. Enter this on the phone to finish passkey registration.",
      tone: "ok",
      code: out.enrollment_token,
      okLabel: "Done",
    });
    refreshStatus();
  });

  document.addEventListener("DOMContentLoaded", () => refreshStatus());
  refreshStatus();
})();
