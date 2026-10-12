# Telegram-style notification channel (optional fallback)

## Purpose

Optional fallback when Windows toast / in-app notifications are missed: deliver reminder text to a private chat the owner controls.

## Privacy trade-off

- **Cost:** Reminder titles/bodies leave the machine and pass through a third-party messenger (metadata + content visible to that service).
- **Mitigation:** Owner opt-in only; redact secrets/PII before send (Stage V3 scanners); never send chat history or screenshots by default; allowlist bot token in local secrets store.

## Shape (if built later)

1. Settings toggle + bot token / chat id (not agent-schedulable).
2. Same reminder pipeline as local toast; channel is an additional sink.
3. Failures fall back to local notification; never block the scheduler.
