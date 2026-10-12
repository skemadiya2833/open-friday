# Adding Gmail / Calendar to the morning briefing (later)

The Stage V5 briefing is **local-only**: today's plan, reminders, and weather/news through existing Friday tools. It deliberately does **not** include Gmail or Google Calendar OAuth.

## How to add later (design only)

1. **Owner opt-in connector** under Settings → Briefing → Connectors, never auto-enabled.
2. Store OAuth tokens outside the repo (e.g. OS credential store / encrypted file under `data/secrets/`), never in chat history.
3. Fetch a short digest (unread count + next 3 events) in `collect_local_digest` behind a feature flag.
4. Keep the built-in job owner-scheduled; models still cannot create `morning_briefing` jobs.
5. Redact secrets/PII with the Stage V3 scanners before speaking or storing the script.

Trade-off: Google OAuth phones home for tokens and calendar/mail metadata — document that privacy cost next to the toggle.
