import time
import pyautogui
from engine.safety import is_risky_step, prompt_user_approval

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3


def execute_step(step: dict) -> str:
    """
    Executes a single action step.
    Returns "screenshot" if a new screen capture is needed before next step,
    "continue" to proceed, or "halt" if user rejected a risky action.
    """
    action = step.get("action", "").upper()
    description = step.get("description", "")

    print(f"\n[Friday] {description}")
    print(f"  -> Action: {action}")

    # Safety gate
    if is_risky_step(step):
        approved = prompt_user_approval(step)
        if not approved:
            print("[Safety] Action rejected by operator. Halting step.")
            return "halt"

    if action == "CLICK":
        x, y = step.get("x"), step.get("y")
        if x is not None and y is not None:
            pyautogui.click(x, y)
            print(f"  -> Clicked at ({x}, {y})")

    elif action == "HOVER":
        x, y = step.get("x"), step.get("y")
        if x is not None and y is not None:
            pyautogui.moveTo(x, y, duration=0.3)

    elif action == "TYPE":
        text = step.get("text", "")
        pyautogui.typewrite(text, interval=0.04)

    elif action == "PASTE":
        import pyperclip
        text = step.get("text", "")
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        print(f"  -> Pasted: {text[:60]}{'...' if len(text) > 60 else ''}")

    elif action == "SCROLL":
        x, y = step.get("x"), step.get("y")
        direction = step.get("direction", "down")
        amount = -5 if direction == "down" else 5
        if x and y:
            pyautogui.scroll(amount, x=x, y=y)
        else:
            pyautogui.scroll(amount)

    elif action == "SEARCH":
        text = step.get("text", "")
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        pyautogui.typewrite(text, interval=0.04)

    elif action == "DRAG":
        # Expects step to have x, y (start) and x2, y2 (end) — extend schema if needed
        pass

    elif action == "WAIT":
        duration = step.get("duration", 1.5)
        time.sleep(duration)

    elif action == "SCREENSHOT":
        print("  -> Requesting fresh screenshot before next step.")
        return "screenshot"

    elif action == "COMPLETE":
        print("\n[Friday] Task marked complete.")
        return "complete"

    elif action == "DELETE":
        # DELETE is always risky — already gated above
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("delete")

    return "continue"