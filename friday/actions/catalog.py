"""Single source of truth for agent actions and prompt vocabulary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    fields: str
    needs_coords: bool = False
    always_reobserve: bool = False


# Human-like interaction vocabulary — vision decides which to use.
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec("WIN_SEARCH", "Open an app via Windows Search", '{"text": str}', always_reobserve=True),
    ActionSpec("CLICK", "Left-click at a coordinate", '{"x": int, "y": int}', needs_coords=True, always_reobserve=True),
    ActionSpec("DOUBLE_CLICK", "Double left-click", '{"x": int, "y": int}', needs_coords=True, always_reobserve=True),
    ActionSpec("RIGHT_CLICK", "Right-click / context menu", '{"x": int, "y": int}', needs_coords=True, always_reobserve=True),
    ActionSpec("MIDDLE_CLICK", "Middle / scroll-wheel click", '{"x": int, "y": int}', needs_coords=True),
    ActionSpec("MOUSE_MOVE", "Move cursor without clicking", '{"x": int, "y": int}', needs_coords=True),
    ActionSpec("HOVER", "Hover to reveal tooltips/menus", '{"x": int, "y": int}', needs_coords=True),
    ActionSpec(
        "MOUSE_DOWN",
        "Press and hold a mouse button",
        '{"x": int, "y": int, "button": "left"|"right"|"middle"}',
        needs_coords=True,
    ),
    ActionSpec(
        "MOUSE_UP",
        "Release a held mouse button",
        '{"x": int, "y": int, "button": "left"|"right"|"middle"}',
    ),
    ActionSpec(
        "DRAG",
        "Drag from (x,y) to (x2,y2)",
        '{"x": int, "y": int, "x2": int, "y2": int}',
        needs_coords=True,
        always_reobserve=True,
    ),
    ActionSpec(
        "DRAG_DROP",
        "Reliable drag-and-drop via mouseDown→move→mouseUp",
        '{"x": int, "y": int, "x2": int, "y2": int}',
        needs_coords=True,
        always_reobserve=True,
    ),
    ActionSpec(
        "SCROLL",
        "Scroll wheel at a position",
        '{"x": int, "y": int, "direction": "up"|"down"|"left"|"right", "amount": int}',
        needs_coords=True,
        always_reobserve=True,
    ),
    ActionSpec("TYPE", "Type / paste literal text into the focused field", '{"text": str}', always_reobserve=True),
    ActionSpec("PASTE", "Paste text via clipboard", '{"text": str}', always_reobserve=True),
    ActionSpec("PRESS_KEY", "Press one key (enter, tab, escape, ...)", '{"key": str}', always_reobserve=True),
    ActionSpec("HOTKEY", "Chord of keys", '{"keys": ["ctrl", "c"]}', always_reobserve=True),
    ActionSpec("KEY_DOWN", "Hold a key", '{"key": str}'),
    ActionSpec("KEY_UP", "Release a held key", '{"key": str}'),
    ActionSpec("SELECT_ALL", "Ctrl+A", "{}"),
    ActionSpec("COPY", "Ctrl+C", "{}"),
    ActionSpec("CUT", "Ctrl+X", "{}"),
    ActionSpec("UNDO", "Ctrl+Z", "{}"),
    ActionSpec("REDO", "Ctrl+Y", "{}"),
    ActionSpec("SEARCH", "Open in-app find (Ctrl+F)", '{"text": str}', always_reobserve=True),
    ActionSpec("SAVE_FILE", "Ctrl+S, optionally type a filename", '{"text": optional_filename}', always_reobserve=True),
    ActionSpec(
        "NAVIGATE",
        "Focus the browser address bar, type a URL, press Enter",
        '{"url": str}',
        always_reobserve=True,
    ),
    ActionSpec(
        "NEW_TAB",
        "Open a new browser tab (Ctrl+T)",
        "{}",
        always_reobserve=True,
    ),
    ActionSpec(
        "CLOSE_TAB",
        "Close the current browser tab (Ctrl+W)",
        "{}",
        always_reobserve=True,
    ),
    ActionSpec(
        "SWITCH_TAB",
        "Cycle browser tabs (Ctrl+Tab)",
        "{}",
        always_reobserve=True,
    ),
    ActionSpec(
        "KNOWLEDGE_SEARCH",
        "Open a search tab to gather missing knowledge, then return to the task",
        '{"query": str}',
        always_reobserve=True,
    ),
    ActionSpec("WAIT", "Pause for page/UI updates", '{"duration": float}'),
    ActionSpec("DELETE", "Select all and delete (always requires approval)", "{}", always_reobserve=True),
    ActionSpec("COMPLETE", "Task finished successfully", "{}"),
)

ACTION_BY_NAME: dict[str, ActionSpec] = {a.name: a for a in ACTIONS}
ALL_ACTION_NAMES: frozenset[str] = frozenset(ACTION_BY_NAME)
COORD_ACTIONS: frozenset[str] = frozenset(a.name for a in ACTIONS if a.needs_coords)
REOBSERVE_ACTIONS: frozenset[str] = frozenset(a.name for a in ACTIONS if a.always_reobserve)

# Aim-verify applies to precise pointer targets.
AIM_ACTIONS: frozenset[str] = frozenset({
    "CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "MIDDLE_CLICK", "HOVER", "SCROLL",
})


def vocabulary_for_prompt() -> str:
    lines = []
    for spec in ACTIONS:
        lines.append(f"{spec.name:<16} — {spec.description} {spec.fields}")
    return "\n".join(lines)
