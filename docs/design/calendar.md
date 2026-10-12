# Google Calendar (secret iCal URL)

Friday reads your calendar through Google's **secret iCal address** and can open **new event** drafts in the browser. No Google OAuth is required for this stage.

## Find your secret iCal URL

1. Open [Google Calendar](https://calendar.google.com) in a browser signed in as the calendar owner.
2. Click the **gear** → **Settings**.
3. Under **Settings for my calendars**, select the calendar you want Friday to use.
4. Scroll to **Integrate calendar**.
5. Copy **Secret address in iCal format** (starts with `https://calendar.google.com/calendar/ical/...`).

Treat this URL like a password: anyone with the link can read that calendar's events.

## Configure Friday

- **API:** `POST /api/calendar/secret` with JSON `{"url": "https://..."}`.
- **Storage:** Windows Credential Manager when the optional `keyring` package is installed (`service=friday`, user `calendar_ical`); otherwise `data/calendar_ical.url` under your Friday data directory (keep file permissions owner-only).

Verify: `GET /api/calendar/secret` returns `configured: true` and a redacted URL (scheme, host, last four characters only).

## Rotate or revoke access

1. In the same **Integrate calendar** section, click **Reset** (or create a new secret link if Google offers regeneration).
2. In Friday: `DELETE /api/calendar/secret`, then `POST` the new URL.
3. Old links stop working immediately after reset.

## What Friday can and cannot do

| Capability | Method |
|------------|--------|
| Today's / week's agenda, next event, free slots | iCal fetch + parse |
| Propose a new event | Google Calendar **template URL** or exported `.ics` (you click Save) |
| Edit or delete existing events | **Not** via iCal — use Google Calendar in the browser or a future Calendar API connector |

Responses from calendar endpoints include a reminder that editing/deleting existing events needs the Calendar API or browser automation.

## Cache

Fetched iCal bodies are cached at `data/calendar_cache.json` with `ETag` / `Last-Modified` for conditional GET. The secret URL is **never** written into the cache file.
