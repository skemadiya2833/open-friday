# FreeCAD + Taiga-S1 CAD skill

Friday turns a spoken/typed part idea into an ordered **feature goal**, then optionally drives FreeCAD with **Taiga-S1** (Biome-S1 family).

| Role | Who |
|------|-----|
| Planner (System 2) | Friday chat model → goal JSON |
| Executor (System 1) | [Taiga-S1](https://huggingface.co/shhivv/taiga-s1) (~1.2M params) over FreeCAD commands |
| Code | `friday/cad/`, `friday/skills/builtin/cad/` |
| Playbook | `skills/builtin-playbooks/freecad-taiga/` |

Upstream: [shhivv/biome-s1](https://github.com/shhivv/biome-s1) (MIT). Friday does not vendor the weights; they download via `from_pretrained("shhivv/taiga-s1")` when building.

## Configuration (Systems UI + Friday)

All CAD knobs live in **Systems → Preferences → CAD / FreeCAD** (`data/runtime_prefs.json`).
Friday can change them with `prefs_update` / the cad skill ("set up CAD", "enable CAD",
"FreeCAD is at C:\\…"). Env vars are fallbacks only.

| Pref / env | Purpose |
|------------|---------|
| `cad_enabled` / `FRIDAY_CAD` | Allow live builds |
| `freecad_install` / `FREECAD_INSTALL` | FreeCAD root (default `C:\Program Files\FreeCAD 1.1`) |
| `freecad_s1_repo` / `FREECAD_S1_REPO` | biome-s1 checkout (default `data/vendor/biome-s1`) |
| `freecad_s1_python` / `FREECAD_S1_PYTHON` | Worker venv Python with torch |
| `freecad_s1_model` / `FREECAD_S1_MODEL` | Default `shhivv/taiga-s1` |
| `freecad_s1_port` / `FREECAD_S1_PORT` | GUI socket (default `8765`) |

Systems also has **Detect FreeCAD**, **Setup Taiga**, and **Launch FreeCAD server** buttons.
API: `/api/cad/status`, `/api/cad/detect`, `/api/cad/setup`, `/api/cad/launch`, `/api/cad/prefs`.

## Runtime

1. Intent routes FreeCAD / Taiga / sized part asks → `cad` skill.
2. Planner emits a validated goal (`friday/cad/schema.py`).
3. If not ready: save `data/workspace/cad/*.goal.json` and list blockers.
4. If ready: socket reset → Taiga `Policy.act` loop → save `.FCStd` / `.png`.

FreeCAD must be running the upstream `scripts/freecad_gui_server.FCMacro` with `FREECAD_S1_REPO` set.

## Scope

PartDesign vocabulary only (pads, pockets, holes, patterns, fillets, etc.). Not assemblies, TechDraw, or Mesh workbenches. Not a substitute for research on 3D printing materials.
