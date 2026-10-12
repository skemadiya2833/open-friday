---
name: system-inventory
description: >-
  Measure and list this Windows PC's hardware and peripherals (CPU/RAM/GPU,
  cameras, displays, audio, USB, printers, network). Prefer Friday direct tools
  over guessing. Use when the owner asks what is connected, how many cameras,
  specs, or device inventory.
---

# System inventory

Friday already has **deterministic** paths for this — prefer them:

| Owner says | What runs |
|---|---|
| list / show cameras, webcams | OpenCV probe (MSMF + DirectShow) + PnP names → HTML |
| peripherals / devices / USB / displays / audio / printers | PowerShell CIM inventory + camera probe → HTML |
| system specs / resources on screen | Measured PowerShell specs → HTML + PowerShell window |

## Rules

1. **Never invent** device names or counts. If a probe fails, say so.
2. Cameras: Windows **MSMF** and **DirectShow** use different indices — the Systems picker stores `backend:index` so capture matches the selection.
3. If only one camera opens, ask the owner to close Zoom/Teams/OBS (they lock devices) and rescan in Systems.
4. Shell inventory is preferrable to clicking through Settings apps.

## Example asks

- "List my cameras"
- "What peripherals are connected?"
- "Show my system specs on screen"
- "How many monitors do I have?"
