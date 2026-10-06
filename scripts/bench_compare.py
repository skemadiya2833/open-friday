"""Per-task and per-group comparison of two benchmark result files with Wilson 95% intervals.
usage: python scripts/bench_compare.py A.json B.json [labelA labelB]"""
import json, math, sys
from collections import defaultdict


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def load(path):
    runs = json.load(open(path, encoding="utf-8"))["runs"]
    by = defaultdict(list)
    for r in runs:
        by[r["task"]].append(r)
    return by, runs


def fmt(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} [{lo:.2f}-{hi:.2f}]"


def main():
    a, ra = load(sys.argv[1]); b, rb = load(sys.argv[2])
    la = sys.argv[3] if len(sys.argv) > 3 else "A"; lb = sys.argv[4] if len(sys.argv) > 4 else "B"
    print(f"| task | {la} | {lb} | meaningful? |\n|---|---|---|---|")
    for t in sorted(set(a) | set(b)):
        ka = sum(r["success"] for r in a.get(t, [])); na = len(a.get(t, []))
        kb = sum(r["success"] for r in b.get(t, [])); nb = len(b.get(t, []))
        la_, ha_ = wilson(ka, na); lb_, hb_ = wilson(kb, nb)
        sig = "yes (CIs disjoint)" if (la_ > hb_ or lb_ > ha_) else "no"
        print(f"| {t} | {fmt(ka, na)} | {fmt(kb, nb)} | {sig} |")
    ga = defaultdict(lambda: [0, 0]); gb = defaultdict(lambda: [0, 0])
    for rs, g in ((ra, ga), (rb, gb)):
        for r in rs:
            g[r["group"]][0] += r["success"]; g[r["group"]][1] += 1
    print(f"\n| group | {la} | {lb} |\n|---|---|---|")
    for k in sorted(set(ga) | set(gb)):
        print(f"| {k} | {fmt(*ga[k])} | {fmt(*gb[k])} |")
    ta = sum(r["success"] for r in ra); tb = sum(r["success"] for r in rb)
    print(f"\n**TOTAL** {la}: {fmt(ta, len(ra))}   {lb}: {fmt(tb, len(rb))}")


main()
