# Phone access

## Simplest — QR from the PC (same Wi‑Fi)

No public domain or passkey required. On the PC: **Devices → Show QR to register phone**. First time, Friday enables phone access and asks you to **restart once**; then Show QR again.

1. On the **PC** (localhost) → **Devices** → optional device name → **Show QR to register phone**.
2. On the **phone** (same Wi‑Fi), scan the QR (or open the link under it).
3. The phone registers and signs in automatically.

Console also prints your LAN URL after a lan-capable restart, e.g. `http://192.168.1.24:8787/`.

If the phone cannot connect, allow the port once (Admin PowerShell):

```
netsh advfirewall firewall add rule name="Friday Control Center 8787" dir=in action=allow protocol=TCP localport=8787 profile=private
```

Or set `.env` explicitly and restart:

```
FRIDAY_AUTH=lan
FRIDAY_HOST=0.0.0.0
FRIDAY_PORT=8787
FRIDAY_REQUIRE_PHYSICAL_INPUT=false
```

**Advanced (manual code):** phone → Devices → Request access → approve on PC → Continue without passkey.

**Passkey (optional):** useful later with a real HTTPS hostname (`FRIDAY_AUTH=remote`). On raw LAN IPs, browsers often reject WebAuthn.

### 3. Camera from the phone

1. Systems → Arm camera → pick device → **Show preview** (or ask Friday what it sees).
2. Preview and snaps require the camera to be armed (same as on the PC).

---

## Hardened — domain + passkeys (`FRIDAY_AUTH=remote`)

WebAuthn needs a **secure context** and a **registrable domain** (not a raw IP, not `.local`).

| Host you type | Works for passkeys? |
|---------------|---------------------|
| `http://192.168.1.24:8787` | **No** for passkeys (LAN mode uses approve-token instead) |
| `https://friday.devoids.in` | **Yes** — if DNS + trusted cert |

### Option A — Your domain + Let's Encrypt (DNS-01)

1. DNS A record → PC LAN IP.
2. Issue a cert (DNS-01).
3. `.env`:
   ```
   FRIDAY_AUTH=remote
   FRIDAY_PUBLIC_HOST=friday.devoids.in
   FRIDAY_ORIGIN=https://friday.devoids.in
   FRIDAY_HOST=0.0.0.0
   ```
4. Pair with passkey registration after approve.

### Option B — Tailscale MagicDNS + cert

Same as remote mode using the Tailscale hostname.

---

## This PC only (default)

```
FRIDAY_AUTH=local
FRIDAY_HOST=127.0.0.1
```

No phone. Optional Windows Hello passkey for practice.

---

## Rules

- **LAN:** identity = owner-approved device session. Soft signals (UA/IP/name) are informational only.
- **Remote:** identity = passkey.
- New phones get role `chat`. Raise roles on the PC Devices page.
- Revoke a device to kill its sessions.
- `FRIDAY_API_TOKEN` is for local scripts only.
