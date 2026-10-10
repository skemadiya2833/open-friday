"""Agentic behaviour helpers: plan-before-act, deep mode, clarifying questions."""

from __future__ import annotations

import os
import re
import time
from typing import Any

_DEEP_HINT = re.compile(
    r"\b(deep mode|think (hard|carefully|deeply)|reason carefully|"
    r"take your time|thorough analysis)\b",
    re.I,
)
_MULTI_STEP = re.compile(
    r"\b(then|after that|next|and also|finally|step \d|first .+ then)\b",
    re.I,
)


def deep_mode_enabled(message: str = "") -> bool:
    env = (os.environ.get("FRIDAY_DEEP") or "").strip().lower() in {"1", "true", "yes", "on"}
    return env or bool(_DEEP_HINT.search(message or ""))


def deep_token_budget() -> int:
    try:
        return max(64, int(os.environ.get("FRIDAY_DEEP_TOKEN_BUDGET", "512")))
    except ValueError:
        return 512


def deep_timeout_s() -> float:
    try:
        return max(5.0, float(os.environ.get("FRIDAY_DEEP_TIMEOUT", "45")))
    except ValueError:
        return 45.0


def looks_multi_step(message: str) -> bool:
    text = (message or "").strip()
    if len(text) > 160 and _MULTI_STEP.search(text):
        return True
    return bool(_MULTI_STEP.search(text)) and len(text.split()) >= 8


def plan_preamble(objective: str) -> str:
    """Short plan block prepended to multi-step agent prompts."""
    return (
        "MULTI-STEP PROTOCOL:\n"
        "1. Write a short PLAN (2–5 bullets) before acting.\n"
        "2. Execute ONE step, then VERIFY it worked from evidence.\n"
        "3. On failure: change strategy (do not repeat the same failing action).\n"
        "4. Ask a clarifying question ONLY if the answer changes the next action.\n"
        "5. Prefer tools/router before GUI clicks.\n"
        "6. When done: summarize what was done and verified.\n"
        f"Objective: {objective.strip()[:500]}\n"
    )


def with_plan_if_needed(system_overlay: str, message: str) -> str:
    if looks_multi_step(message):
        return f"{system_overlay}\n\n{plan_preamble(message)}"
    return system_overlay


def run_deep_chat(
    messages: list[dict[str, Any]],
    *,
    on_token=None,
) -> dict[str, Any]:
    """Chat with thinking enabled and a time budget; fall back if slow."""
    from friday.config import CHAT_NUM_CTX, CHAT_NUM_PREDICT
    from friday.models.local import query_model_text

    budget = deep_token_budget()
    timeout = deep_timeout_s()
    t0 = time.monotonic()
    result = query_model_text(
        "",
        messages=messages,
        format_json=False,
        reasoning_mode=True,
        think=True,
        num_predict=min(CHAT_NUM_PREDICT + budget, budget + 256),
        num_ctx=CHAT_NUM_CTX,
        on_token=on_token,
    )
    elapsed = time.monotonic() - t0
    meta = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    meta["deep"] = True
    meta["deep_elapsed_s"] = round(elapsed, 2)
    if elapsed > timeout or result.get("routing") == "FALLBACK_TO_CLOUD":
        # Fall back to a normal (non-thinking) pass.
        fallback = query_model_text(
            "",
            messages=messages,
            format_json=False,
            reasoning_mode=False,
            think=False,
            num_predict=CHAT_NUM_PREDICT,
            num_ctx=CHAT_NUM_CTX,
            on_token=on_token,
        )
        fb_meta = dict(fallback.get("metadata") or {}) if isinstance(fallback.get("metadata"), dict) else {}
        fb_meta.update({"deep": True, "deep_fallback": True, "deep_elapsed_s": round(elapsed, 2)})
        fallback["metadata"] = fb_meta
        return fallback
    result["metadata"] = meta
    return result
