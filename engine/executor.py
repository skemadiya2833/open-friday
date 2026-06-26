import time
import pyautogui
import pyperclip
from config import OVERLAY_ENABLED
from engine.safety import is_risky_step, prompt_user_approval
from engine.coordinates import _extract_win_search_text
from engine.session import TaskSession

if OVERLAY_ENABLED:
    from engine import overlay

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3


def execute_step(
    step: dict,
    step_index: int = 1,
    total_steps: int = 1,
    session: TaskSession | None = None,
) -> str:
    """
    Executes a single action step.

    Returns:
        "screenshot" — fresh capture needed before next step
        "continue"   — proceed to next step
        "skipped"    — action not performed (guard or missing data)
        "complete"   — task is done, exit loop
        "halt"       — operator rejected a risky action, exit loop
    """
    action = step.get("action", "").upper()
    description = step.get("description", "")

    print(f"\n[Friday] {description}")
    print(f"  -> Action: {action}")

    if OVERLAY_ENABLED:
        overlay.update(step_index, action, "running", step=step)

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
        result = _dispatch_action(action, step, session=session)
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
    Paste text via clipboard. Reliable for unicode, long strings,
    and special characters that pyautogui.typewrite drops.
    """
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    print(f"  -> Typed (via paste): {text[:80]}{'...' if len(text) > 80 else ''}")


def _resolve_xy(step: dict) -> tuple[int | None, int | None]:
    x, y = step.get("x"), step.get("y")
    if x is not None and y is not None:
        return int(x), int(y)
    return None, None


def _dispatch_action(action: str, step: dict, session: TaskSession | None = None) -> str:

    # ------------------------------------------------------------------
    # WIN_SEARCH
    # ------------------------------------------------------------------
    if action == "WIN_SEARCH":
        query = step.get("text") or step.get("query") or ""
        if not str(query).strip():
            query = _extract_win_search_text(step)
        if not str(query).strip():
            print("  -> [GUARD] WIN_SEARCH skipped: 'text' field is empty.")
            return "skipped"
        if session and session.has_recent_win_search(str(query)):
            print(
                f"  -> [GUARD] WIN_SEARCH skipped: '{query}' already launched. "
                "Interact with the open window instead."
            )
            return "skipped"
        pyautogui.press("win")
        time.sleep(1.5)          # give the search bar time to appear
        _type_text(query)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(2.5)          # give the launched app time to open
        print(f"  -> Win searched for: {query}")
        # Always request a fresh screenshot after launching an app so the
        # model sees the actual window state (including any profile pickers
        # or permission dialogs) before deciding the next action.
        return "screenshot"

    # ------------------------------------------------------------------
    # CLICK
    # ------------------------------------------------------------------
    if action == "CLICK":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.click(x, y)
            print(f"  -> Left-clicked at ({x}, {y})")
        else:
            print("  -> CLICK missing coordinates, skipped.")
        return "screenshot"

    # ------------------------------------------------------------------
    # DOUBLE_CLICK
    # ------------------------------------------------------------------
    if action == "DOUBLE_CLICK":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.doubleClick(x, y)
            print(f"  -> Double-clicked at ({x}, {y})")
        else:
            print("  -> DOUBLE_CLICK missing coordinates, skipped.")
        return "screenshot"

    # ------------------------------------------------------------------
    # RIGHT_CLICK
    # ------------------------------------------------------------------
    if action == "RIGHT_CLICK":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.rightClick(x, y)
            print(f"  -> Right-clicked at ({x}, {y})")
        else:
            print("  -> RIGHT_CLICK missing coordinates, skipped.")
        return "screenshot"

    # ------------------------------------------------------------------
    # MIDDLE_CLICK
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
    # MOUSE_DOWN
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
    # MOUSE_UP
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
    # MOUSE_MOVE
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
    # HOVER
    # ------------------------------------------------------------------
    if action == "HOVER":
        x, y = _resolve_xy(step)
        if x is not None:
            pyautogui.moveTo(x, y, duration=0.3)
            time.sleep(0.4)
            print(f"  -> Hovered at ({x}, {y})")
        return "continue"

    # ------------------------------------------------------------------
    # DRAG
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
    # DRAG_DROP
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
    # SCROLL
    # ------------------------------------------------------------------
    if action == "SCROLL":
        x, y = _resolve_xy(step)
        direction = step.get("direction", "down").lower()
        amount = int(step.get("amount", 3))
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
    # TYPE
    # ------------------------------------------------------------------
    if action == "TYPE":
        text = step.get("text") or ""
        if not text:
            print("  -> TYPE has no text, skipped.")
            return "continue"

        _PLACEHOLDER_SIGNALS = (
            "lyrics of", "here are the lyrics", "insert lyrics",
            "insert content", "insert poem", "paste content", "paste lyrics",
            "[lyrics]", "[content]", "[poem]", "[insert", "...",
        )
        text_lower = text.strip().lower()
        if any(signal in text_lower for signal in _PLACEHOLDER_SIGNALS):
            print(
                f"  -> [GUARD] TYPE blocked: placeholder text detected.\n"
                f"     Content: {text[:120]!r}"
            )
            return "halt"

        _type_text(text)
        return "screenshot"

    # ------------------------------------------------------------------
    # PASTE
    # ------------------------------------------------------------------
    if action == "PASTE":
        text = step.get("text") or ""
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        print(f"  -> Pasted: {text[:60]}{'...' if len(text) > 60 else ''}")
        return "continue"

    # ------------------------------------------------------------------
    # PRESS_KEY
    # ------------------------------------------------------------------
    if action == "PRESS_KEY":
        key = step.get("key") or ""
        if key:
            pyautogui.press(key)
            print(f"  -> Pressed key: {key}")
        else:
            print("  -> PRESS_KEY has no key, skipped.")
        return "screenshot"

    # ------------------------------------------------------------------
    # HOTKEY
    # ------------------------------------------------------------------
    if action == "HOTKEY":
        keys = step.get("keys") or []
        if keys:
            pyautogui.hotkey(*keys)
            print(f"  -> Hotkey: {'+'.join(keys)}")
        else:
            print("  -> HOTKEY has no keys, skipped.")
        return "screenshot"

    # ------------------------------------------------------------------
    # KEY_DOWN
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
    # KEY_UP
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
    # SELECT_ALL
    # ------------------------------------------------------------------
    if action == "SELECT_ALL":
        pyautogui.hotkey("ctrl", "a")
        print("  -> Selected all (Ctrl+A)")
        return "continue"

    # ------------------------------------------------------------------
    # COPY
    # ------------------------------------------------------------------
    if action == "COPY":
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.2)
        print("  -> Copied selection (Ctrl+C)")
        return "continue"

    # ------------------------------------------------------------------
    # CUT
    # ------------------------------------------------------------------
    if action == "CUT":
        pyautogui.hotkey("ctrl", "x")
        time.sleep(0.2)
        print("  -> Cut selection (Ctrl+X)")
        return "continue"

    # ------------------------------------------------------------------
    # UNDO
    # ------------------------------------------------------------------
    if action == "UNDO":
        pyautogui.hotkey("ctrl", "z")
        print("  -> Undo (Ctrl+Z)")
        return "continue"

    # ------------------------------------------------------------------
    # REDO
    # ------------------------------------------------------------------
    if action == "REDO":
        pyautogui.hotkey("ctrl", "y")
        print("  -> Redo (Ctrl+Y)")
        return "continue"

    # ------------------------------------------------------------------
    # SEARCH
    # ------------------------------------------------------------------
    if action == "SEARCH":
        text = step.get("text") or ""
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        if text:
            _type_text(text)
        return "continue"

    # ------------------------------------------------------------------
    # SAVE_FILE
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
    # SCREENSHOT
    # ------------------------------------------------------------------
    if action == "SCREENSHOT":
        print("  -> Requesting fresh screenshot before next step.")
        return "screenshot"

    # ------------------------------------------------------------------
    # WAIT
    # ------------------------------------------------------------------
    if action == "WAIT":
        duration = float(step.get("duration", 1.5))
        time.sleep(duration)
        print(f"  -> Waited {duration}s")
        return "continue"

    # ------------------------------------------------------------------
    # COMPLETE
    # ------------------------------------------------------------------
    if action == "COMPLETE":
        print("\n[Friday] Task marked complete.")
        return "complete"

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------
    if action == "DELETE":
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("delete")
        print("  -> Deleted all selected content")
        return "continue"

    print(f"  -> Unknown action '{action}', skipped.")
    return "continue"