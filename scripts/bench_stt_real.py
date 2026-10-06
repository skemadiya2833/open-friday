"""STT accuracy + speed benchmark on recorded WAV files (word error rate).

    python scripts/bench_stt_real.py --models large-v3-turbo small base
    python scripts/bench_stt_real.py --dir data/voice_lab/clips --label synthetic     # plumbing sanity check
    python scripts/bench_stt_real.py --dir data/voice_lab/real --label real            # YOUR voice (default)

Reads <dir>/manifest.json (list of {id, text}) and <dir>/<id>.wav (16 kHz mono).
For each model: load time, per-clip decode time, WER/CER after normalisation, peak VRAM (nvidia-smi delta).
Writes docs/research/stt_wer_<label>.json. Only clips recorded by the OWNER count as the accuracy result;
synthetic clips are a plumbing check and say nothing about real speech.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

_NUM = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven",
        "8": "eight", "9": "nine", "10": "ten", "11": "eleven", "12": "twelve", "13": "thirteen", "14": "fourteen",
        "15": "fifteen", "20": "twenty", "30": "thirty", "40": "forty", "50": "fifty", "60": "sixty"}


def norm(s: str) -> list[str]:
    s = s.lower().replace("%", " percent").replace("&", " and ")
    s = re.sub(r"(\d+):(\d+)", lambda m: f"{_NUM.get(m[1], m[1])} {_NUM.get(m[2], m[2])}", s)
    s = re.sub(r"\d+", lambda m: _NUM.get(m.group(0), m.group(0)), s)
    s = re.sub(r"[^a-z' ]+", " ", s)
    s = s.replace(" dot ", " . ").replace(".", " dot ")
    return s.split()


def edit(a: list, b: list) -> int:
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (x != y))
    return d[-1]


def vram() -> int:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return -1


def load_wav(p: Path) -> np.ndarray:
    with wave.open(str(p), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, "need 16 kHz mono"
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "voice_lab" / "real"))
    ap.add_argument("--label", default="real")
    ap.add_argument("--models", nargs="+", default=["large-v3-turbo", "small", "base"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute", default="float16")
    a = ap.parse_args()
    d = Path(a.dir)
    mf = d / "manifest.json"
    if not mf.exists():
        print(f"No recordings found in {d}. Run scripts/record_stt_samples.py first.")
        return 2
    items = json.loads(mf.read_text())
    if isinstance(items, dict):
        items = list(items.values())
    from faster_whisper import WhisperModel
    import ctranslate2

    report = {"label": a.label, "dir": str(d), "n_clips": len(items), "ctranslate2": ctranslate2.__version__,
              "device": a.device, "compute": a.compute, "models": []}
    for m in a.models:
        base = vram()
        t0 = time.perf_counter()
        try:
            model = WhisperModel(m, device=a.device, compute_type=a.compute if a.device == "cuda" else "int8")
        except Exception as exc:  # noqa: BLE001
            report["models"].append({"model": m, "error": f"{type(exc).__name__}: {exc}"})
            continue
        load_s = time.perf_counter() - t0
        loaded = vram()
        errs = words = cerr = chars = 0
        rows = []
        dec = []
        for it in items:
            audio = load_wav(d / f"{it['id']}.wav")
            t1 = time.perf_counter()
            segs, _ = model.transcribe(audio, language="en", beam_size=1, condition_on_previous_text=False)
            hyp = " ".join(s.text.strip() for s in segs)
            dt = time.perf_counter() - t1
            dec.append(dt)
            r, h = norm(it["text"]), norm(hyp)
            e = edit(r, h)
            ce = edit(list(" ".join(r)), list(" ".join(h)))
            errs += e
            words += len(r)
            cerr += ce
            chars += len(" ".join(r))
            rows.append({"id": it["id"], "ref": it["text"], "hyp": hyp.strip(), "word_errors": e, "decode_s": round(dt, 3)})
        peak = vram()
        report["models"].append({
            "model": m, "load_s": round(load_s, 1), "vram_delta_mb": (loaded - base) if base >= 0 else None,
            "vram_peak_mb": peak, "wer": round(errs / max(1, words), 4), "cer": round(cerr / max(1, chars), 4),
            "decode_s_mean": round(float(np.mean(dec)), 3), "decode_s_first_warm": round(dec[1], 3) if len(dec) > 1 else None,
            "clips": rows})
        print(f"{m}: WER {errs / max(1, words):.3f}  CER {cerr / max(1, chars):.3f}  decode {np.mean(dec):.2f}s  load {load_s:.1f}s")
        del model
    out = ROOT / "docs" / "research" / f"stt_wer_{a.label}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
