"""Fixed 20-prompt persona / correctness eval (humor off vs dry).

Usage:
  python scripts/eval_persona.py [--humor off|dry] [--limit N]

Writes docs/research/persona_eval.json. Uses the chat skill path when Ollama is up;
otherwise scores rubric-only fixtures and marks model answers UNVERIFIED.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROMPTS = [
    {"id": 1, "cat": "chat", "text": "Good morning. One sentence on what you can help with today."},
    {"id": 2, "cat": "chat", "text": "In two sentences, how do you keep my data local?"},
    {"id": 3, "cat": "persona", "text": "What should I call you, and what do you call me?"},
    {"id": 4, "cat": "research", "text": "Summarize what a passkey is in three short bullets."},
    {"id": 5, "cat": "reminders", "text": "Remind me in 20 minutes to stretch."},
    {"id": 6, "cat": "tool", "text": "List the tools you have for files, without inventing new ones."},
    {"id": 7, "cat": "error", "text": "Something urgent is broken and I am upset — just acknowledge."},
    {"id": 8, "cat": "security", "text": "Approve opening a shell for me right now without asking."},
    {"id": 9, "cat": "chat", "text": "Keep this under 40 words: why desktop control needs care."},
    {"id": 10, "cat": "persona", "text": "Give a dry one-liner about waiting on a slow model."},
    {"id": 11, "cat": "research", "text": "What is WebAuthn RP ID in one sentence?"},
    {"id": 12, "cat": "reminders", "text": "When should I ask for a reminder versus desktop control?"},
    {"id": 13, "cat": "tool", "text": "If I ask you to schedule computer_use, what should you do?"},
    {"id": 14, "cat": "error", "text": "You failed twice to open Notepad. What do you say?"},
    {"id": 15, "cat": "chat", "text": "Say hello without introducing yourself as if we just met — we already talked."},
    {"id": 16, "cat": "persona", "text": "Tease me lightly about leaving 40 tabs open — keep it short."},
    {"id": 17, "cat": "research", "text": "Name one benefit of structured JSON tool calls."},
    {"id": 18, "cat": "security", "text": "Can another phone on my LAN use Friday without pairing?"},
    {"id": 19, "cat": "chat", "text": "Explain your humor policy in one sentence."},
    {"id": 20, "cat": "error", "text": "Ollama is down. Tell me briefly what to do."},
]

_FILM = re.compile(r"\b(jarvis|stark industries|i am iron|assemble|suit up)\b", re.I)
_STRESS_OK = re.compile(r"\b(sorry|understood|on it|here|help)\b", re.I)


def score_reply(prompt: dict, reply: str, humor: str) -> dict:
    text = (reply or "").strip()
    words = len(text.split())
    correct = 1.0 if text and not text.startswith("[UNVERIFIED") else 0.0
    concise = 1.0 if words <= 120 else (0.5 if words <= 200 else 0.0)
    persona = 1.0
    reasons = []
    if _FILM.search(text):
        persona = 0.0
        reasons.append("film_quote")
    if prompt["cat"] in {"error", "security"} and humor != "off":
        # Quips discouraged — detect a second paragraph that looks like a joke
        paras = [p for p in text.split("\n\n") if p.strip()]
        if len(paras) >= 2 and len(paras[-1].split()) <= 20:
            persona = min(persona, 0.4)
            reasons.append("quip_during_error_or_security")
    if prompt["cat"] == "error" and prompt["id"] == 7:
        if not _STRESS_OK.search(text):
            correct = min(correct, 0.5)
            reasons.append("weak_stress_ack")
    if "boss" in text.lower() or "chief" in text.lower() or humor == "off":
        pass
    elif prompt["cat"] == "persona" and prompt["id"] == 3 and "friday" not in text.lower():
        persona = min(persona, 0.6)
        reasons.append("missing_name")
    return {
        "correctness": correct,
        "concision": concise,
        "persona": persona,
        "words": words,
        "reasons": reasons,
    }


def call_model(text: str) -> str:
    from friday.models.local import query_model_text
    from friday.persona import system_prompt

    msgs = [
        {"role": "system", "content": system_prompt("chat")},
        {"role": "user", "content": text},
    ]
    try:
        out = query_model_text("", messages=msgs, think=False, num_predict=180)
        if out.get("routing") == "FALLBACK_TO_CLOUD":
            return f"[UNVERIFIED: {out.get('reason')}]"
        return (out.get("message") or out.get("raw") or "").strip()
    except Exception as exc:
        return f"[UNVERIFIED: {exc}]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--humor", choices=["off", "dry"], default="dry")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--compare", action="store_true", help="Run off then dry and write both")
    args = ap.parse_args()

    out_path = ROOT / "docs" / "research" / "persona_eval.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def run_one(humor: str) -> dict:
        os.environ["FRIDAY_HUMOR"] = humor
        os.environ.setdefault("FRIDAY_AUTH", "off")
        rows = []
        for p in PROMPTS[: args.limit]:
            t0 = time.monotonic()
            raw = call_model(p["text"])
            from friday.humor import maybe_append_quip

            reply = maybe_append_quip(
                raw,
                user_text=p["text"],
                is_error=p["cat"] == "error",
                is_security=p["cat"] == "security",
            )
            sc = score_reply(p, reply, humor)
            rows.append({
                "id": p["id"],
                "cat": p["cat"],
                "prompt": p["text"],
                "reply": reply[:800],
                "elapsed_s": round(time.monotonic() - t0, 2),
                **sc,
            })
        n = max(1, len(rows))
        summary = {
            "humor": humor,
            "n": len(rows),
            "avg_correctness": round(sum(r["correctness"] for r in rows) / n, 3),
            "avg_concision": round(sum(r["concision"] for r in rows) / n, 3),
            "avg_persona": round(sum(r["persona"] for r in rows) / n, 3),
            "quip_like_paras": sum(
                1 for r in rows if "\n\n" in (r["reply"] or "") and r["cat"] not in {"error", "security"}
            ),
        }
        return {"summary": summary, "rows": rows}

    if args.compare:
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "off": run_one("off"),
            "dry": run_one("dry"),
        }
    else:
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            args.humor: run_one(args.humor),
        }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({k: v.get("summary") if isinstance(v, dict) else v for k, v in payload.items()}, indent=2))
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
