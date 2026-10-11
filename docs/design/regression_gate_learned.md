# Regression gate for any learned change

## Rule

Any change that comes from traces → skill proposals (or similar learning) is **accepted only if** a held-out eval set does not regress.

## Gate

1. Freeze a held-out prompt/task set (persona 20-prompt + hybrid smoke tasks).
2. Score baseline on that set before applying the proposal.
3. Apply the proposal in a quarantine / branch, re-score.
4. Accept only if correctness and safety metrics are ≥ baseline within a small epsilon; otherwise reject and keep the proposal as documentation.

## Non-goals

- No online weight updates in the product path.
- No silent auto-merge of agent-written skills.
