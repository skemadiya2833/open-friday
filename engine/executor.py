import time
import pyautogui
import pyperclip
from config import OVERLAY_ENABLED
from engine.safety import is_risky_step, prompt_user_approval

if OVERLAY_ENABLED:
    from engine import overlay

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3


def execute_step(
    step: dict,
    step_index: int = 1,
    total_steps: int = 1,
) -> str:
    """
    Executes a single action step.

    Returns:
        "screenshot" — fresh capture needed before next step
        "continue"   — proceed to next step
        "complete"   — task is done, exit loop
        "halt"       — operator rejected a risky action, exit loop
    """
    action = step.get("action", "").upper()
    description = step.get("description", "")

    print(f"\n[Friday] {description}")
    print(f"  -> Action: {action}")

    if OVERLAY_ENABLED:
        overlay.update(step_index, action, "running", step=step)

    # Safety gate
    if is_risky_step(step):
        if OVERLAY_ENABLED:
            overlay.update(step_index, action, "waiting for approval", step=step)
        approved = prompt_user_approval(step)
        if not approved:
            print("[Safety] Action rejected by operator. Halting step.")
            if OVERLAY_ENABLED:
                overlay.update(step_index, action, "error", step=step)
            return "halt"
        if OVERLAY_ENABLED:
            overlay.update(step_index, action, "running", step=step)

    try:
        result = _dispatch_action(action, step)
    except Exception as exc:
        print(f"  -> Error: {exc}")
        if OVERLAY_ENABLED:
            overlay.update(step_index, action, "error", step=step)
        return "continue"

    if result in ("screenshot", "complete", "halt"):
        if OVERLAY_ENABLED and result == "complete":
            overlay.update(step_index, action, "complete", step=step)
        return result

    if OVERLAY_ENABLED:
        overlay.update(step_index, action, "complete", step=step)

    return "continue"


def _type_text(text: str) -> None:
    """
    Paste text via clipboard. Far more reliable than typewrite for:
    - Unicode characters
    - Long strings
    - Special characters that typewrite misses
    """
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    print(f"  -> Typed (via paste): {text[:80]}{'...' if len(text) > 80 else ''}")


def _resolve_xy(step: dict) -> tuple[int | None, int | None]:
    """Extract and cast x/y coordinates from a step dict."""
    x, y = step.get("x"), step.get("y")
    if x is not None and y is not None:
        return int(x), int(y)
    return None, None


def _dispatch_action(action: str, step: dict) -> str:

    # ------------------------------------------------------------------
    # WIN_SEARCH — press Win key, wait for search bar, type query, Enter
    # ------------------------------------------------------------------
    if action == "WIN_SEARCH":
        query = step.get("text") or step.get("query") or ""
        if not query.strip():
            print("  -> [GUARD] WIN_SEARCH blocked: 'text' field is empty. Model must specify an app name.")
            return "halt"
        pyautogui.press("win")
        time.sleep(1.2)
        _type_text(query)
        time.sleep(0.6)
        pyautogui.press("enter")
        time.sleep(1.5)
        print(f"  -> Win searched for: {query}")
        return "continue"

    # ------------------------------------------------------------------
    # CLICK — standard left-click
    # ------------------------------------------------------------------
    if action == "CLICK":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.click(x, y)
            print(f"  -> Left-clicked at ({x}, {y})")
        else:
            print("  -> CLICK missing coordinates, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # DOUBLE_CLICK — two rapid left-clicks
    # ------------------------------------------------------------------
    if action == "DOUBLE_CLICK":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.doubleClick(x, y)
            print(f"  -> Double-clicked at ({x}, {y})")
        else:
            print("  -> DOUBLE_CLICK missing coordinates, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # RIGHT_CLICK — context menu click
    # ------------------------------------------------------------------
    if action == "RIGHT_CLICK":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.rightClick(x, y)
            print(f"  -> Right-clicked at ({x}, {y})")
        else:
            print("  -> RIGHT_CLICK missing coordinates, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # MIDDLE_CLICK — scroll-wheel button click (opens links in new tab, etc.)
    # ------------------------------------------------------------------
    if action == "MIDDLE_CLICK":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.middleClick(x, y)
            print(f"  -> Middle-clicked at ({x}, {y})")
        else:
            print("  -> MIDDLE_CLICK missing coordinates, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # MOUSE_DOWN — press and hold a mouse button without releasing
    # ------------------------------------------------------------------
    if action == "MOUSE_DOWN":
        x, y = _resolve_xy(step)
        button = step.get("button", "left")
        if x is not None:
            pyautogui.mouseDown(x, y, button=button)
            print(f"  -> Mouse down ({button}) at ({x}, {y})")
        else:
            pyautogui.mouseDown(button=button)
            print(f"  -> Mouse down ({button}) at current position")
        return "continue"

    # ------------------------------------------------------------------
    # MOUSE_UP — release a held mouse button
    # ------------------------------------------------------------------
    if action == "MOUSE_UP":
        x, y = _resolve_xy(step)
        button = step.get("button", "left")
        if x is not None:
            pyautogui.mouseUp(x, y, button=button)
            print(f"  -> Mouse up ({button}) at ({x}, {y})")
        else:
            pyautogui.mouseUp(button=button)
            print(f"  -> Mouse up ({button}) at current position")
        return "continue"

    # ------------------------------------------------------------------
    # MOUSE_MOVE — move cursor to coordinate without clicking
    # ------------------------------------------------------------------
    if action == "MOUSE_MOVE":
        x, y = _resolve_xy(step)
        if x is not None:
            duration = float(step.get("duration", 0.2))
            pyautogui.moveTo(x, y, duration=duration)
            print(f"  -> Cursor moved to ({x}, {y})")
        else:
            print("  -> MOUSE_MOVE missing coordinates, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # HOVER — move mouse to coordinate and pause briefly (triggers tooltips etc.)
    # ------------------------------------------------------------------
    if action == "HOVER":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.moveTo(x, y, duration=0.3)
            time.sleep(0.4)
            print(f"  -> Hovered at ({x}, {y})")
        return "continue"

    # ------------------------------------------------------------------
    # DRAG — click-drag from (x, y) to (x2, y2)
    # ------------------------------------------------------------------
    if action == "DRAG":
        x, y = _resolve_xy(step)
        x2, y2 = step.get("x2"), step.get("y2")
        if all(v is not None for v in (x, y, x2, y2)):
            pyautogui.drag(int(x2) - x, int(y2) - y, duration=0.4, startX=x, startY=y)
            print(f"  -> Dragged from ({x}, {y}) to ({x2}, {y2})")
        else:
            print("  -> DRAG missing coordinates, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # DRAG_DROP — explicit mouseDown → moveTo → mouseUp sequence for
    # stubborn drag targets (file managers, canvas apps, kanban boards)
    # ------------------------------------------------------------------
    if action == "DRAG_DROP":
        x, y = _resolve_xy(step)
        x2, y2 = step.get("x2"), step.get("y2")
        if all(v is not None for v in (x, y, x2, y2)):
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.mouseDown(button="left")
            time.sleep(0.15)
            pyautogui.moveTo(int(x2), int(y2), duration=0.5)
            time.sleep(0.1)
            pyautogui.mouseUp(button="left")
            print(f"  -> Drag-dropped from ({x}, {y}) to ({x2}, {y2})")
        else:
            print("  -> DRAG_DROP missing coordinates, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # SCROLL — scroll wheel at position; supports all four directions
    # ------------------------------------------------------------------
    if action == "SCROLL":
        x, y = _resolve_xy(step)
        direction = step.get("direction", "down").lower()
        amount = int(step.get("amount", 3))

        # pyautogui.scroll: positive = up, negative = down
        # pyautogui.hscroll: positive = right, negative = left
        if direction in ("up", "down"):
            clicks = amount if direction == "up" else -amount
            if x is not None:
                pyautogui.scroll(clicks, x=x, y=y)
            else:
                pyautogui.scroll(clicks)
            print(f"  -> Scrolled {direction} {amount} clicks at ({x}, {y})")
        elif direction in ("left", "right"):
            clicks = amount if direction == "right" else -amount
            if x is not None:
                pyautogui.hscroll(clicks, x=x, y=y)
            else:
                pyautogui.hscroll(clicks)
            print(f"  -> Scrolled horizontally {direction} {amount} clicks at ({x}, {y})")
        else:
            print(f"  -> Unknown scroll direction '{direction}', skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # TYPE — paste via clipboard (handles unicode, special chars)
    # ------------------------------------------------------------------
    if action == "TYPE":
        text = step.get("text") or ""
        if not text:
            print("  -> TYPE has no text, skipped.")
            return "continue"

        # Guard: catch placeholder text the model should never emit.
        # If it slips past the prompt rules, abort the whole plan here
        # rather than pasting garbage into the user's file.
        _PLACEHOLDER_SIGNALS = (
            "lyrics of",
            "here are the lyrics",
            "insert lyrics",
            "insert content",
            "insert poem",
            "paste content",
            "paste lyrics",
            "[lyrics]",
            "[content]",
            "[poem]",
            "[insert",
            "...",          # trailing ellipsis = truncated placeholder
        )
        text_lower = text.strip().lower()
        if any(signal in text_lower for signal in _PLACEHOLDER_SIGNALS):
            print(
                f"  -> [GUARD] TYPE blocked: placeholder text detected.\n"
                f"     Content was: {text[:120]!r}\n"
                f"     The model must fetch real content via browser before typing."
            )
            return "halt"

        _type_text(text)
        return "continue"

    # ------------------------------------------------------------------
    # PASTE — explicit clipboard paste of provided text
    # ------------------------------------------------------------------
    if action == "PASTE":
        text = step.get("text") or ""
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        print(f"  -> Pasted: {text[:60]}{'...' if len(text) > 60 else ''}")
        return "continue"

    # ------------------------------------------------------------------
    # PRESS_KEY — press a single named key
    # Supports all pyautogui key names: enter, tab, escape, backspace,
    # delete, space, home, end, pageup, pagedown, up, down, left, right,
    # f1–f12, printscreen, insert, capslock, numlock, scrolllock, etc.
    # ------------------------------------------------------------------
    if action == "PRESS_KEY":
        key = step.get("key") or ""
        if key:
            pyautogui.press(key)
            print(f"  -> Pressed key: {key}")
        else:
            print("  -> PRESS_KEY has no key, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # HOTKEY — press multiple keys simultaneously
    # e.g. ["ctrl","c"], ["ctrl","shift","esc"], ["alt","f4"]
    # ------------------------------------------------------------------
    if action == "HOTKEY":
        keys = step.get("keys") or []
        if keys:
            pyautogui.hotkey(*keys)
            print(f"  -> Hotkey: {'+'.join(keys)}")
        else:
            print("  -> HOTKEY has no keys, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # KEY_DOWN — hold a key without releasing (for shift-clicks, etc.)
    # ------------------------------------------------------------------
    if action == "KEY_DOWN":
        key = step.get("key") or ""
        if key:
            pyautogui.keyDown(key)
            print(f"  -> Key down: {key}")
        else:
            print("  -> KEY_DOWN has no key, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # KEY_UP — release a held key
    # ------------------------------------------------------------------
    if action == "KEY_UP":
        key = step.get("key") or ""
        if key:
            pyautogui.keyUp(key)
            print(f"  -> Key up: {key}")
        else:
            print("  -> KEY_UP has no key, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # SELECT_ALL — Ctrl+A
    # ------------------------------------------------------------------
    if action == "SELECT_ALL":
        pyautogui.hotkey("ctrl", "a")
        print("  -> Selected all (Ctrl+A)")
        return "continue"

    # ------------------------------------------------------------------
    # COPY — Ctrl+C
    # ------------------------------------------------------------------
    if action == "COPY":
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.2)
        print("  -> Copied selection (Ctrl+C)")
        return "continue"

    # ------------------------------------------------------------------
    # CUT — Ctrl+X
    # ------------------------------------------------------------------
    if action == "CUT":
        pyautogui.hotkey("ctrl", "x")
        time.sleep(0.2)
        print("  -> Cut selection (Ctrl+X)")
        return "continue"

    # ------------------------------------------------------------------
    # UNDO — Ctrl+Z
    # ------------------------------------------------------------------
    if action == "UNDO":
        pyautogui.hotkey("ctrl", "z")
        print("  -> Undo (Ctrl+Z)")
        return "continue"

    # ------------------------------------------------------------------
    # REDO — Ctrl+Y
    # ------------------------------------------------------------------
    if action == "REDO":
        pyautogui.hotkey("ctrl", "y")
        print("  -> Redo (Ctrl+Y)")
        return "continue"

    # ------------------------------------------------------------------
    # SEARCH — Ctrl+F in-app find bar
    # ------------------------------------------------------------------
    if action == "SEARCH":
        text = step.get("text") or ""
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        if text:
            _type_text(text)
        return "continue"

    # ------------------------------------------------------------------
    # SAVE_FILE — Ctrl+S, then optionally type a filename in the dialog
    # ------------------------------------------------------------------
    if action == "SAVE_FILE":
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.6)
        filename = step.get("text") or ""
        if filename:
            _type_text(filename)
            pyautogui.press("enter")
            print(f"  -> Saved file as: {filename}")
        else:
            print("  -> Saved file (Ctrl+S)")
        return "continue"

    # ------------------------------------------------------------------
    # WIN_SEARCH — already handled above, but kept for reference
    # SCREENSHOT — request fresh capture before next step
    # ------------------------------------------------------------------
    if action == "SCREENSHOT":
        print("  -> Requesting fresh screenshot before next step.")
        return "screenshot"

    # ------------------------------------------------------------------
    # WAIT — pause execution for a given duration
    # ------------------------------------------------------------------
    if action == "WAIT":
        duration = float(step.get("duration", 1.5))
        time.sleep(duration)
        print(f"  -> Waited {duration}s")
        return "continue"

    # ------------------------------------------------------------------
    # COMPLETE — task finished
    # ------------------------------------------------------------------
    if action == "COMPLETE":
        print("\n[Friday] Task marked complete.")
        return "complete"

    # ------------------------------------------------------------------
    # DELETE — select all and delete (always risky, safety-gated above)
    # ------------------------------------------------------------------
    if action == "DELETE":
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("delete")
        print("  -> Deleted all selected content")
        return "continue"

    print(f"  -> Unknown action '{action}', skipped.")
    return "continue"