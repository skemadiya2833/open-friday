# Conversational turn-taking (browser voice)

Friday’s **Realtime** voice mode does **not** treat Chrome `SpeechRecognition` `isFinal` as end-of-turn. Chrome often finalizes after a short mid-phrase breath; committing there feels like “it listens too little and starts thinking.”

## What we implemented

File: `web/public/turn.js` (loaded before `app.js`).

A turn commits only when **all** of these hold (or a max eagerness timeout fires):

1. **Mic energy quiet** — Web Audio analyser RMS below threshold for ~300–400 ms (not just ASR silence).
2. **No open interim hypothesis** — still revising transcript → keep listening.
3. **Semantic completeness** — local heuristics (punctuation, trailing “and/um/the…”, short acknowledgements, short imperatives). Incomplete text → longer silence required.

Eagerness bands (Realtime = `medium`, Relaxed = `low`) follow the *idea* of OpenAI Realtime `semantic_vad` timeouts (high ≈ 2 s, medium ≈ 4 s, low ≈ 6–8 s max wait). No OpenAI API is called; scoring is local.

While waiting, UI stays on **LISTENING** (“Still listening…” / “Go on — I'm still listening”) instead of jumping to thinking.

## Sources (ideas only — no code copied)

| Source | Idea used |
|--------|-----------|
| [OpenAI Realtime VAD](https://developers.openai.com/api/docs/guides/realtime-vad) | `server_vad` silence vs `semantic_vad` completeness + eagerness max waits |
| [Deepgram end of speech](https://developers.deepgram.com/docs/understanding-end-of-speech-detection) | Utterance end needs ≥ ~1 s word-gap; VAD alone fails in noise |
| [Azure Speech timeouts](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech) | Longer `segmentationSilenceTimeoutMs` tolerates mid-phrase pauses |
| [Chrome Web Speech intro](https://developer.chrome.com/blog/voice-driven-web-apps-introduction-to-the-web-speech-api) | `continuous` + `interimResults`; finals change under you — not turn boundaries |
| Research on adaptive endpointing | Fixed silence alone causes early cutoffs on disfluencies |

## Tuning

- Overlay: **Realtime** (snappier, medium eagerness) vs **Relaxed** (patient, low eagerness).
- Desk speakers: keep duplex **Hold** so Friday’s voice does not re-trigger the mic.
