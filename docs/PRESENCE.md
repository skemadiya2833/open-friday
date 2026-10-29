# Presence — skins, model switch, camera presence, avatar

Architecture-first callsign packs. **Style ≠ capability.** Switching Ultron/Jarvis/etc. changes voice, HUD, humor, and a short tone delta — never tools, approvals, e-stop, or safety policy.

## Principles

- Inspired callsigns only (Friday default). Original writing — no film quotes; never claim to be a franchise character.
- Capability clamp is always in the prompt for every skin: theatrical persona is performance only; no unauthorized access or “system takeover.”
- Prefer data modules under `friday/presence/` and `friday/avatar/` over stuffing lore into `CORE`.

## Skins

| Id | Callsign | Voice (Kokoro → Edge) | Notes |
|----|----------|----------------------|--------|
| friday | FRIDAY | `af_bella` → Ava | Teal · addresses **boss** |
| jarvis | JARVIS | `bm_george` → Ryan (GB) | Blue · addresses **sir** |
| ultron | ULTRON | `am_puck` → Davis | Yellow · **boy** / **old man** |
| vision | VISION | `bm_fable` → Thomas (GB) | Purple · **friend** |
| karen | KAREN | `af_sarah` → Jenny | Magenta · **chief** |
| edith | EDITH | `af_nicole` → Aria | Amber · **sir** |

Switching a skin sets `tts_voice` + `tts_engine` so a male callsign never remaps onto a female stand-in. Browser fallback uses `voice_profile` (`male_gb` / `male_us` / `female_us`).

Voice/chat: `switch to jarvis`, `ultron mode`, `be friday`.

Prefs: `presence_skin`, Systems → Persona.

## Model switch

`switch to qwen` / `switch to gemma` resolves against installed Ollama tags, patches `chat_model` (and `vision_model` when the tag is multimodal), then notifies `ModelManager`.

`what model are you on?` → presence skill status.

## Camera presence

Pref `camera_presence` (off by default). `see me` / `camera presence on` enables; requires camera enabled + arm (same LED/HUD/e-stop as one-shot camera).

Each chat turn while on: one glance → appearance notes → optional in-character compliment when look *changed* → frame discarded.

## Avatar / talking head

- Upload portrait: `POST /api/presence/portrait/{skin_id}` (png/jpg/webp) → `data/presence/portraits/`.
- HUD shows still portrait when present (`#avatarPanel`).
- Prefs: `avatar_engine` = `auto|still|musetalk|wav2lip`; `avatar_lipsync` (off by default).
- Engines live under `data/vendor/MuseTalk` and `data/vendor/Wav2Lip` when installed; otherwise still portrait only.
- MuseTalk is the preferred lip-sync engine; Wav2Lip is the low-VRAM option.

## API

| Method | Path | Role |
|--------|------|------|
| GET | `/api/presence` | Active skin + avatar status |
| POST | `/api/presence/skin` | `{ "skin_id": "jarvis" }` |
| GET/POST | `/api/presence/portrait/{skin_id}` | Fetch / upload |
| GET | `/api/presence/avatar/latest` | Still/lipsync status for HUD |

## Code map

- `friday/presence/` — skins, registry, model switch, camera presence
- `friday/avatar/` — still / MuseTalk / Wav2Lip facade
- `friday/skills/builtin/presence/` — chat/voice skill
- HUD: `web/public/index.html`, `app.js`, `styles.css` (`skin-*` themes)
