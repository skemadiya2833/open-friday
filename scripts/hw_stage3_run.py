"""Stage 3 hardware inventory + measured experiments (<10 min budget).

Writes only under .internal/hw/ (gitignored). Does not modify the Windows Ollama service.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Run Stage 3 hardware measurements")
    p.add_argument("--skip-whisper", action="store_true", help="Skip faster-whisper load (faster)")
    p.add_argument("--npu-web", action="store_true", help="Fetch brief web notes for npu_research.md")
    args = p.parse_args()

    web_notes = None
    if args.npu_web:
        try:
            import urllib.request

            url = "https://ryzenai.docs.amd.com/en/latest/modelrun.html"
            with urllib.request.urlopen(url, timeout=8.0) as r:  # noqa: S310
                snippet = r.read(1200).decode("utf-8", errors="replace")
            web_notes = f"- Fetched `{url}` (truncated): …{snippet[:400]}…"
        except Exception as exc:  # noqa: BLE001
            web_notes = f"- Web fetch failed: {exc}"

    from friday.diagnostics.hardware import collect_inventory, hw_data_dir
    from friday.diagnostics.hw_experiments import (
        measure_ollama_tune,
        measure_speech_and_embed,
        write_igpu_display_guide,
        write_npu_research_md,
    )
    from friday.runtime.resource_policy import measure_residency

    print(f"[hw] output dir: {hw_data_dir()}")
    inv = collect_inventory(write_json=True)
    print(f"[hw] inventory.json ({inv.get('duration_s')}s)")

    res = measure_residency()
    print(f"[hw] residency.json status={res.get('status')}")

    if args.skip_whisper:
        from friday.diagnostics.hw_experiments import _write_json

        _write_json("speech_embed.json", {"status": "SKIPPED", "reason": "--skip-whisper"})
    else:
        se = measure_speech_and_embed(audio_seconds=1.5)
        print(f"[hw] speech_embed.json status={se.get('status')}")

    tune = measure_ollama_tune()
    print(f"[hw] ollama_tune.json status={tune.get('status')}")

    write_igpu_display_guide()
    write_npu_research_md(web_notes=web_notes)
    print("[hw] igpu_display.md + npu_research.md written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
