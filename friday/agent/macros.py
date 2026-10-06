"""Macro layer (Stage I1 / M4): deterministic high-level actions the model can choose instead of long click chains.

Each macro is a fixed sequence of the same low-level tool calls the agent already uses, so policy, grants and the
audit log apply to every primitive. Low-level actions stay available as the fallback. Off unless
``HybridConfig.macros`` is true (benchmarked before being turned on).

    focus        {"title": "..."}            bring a window to the front (App tool, mode switch)
    type_focused {"text": "...", "enter": b}  type into whatever has focus (no element needed)
    save_as      {"path": "C:\\...\\a.txt"}   Ctrl+S, type the path in the dialog, Enter
    open_folder  {"path": "C:\\...\\dir"}     File Explorer, Ctrl+L, type the path, Enter
    read_title   {}                           report the focused window title (no tool call)
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from friday.agent import guard as G

MACROS = ("focus", "type_focused", "save_as", "open_folder", "read_title")

PROMPT = """
Macros (prefer these when they fit; they are reliable multi-step actions):
  {"action":"focus","title":"<window title or app>"}        bring a window to the front
  {"action":"type_focused","text":"...","enter":false}       type into the focused window (no id needed)
  {"action":"save_as","path":"C:\\\\full\\\\path\\\\file.txt"}      save the current document through the Save dialog
  {"action":"open_folder","path":"C:\\\\full\\\\path"}              open a folder in File Explorer
  {"action":"read_title"}                                    tell me the focused window's title
"""

_BAD_PATH = re.compile(r"(^|[\\/])\.\.([\\/]|$)|^\\\\|^[a-z]:\\(windows|program files|programdata)\b|%|\$env:|[<>|*?\"]", re.I)


def path_problem(path: str) -> str | None:
    p = (path or "").strip()
    if not p:
        return "empty path"
    if len(p) > 260:
        return "path too long"
    if _BAD_PATH.search(p):
        return "path is outside the places an agent may write (system folders, network shares, '..', wildcards)"
    return None


def validate(raw: dict) -> str:
    """'' when the macro request is well formed, else the reason."""
    a = str(raw.get("action", "")).lower()
    if a == "focus" and not str(raw.get("title", "")).strip():
        return "focus needs 'title'"
    if a == "type_focused" and "text" not in raw:
        return "type_focused needs 'text'"
    if a in ("save_as", "open_folder"):
        bad = path_problem(str(raw.get("path", "")))
        if bad:
            return f"{a}: {bad}"
    return ""


def check(cfg: G.GuardConfig, raw: dict, focused_title: str, *, context: list[str] | None = None,
          dialog: Any = None) -> G.Verdict:
    """Guard verdict for a macro: same rules as the primitives it is made of."""
    a = str(raw.get("action", "")).lower()
    if a == "focus":
        return G.check_window(cfg, str(raw.get("title", "")))
    if a == "read_title":
        return G.Verdict("allow")
    v = G.check_window(cfg, focused_title)
    if v.action != "allow":
        return v
    v = G.check_protected(cfg, focused_title, context or [])
    if v.action != "allow":
        return v
    if a == "type_focused":
        return G.check_action(cfg, "type", title=focused_title, text=str(raw.get("text", "")), context=context, dialog=dialog)
    if a == "save_as":
        return G.check_action(cfg, "shortcut", title=focused_title, keys="ctrl+s", context=context, dialog=dialog)
    return G.Verdict("allow")        # open_folder launches Explorer and types a validated path


def run(desk: Any, raw: dict, *, force_ask: bool, settle: float = 0.6, sleep: Callable[[float], None] = time.sleep,
        focused_title: str = "") -> tuple[bool, str]:
    """Execute a macro through ``desk.call``. Returns (ok, message). Stops at the first failing primitive."""
    a = str(raw.get("action", "")).lower()

    def call(tool: str, args: dict) -> tuple[bool, str]:
        res = desk.call(tool, args, force_ask=force_ask)
        return (not res.is_error), (res.text()[:160] if res.is_error else "")

    if a == "read_title":
        return True, f'The focused window title is "{focused_title}".'
    if a == "focus":
        ok, why = call("App", {"mode": "switch", "name": str(raw["title"])})
        return ok, why or f"focused {raw['title']!r}"
    if a == "type_focused":
        ok, why = call("Type", {"text": str(raw["text"]), "clear": False, "press_enter": bool(raw.get("enter"))})
        return ok, why
    if a == "save_as":
        steps = [("Shortcut", {"shortcut": "ctrl+s"}), ("Wait", {"duration": 1}),
                 ("Type", {"text": str(raw["path"]), "clear": True, "press_enter": True})]
    elif a == "open_folder":
        steps = [("App", {"mode": "launch", "name": "explorer"}), ("Wait", {"duration": 1}),
                 ("Shortcut", {"shortcut": "ctrl+l"}),
                 ("Type", {"text": str(raw["path"]), "clear": True, "press_enter": True})]
    else:
        return False, f"unknown macro {a}"
    for tool, args in steps:
        ok, why = call(tool, args)
        if not ok:
            return False, f"{a} failed at {tool}: {why}"
        sleep(settle)
    return True, ""
