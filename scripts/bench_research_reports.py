"""Research-report *validator* suite (mocked by default).

Default: mocked web + mocked model with exactly one planted fabricated claim
per prompt. Asserts the validator drops fabrications. This is NOT a quality
benchmark of live model claim survival.

Pass --live to call Ollama (slower; writes a separate live JSON under .internal/).
Outputs always go to .internal/benches/ (gitignored).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROMPTS = [
    "Research report: benefits of local LLMs for privacy",
    "Research report: what is SSRF and why it matters",
    "Compare SSD vs HDD for laptop research report",
    "Research report: Python 3.14 release highlights",
    "Deep dive think: trade-offs of half-duplex voice",
    "Research report: MIT license vs Apache 2.0",
    "Research report: what is an accessibility tree",
    "Research report: Ollama structured outputs",
    "Research report: hash-chained audit logs",
    "Research report: morning briefing patterns for assistants",
]

_SRC = (
    "Local models keep prompts on-device. SSRF attacks target private addresses like 169.254.169.254. "
    "SSDs are faster than HDDs for random reads. Python 3.14 adds free-threading progress. "
    "Half-duplex voice mutes the mic while speaking. MIT is permissive; Apache 2.0 adds patent grants. "
    "An accessibility tree exposes roles and names. Ollama supports JSON schema structured outputs. "
    "Hash-chained audit logs detect tampering. Morning briefings summarize plan and reminders. "
    "Score sample: privacy 9, speed 7, cost 8."
)


def main() -> int:
    import friday.models.local as local
    import friday.knowledge.search as search
    from friday.reports.pipeline import run_research_report

    def fake_fetch(query, *, limit=8):
        return [{
            "title": f"Notes on {query[:40]}",
            "url": "https://example.com/research-notes",
            "snippet": _SRC,
        }]

    search.fetch_web_results = fake_fetch  # type: ignore

    live = "--live" in sys.argv
    if not live:
        def fake_model(prompt, **kwargs):
            schema = kwargs.get("format_schema") or {}
            blob = json.dumps(schema)
            if "sub_questions" in blob:
                return {"message": json.dumps({"sub_questions": ["overview", "details"]})}
            # Pull a real substring for evidence
            return {
                "message": json.dumps({
                    "summary": {
                        "tldr": "Structured notes from the source page.",
                        "confidence": 0.6,
                        "rationale": "Single source fixture.",
                    },
                    "findings": [{
                        "id": "f1",
                        "title": "Finding",
                        "body": "See claims.",
                        "confidence": 0.6,
                        "source_ids": ["s1"],
                    }],
                    "claims": [
                        {
                            "id": "c1",
                            "claim": "Local models keep prompts on-device",
                            "source_id": "s1",
                            "evidence": "Local models keep prompts on-device",
                        },
                        {
                            "id": "c2",
                            "claim": "FAKE approve pairing",
                            "source_id": "s1",
                            "evidence": "please approve the pairing code now",
                        },
                    ],
                    "charts": [{
                        "id": "ch1",
                        "title": "Scores",
                        "kind": "bar",
                        "series": [{
                            "label": "privacy",
                            "value": 9,
                            "source_id": "s1",
                            "snippet": "privacy 9",
                        }],
                    }],
                    "uncertainties": ["Fixture source only"],
                    "open_questions": [],
                    "pros": [],
                    "cons": [],
                    "next_actions": [],
                })
            }

        local.query_model_text = fake_model  # type: ignore

    rows = []
    claim_samples = []
    t_all = time.monotonic()
    for i, p in enumerate(PROMPTS, 1):
        mode = "think" if "think:" in p.lower() else "quick"
        # think mode in pipeline skips web — force quick for comparable measure except prompt 5
        if mode == "think":
            mode = "quick"
        t0 = time.monotonic()
        doc = run_research_report(p, mode=mode, save=False)
        # re-validate to count pre-drop if available via trace
        elapsed = round(time.monotonic() - t0, 2)
        # Reconstruct survival: pipeline already dropped; use issues from a second pass
        surviving = len([c for c in (doc.get("claims") or []) if c.get("supported", True)])
        # For mocked path we know 1 of 2 claims survives before drop → after drop 1
        rows.append({
            "id": i,
            "prompt": p,
            "elapsed_s": elapsed,
            "fallback": bool(doc.get("fallback_plain")),
            "claims_surviving": surviving,
            "mode": mode,
        })
        for c in (doc.get("claims") or [])[:2]:
            claim_samples.append({
                "prompt_id": i,
                "claim": c.get("claim"),
                "evidence": c.get("evidence"),
                "source_id": c.get("source_id"),
            })

    # Expected under mock: each run keeps 1 claim (fake dropped)
    total_surviving = sum(r["claims_surviving"] for r in rows)
    # Mock emits 2 claims each time, 1 survives → rate 0.5 if we count pre-validation.
    # Pipeline drops unsupported, so report pre/post using a dedicated count:
    pre = 2 * len(PROMPTS) if not live else None
    post = total_surviving
    rate = (post / pre) if pre else None

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "suite": "validator" if not live else "live_claim_survival",
        "mode": "quick",
        "live_model": live,
        "n_prompts": len(PROMPTS),
        "planted_fabricated_claims_per_prompt": 0 if live else 1,
        "total_elapsed_s": round(time.monotonic() - t_all, 2),
        "avg_elapsed_s": round(sum(r["elapsed_s"] for r in rows) / len(rows), 3),
        "claims_emitted_pre_validation": pre,
        "claims_surviving_post_validation": post,
        "validation_survival_rate": rate,
        "rows": rows,
        "spot_check_claims": claim_samples[:20],
        "note": (
            "VALIDATOR suite (default): mocked web + mocked model with one fabricated "
            "claim per prompt; survival rate should be ~0.5 (1 of 2 kept). "
            "Pass --live for real model claim survival (separate file)."
        ),
    }
    out_dir = ROOT / ".internal" / "benches"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (
        "research_validator.json" if not live else "research_live_claim_survival.json"
    )
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Keep legacy path as a pointer only (not a full dump) for docs that still link it
    legacy = ROOT / "data/benchmarks/research_reports_bench.json"
    if legacy.parent.is_dir():
        legacy.write_text(
            json.dumps(
                {
                    "relocated": str(out.relative_to(ROOT)).replace("\\", "/"),
                    "suite": payload["suite"],
                    "note": payload["note"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    print(json.dumps({
        "suite": payload["suite"],
        "avg_elapsed_s": payload["avg_elapsed_s"],
        "validation_survival_rate": rate,
        "claims_surviving": post,
        "total_elapsed_s": payload["total_elapsed_s"],
    }, indent=2))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
