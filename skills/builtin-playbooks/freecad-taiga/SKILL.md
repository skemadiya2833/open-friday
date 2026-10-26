---
name: freecad-taiga
description: >-
  Plan FreeCAD PartDesign parts as ordered Taiga-S1 feature goals, then build
  them live when FreeCAD's Taiga socket server is running. Use when the owner
  describes a plate, bracket, flange, hole pattern, fillet, or CAD part idea.
license: Proprietary — Friday built-in playbook (Taiga-S1 / biome-s1 are MIT upstream)
metadata:
  friday:builtin: "true"
  category: playbooks
  upstream: https://github.com/shhivv/biome-s1
---

# FreeCAD + Taiga-S1

Friday is the **planner** (System 2). [Taiga-S1](https://huggingface.co/shhivv/taiga-s1) is the **executor** (System 1): a 1.2M-parameter model that picks the next FreeCAD PartDesign command from live session state. Numbers come from the goal you plan.

## When to use

- Owner asks to build / model / design a part in FreeCAD or with Taiga
- Concrete mm sizes (or clear defaults) for a PartDesign solid
- Not for filament shopping, slicer settings, or general 3D-print research

## Flow

1. Turn the idea into an ordered feature list (see `references/feature-vocabulary.md`).
2. **Assume** open sizes when the owner says “assume” / “about” / leaves gaps — only ask when the shape itself is unclear.
3. Bring FreeCAD + Taiga up yourself (`ensure_ready`: enable prefs, setup worker, launch GUI server).
4. Build. Never claim a `.FCStd` was written unless the build finished this turn.

## Example asks

- "In FreeCAD, make a 40×30×10 plate with a Ø6 hole and fillet the top 1 mm"
- "Build a bracket in FreeCAD: base plate 60×40×8, four Ø5 holes on a polar pattern"
- "Taiga status" / "is FreeCAD CAD ready?"

## Setup

Prefer **Systems → CAD** (Detect / Setup / Launch) or ask Friday: “set up CAD”.

Friday stores paths in Systems prefs (`freecad_install`, `freecad_s1_repo`, `freecad_s1_python`, `cad_enabled`).
She can change them when you tell her a path or say enable/disable CAD.
Default FreeCAD root on this machine: `C:\Program Files\FreeCAD 1.1`.
Taiga lives under `data/vendor/biome-s1` after setup.
