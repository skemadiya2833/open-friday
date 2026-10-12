# Trajectory export format (JSON Lines)

One JSON object per line (`GET /api/experience/export`, `ExperienceStore.export_trajectories`). No screenshots.
Typed text is never stored, only `text_len`. Secrets are redacted.

```json
{"id": "a1b2c3d4e5f6", "ts": 1791300000.0, "run_id": "...", "task": "Open Notepad and type hello",
 "apps": ["notepad"], "model": "qwen2.5vl:7b-q4_K_M", "prompt_version": "hybrid-h1", "guard_version": "guard-k3",
 "outcome": "success|failure|halted", "judgment": "objective|self|system", "confidence": 0.95,
 "failure_reason": null | {"kind": "unchanged_screen|repeated_action|hung_window|call_timeout|time_cap|objective_check_failed", "detail": "...", "recovery_tried": ["reobserve"], "elapsed_s": 41.2, "steps": 6},
 "duration_s": 21.4, "untrusted_source": false,
 "steps": [{"action": "launch|click|type|shortcut|scroll|wait|click_xy|type_xy", "element": "Text editor", "etype": "edit",
            "window": "Untitled - Notepad", "keys": "ctrl+s", "app": "notepad", "text_len": 5, "result": "changed"}]}
```
`judgment=objective` rows (a programmatic check agreed or disagreed with the agent) are the only ones suitable as
training labels; `self` rows are the agent's own claim.
