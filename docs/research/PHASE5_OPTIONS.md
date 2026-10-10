# Phase 5 research: possible integrations (research only)

Date: 2026-10-06. Machine: Windows 11, Python 3.14.6, RTX 5060 Ti 16 GB, Ryzen 7 8700G, Bluetooth present.
Method: web evidence (links below) plus a resolver check. For Python-package options I ran
`uv pip compile --python-version 3.14 --python-platform windows --only-binary :all:` on
`bleak pycaw psutil playwright`: it resolves with binary wheels only (bleak 3.0.2, pycaw 20260927,
psutil 7.2.2, playwright 1.63.0, winrt-* 3.2.1). That proves a wheel exists, not that the feature works on this PC.
Nothing below was run against real devices except the read-only sensor tool.

Built: only `friday/experimental/sensors.py` (read-only, no new dependencies, OFF unless `FRIDAY_SENSORS=true`, tested).
Everything else is a recommendation. Every state-changing option would be a `confirm` tier tool behind the existing
policy, grant and audit layers.

## Ranking (value to you vs. risk)

| # | Option | Value | Risk | Effort | Verdict |
|---|---|---|---|---|---|
| 1 | Playwright MCP browser sub-agent | High: most tasks are web; DOM refs beat pixels | Medium: a browser sees logged-in sessions; page text is prompt-injection surface | Low (it is an MCP server, our manager already runs those) | Do first, with a throw-away profile |
| 2 | Read-only sensors (done) | Medium | Very low | Done | Keep, off by default |
| 3 | Power plan + audio output switching | Medium | Low-medium: reversible, local, no network | Low | Do second, confirm tier |
| 4 | Home Assistant via its official MCP server | High if you own HA devices | Medium: controls real-world devices; needs a long-lived token | Low-medium | Do third, per-entity allow-list |
| 5 | SignalRGB local API / OpenRGB | Medium (cosmetic) | Low | Low | Optional. SignalRGB API needs Pro and is "unstable" |
| 6 | BLE LED strip skill (bleak) | Low-medium | Low (needs pairing range only) | Medium: protocol differs per strip | Optional, after HA decision (HA already has the ELK-BLEDOM integration) |
| 7 | Authenticated remote access | Medium | High if done wrong: exposes a desktop-control agent | Medium | Only via Tailscale Serve, never a public tunnel |
| 8 | Screen memory | Medium | High: records passwords, messages, banking | High | Defer. Read the privacy section first |
| 9 | Ryzen 8700G NPU | Low | Low | High | Not worth it (see below) |

## 1. Playwright MCP browser sub-agent
- `@playwright/mcp` 0.0.83, Apache-2.0, Microsoft. Works from accessibility snapshots with element refs, no vision model needed; `--browser` chrome/firefox/webkit/msedge, `--headless`, `--config file`. Tools include `browser_snapshot`, `browser_find`. Sources: https://www.npmjs.com/package/@playwright/mcp , https://playwright.dev/docs/getting-started-mcp , https://playwright.dev/mcp/snapshots
- Needs Node/npx (not verified installed here; the `web/` folder already uses npm). Pin the version in `config/mcp_servers.yaml` (the repo already pins windows-mcp the same way), `risk.default: confirm`, safe list limited to `browser_snapshot`, `browser_find`, `browser_tabs`.
- Use an isolated profile (not your daily Chrome) and a domain allow-list; treat all page text as untrusted (same fence as the hybrid agent).
- Why first: the Windows desktop agent should hand any pure-web task to this, which makes the browser benchmark tasks cheaper and safer.

## 3. Power plans and audio switching
- Power plans: built-in `powercfg /list`, `powercfg /setactive <GUID>`. No admin needed for switching between existing user-visible plans on most setups (UNVERIFIED on this PC). Reversible. Wrap as a fixed-argument tool that only accepts a GUID from `powercfg /list`.
- Audio default device: `pycaw` `AudioUtilities.SetDefaultDevice(device_id, roles)` via IPolicyConfig, `GetAllDevices(...)` to list; PowerShell alternative `AudioDeviceCmdlets` (`Set-AudioDevice`). Sources: https://andremiras.github.io/pycaw/examples/index.html , https://github.com/frgnca/audiodevicecmdlets . IPolicyConfig is an undocumented Windows COM interface: it can break after a Windows update (risk: low impact, just a failed tool).
- Both are persistent system settings, so they are NOT done in this run (hard skip). Tools would be confirm-tier with an allow-list of known device names.

## 4. Home Assistant
- Official `mcp_server` integration: Streamable HTTP at `/api/mcp` (Assist API at `/api/mcp/assist`), bearer token or OAuth, stateless. For stdio-only clients use `mcp-proxy --transport=streamablehttp --stateless`. Source: https://www.home-assistant.io/integrations/mcp_server/ . Our MCP SDK client can also connect over Streamable HTTP directly (SDK pinned at 2.3.0; the HTTP client path was NOT exercised in this run).
- Risk: it controls lights, locks, heating. Create a dedicated HA user and token, expose only chosen entities (HA lets you pick exposed entities for Assist), keep locks/alarms out, tier the whole server `confirm`.
- Bonus: HA already has an ELK-BLEDOM integration (https://github.com/dave-code-ruiz/elkbledom, MIT), so a BLE strip could be controlled through HA with no Friday-side Bluetooth code.

## 5. SignalRGB / OpenRGB
- SignalRGB local REST API: `http://127.0.0.1:16038/api/v1` (`GET /lighting`, `PATCH /lighting/global_brightness`, `PATCH /lighting/enabled`, `POST /lighting/effects/{id}/apply`). Docs state it is unstable and most endpoints need SignalRGB Pro (403 otherwise). Also URL protocol `signalrgb://effect/apply/<name>` and `POST http://localhost:16034/canvas/event?...` for custom effects. Sources: https://docs.signalrgb.com/developer/signalrgb-api/introduction/ , https://docs.signalrgb.com/developer/signalrgb-api/lighting/ , https://docs.signalrgb.com/developer/lightscripts/creating-dev-integrations/
- OpenRGB (SDK server on 127.0.0.1:6742) can be bridged into SignalRGB by a community addon: https://github.com/Fefedu973/SignalRGB-To-OpenRGB-Bridge . Third-party code, review before installing.
- Low risk (cosmetic, loopback only). A tool would call only `effects/list`, `apply`, `brightness`, `enabled`.

## 6. BLE LED strip skill
- `bleak` 3.0.2 (MIT), Python >= 3.10, Windows 11 build 22000+. ELK-BLEDOM-style strips take 9-byte packets on characteristic `0000fff3-...` (example red: `7e070503ff00000aef`); other families (LEDBLE/XROCKER) use `ffe1`. Sources: https://pypi.org/project/bleak/ , https://github.com/FergusInLondon/ELK-BLEDOM/blob/master/PROTCOL.md , https://github.com/dave-code-ruiz/elkbledom
- Needs YOUR strip's model and a sniff to confirm the protocol. UNVERIFIED without the device. Windows needs the strip not paired to the phone at the same time.

## 7. Authenticated remote access
- Today the server binds loopback and refuses a non-loopback bind without a bearer token (Phase 1). That is local-only security, not an internet-facing design.
- Best fit: Tailscale Serve (`tailscale serve --bg localhost:<port>`), tailnet-only, ACLs, and it injects `Tailscale-User-Login` headers and strips any client-supplied ones. Keep Friday bound to 127.0.0.1 so only Serve can reach it. Source: https://tailscale.com/docs/features/tailscale-serve . Do NOT use Tailscale Funnel (public).
- Alternative: Cloudflare Tunnel + Access (identity-provider gated). Source: https://blog.cloudflare.com/protected-quick-tunnels/ . More moving parts and a public hostname.
- Required before enabling: real user authentication in Friday (not only a shared token), per-request approval stays same-origin UI only, remote sessions must NOT be able to grant approvals. Approvals need a second factor if remote use is allowed. Not built.

## 8. Screen memory (optional, privacy first)
- `screenpipe` is source-available, not OSI open source (personal use free, commercial needs a licence); captures screen + audio, accessibility text with OCR fallback, can exclude windows such as password managers. Source: https://github.com/screenpipe/screenpipe . Licence matters for you only if you ever sell this.
- OSS option: `screen-memory-mcp` (Windows OCR + local embeddings + SQLite, text only, ~30 MB/day). Source: https://github.com/yonglim2392/screen-memory-mcp . Not audited by me; small project.
- Privacy controls any option must have before use: default OFF, app/window deny-list (password managers, banking, Friday's own approval UI), pause hotkey, retention limit (e.g. 7 days), encrypted store, "forget last N minutes", no cloud model ever sees it unless you tick a box per query. Recommend deferring; the value is lower than 1-4.

## 9. Ryzen 7 8700G NPU
- AMD lists up to 16 TOPS. The Ryzen AI software stack documents LLM support for newer parts (Ryzen AI 300 series); AMD staff state the 8700G NPU "is designed for vision processing ... not LLM inference" and Hybrid mode needs a Ryzen AI 9 HX 300 or newer. Python 3.10-3.12 and Windows 11 24H2 are required for the Ryzen AI ONNX stack (Friday runs 3.14, so it would need an isolated 3.12 process, same pattern as the TTS worker). Sources: https://github.com/amd/gaia/issues/122 , https://ryzenai.docs.amd.com/en/1.7.1/winml/installation.html , https://ryzenai.docs.amd.com/en/latest/modelrun.html
- Conclusion: not useful for the LLM or Whisper (the RTX 5060 Ti is far faster). Possible tiny wins (wake word, VAD) are already ~1 ms per frame on CPU in this repo. Skip.

## Read-only sensor tool (built)
`friday/experimental/sensors.py`: CPU load (GetSystemTimes), memory, disks, power status, GPU through `nvidia-smi --query-gpu` with a fixed argument list, and temperatures only if you run LibreHardwareMonitor with its Remote Web Server (`http://127.0.0.1:8085/data.json`, MPL-2.0; psutil has no Windows temperature sensors). Registered only with `FRIDAY_SENSORS=true`. Tests: `tests/test_sensors.py`.
