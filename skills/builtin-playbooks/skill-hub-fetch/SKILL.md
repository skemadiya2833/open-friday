---
name: skill-hub-fetch
description: >-
  How to import community agentskills.io / ClawHub / Hermes-style SKILL.md packs
  into Friday safely (inbox → quarantine → owner approve).
license: MIT
compatibility: friday>=0.1
metadata:
  friday:
    origin: hybrid-absorb
    credits: OpenClaw ClawHub, Hermes Agent, agentskills.io
---

# Skill hub fetch (Friday)

Friday already speaks **agentskills.io** `SKILL.md`. Community registries (ClawHub, Hermes hubs, raw GitHub) are **sources of text**, not auto-trust.

## Owner steps

1. Systems → **Skill hub fetch** = on.
2. `POST /api/skillmd/fetch` with `{ "url": "https://…/SKILL.md" }` (or a `.zip`) from the Control Center (same-origin + physical presence).
3. File lands in **inbox** only.
4. Import → quarantine review (hash, injection heuristics, no code execution).
5. Approve → **installed** (hash-bound). Edits revoke trust.

## Agent rules

- Discovery/activate only see **installed** skills.
- `allowed-tools` in a SKILL.md never grants rights — policy.yaml does.
- Credit the upstream skill license in the skill folder when you publish forks.

## Credits

Patterns inspired by OpenClaw ClawHub and Hermes Agent skill install flows. Friday’s store and security review are native (`friday/skills/agentskills.py`, `friday/skills/skill_security.py`).
