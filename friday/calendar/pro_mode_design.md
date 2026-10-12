# Pro mode: dedicated Chrome profile via CDP (design only)

Optional future path for users who want Friday to **edit** Google Calendar in the browser without OAuth API scopes.

## Idea

- Launch Chrome with a **dedicated user-data-dir** (separate from daily browsing).
- Connect over **Chrome DevTools Protocol (CDP)** from Friday's computer-use stack.
- The user signs into Google once in that profile; Friday automates only Calendar tabs.

## Risks

| Risk | Mitigation |
|------|------------|
| Session hijack if profile dir is copied | Store profile under `DATA_DIR` with strict ACLs; never sync to cloud backups without encryption |
| CDP port exposed on LAN | Bind CDP to loopback only; refuse remote binds unless FRIDAY_AUTH + token |
| Prompt injection driving destructive clicks | Require confirm tier for delete/move; estop kills CDP session |
| Google ToS / automation detection | Document that this is single-user automation, not a multi-tenant service |
| Stale DOM / A/B UI | Prefer template URLs + iCal read for reliability; CDP as opt-in pro mode |

## Non-goals

- No automatic event submission without user confirmation in the Calendar UI.
- No shared multi-user Chrome profile on a family PC without explicit role separation.

This package ships **iCal read + template create URLs** only; CDP pro mode remains a separate gate.
