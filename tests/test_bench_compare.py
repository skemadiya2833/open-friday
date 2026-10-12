"""Stage M1: bench_compare statistics and exclusion rules."""
import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("bench_compare", Path(__file__).parents[1] / "scripts" / "bench_compare.py")
bc = importlib.util.module_from_spec(spec)
sys.modules["bench_compare"] = bc
spec.loader.exec_module(bc)


def run(task, group, rep, ok, **kw):
    return {"task": task, "group": group, "rep": rep, "outcome": "PASS" if ok else "FAIL", "success": ok,
            "steps": 3, "wall_s": 10.0, **kw}


def write(p, runs, reps=3):
    p.write_text(json.dumps({"meta": {"reps": reps}, "runs": runs}), encoding="utf-8")
    return str(p)


def test_fisher_exact_known_values():
    assert abs(bc.fisher_exact(3, 3, 0, 3) - 0.1) < 1e-9          # classic 3/3 vs 0/3
    assert abs(bc.fisher_exact(5, 10, 5, 10) - 1.0) < 1e-9
    assert bc.fisher_exact(0, 0, 1, 2) == 1.0


def test_only_tasks_complete_in_both_are_compared_and_aborts_are_counted(tmp_path):
    a = [run("t1", "g", i, True) for i in (1, 2, 3)] + [run("t2", "g", i, False) for i in (1, 2, 3)] \
        + [run("t3", "g", 1, True)]
    b = [run("t1", "g", i, i < 3) for i in (1, 2, 3)] + [run("t2", "g", 1, False, aborted=True, status="estop")] \
        + [run("t2", "g", i, False) for i in (2, 3)] + [run("t3", "g", i, True) for i in (1, 2, 3)]
    text, res = bc.compare(write(tmp_path / "a.json", a), write(tmp_path / "b.json", b), "A", "B", boots=200)
    assert res["common_tasks"] == ["t1"]                            # t2 has an aborted run in B, t3 incomplete in A
    assert res["aborted"] == {"A": 0, "B": 1}
    assert "t2" in text and "aborted run(s) discarded" in text and "only 1/3 reps" in text
    assert res["groups"]["g"]["A"] == [3, 3] and res["groups"]["g"]["B"] == [2, 3]


def test_bootstrap_over_tasks_flags_a_consistent_difference(tmp_path):
    tasks = [f"t{i}" for i in range(8)]
    a = [run(t, "g", r, False) for t in tasks for r in (1, 2, 3)]
    b = [run(t, "g", r, True) for t in tasks for r in (1, 2, 3)]
    _, res = bc.compare(write(tmp_path / "a.json", a), write(tmp_path / "b.json", b), boots=500)
    lo, hi = res["total"]["diff_ci95"]
    assert lo > 0.9 and hi <= 1.0
    same = write(tmp_path / "c.json", a)
    _, res2 = bc.compare(write(tmp_path / "a2.json", a), same, boots=500)
    assert res2["total"]["diff_ci95"] == [0.0, 0.0]
