"""Fixed, safe benchmark tasks with automatic success checks (26 tasks).

Safety rules for every task: scratch files and folders only, no accounts, no network beyond a
local test page, Settings tasks are strictly read-only. Success is judged from the outside
(file contents, window state, UI Automation reads, or events the local test server received),
never from what the agent says.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from friday.bench import winutil as wu
from friday.bench.site import Site

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


@dataclass
class Ctx:
    scratch: Path
    site: Site
    token: str
    rep: int
    chrome: subprocess.Popen | None = None
    notes: dict = field(default_factory=dict)


Check = Callable[[Ctx], tuple[bool, str]]


@dataclass
class Task:
    id: str
    group: str
    objective: Callable[[Ctx], str]
    check: Check
    setup: Callable[[Ctx], None] | None = None
    timeout: int = 100


# ----------------------------------------------------------------------------- checks
def _file_has(path: Path, expected: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"file missing: {path.name}"
    got = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n").strip()
    want = expected.replace("\r\n", "\n").strip()
    return (got == want, "ok" if got == want else f"content {got!r} != {want!r}")


def _window(title: str = "", cls: str = "", exe: str = "") -> bool:
    return bool(wu.find_windows(title, cls, exe))


def _calc(expect: str) -> Check:
    def check(ctx: Ctx):
        wins = wu.find_windows("Calculator")
        if not wins:
            return False, "no Calculator window"
        for w in wins:
            val = wu.uia_by_automation_id(w.hwnd, "CalculatorResults") or ""
            if val.strip().endswith(expect):
                return True, f"display {val!r}"
        return False, f"display was {val!r}, wanted ...{expect}"

    return check


def _settings_has(*needles: str) -> Check:
    def check(ctx: Ctx):
        wins = wu.find_windows("Settings", exe="applicationframehost.exe") or wu.find_windows("Settings")
        if not wins:
            return False, "no Settings window"
        blob = " | ".join(n for w in wins for n in wu.uia_names(w.hwnd)).lower()
        ok = any(n.lower() in blob for n in needles)
        return ok, "ok" if ok else f"none of {needles} visible"

    return check


def _site(kind: str, pred: Callable[[list[dict]], bool], why: str) -> Check:
    def check(ctx: Ctx):
        evs = ctx.site.events(ctx.token, kind)
        return (pred(evs), f"{len(evs)} {kind} event(s)" if pred(evs) else f"{why}; saw {evs[-3:]}")

    return check


def _open_chrome(page: str):
    def setup(ctx: Ctx) -> None:
        profile = ctx.scratch / "chrome_profile"
        ctx.chrome = subprocess.Popen(
            [CHROME, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
             "--disable-sync", "--disable-features=Translate", "--new-window", ctx.site.url(page, ctx.token)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import time

        end = time.time() + 20
        while time.time() < end and not wu.find_windows(exe="chrome.exe", title_contains=""):
            time.sleep(0.5)
        time.sleep(3.0)   # page load + focus settle

    return setup


def build_tasks() -> list[Task]:
    P = lambda ctx, name: ctx.scratch / name      # noqa: E731
    T: list[Task] = []

    # ---- Notepad (6)
    T.append(Task("notepad_open", "notepad", lambda c: "Open Notepad.",
                  lambda c: (_window(exe="notepad.exe"), "notepad window present" if _window(exe="notepad.exe") else "no Notepad window")))
    T.append(Task("notepad_type_save", "notepad",
                  lambda c: f"Open Notepad, type exactly: hello friday  then save the file as {P(c,'n2.txt')}",
                  lambda c: _file_has(P(c, "n2.txt"), "hello friday")))
    T.append(Task("notepad_two_lines", "notepad",
                  lambda c: f"Open Notepad, type the word alpha, press Enter, type the word beta, and save the file as {P(c,'n3.txt')}",
                  lambda c: _file_has(P(c, "n3.txt"), "alpha\nbeta")))
    T.append(Task("notepad_save_and_close", "notepad",
                  lambda c: f"Open Notepad, type: friday benchmark 42  save it as {P(c,'n4.txt')} and then close Notepad.",
                  lambda c: (lambda r: (r[0] and not _window(exe="notepad.exe"), r[1] + ("" if not _window(exe="notepad.exe") else "; Notepad still open")))(_file_has(P(c, "n4.txt"), "friday benchmark 42"))))
    T.append(Task("notepad_subfolder", "notepad",
                  lambda c: f"Open Notepad, type: nested ok  and save it as {P(c,'sub')}\\n5.txt (the folder already exists).",
                  lambda c: _file_has(P(c, "sub") / "n5.txt", "nested ok"),
                  setup=lambda c: (P(c, "sub").mkdir(parents=True, exist_ok=True))))
    T.append(Task("notepad_edit", "notepad",
                  lambda c: f"Open Notepad, type: temp  then select all and delete it, type: final  and save as {P(c,'n6.txt')}",
                  lambda c: _file_has(P(c, "n6.txt"), "final")))

    # ---- Calculator (4)
    T.append(Task("calc_open", "calculator", lambda c: "Open the Calculator app.",
                  lambda c: (_window("Calculator"), "ok" if _window("Calculator") else "no Calculator window")))
    T.append(Task("calc_add", "calculator", lambda c: "Open Calculator and compute 12 + 30. Leave the result on screen.", _calc("42")))
    T.append(Task("calc_mul", "calculator", lambda c: "Open Calculator and compute 7 x 8. Leave the result on screen.", _calc("56")))
    T.append(Task("calc_div", "calculator", lambda c: "Open Calculator and compute 144 divided by 12. Leave the result on screen.", _calc("12")))

    # ---- File Explorer (4)
    def _explorer_title(name_of: Callable[[Ctx], str]) -> Check:
        def check(ctx: Ctx):
            name = name_of(ctx)
            ok = bool(wu.find_windows(name, cls="CabinetWClass"))
            return ok, "ok" if ok else f"no Explorer window titled {name!r}"
        return check

    T.append(Task("explorer_open_folder", "explorer",
                  lambda c: f"Open File Explorer and show the folder {c.scratch}",
                  _explorer_title(lambda c: c.scratch.name)))
    T.append(Task("explorer_new_folder", "explorer",
                  lambda c: f"In File Explorer, open {c.scratch} and create a new folder named bench_folder",
                  lambda c: ((P(c, "bench_folder").is_dir()), "ok" if P(c, "bench_folder").is_dir() else "folder not created")))
    T.append(Task("explorer_subfolder", "explorer",
                  lambda c: f"Open File Explorer and navigate into the folder {P(c,'sub')}",
                  _explorer_title(lambda c: "sub"),
                  setup=lambda c: P(c, "sub").mkdir(parents=True, exist_ok=True)))
    T.append(Task("explorer_new_textfile", "explorer",
                  lambda c: f"In File Explorer, open {c.scratch} and create a new text document named bench_note.txt",
                  lambda c: ((P(c, "bench_note.txt").exists()), "ok" if P(c, "bench_note.txt").exists() else "file not created")))

    # ---- Settings, read-only (3)
    T.append(Task("settings_open", "settings", lambda c: "Open the Windows Settings app. Do not change anything.",
                  lambda c: (_window("Settings"), "ok" if _window("Settings") else "no Settings window")))
    T.append(Task("settings_about", "settings",
                  lambda c: "Open Windows Settings and go to System, then About, to read the device specifications. Do not change anything.",
                  _settings_has("Device specifications", "Device name")))
    T.append(Task("settings_display", "settings",
                  lambda c: "Open Windows Settings and go to System, then Display, to look at the screen settings. Do not change anything.",
                  _settings_has("Display resolution", "Scale", "Brightness")))

    # ---- Chrome on a local test page (5)
    T.append(Task("chrome_counter", "chrome", lambda c: "The Chrome window shows a test page. Click the Increment button 3 times.",
                  _site("inc", lambda e: len(e) >= 3 and max(x.get("n", 0) for x in e) >= 3, "fewer than 3 clicks"),
                  setup=_open_chrome("counter")))
    T.append(Task("chrome_form", "chrome", lambda c: "The Chrome window shows a form. Type Friday into the Name field and click Submit.",
                  _site("submit", lambda e: any(x.get("name", "").strip().lower() == "friday" for x in e), "name was not Friday"),
                  setup=_open_chrome("form")))
    T.append(Task("chrome_select", "chrome",
                  lambda c: "The Chrome window shows a preferences form. Choose Blue as the favorite color, tick the I agree box, and click Save preferences.",
                  _site("submit", lambda e: any(x.get("color") == "Blue" and x.get("agree") is True for x in e), "wrong color/agree"),
                  setup=_open_chrome("select")))
    T.append(Task("chrome_scroll", "chrome", lambda c: "The Chrome window shows a long page. Scroll down to the bottom and click the button there.",
                  _site("bottom_click", lambda e: len(e) >= 1, "bottom button not clicked"),
                  setup=_open_chrome("long")))
    T.append(Task("chrome_navigate", "chrome", lambda c: "In Chrome, click the link to page 2, then click the Confirm button on that page.",
                  _site("confirm", lambda e: len(e) >= 1, "confirm not clicked"),
                  setup=_open_chrome("nav1")))

    # ---- Canvas / custom drawn UI (4)
    T.append(Task("canvas_click_red", "canvas", lambda c: "The Chrome window shows a canvas. Click the red circle.",
                  _site("click", lambda e: any(x.get("hit") == "red" for x in e), "red circle not hit"),
                  setup=_open_chrome("canvas_click")))
    T.append(Task("canvas_blue_then_red", "canvas",
                  lambda c: "The Chrome window shows a canvas. First click the blue square, then click the red circle.",
                  _site("click", lambda e: [x.get("hit") for x in e if x.get("hit") in ("red", "blue")][:2] == ["blue", "red"], "wrong order"),
                  setup=_open_chrome("canvas_click")))
    T.append(Task("canvas_drag", "canvas", lambda c: "The Chrome window shows a canvas. Drag from the green dot to the orange dot.",
                  _site("stroke", lambda e: any(x.get("start_a") and x.get("end_b") for x in e), "drag did not connect the dots"),
                  setup=_open_chrome("canvas_drag")))
    T.append(Task("canvas_game", "canvas", lambda c: "The Chrome window shows a game. Click the green target 3 times; it moves after each hit.",
                  _site("target", lambda e: sum(1 for x in e if x.get("hit")) >= 3, "fewer than 3 hits"),
                  setup=_open_chrome("canvas_game")))
    return T


def group_precondition(group: str) -> str | None:
    """Return a reason to skip a whole group if it would touch the user's own windows."""
    if group == "notepad" and wu.find_windows(exe="notepad.exe"):
        return "a Notepad window is already open (close it first)"
    if group == "calculator" and wu.find_windows("Calculator"):
        return "Calculator is already open"
    if group == "settings" and wu.find_windows("Settings", exe="applicationframehost.exe"):
        return "Settings is already open"
    if group in ("chrome", "canvas") and not os.path.exists(CHROME):
        return f"Chrome not found at {CHROME}"
    return None


def fresh_scratch(root: Path, task_id: str, rep: int) -> Path:
    p = root / f"{task_id}_{rep}"
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True)
    return p
