# Camera assistant

Privacy-first local webcam sensing. **v1 shipped** (one-shot describe). Continuous presence / ring buffer is backlog.

## Why

Friday already sees the **screen** (computer-use / observe). The camera lets Friday see **desk / owner context** — “what am I looking at?” — without OAuth or cloud upload.

## v1 (shipped)

| Capability | Detail |
|------------|--------|
| Opt-in | `FRIDAY_CAMERA=off` by default |
| Extras | `pip install -r requirements/camera.lock.txt` (OpenCV headless) |
| Arm grant | Systems → **Arm camera** (TTL, default 5 min) or `POST /api/camera/arm` |
| Skill | `camera` — triggers like “what am I looking at”, “what’s on my desk” |
| Capture | One JPEG in memory → local VLM → discard; never written to disk/memory/reports |
| Fence | Prompt treats frame as `CAMERA_DATA` untrusted data |
| Kill switch | E-stop (`Ctrl+Alt+F12`) disarms and clears live flag |
| Audit | `camera_arm` / `camera_disarm` / `camera_snap` with size/duration only |

Code: `friday/camera/`, `friday/skills/builtin/camera/`, `friday/server/routes_camera.py`.

## Defaults that must hold

1. Off unless `FRIDAY_CAMERA=on`.
2. No capture without an active arm grant.
3. Local only — describe uses Ollama vision on-box.
4. OS camera LED + HUD “CAMERA LIVE” / overlay status while the device is open.
5. E-stop disarms immediately.
6. Retention: discard after the turn (no ring buffer in v1).

## Threat notes

See **T15** in [`docs/THREAT_MODEL.md`](../THREAT_MODEL.md).

## v2 backlog (not built)

- Short ring buffer (≤30s) with wipe-on-stop
- Presence / “are you at the PC?” for operators + toasts
- Sensitive-app / lock-screen deny while capturing
- Multi-camera; face recognition databases (explicit non-goal)

## Non-goals

- Always-on surveillance
- Phone camera as primary path
- Replacing screen computer-use with the webcam
