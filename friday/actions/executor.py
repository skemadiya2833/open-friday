"""Execute a single intentional action against the live desktop."""

from __future__ import annotations

import time

import pyautogui
import pyperclip

from friday.actions.catalog import AIM_ACTIONS, REOBSERVE_ACTIONS
from friday.actions.coordinates import extract_win_search_text
from friday.config import AIM_VERIFY_ENABLED, CLICK_MARKER_ENABLED, OVERLAY_ENABLED
from friday.safety import is_risky, prompt_approval
from friday.types import ActionStep, StepResult, VisionPayload

pyautogui.FAILSAFE = True
# Global inter-call delay. Kept small so multi-step actions feel responsive;
# per-action settle sleeps below handle the cases that genuinely need waiting.
pyautogui.PAUSE = float(__import__("os").getenv("PYAUTOGUI_PAUSE", "0.1"))


def execute_action(
    step: ActionStep,
    *,
    session=None,
    feed=None,
    vision: VisionPayload | None = None,
    step_index: int = 1,
) -> StepResult:
    """
    Run exactly one action. Never chains actions — the agent loop re-observes.
    """
    action = step.action.upper()
    data = step.to_dict()

    print(f"\n[Friday] {step.description or action}")
    print(f"  -> Action: {action}")

    if OVERLAY_ENABLED:
        from friday.ui import overlay
        overlay.update(step_index, action, "running", step=data)

    if is_risky(step):
        if OVERLAY_ENABLED:
            from friday.ui import overlay
            overlay.update(step_index, action, "waiting for approval", step=data)
        if not prompt_approval(step):
            print("[Safety] Action rejected by operator. Halting.")
            if OVERLAY_ENABLED:
                from friday.ui import overlay
                overlay.update(step_index, action, "error", step=data)
            return StepResult.HALT

    if (
        AIM_VERIFY_ENABLED
        and feed is not None
        and vision is not None
        and action in AIM_ACTIONS
        and step.x is not None
        and step.y is not None
    ):
        from friday.actions.aim_verify import refine_aim
        step = refine_aim(step, feed, vision.native_size, vision.image_size)
        data = step.to_dict()

        if step.extras.get("_aim_abort"):
            print(
                "  -> [AIM] Target not confirmed — skipping this click and "
                "re-observing so the model can re-aim or pick another target."
            )
            if OVERLAY_ENABLED:
                from friday.ui import overlay
                overlay.update(step_index, action, "running", step=data)
            return StepResult.SKIPPED

    try:
        result = _dispatch(step, session=session)
    except Exception as exc:
        print(f"  -> Error: {exc}")
        if OVERLAY_ENABLED:
            from friday.ui import overlay
            overlay.update(step_index, action, "error", step=data)
        return StepResult.ERROR

    if OVERLAY_ENABLED and result not in (StepResult.HALT,):
        from friday.ui import overlay
        status = "complete" if result == StepResult.COMPLETE else "running"
        overlay.update(step_index, action, status, step=data)

    return result


def _type_text(text: str) -> None:
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    print(f"  -> Typed (via paste): {text[:80]}{'...' if len(text) > 80 else ''}")


def _is_placeholder_type_text(text: str) -> bool:
    t = text.strip()
    if not t or t in ("...", "…"):
        return True
    lower = t.lower()
    if len(t) > 200 or t.count("\n") >= 2:
        return False
    if any(lower.startswith(p) for p in ("[lyrics]", "[content]", "[poem]", "[insert")):
        return True
    stub_phrases = (
        "here are the lyrics", "insert lyrics", "insert content",
        "insert poem", "paste content", "paste lyrics",
        "type the lyrics", "enter the lyrics",
    )
    if len(t) < 80 and any(p in lower for p in stub_phrases):
        return True
    if lower.startswith("lyrics of") and "\n" not in t and len(t) < 100:
        return True
    return False


def _with_marker(step: ActionStep, x: int, y: int) -> None:
    if not CLICK_MARKER_ENABLED:
        return
    from friday.ui.click_marker import hide_aim_cursor, log_click_target, show_click_target
    data = step.to_dict()
    if data.get("_aim_verified"):
        log_click_target(data, x, y)
        return
    log_click_target(data, x, y)
    show_click_target(x, y, step=data)


def _after_marker(step: ActionStep) -> None:
    if step.extras.get("_aim_verified") and CLICK_MARKER_ENABLED:
        from friday.ui.click_marker import hide_aim_cursor
        hide_aim_cursor()


def _reobserve_if(action: str, default: StepResult = StepResult.CONTINUE) -> StepResult:
    if action in REOBSERVE_ACTIONS:
        return StepResult.REOBSERVE
    return default


def _dispatch(step: ActionStep, session=None) -> StepResult:
    action = step.action.upper()
    x, y = step.x, step.y

    if action == "WIN_SEARCH":
        query = step.text or step.query or ""
        if not str(query).strip():
            query = extract_win_search_text(step.to_dict())
        if not str(query).strip():
            print("  -> [GUARD] WIN_SEARCH skipped: empty query.")
            return StepResult.SKIPPED
        if session is not None and session.has_recent_win_search(str(query)):
            print(f"  -> [GUARD] WIN_SEARCH skipped: '{query}' already launched.")
            return StepResult.SKIPPED
        pyautogui.press("win")
        time.sleep(1.5)
        _type_text(query)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(2.5)
        print(f"  -> Win searched for: {query}")
        return StepResult.REOBSERVE

    if action == "CLICK":
        if x is None or y is None:
            print("  -> CLICK missing coordinates, skipped.")
            return StepResult.SKIPPED
        _with_marker(step, x, y)
        pyautogui.click(x, y)
        _after_marker(step)
        print(f"  -> Left-clicked at ({x}, {y})")
        return StepResult.REOBSERVE

    if action == "DOUBLE_CLICK":
        if x is None or y is None:
            print("  -> DOUBLE_CLICK missing coordinates, skipped.")
            return StepResult.SKIPPED
        _with_marker(step, x, y)
        pyautogui.doubleClick(x, y)
        _after_marker(step)
        print(f"  -> Double-clicked at ({x}, {y})")
        return StepResult.REOBSERVE

    if action == "RIGHT_CLICK":
        if x is None or y is None:
            print("  -> RIGHT_CLICK missing coordinates, skipped.")
            return StepResult.SKIPPED
        _with_marker(step, x, y)
        pyautogui.rightClick(x, y)
        _after_marker(step)
        print(f"  -> Right-clicked at ({x}, {y})")
        return StepResult.REOBSERVE

    if action == "MIDDLE_CLICK":
        if x is None or y is None:
            print("  -> MIDDLE_CLICK missing coordinates, skipped.")
            return StepResult.SKIPPED
        _with_marker(step, x, y)
        pyautogui.middleClick(x, y)
        _after_marker(step)
        print(f"  -> Middle-clicked at ({x}, {y})")
        return _reobserve_if(action)

    if action == "MOUSE_DOWN":
        button = step.button or "left"
        if x is not None and y is not None:
            pyautogui.mouseDown(x, y, button=button)
            print(f"  -> Mouse down ({button}) at ({x}, {y})")
        else:
            pyautogui.mouseDown(button=button)
            print(f"  -> Mouse down ({button}) at current position")
        return StepResult.CONTINUE

    if action == "MOUSE_UP":
        button = step.button or "left"
        if x is not None and y is not None:
            pyautogui.mouseUp(x, y, button=button)
            print(f"  -> Mouse up ({button}) at ({x}, {y})")
        else:
            pyautogui.mouseUp(button=button)
            print(f"  -> Mouse up ({button}) at current position")
        return StepResult.CONTINUE

    if action == "MOUSE_MOVE":
        if x is None or y is None:
            print("  -> MOUSE_MOVE missing coordinates, skipped.")
            return StepResult.SKIPPED
        duration = float(step.duration if step.duration is not None else 0.2)
        pyautogui.moveTo(x, y, duration=duration)
        print(f"  -> Cursor moved to ({x}, {y})")
        return StepResult.CONTINUE

    if action == "HOVER":
        if x is None or y is None:
            print("  -> HOVER missing coordinates, skipped.")
            return StepResult.SKIPPED
        _with_marker(step, x, y)
        pyautogui.moveTo(x, y, duration=0.3)
        time.sleep(0.4)
        _after_marker(step)
        print(f"  -> Hovered at ({x}, {y})")
        return _reobserve_if(action)

    if action in ("DRAG", "DRAG_DROP"):
        x2, y2 = step.x2, step.y2
        if None in (x, y, x2, y2):
            print(f"  -> {action} missing coordinates, skipped.")
            return StepResult.SKIPPED
        if action == "DRAG":
            pyautogui.drag(int(x2) - x, int(y2) - y, duration=0.4, startX=x, startY=y)
        else:
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.mouseDown(button="left")
            time.sleep(0.15)
            pyautogui.moveTo(int(x2), int(y2), duration=0.5)
            time.sleep(0.1)
            pyautogui.mouseUp(button="left")
        print(f"  -> {action} from ({x}, {y}) to ({x2}, {y2})")
        return StepResult.REOBSERVE

    if action == "SCROLL":
        direction = (step.direction or "down").lower()
        amount = int(step.amount if step.amount is not None else 3)
        if x is not None and y is not None:
            _with_marker(step, x, y)
        if direction in ("up", "down"):
            clicks = amount if direction == "up" else -amount
            if x is not None:
                pyautogui.scroll(clicks, x=x, y=y)
            else:
                pyautogui.scroll(clicks)
            print(f"  -> Scrolled {direction} {amount}")
        elif direction in ("left", "right"):
            clicks = amount if direction == "right" else -amount
            if x is not None:
                pyautogui.hscroll(clicks, x=x, y=y)
            else:
                pyautogui.hscroll(clicks)
            print(f"  -> Scrolled horizontally {direction} {amount}")
        else:
            print(f"  -> Unknown scroll direction '{direction}', skipped.")
            return StepResult.SKIPPED
        if x is not None and y is not None:
            _after_marker(step)
        return StepResult.REOBSERVE

    if action == "TYPE":
        text = step.text or ""
        if not text:
            print("  -> TYPE has no text, skipped.")
            return StepResult.SKIPPED
        if _is_placeholder_type_text(text):
            print("  -> [GUARD] TYPE skipped: placeholder/description text, not real content.")
            return StepResult.SKIPPED
        _type_text(text)
        return StepResult.REOBSERVE

    if action == "PASTE":
        text = step.text or ""
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        print(f"  -> Pasted: {text[:60]}{'...' if len(text) > 60 else ''}")
        return StepResult.REOBSERVE

    if action == "PRESS_KEY":
        key = step.key or ""
        if not key:
            print("  -> PRESS_KEY has no key, skipped.")
            return StepResult.SKIPPED
        pyautogui.press(key)
        print(f"  -> Pressed key: {key}")
        return StepResult.REOBSERVE

    if action == "HOTKEY":
        keys = step.keys or []
        if not keys:
            print("  -> HOTKEY has no keys, skipped.")
            return StepResult.SKIPPED
        pyautogui.hotkey(*keys)
        print(f"  -> Hotkey: {'+'.join(keys)}")
        return StepResult.REOBSERVE

    if action == "KEY_DOWN":
        key = step.key or ""
        if not key:
            return StepResult.SKIPPED
        pyautogui.keyDown(key)
        print(f"  -> Key down: {key}")
        return StepResult.CONTINUE

    if action == "KEY_UP":
        key = step.key or ""
        if not key:
            return StepResult.SKIPPED
        pyautogui.keyUp(key)
        print(f"  -> Key up: {key}")
        return StepResult.CONTINUE

    if action == "SELECT_ALL":
        pyautogui.hotkey("ctrl", "a")
        print("  -> Selected all")
        return StepResult.CONTINUE

    if action == "COPY":
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.2)
        print("  -> Copied")
        return StepResult.CONTINUE

    if action == "CUT":
        pyautogui.hotkey("ctrl", "x")
        time.sleep(0.2)
        print("  -> Cut")
        return StepResult.CONTINUE

    if action == "UNDO":
        pyautogui.hotkey("ctrl", "z")
        print("  -> Undo")
        return StepResult.CONTINUE

    if action == "REDO":
        pyautogui.hotkey("ctrl", "y")
        print("  -> Redo")
        return StepResult.CONTINUE

    if action == "SEARCH":
        text = step.text or ""
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        if text:
            _type_text(text)
        return StepResult.REOBSERVE

    if action == "SAVE_FILE":
        pyautogui.hotkey("ctrl", "s")
        # Save dialogs can take a moment to appear and grab focus.
        time.sleep(1.2)
        filename = step.text or ""
        if filename:
            _type_text(filename)
            time.sleep(0.4)
            pyautogui.press("enter")
            time.sleep(0.8)
            print(f"  -> Saved as: {filename}")
        else:
            print("  -> Saved (Ctrl+S)")
        return StepResult.REOBSERVE

    if action == "NAVIGATE":
        url = step.url or step.text or ""
        if not url:
            print("  -> NAVIGATE missing url, skipped.")
            return StepResult.SKIPPED
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.35)
        _type_text(url)
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(1.5)
        print(f"  -> Navigated to: {url}")
        return StepResult.REOBSERVE

    if action == "NEW_TAB":
        pyautogui.hotkey("ctrl", "t")
        time.sleep(0.4)
        print("  -> New tab")
        return StepResult.REOBSERVE

    if action == "CLOSE_TAB":
        pyautogui.hotkey("ctrl", "w")
        time.sleep(0.4)
        print("  -> Closed tab")
        return StepResult.REOBSERVE

    if action == "SWITCH_TAB":
        pyautogui.hotkey("ctrl", "tab")
        time.sleep(0.4)
        print("  -> Switched tab")
        return StepResult.REOBSERVE

    if action == "KNOWLEDGE_SEARCH":
        from friday.knowledge.search import perform_knowledge_search
        query = step.query or step.text or ""
        if not query:
            print("  -> KNOWLEDGE_SEARCH missing query, skipped.")
            return StepResult.SKIPPED
        if session is not None and not session.can_knowledge_search():
            print("  -> [GUARD] Knowledge search budget exhausted.")
            return StepResult.SKIPPED
        note = perform_knowledge_search(query)
        if session is not None:
            session.add_knowledge(note)
        return StepResult.REOBSERVE

    if action == "WAIT":
        duration = float(step.duration if step.duration is not None else 1.5)
        time.sleep(duration)
        print(f"  -> Waited {duration}s")
        return _reobserve_if(action)

    if action == "COMPLETE":
        print("\n[Friday] Task marked complete.")
        return StepResult.COMPLETE

    if action == "DELETE":
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("delete")
        print("  -> Deleted selection")
        return StepResult.REOBSERVE

    # Legacy alias
    if action == "SCREENSHOT":
        print("  -> Re-observe requested.")
        return StepResult.REOBSERVE

    print(f"  -> Unknown action '{action}', skipped.")
    return StepResult.SKIPPED
