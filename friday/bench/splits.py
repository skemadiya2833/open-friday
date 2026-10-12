"""Frozen development / held-out split of the benchmark tasks (Stage L7).

Decided once, before any memory experiment. Rule: tune prompts, macros, memory and recovery ONLY on ``DEV``;
``HELDOUT`` is run for the final memory-off vs memory-on comparison and never used to change anything.
Honest caveat: earlier diagnosis work (Stages G/H) looked at overall results, but no held-out task below was
used as a debugging target (those were chrome_counter, calc_add/calc_mul smoke runs and the Settings tasks).
"""

HELDOUT = ("notepad_two_lines", "notepad_edit", "calc_mul", "explorer_new_textfile",
           "settings_display", "chrome_select", "canvas_blue_then_red")


def split_of(task_id: str) -> str:
    return "heldout" if task_id in HELDOUT else "dev"
