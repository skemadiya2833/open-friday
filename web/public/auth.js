/* Passkey pairing / login UI. Soft signals only — never used as an authenticator. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);

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
        line.textContent = `Mode ${st.mode} · RP ${st.rp_id} · ${st.authenticated ? "signed in (" + (st.role || "?") + ")" : "signed out"} · ${st.device_count} device(s). Phone needs FRIDAY_PUBLIC_HOST — see docs/PHONE_SETUP.md.`;
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
          if (!confirm("Revoke requires a fresh passkey. Continue after step-up?")) return;
          // Step-up is manual via Sign in for now if needed.
          const r = await fetch("/api/auth/devices/" + d.id, { method: "DELETE" });
          if (!r.ok) alert((await r.json()).detail || "revoke failed — complete step-up first");
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
      alert("This browser has no WebAuthn.");
      return;
    }
    const optRes = await fetch("/api/auth/register/options", { method: "POST" });
    const body = await optRes.json();
    if (!optRes.ok) {
      alert(body.detail || "options failed");
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
      alert(out.detail || "register failed");
      return;
    }
    alert("Registered: " + out.label + " (" + out.role + ")");
    refreshStatus();
  }

  async function login() {
    const optRes = await fetch("/api/auth/login/options", { method: "POST" });
    const body = await optRes.json();
    if (!optRes.ok) {
      alert(body.detail || "login options failed");
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
      alert(out.detail || "login failed");
      return;
    }
    refreshStatus();
  }

  $("#btnAuthBootstrap")?.addEventListener("click", () => bootstrapPc().catch((e) => alert(e.message)));
  $("#btnAuthLogin")?.addEventListener("click", () => login().catch((e) => alert(e.message)));
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
      alert(out.detail || "approve failed — press a physical key, then retry");
      return;
    }
    alert("Enrollment token created (5 min). Enter it on the phone to finish passkey registration.\n" + out.enrollment_token);
    refreshStatus();
  });

  document.addEventListener("DOMContentLoaded", () => refreshStatus());
  refreshStatus();
})();
