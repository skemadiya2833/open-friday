/* Pairing / passkey UI. Soft signals only — never used as an authenticator. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);

  let phonePending = null; // { pending_id, code }
  let waitTimer = 0;

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
      const st = await (await fetch("/api/auth/status", { credentials: "same-origin" })).json();
      if (line) {
        const gate = st.passkeys_required
          ? "passkeys required"
          : st.passkeys_optional
            ? "passkey optional"
            : "no login on this PC";
        const ips = (st.lan_ips || []).length ? ` · LAN ${(st.lan_ips || []).join(", ")}` : "";
        line.textContent = `Mode ${st.mode} (${gate}) · ${st.authenticated ? "signed in (" + (st.role || "?") + ")" : "signed out"} · ${st.device_count} device(s)${ips}`;
      }
      if (st.authenticated && (st.role === "admin" || st.loopback)) {
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
      const data = await (await fetch("/api/auth/devices", { credentials: "same-origin" })).json();
      box.replaceChildren();
      for (const d of data.devices || []) {
        const el = document.createElement("div");
        el.className = "card";
        el.innerHTML = `<div><h3></h3><p class="muted"></p></div><div class="actions"></div>`;
        el.querySelector("h3").textContent = d.label;
        const kind = d.auth_kind === "approved" ? "approved (no passkey)" : "passkey";
        el.querySelector("p").textContent = `${d.role} · ${kind} · last ${new Date(d.last_used * 1000).toLocaleString()}`;
        const rev = document.createElement("button");
        rev.type = "button";
        rev.className = "ghost danger";
        rev.textContent = "Revoke";
        rev.onclick = async () => {
          const ok = await dlgConfirm({
            eyebrow: "DEVICES",
            title: `Revoke “${d.label}”?`,
            body: "The device will lose access until paired again.",
            tone: "danger",
            confirmLabel: "Revoke device",
            cancelLabel: "Cancel",
          });
          if (!ok) return;
          const r = await fetch("/api/auth/devices/" + d.id, {
            method: "DELETE",
            credentials: "same-origin",
          });
          if (!r.ok) {
            const detail = (await r.json().catch(() => ({}))).detail || "Revoke failed.";
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
      const data = await (await fetch("/api/auth/pair/pending", { credentials: "same-origin" })).json();
      box.replaceChildren();
      for (const p of data.pending || []) {
        const el = document.createElement("div");
        el.className = "card";
        el.innerHTML = `<div><h3></h3><p class="muted"></p></div>`;
        el.querySelector("h3").textContent = p.device_name + " · code " + p.code;
        el.querySelector("p").textContent = JSON.stringify(p.soft || {});
        box.append(el);
        const id = $("#pairPendingId");
        const code = $("#pairCode");
        if (id && !id.value) id.value = p.id;
        if (code && !code.value) code.value = p.code;
      }
    } catch (_) {
      box.textContent = "";
    }
  }

  function stopWait() {
    if (waitTimer) clearInterval(waitTimer);
    waitTimer = 0;
  }

  async function requestAccess() {
    const name = ($("#pairDeviceName")?.value || "").trim() || "Phone";
    const hint = $("#pairPhoneHint");
    const actions = $("#pairPhoneActions");
    const r = await fetch("/api/auth/pair/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_name: name }),
    });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) {
      await dlgAlert({
        eyebrow: "PAIRING",
        title: "Request failed",
        body: String(out.detail || "Could not start pairing."),
        tone: "danger",
      });
      return;
    }
    phonePending = { pending_id: out.pending_id, code: out.code };
    if (hint) {
      hint.textContent = `Code ${out.code} — show this on the PC Devices page and tap Approve. Waiting…`;
    }
    actions?.classList.remove("hidden");
    stopWait();
    waitTimer = setInterval(async () => {
      if (!phonePending) return;
      try {
        const w = await fetch("/api/auth/pair/wait", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(phonePending),
        });
        const st = await w.json().catch(() => ({}));
        if (st.status === "approved" && hint) {
          hint.textContent = `Approved — tap Continue without passkey (or Register passkey).`;
          stopWait();
        } else if (st.status === "expired" || st.status === "missing") {
          if (hint) hint.textContent = "Request expired — tap Request access again.";
          stopWait();
        }
      } catch (_) { /* ignore */ }
    }, 2000);
  }

  async function claimWithoutPasskey() {
    if (!phonePending) {
      await dlgAlert({ eyebrow: "PAIRING", title: "No request", body: "Tap Request access first.", tone: "warn" });
      return;
    }
    const r = await fetch("/api/auth/pair/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(phonePending),
    });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) {
      await dlgAlert({
        eyebrow: "PAIRING",
        title: "Not connected yet",
        body: String(out.detail || "Wait for PC approve, then try again."),
        tone: "warn",
      });
      return;
    }
    stopWait();
    phonePending = null;
    await dlgNotice({
      eyebrow: "PAIRING",
      title: "Connected",
      body: `${out.label} is signed in as ${out.role}. Passkey optional later.`,
      tone: "ok",
      okLabel: "Open Friday",
    });
    window.hideAuthGate?.();
    location.reload();
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
    const optRes = await fetch("/api/auth/register/options", { method: "POST", credentials: "same-origin" });
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
      credentials: "same-origin",
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

  async function registerPasskeyAfterPair() {
    // Claim first if needed, then use enrollment from approve for WebAuthn —
    // for LAN we claim session then optional passkey is a future upgrade.
    // If still pending approval, claim may fail; if approved, claim then reload.
    if (phonePending) {
      await claimWithoutPasskey();
      return;
    }
    await dlgAlert({
      eyebrow: "PASSKEYS",
      title: "Connect first",
      body: "Use Continue without passkey after PC approve. Passkey upgrade can be added when a public hostname is configured.",
      tone: "warn",
    });
  }

  async function login() {
    const optRes = await fetch("/api/auth/login/options", { method: "POST" });
    const body = await optRes.json();
    if (!optRes.ok) {
      await dlgAlert({
        eyebrow: "PASSKEYS",
        title: "Couldn’t start sign-in",
        body: String(body.detail || "Login options failed. On LAN, use Request access instead."),
        tone: "danger",
      });
      return;
    }
    const challenge = body.options.challenge;
    const cred = await navigator.credentials.get({ publicKey: reviveGet(body.options) });
    const ver = await fetch("/api/auth/login/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
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

  async function showPairQr() {
    const name = ($("#pairDeviceName")?.value || "").trim() || "Phone";
    const hint = $("#qrPairHint");
    const box = $("#qrPairBox");
    const svgHost = $("#qrPairSvg");
    const urlEl = $("#qrPairUrl");
    if (hint) hint.textContent = "Creating invite…";
    const r = await fetch("/api/auth/pair/qr", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ device_name: name }),
    });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) {
      await dlgAlert({
        eyebrow: "QR PAIR",
        title: "Couldn’t create QR",
        body: String(out.detail || "Try again from localhost on the PC."),
        tone: "danger",
      });
      return;
    }
    if (out.needs_restart) {
      if (hint) hint.textContent = out.message || "Restart Friday, then click Show QR again.";
      box?.classList.add("hidden");
      await dlgNotice({
        eyebrow: "QR PAIR",
        title: "Restart Friday once",
        body: out.message || "Phone access was enabled. Restart the Friday process, then Show QR again.",
        tone: "warn",
        okLabel: "OK",
      });
      return;
    }
    if (hint) hint.textContent = out.message || "Scan with your phone (same Wi‑Fi).";
    if (svgHost) {
      if (out.svg) svgHost.innerHTML = out.svg;
      else svgHost.textContent = "QR unavailable — use the link below.";
    }
    if (urlEl) urlEl.textContent = out.url || "";
    box?.classList.remove("hidden");
    window._fridayPairUrl = out.url || "";
  }

  async function redeemPairToken(token) {
    const r = await fetch("/api/auth/pair/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ token }),
    });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) {
      await dlgAlert({
        eyebrow: "QR PAIR",
        title: "Couldn’t join",
        body: String(out.detail || "Ask the PC for a fresh QR."),
        tone: "danger",
      });
      return false;
    }
    window.hideAuthGate?.();
    // Drop ?pair= then reload into the signed-in HUD (cookie already set).
    const u = new URL(location.href);
    u.searchParams.delete("pair");
    history.replaceState(null, "", u.pathname + u.search + u.hash);
    location.reload();
    return true;
  }

  async function consumePairQuery() {
    const token = new URLSearchParams(location.search).get("pair");
    if (!token) return false;
    return redeemPairToken(token);
  }

  window.FridayAuth = {
    bootstrapPc: () =>
      bootstrapPc().catch((e) =>
        dlgAlert({ eyebrow: "PASSKEYS", title: "Registration error", body: e.message || String(e), tone: "danger" })),
    login: () =>
      login().catch((e) =>
        dlgAlert({ eyebrow: "PASSKEYS", title: "Sign-in error", body: e.message || String(e), tone: "danger" })),
    requestAccess: () =>
      requestAccess().catch((e) =>
        dlgAlert({ eyebrow: "PAIRING", title: "Request error", body: e.message || String(e), tone: "danger" })),
    claim: () =>
      claimWithoutPasskey().catch((e) =>
        dlgAlert({ eyebrow: "PAIRING", title: "Claim error", body: e.message || String(e), tone: "danger" })),
    showPairQr: () =>
      showPairQr().catch((e) =>
        dlgAlert({ eyebrow: "QR PAIR", title: "Error", body: e.message || String(e), tone: "danger" })),
    consumePairQuery,
    refreshStatus,
  };

  $("#btnAuthBootstrap")?.addEventListener("click", () => window.FridayAuth.bootstrapPc());
  $("#btnAuthLogin")?.addEventListener("click", () => window.FridayAuth.login());
  $("#btnAuthRefresh")?.addEventListener("click", () => refreshStatus());
  $("#btnShowPairQr")?.addEventListener("click", () => window.FridayAuth.showPairQr());
  $("#btnCopyPairUrl")?.addEventListener("click", async () => {
    const url = window._fridayPairUrl || $("#qrPairUrl")?.textContent || "";
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      const hint = $("#qrPairHint");
      if (hint) hint.textContent = "Link copied.";
    } catch (_) {
      await dlgAlert({ eyebrow: "QR PAIR", title: "Copy failed", body: url, tone: "warn" });
    }
  });
  $("#btnPairRequest")?.addEventListener("click", () => window.FridayAuth.requestAccess());
  $("#btnPairClaim")?.addEventListener("click", () => window.FridayAuth.claim());
  $("#btnPairApprove")?.addEventListener("click", async () => {
    const pending_id = $("#pairPendingId")?.value?.trim();
    const code = $("#pairCode")?.value?.trim();
    const r = await fetch("/api/auth/pair/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ pending_id, code }),
    });
    const out = await r.json();
    if (!r.ok) {
      await dlgAlert({
        eyebrow: "PAIRING",
        title: "Approve failed",
        body: String(out.detail || "Check the code and try again."),
        tone: "danger",
      });
      return;
    }
    await dlgNotice({
      eyebrow: "PAIRING",
      title: "Phone approved",
      body: "On the phone tap Continue without passkey (or Register passkey).",
      tone: "ok",
      okLabel: "Done",
    });
    refreshStatus();
  });

  document.addEventListener("DOMContentLoaded", () => refreshStatus());
  refreshStatus();
})();
