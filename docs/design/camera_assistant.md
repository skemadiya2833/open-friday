# Camera assistant (future)

Design-only. **Not implemented.** Privacy-first sketch for a later milestone.

## Why

Friday already sees the **screen** (computer-use). A camera would let Friday see the **desk / owner context** — what you are physically doing — so it can nudge, brief, or answer “what am I looking at?” without cloud connectors.

## Product intent

| In scope (later) | Out of scope |
|------------------|--------------|
| Opt-in local webcam frames for short contextual questions | Always-on surveillance / recording strangers |
| Ephemeral buffer (seconds) for “what’s on my desk?” | Uploading frames to cloud by default |
| Presence / “are you at the PC?” for operators + on-screen toasts | Silent background recording without UI indicator |
| Local VLM on Ollama when vision model is present | Replacing screen computer-use with camera |

## Defaults (must hold if built)

1. **Off by default** — `FRIDAY_CAMERA=off` (or unset).
2. **Owner grant required** — not agent-schedulable; same run-grant / confirm posture as dangerous tools.
3. **Local only** — frames stay on device; never leave in research reports or experience exports unless the owner explicitly opts in per capture.
4. **Physical indicator** — OS camera LED / in-app “camera live” HUD chip while capturing.
5. **Kill switch** — e-stop (`Ctrl+Alt+F12`) cancels capture and revokes camera grant immediately.
6. **Retention** — default: discard after the turn; optional short ring buffer (e.g. ≤30s) with clear Settings UI and wipe on stop.

## Threat notes (add to THREAT_MODEL when implementing)

- Camera is a high-sensitivity sensor: treat frames like screen content (untrusted `CAMERA_DATA` fence; never concatenate into tool instructions).
- No auto-start on boot; tray must show camera state.
- Policy deny when locked-screen / secure desktop / sensitive apps are foreground (reuse sensitive-app deny list ideas).
- Logs: record that camera ran (audit chain), not the pixels.

## Non-goals for v1 of this feature

- Multi-camera arrays, face recognition databases, emotion scoring sold as product.
- Phone camera streaming as the primary path (desk PC webcam only for v1).
- Replacing Windows toast/overlay notify with “watch me forever.”

## Relation to OpenJarvis

OpenJarvis does not provide computer-use or a camera product path. Friday’s differentiator remains **local desktop autonomy + on-screen presence**; camera is an optional sensing layer on top of that, never a reason to add OAuth.
