# Activity awareness (ActivityWatch + optional local logger)

Friday reads activity data to power productivity metrics and visual reports. **Friday never installs ActivityWatch (AW)** — the owner installs and runs AW separately.

## ActivityWatch (recommended)

1. Install [ActivityWatch](https://activitywatch.net/) on your PC and start the AW server (default `http://127.0.0.1:5600`).
2. Enable the window watcher so title/app events are recorded.
3. In Friday Control Center, check **Activity status** (`GET /api/activity/status`) — `activitywatch.available` should be `true`.
4. Review suggested keyword rules (`GET /api/activity/aw/rules`) and approve categories you want (`POST /api/activity/aw/rules/approve`). Approved rules are stored in `DATA_DIR/aw_rules.json`.

If AW is not running, Friday returns `available: false` and falls back to local logging only when consented.

## Local foreground logger (opt-in)

**Off by default.** No screenshots.

1. Owner explicitly enables consent: `POST /api/activity/consent` with `{ "enabled": true }`. State is stored in `DATA_DIR/activity_consent.json`.
2. While enabled, Friday periodically samples the foreground window title and process name (Windows). Password managers, banking-related titles, and InPrivate/Incognito sessions are excluded; secrets are redacted via `friday.security.content_scan`.
3. Samples are append-only in `DATA_DIR/activity_local.jsonl` with retention limits.
4. **Delete everything:** `DELETE /api/activity/local/all` removes local samples and consent.

## Productivity reports

Computed metrics (time allocation, focus blocks, meeting load, deep-work ratio, trends) are exposed at `GET /api/activity/metrics` and as a visual catalog at `GET /api/activity/reports/productivity`. Model-written commentary must pass the commentary guard — every number in commentary must appear in the computed metrics payload.

## Privacy

- AW data stays on localhost; Friday uses read-only HTTP to `127.0.0.1`.
- Local logging requires consent and supports full delete.
- Private reference documents live in `.private_library/` (gitignored) and are cited by file path only.
