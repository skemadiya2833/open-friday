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


def _dispatch_action(action: str, step: dict) -> str:

    # ------------------------------------------------------------------
    # WIN_SEARCH — press Win key, wait for search bar, type query, Enter
    # This is the correct deterministic way to open apps on Windows.
    # Never guess taskbar coordinates for this.
    # ------------------------------------------------------------------
    if action == "WIN_SEARCH":
        query = step.get("text") or step.get("query") or ""
        pyautogui.press("win")
        time.sleep(1.2)                       # wait for Start Menu / search box
        _type_text(query)
        time.sleep(0.6)
        pyautogui.press("enter")
        time.sleep(1.5)                       # wait for app to launch
        print(f"  -> Win searched for: {query}")
        return "continue"

    # ------------------------------------------------------------------
    # PRESS_KEY — press a named key (enter, tab, escape, etc.)
    # ------------------------------------------------------------------
    if action == "PRESS_KEY":
        key = step.get("key") or ""
        if key:
            pyautogui.press(key)
            print(f"  -> Pressed key: {key}")
        return "continue"

    # ------------------------------------------------------------------
    # SAVE_FILE — Ctrl+S
    # ------------------------------------------------------------------
    if action == "SAVE_FILE":
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.6)
        print("  -> Saved file (Ctrl+S)")
        return "continue"

    # ------------------------------------------------------------------
    # CLICK
    # ------------------------------------------------------------------
    if action == "CLICK":
        x, y = step.get("x"), step.get("y")
        if x is not None and y is not None:
            pyautogui.click(int(x), int(y))
            print(f"  -> Clicked at ({x}, {y})")
        else:
            print("  -> CLICK missing coordinates, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # HOVER
    # ------------------------------------------------------------------
    if action == "HOVER":
        x, y = step.get("x"), step.get("y")
        if x is not None and y is not None:
            pyautogui.moveTo(int(x), int(y), duration=0.3)
        return "continue"

    # ------------------------------------------------------------------
    # TYPE — use clipboard paste for reliability
    # ------------------------------------------------------------------
    if action == "TYPE":
        text = step.get("text") or ""
        if text:
            _type_text(text)
        else:
            print("  -> TYPE has no text, skipped.")
        return "continue"

    # ------------------------------------------------------------------
    # PASTE — explicit clipboard paste
    # ------------------------------------------------------------------
    if action == "PASTE":
        text = step.get("text") or ""
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        print(f"  -> Pasted: {text[:60]}{'...' if len(text) > 60 else ''}")
        return "continue"

    # ------------------------------------------------------------------
    # SCROLL
    # ------------------------------------------------------------------
    if action == "SCROLL":
        x, y = step.get("x"), step.get("y")
        direction = step.get("direction", "down")
        amount = -5 if direction == "down" else 5
        if x and y:
            pyautogui.scroll(amount, x=int(x), y=int(y))
        else:
            pyautogui.scroll(amount)
        return "continue"

    # ------------------------------------------------------------------
    # SEARCH — Ctrl+F in-app search (not Windows search)
    # ------------------------------------------------------------------
    if action == "SEARCH":
        text = step.get("text") or ""
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        if text:
            _type_text(text)
        return "continue"

    # ------------------------------------------------------------------
    # DRAG
    # ------------------------------------------------------------------
    if action == "DRAG":
        x, y = step.get("x"), step.get("y")
        x2, y2 = step.get("x2"), step.get("y2")
        if all(v is not None for v in (x, y, x2, y2)):
            pyautogui.mouseDown(int(x), int(y))
            time.sleep(0.1)
            pyautogui.moveTo(int(x2), int(y2), duration=0.4)
            pyautogui.mouseUp()
        return "continue"

    # ------------------------------------------------------------------
    # WAIT
    # ------------------------------------------------------------------
    if action == "WAIT":
        duration = float(step.get("duration", 1.5))
        time.sleep(duration)
        return "continue"

    # ------------------------------------------------------------------
    # SCREENSHOT — request fresh capture before next step
    # ------------------------------------------------------------------
    if action == "SCREENSHOT":
        print("  -> Requesting fresh screenshot before next step.")
        return "screenshot"

    # ------------------------------------------------------------------
    # COMPLETE — task finished
    # ------------------------------------------------------------------
    if action == "COMPLETE":
        print("\n[Friday] Task marked complete.")
        return "complete"

    # ------------------------------------------------------------------
    # DELETE — always risky, already gated above
    # ------------------------------------------------------------------
    if action == "DELETE":
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("delete")
        return "continue"

    print(f"  -> Unknown action '{action}', skipped.")
    return "continue"