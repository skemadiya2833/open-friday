# Agent failure modes: what others found, what we applied (2026-10-06)

Sources (fetched this session): VLAA-GUI "Knowing when to STOP, RECOVER and SEARCH" (arXiv 2604.21375), "Naive Visual
Memory is Not Enough: A Failure-Mode Study of GUI Agents" (2606.14106), OSWorld 2.0 (2606.29537), UFO2 (2504.14603),
and voice-agent latency write-ups (Picovoice guide, netguru, arXiv 2603.05413, QubitTool, agent-patterns catalog).

## GUI agents

| Finding | Source | What we did |
|---|---|---|
| Repetitive loops are a chronic failure; single-granularity anti-loop heuristics are not enough. Detect repeated actions, **recurring screen states** and no-change, and escalate. | VLAA-GUI | `StallDetector` now also detects *state cycles* (returning to an earlier screen state `max_revisits`=2 times, i.e. the 3rd visit, same threshold as VLAA tier 2). A cycle skips the useless re-observe/Escape rungs and goes straight to "change strategy"; a 3rd cycle stops the run with a structured `agent_failure`. |
| Strategy change should be forced, not suggested (hard directive). | VLAA-GUI | The note injected after a cycle lists the last six steps and forbids repeating them. |
| Programmatic route beats GUI where possible (their Coding Agent; Agent S3 coding actions). | VLAA-GUI, Agent S3 | `friday/agent/router.py`: tools-first. "Type X, press Enter, type Y, save as PATH" is written directly (verified by read-back). No GUI, no loop possible. |
| Agents declare success early or never verify. | VLAA-GUI, OSWorld 2.0 | Already present: `done` needs on-screen evidence. Router verifies by reading the file back. |
| Agents spend <7% of budget on detecting/repairing their own errors; they undo and redo work. | OSWorld 2.0 | Self-undo guard: no click back into the field just typed in; no clear-and-retype of text already typed there. |
| Control detection failures dominate on Windows (62% of UFO2 failures); UIA + vision hybrid helps. | UFO2 | Already hybrid (UIA tree + screenshot fallback). Unchanged. |
| Full-screenshot memory worsens action-level failures; store action-local crops. | AGMem | Experience memory stays text-only and off by default (consistent with the finding). Not changed. |

Root cause of the Notepad two-line failure the owner saw: each `type` action carried the element id, and Windows-MCP clicks
the element before typing. Typing "beta" on line 2 therefore re-clicked the text area (cursor lands on line 1), the model
saw a wrong result, cleared, and the same state recurred. Fixed three ways (composite multi-line `type`, self-undo guard,
cycle breaker), plus the router which avoids the GUI for this class of task.

## Voice

| Finding | What we did |
|---|---|
| Realtime = streaming + pipelining; send tokens to TTS at sentence boundaries, min ~10 chars, flush at end. | `FridayLive.speaker`: sentence splitter (min 18 chars, never splits `3.5`), audio of sentence N+1 is fetched while N plays. |
| Fixed silence timeout is a poor end-of-turn proxy; short = cuts people off, long = sluggish. | Two profiles: Realtime 550 ms, Relaxed 1100 ms (owner choice). Semantic endpointing (small turn model) is a documented next step, not built. |
| Fillers only for genuinely slow turns, short, and must be interruptible. | Filler after 1.3 s (Realtime) / 2.4 s (Relaxed), at most 2 per turn, immediately when desktop work starts; clicking the orb interrupts. |
| Barge-in must invalidate in-flight work, not only audio. | Orb click aborts the speaker queue and stops audio. **Gap:** it does not cancel the running chat request or detect speech-over-playback automatically (echo risk); recorded as a limitation. |

## Not verified
Everything above the Notepad router was verified by unit tests only; no live GUI benchmark was run after these changes
(live budget nearly spent). The UI was checked in the Cursor browser (overlay renders, sentence splitter output, settings
persist); microphone input and real TTS audio were not exercised.
