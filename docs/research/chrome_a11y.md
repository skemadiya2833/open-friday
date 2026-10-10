# G1/G2 diagnosis: why Chrome and canvas tasks ended after 0-2 steps

Method: `scripts/diag_chrome_a11y.py` (Chrome variants, timed Windows-MCP snapshots, `use_dom` on/off) and
`scripts/hybrid_debug.py --page counter` (one live agent run with every observation and model reply printed).
Raw dumps contain the owner's window titles and are git-ignored; `diag_chrome/summary.json` is kept.

## Root causes (all verified live)
1. **Chromium builds its accessibility tree lazily.** The first UI-Automation query only wakes it. A snapshot 2-3 s
   after the window appears shows the taskbar and no page; about 5 s later the page is present. Launching with
   `--force-renderer-accessibility` makes it available at once (verified), but the agent cannot control how the user's
   browser was started, so the generic fix is in the agent: `_settle_browser_tree` re-snapshots (4 x 1.5 s) while a
   browser window is focused and no `document` element exists. No benchmark-specific code.
2. **Taskbar clicks stole focus.** With no page visible, the model clicked the taskbar Chrome button, which switched
   focus to the editor window; its enormous tree came back truncated with 0 elements and the model looped on stale ids.
   Fixed indirectly by (1); the repetition guard and the no-effect limit remain as backstops.
3. **Text nodes were discarded** (e.g. `Count: 3`), so state shown on canvas/page was invisible and the action
   fingerprint saw "no change" after real changes. Text nodes are now parsed (G2), shown to the model as `page_text`,
   and part of the fingerprint.

## G2 parser
Element names containing line breaks (taskbar tray, clock) are joined back into one node (`join_multiline_nodes`);
tests use the anonymised live fixture.

## Result after the fixes (single counter-page run)
The agent now sees the page, clicks the right element and every click is verified as `changed`. It still does not
stop at "3 clicks" (qwen2.5vl:7b does not count its own repeated actions) and ends FAILED at the step limit. That is a
model limitation, reported as such in the benchmark rather than special-cased.
