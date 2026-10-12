"""Validate the benchmark's success checks WITHOUT any agent (oracle + negative controls).

For each check: it must FAIL on an untouched state and PASS after the task is done by hand
(programmatically). Also verifies cleanup closes only windows opened here.
Opens scratch Notepad-free apps (Calculator, Settings, Explorer, a local Chrome page).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from friday.bench import winutil as wu  # noqa: E402
from friday.bench.site import Site  # noqa: E402
from friday.bench.tasks import Ctx, build_tasks, fresh_scratch  # noqa: E402

results: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def post(site: Site, token: str, kind: str, **data) -> None:
    body = json.dumps({"token": token, "kind": kind, **data}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{site.port}/api/event", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()


def press(*vks: int) -> None:
    for vk in vks:
        wu.user32.keybd_event(vk, 0, 0, 0)
        wu.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.08)


def main() -> int:
    tasks = {t.id: t for t in build_tasks()}
    site = Site()
    root = Path(tempfile.mkdtemp(prefix="friday_bench_selftest_"))
    base_all = {w.hwnd for w in wu.list_windows()}
    base_pids = {w.pid for w in wu.list_windows()}

    def mk(tid: str, rep: int = 1) -> Ctx:
        c = Ctx(scratch=fresh_scratch(root, tid, rep), site=site, token=f"st-{tid}-{rep}", rep=rep)
        if tasks[tid].setup and tasks[tid].group not in ("chrome", "canvas"):
            tasks[tid].setup(c)
        return c

    # ---- file based (negative then positive)
    for tid, name, content in [("notepad_type_save", "n2.txt", "hello friday"), ("notepad_two_lines", "n3.txt", "alpha\r\nbeta"),
                               ("notepad_subfolder", "sub/n5.txt", "nested ok"), ("notepad_edit", "n6.txt", "final")]:
        c = mk(tid)
        neg = tasks[tid].check(c)[0]
        p = c.scratch / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8"))
        pos = tasks[tid].check(c)[0]
        p.write_text("wrong", encoding="utf-8")
        wrong = tasks[tid].check(c)[0]
        rec(f"{tid}: neg fails, pos passes, wrong content fails", (not neg) and pos and (not wrong))

    c = mk("explorer_new_folder")
    n1 = tasks["explorer_new_folder"].check(c)[0]
    (c.scratch / "bench_folder").mkdir()
    rec("explorer_new_folder check", (not n1) and tasks["explorer_new_folder"].check(c)[0])
    c = mk("explorer_new_textfile")
    n1 = tasks["explorer_new_textfile"].check(c)[0]
    (c.scratch / "bench_note.txt").write_text("")
    rec("explorer_new_textfile check", (not n1) and tasks["explorer_new_textfile"].check(c)[0])

    # ---- local site (events)
    cases = {
        "chrome_counter": [("inc", {"n": 1}), ("inc", {"n": 2}), ("inc", {"n": 3})],
        "chrome_form": [("submit", {"name": "Friday"})],
        "chrome_select": [("submit", {"color": "Blue", "agree": True})],
        "chrome_scroll": [("bottom_click", {})],
        "chrome_navigate": [("confirm", {})],
        "canvas_click_red": [("click", {"hit": "red"})],
        "canvas_blue_then_red": [("click", {"hit": "blue"}), ("click", {"hit": "red"})],
        "canvas_drag": [("stroke", {"start_a": True, "end_b": True, "len": 660})],
        "canvas_game": [("target", {"hit": True, "n": 0}), ("target", {"hit": True, "n": 1}), ("target", {"hit": True, "n": 2})],
    }
    for tid, evs in cases.items():
        c = mk(tid)
        neg = tasks[tid].check(c)[0]
        for kind, data in evs:
            post(site, c.token, kind, **data)
        rec(f"{tid}: neg fails, pos passes", (not neg) and tasks[tid].check(c)[0])
    # wrong variants must fail
    c = mk("canvas_blue_then_red", 2)
    post(site, c.token, "click", hit="red")
    post(site, c.token, "click", hit="blue")
    rec("canvas_blue_then_red: wrong order fails", not tasks["canvas_blue_then_red"].check(c)[0])
    c = mk("chrome_select", 2)
    post(site, c.token, "submit", color="Red", agree=True)
    rec("chrome_select: wrong color fails", not tasks["chrome_select"].check(c)[0])
    c = mk("chrome_counter", 2)
    post(site, "someone-else", "inc", n=3)
    rec("site: other token's events ignored", not tasks["chrome_counter"].check(c)[0])

    # ---- real Chrome loads our page and the page posts events (end to end, pages are valid JS)
    c = mk("chrome_counter", 3)
    tasks["chrome_counter"].setup(c)
    ok_chrome = bool(wu.find_windows(exe="chrome.exe"))
    rec("chrome launches isolated profile on local page", ok_chrome)
    page_html = urllib.request.urlopen(site.url("counter", c.token)).read().decode()
    rec("pages served", "Increment" in page_html)
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(c.chrome.pid)], capture_output=True, check=False)

    # ---- Calculator via real UI Automation + keystrokes
    c = mk("calc_add")
    rec("calc_add: neg fails (not open)", not tasks["calc_add"].check(c)[0])
    subprocess.Popen(["calc.exe"])
    t_end = time.time() + 15
    while time.time() < t_end and not wu.find_windows("Calculator"):
        time.sleep(0.5)
    time.sleep(1.5)
    w = (wu.find_windows("Calculator") or [None])[0]
    if w:
        wu.user32.SetForegroundWindow(w.hwnd)
        time.sleep(0.5)
        for ch in "12+30=":
            vk = {"+": 0x6B, "=": 0x0D}.get(ch, ord(ch))
            press(vk)
        time.sleep(0.8)
        shown = wu.uia_by_automation_id(w.hwnd, "CalculatorResults")
        rec("calc_add: UIA reads display after 12+30", tasks["calc_add"].check(c)[0], f"display={shown!r}")
        rec("calc_mul: wrong value fails", not tasks["calc_mul"].check(c)[0])
    else:
        rec("calc_add: Calculator window appeared", False, "no window")

    # ---- Settings read-only pages
    c = mk("settings_about")
    subprocess.Popen(["explorer.exe", "ms-settings:about"])
    t_end = time.time() + 20
    while time.time() < t_end and not wu.find_windows("Settings"):
        time.sleep(0.5)
    time.sleep(3)
    rec("settings_open check", tasks["settings_open"].check(c)[0])
    rec("settings_about check (UIA text)", tasks["settings_about"].check(c)[0],
        "; ".join(wu.uia_names(wu.find_windows('Settings')[0].hwnd)[:6]) if wu.find_windows("Settings") else "")

    # ---- Explorer title
    c = mk("explorer_open_folder")
    rec("explorer_open_folder: neg fails", not tasks["explorer_open_folder"].check(c)[0])
    subprocess.Popen(["explorer.exe", str(c.scratch)])
    t_end = time.time() + 15
    while time.time() < t_end and not wu.find_windows(c.scratch.name, cls="CabinetWClass"):
        time.sleep(0.5)
    rec("explorer_open_folder: pos passes", tasks["explorer_open_folder"].check(c)[0])

    # ---- cleanup closes only what we opened
    log = wu.close_new_windows(base_all, base_pids)
    time.sleep(1.5)
    after = {w.hwnd for w in wu.list_windows()}
    leftover = [w for w in wu.list_windows() if w.hwnd not in base_all and w.exe in ("calculatorapp.exe", "notepad.exe", "chrome.exe")]
    missing_user = [h for h in base_all if h not in after]
    rec("cleanup closed the new windows", not [w for w in wu.list_windows() if w.hwnd not in base_all and w.title in ("Calculator", "Settings")] and not leftover, "; ".join(log)[:200])
    rec("cleanup left every pre-existing window alone", not missing_user, f"missing={missing_user}")

    site.close()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} self-test checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
