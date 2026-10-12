# FRIDAY HUD — Stage 4 design

Original heads-up display language inspired by tactical sci-fi assistant UIs (including **ideas-only** cues from [Arwes](https://github.com/arwes/arwes) — MIT, unmaintained; no Arwes code or assets in this repo). This is **not** a film replica: no logos, stills, audio samples, or trademarked glyphs.

## Palette tokens

| Token | Role | Value |
|-------|------|--------|
| `--bg` / `--bg-2` | Deep space base | `#05070c` / `#0a1018` |
| `--panel` / `--panel-2` | Glass panels | cyan-tinted rgba overlays |
| `--line` | Primary grid & borders | `rgba(90, 200, 255, 0.18)` |
| `--line-hot` | Alert / approval accent | `rgba(255, 140, 60, 0.55)` |
| `--text` / `--muted` | Body / secondary | `#e8f4ff` / `#7f9bb0` |
| `--accent` / `--accent-2` | Warm HUD highlight | `#ff6a2b` / `#ffb347` |
| `--cyan` / `--cyan-dim` | Telemetry & links | `#3ecbff` / `rgba(62, 203, 255, 0.14)` |
| `--ok` / `--warn` | Status | `#3ef0a8` / `#f0c14a` |

Restrained glow: single-layer `text-shadow` or blurred radial backgrounds at ≤45% opacity. No full-screen bloom on mobile.

## Typography

| Role | Stack | Notes |
|------|--------|--------|
| Display headings | `--hud-display` | `Segoe UI`, `system-ui`, sans-serif — wide tracking, uppercase |
| UI body | `--hud-ui` | Same as `--font` in `styles.css` |
| Telemetry / codes | `--hud-mono` | `Cascadia Mono`, `Consolas`, `ui-monospace`, monospace |

**Licenses:** The UI ships **system fonts only** (no CDN). Optional self-hosted open fonts (all **SIL Open Font License 1.1** if you add them under `web/public/fonts/`):

- **Rajdhani** — UI body (optional)
- **Orbitron** — display (optional)
- **Share Tech Mono** — mono readouts (optional)

Do not commit proprietary or film-linked typefaces.

## Line weights & frames

- Primary panel border: **1px** `--line`
- Corner brackets (screen + panels): **2px** accent/cyan L-shapes, 14–28px leg length
- Eyebrow rules: **1px** under section labels
- Focus ring: **1px** `--cyan`, 2px offset (`:focus-visible`)

## Grid & atmosphere

- Perspective grid at ~5% opacity; disabled under `prefers-reduced-motion` or **Low effects**
- Hex overlay: inline SVG data-URI (no external assets)
- Scanline overlay: subtle; paused when tab hidden

## Motion tokens (`hud.css` / `motion.js`)

| Token | Duration | Use |
|-------|----------|-----|
| `--motion-fast` | 120ms | Hovers, micro feedback |
| `--motion-base` | 200ms | Panel clips, tab fade |
| `--motion-slow` | 320ms | Assemble strokes, list stagger |

Compositor-only animation properties: `transform`, `opacity`. Clip-path and SVG `stroke-dashoffset` used sparingly for panel assemble.

## Effects budget

- **Low effects** (`localStorage.friday_low_effects=1`): shorter motion, no grid drift, no decipher on headings
- **Hidden document**: all ambient loops paused
- **Heavy workload** (`body[data-workload="heavy"]`): agent or sustained model activity — reduced shimmer and background motion

## Audio (procedural)

All UI cues synthesized in `sfx.js` (Web Audio). Master gain ~0.28. No hover sounds. Cues ≤400ms. Mute during voice listen/speak. See `docs/REFERENCES.md` for Arwes credit (visual ideas only).

## Surfaces covered

Header telemetry, rail nav, chat stream, voice overlay orb, Tools/MCP, Devices, Reports canvas, Tasks/planner + calendar agenda strip, Systems settings, `/health` performance link.

Mobile: bottom nav rail, lighter grid/glow, same tokens with smaller type scale (see `hud.css` `@media`).
