# Phone access with passkeys

WebAuthn (fingerprint / face / PIN) needs a **secure context** and a **registrable domain** as the relying-party ID.

| Host you type | Works for passkeys? |
|---------------|---------------------|
| `http://192.168.1.24:8787` | **No** — not secure; Chromium rejects IP RP IDs |
| `https://192.168.1.24:8788` | **No** — IP RP ID rejected even with HTTPS |
| `https://friday.local` | **No** — `.local` rejected as RP ID |
| `http://localhost:8787` | **Yes on this PC only** — not reachable from a phone |
| `https://friday.devoids.in` (example) | **Yes** — if DNS + trusted cert |

Until you finish one of the hostname options below, Friday **binds to loopback only** (`FRIDAY_AUTH=local`). Remote / phone access stays **OFF**.

---

## Option A — Your domain + Let's Encrypt (DNS-01)

Example: `friday.devoids.in` → your PC's LAN IP (`192.168.1.24`).

1. **DNS A record** at your registrar (Devoids / wherever `devoids.in` is hosted):
   - Name: `friday` (or the subdomain you want)
   - Type: `A`
   - Value: `192.168.1.24` (update if your LAN IP changes)
   - TTL: 300

2. **Check whether the router / ISP DNS rewrites private answers** (DNS rebinding protection):
   ```powershell
   nslookup friday.devoids.in
   ```
   From the **phone** (same Wi‑Fi) and from the PC. If the answer is not `192.168.1.24`, the resolver is blocking RFC1918 in public DNS. Fixes: use the router's DNS override, Cloudflare DNS with a private zone, or Option B (Tailscale).

3. **Certificate via DNS-01** (nothing needs to be exposed to the internet):
   - Install a ACME client that supports DNS-01 for your DNS provider (e.g. `certbot` with a DNS plugin, or `lego`, or Cloudflare API tokens if the zone is there).
   - Issue a cert for `friday.devoids.in` only.
   - Store `fullchain.pem` + `privkey.pem` somewhere outside the repo (never commit them).

4. **Point Friday at the hostname** (owner edits `.env` — not done automatically):
   ```
   FRIDAY_AUTH=remote
   FRIDAY_PUBLIC_HOST=friday.devoids.in
   FRIDAY_ORIGIN=https://friday.devoids.in
   FRIDAY_HOST=0.0.0.0
   FRIDAY_PORT=8787
   FRIDAY_TLS_PORT=443
   ```
   Wire your TLS files into the HTTPS listener (or put a local reverse proxy such as Caddy in front). Exact install of certbot/Caddy is **owner action**; this run does not install them.

5. On the phone open `https://friday.devoids.in/` → **Request access** → enter a device name → compare the **6-digit code** with the PC → owner approves on the PC (physical key/click required) → phone creates a passkey → signs in.

---

## Option B — Tailscale (or similar) private name + its cert

1. Install Tailscale on the PC and the phone (owner installs; not done in this run).
2. Use the MagicDNS name (e.g. `pc-name.tailnet-name.ts.net`) which already has a trusted certificate in supported setups.
3. Set:
   ```
   FRIDAY_AUTH=remote
   FRIDAY_PUBLIC_HOST=pc-name.tailnet-name.ts.net
   FRIDAY_ORIGIN=https://pc-name.tailnet-name.ts.net
   FRIDAY_HOST=0.0.0.0
   ```
4. Open that HTTPS URL on the phone and pair as in Option A step 5.

---

## On this PC only (default)

```
FRIDAY_AUTH=local
FRIDAY_HOST=127.0.0.1
```

Open `http://localhost:8787/`. First visit bootstraps an admin passkey for this machine (Windows Hello). No phone.

---

## Pairing rules (summary)

- Device identity = **passkey**. Browser fingerprint is never an authenticator (soft signals: UA, IP, time, name — shown only as info).
- Owner approval of a pairing requires the **physical-input gate** (or equivalent user verification on the PC), not a click the desktop agent can forge.
- **Remote Desktop / accessibility lock-out:** some sessions mark real keys as “injected”. If that happens, set `FRIDAY_PAIR_APPROVE=hello` (or `either`) and complete a Windows Hello / passkey **step-up on the PC** before tapping Approve. Synthetic SendInput / keybd_event / Windows-MCP clicks still fail the physical gate (`scripts/physical_gate_manual.py`).
- New devices get role **`chat`** (chat + reminders). Owner raises roles on the PC Devices page after a step-up passkey.
- Revoking a device kills its sessions immediately.
- No password fallback. Recovery = physical access to this PC.
- `FRIDAY_API_TOKEN` remains an optional bearer token for local scripts only.
