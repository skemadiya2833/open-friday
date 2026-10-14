"""Compare two benchmark result files (Stage M1).

    python scripts/bench_compare.py A.json B.json [labelA labelB] [--boot 10000] [--json out.json]

Rules
* Only tasks that are *complete in both files* are compared (every planned rep present, none aborted, none NOT_RUN or
  SKIPPED). Everything else is listed as "not compared" with the reason, never silently dropped.
* Aborted runs (e-stop, ``aborted``/status ``estop``) are excluded and counted per file.
* Per group: two-sided Fisher exact test on pooled pass/fail counts (A vs B).
* Totals: bootstrap over TASKS (resample tasks with replacement, pooled pass rate difference) -> 95% interval.
  Runs of one task are not independent samples, so the task is the unit.
* Also reports mean steps and mean wall time of the compared runs.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import defaultdict


def _logc(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact(a_pass: int, a_n: int, b_pass: int, b_n: int) -> float:
    """Two-sided Fisher exact p-value for a 2x2 table [[a_pass, a_fail], [b_pass, b_fail]]."""
    total, passes = a_n + b_n, a_pass + b_pass
    if a_n == 0 or b_n == 0:
        return 1.0

    def p(x: int) -> float:
        return math.exp(_logc(passes, x) + _logc(total - passes, a_n - x) - _logc(total, a_n))

    lo, hi = max(0, a_n - (total - passes)), min(a_n, passes)
    obs = p(a_pass)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs * (1 + 1e-9)))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load(path: str) -> tuple[dict, list[dict]]:
    d = json.load(open(path, encoding="utf-8"))
    return d.get("meta", {}), d["runs"]


def is_aborted(r: dict) -> bool:
    return bool(r.get("aborted")) or r.get("status") == "estop"


def classify(runs: list[dict], reps: int | None) -> tuple[dict[str, list[dict]], dict[str, str], int]:
    """-> (complete tasks, {task: reason not complete}, aborted run count)"""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by[r["task"]].append(r)
    aborted = sum(1 for r in runs if is_aborted(r))
    complete: dict[str, list[dict]] = {}
    why: dict[str, str] = {}
    for t, rs in by.items():
        good = [r for r in rs if not is_aborted(r) and r.get("outcome") in ("PASS", "FAIL")]
        if any(r.get("outcome") == "NOT_RUN" for r in rs):
            why[t] = "NOT_RUN (budget)"
        elif any(r.get("outcome") == "SKIPPED" for r in rs):
            why[t] = "SKIPPED"
        elif len(good) < len(rs):
            why[t] = f"{len(rs) - len(good)} aborted run(s) discarded"
        elif reps and len(good) < reps:
            why[t] = f"only {len(good)}/{reps} reps"
        else:
            complete[t] = good
    return complete, why, aborted


def boot_diff(a: dict[str, list[dict]], b: dict[str, list[dict]], tasks: list[str], n: int, seed: int = 7):
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        pick = [rng.choice(tasks) for _ in tasks]
        pa = sum(sum(r["success"] for r in a[t]) for t in pick) / max(1, sum(len(a[t]) for t in pick))
        pb = sum(sum(r["success"] for r in b[t]) for t in pick) / max(1, sum(len(b[t]) for t in pick))
        diffs.append(pb - pa)
    diffs.sort()
    return diffs[int(0.025 * n)], diffs[int(0.975 * n) - 1]


def compare(pa: str, pb: str, la: str = "A", lb: str = "B", boots: int = 10000) -> tuple[str, dict]:
    ma, ra = load(pa)
    mb, rb = load(pb)
    ca, wa, ab_a = classify(ra, ma.get("reps"))
    cb, wb, ab_b = classify(rb, mb.get("reps"))
    common = sorted(set(ca) & set(cb))
    out = [f"# {la} vs {lb}", "",
           f"Compared tasks (complete in both): **{len(common)}**. Aborted runs excluded: {la} {ab_a}, {lb} {ab_b}.", ""]
    notc = {t: f"{la}: {wa.get(t, 'ok' if t in ca else 'not run')}; {lb}: {wb.get(t, 'ok' if t in cb else 'not run')}"
            for t in sorted((set(ca) | set(cb) | set(wa) | set(wb)) - set(common))}
    if notc:
        out += ["Not compared:", *[f"- {t}: {w}" for t, w in notc.items()], ""]
    out += [f"| task | group | {la} | {lb} | steps {la}/{lb} | wall s {la}/{lb} |", "|---|---|---|---|---|---|"]
    grp = defaultdict(lambda: [0, 0, 0, 0])
    for t in common:
        g = ca[t][0]["group"]
        ka, na, kb, nb = sum(r["success"] for r in ca[t]), len(ca[t]), sum(r["success"] for r in cb[t]), len(cb[t])
        grp[g][0] += ka; grp[g][1] += na; grp[g][2] += kb; grp[g][3] += nb
        ms = lambda rs, k: statistics.mean(r.get(k, 0) or 0 for r in rs)          # noqa: E731
        out.append(f"| {t} | {g} | {ka}/{na} | {kb}/{nb} | {ms(ca[t], 'steps'):.1f}/{ms(cb[t], 'steps'):.1f} | "
                   f"{ms(ca[t], 'wall_s'):.0f}/{ms(cb[t], 'wall_s'):.0f} |")
    out += ["", f"| group | {la} | {lb} | Fisher exact p |", "|---|---|---|---|"]
    res: dict = {"groups": {}, "common_tasks": common, "aborted": {la: ab_a, lb: ab_b}}
    for g, (ka, na, kb, nb) in sorted(grp.items()):
        p = fisher_exact(ka, na, kb, nb)
        res["groups"][g] = {la: [ka, na], lb: [kb, nb], "p": p}
        out.append(f"| {g} | {ka}/{na} | {kb}/{nb} | {p:.3f}{' *' if p < 0.05 else ''} |")
    if common:
        ta = [sum(r["success"] for r in ca[t]) for t in common]
        tb = [sum(r["success"] for r in cb[t]) for t in common]
        na_, nb_ = sum(len(ca[t]) for t in common), sum(len(cb[t]) for t in common)
        lo, hi = boot_diff(ca, cb, common, boots)
        res["total"] = {la: [sum(ta), na_], lb: [sum(tb), nb_], "diff_ci95": [lo, hi]}
        meaningful = lo > 0 or hi < 0
        out += ["", f"**TOTAL** {la}: {sum(ta)}/{na_}, {lb}: {sum(tb)}/{nb_}; pass-rate difference ({lb}-{la}) "
                    f"{(sum(tb) / nb_ - sum(ta) / na_) * 100:+.1f} pts, bootstrap-over-tasks 95% CI [{lo * 100:+.1f}, {hi * 100:+.1f}] pts "
                    f"=> {'MEANINGFUL' if meaningful else 'not distinguishable from noise'}.",
                ""
                f"Wilson 95% per arm: {la} {wilson(sum(ta), na_)[0]:.2f}-{wilson(sum(ta), na_)[1]:.2f}, "
                f"{lb} {wilson(sum(tb), nb_)[0]:.2f}-{wilson(sum(tb), nb_)[1]:.2f}."]
    return "\n".join(out), res


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    boots = int(argv[argv.index("--boot") + 1]) if "--boot" in argv else 10000
    args = [a for a in args if a != str(boots)]
    jpath = argv[argv.index("--json") + 1] if "--json" in argv else None
    if jpath:
        args = [a for a in args if a != jpath]
    la = args[2] if len(args) > 2 else "A"
    lb = args[3] if len(args) > 3 else "B"
    text, res = compare(args[0], args[1], la, lb, boots)
    print(text)
    if jpath:
        json.dump(res, open(jpath, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
