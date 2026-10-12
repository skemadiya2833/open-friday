"""Run recorder and outcome judgment (Stage L1, L2).

Trajectories are *structured* and contain no screenshots. Typed text is not stored (only its length), element names
and window titles are secret-redacted and truncated. Judgment: an objective check (benchmark ``task.check`` or any
programmatic verifier) is authoritative; the agent's own ``done`` is a low-confidence self-judgment.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from friday.safety.redact import redact_text

PROMPT_VERSION = "hybrid-h1"          # bump when SYSTEM_RULES changes in a way that matters for comparisons
GUARD_VERSION = "guard-k3"
_BROWSER = re.compile(r"(google chrome|microsoft edge|mozilla firefox|brave|opera|vivaldi)", re.I)
CONF_OBJECTIVE = 0.95
CONF_SELF = 0.4
CONF_SYSTEM_FAILURE = 0.7            # a failure the controller itself detected (stall, hung window, timeout)


def clip(text: str, n: int = 80) -> str:
    return redact_text(re.sub(r"\s+", " ", text or "")).strip()[:n]


@dataclass
class Step:
    action: str
    element: str = ""
    etype: str = ""
    window: str = ""
    keys: str = ""
    app: str = ""
    text_len: int = 0
    result: str = ""

    def short(self) -> str:
        bits = [self.action.lower()]
        if self.app:
            bits.append(self.app)
        if self.element:
            bits.append(f"'{self.element[:40]}'")
        if self.keys:
            bits.append(self.keys)
        if self.text_len:
            bits.append(f"<{self.text_len} chars>")
        return " ".join(bits)


@dataclass
class Trajectory:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)
    task: str = ""
    apps: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    outcome: str = "unknown"                 # success | failure | halted
    judgment: str = "self"                   # objective | self | system
    confidence: float = CONF_SELF
    failure_reason: dict | str | None = None
    duration_s: float = 0.0
    model: str = ""
    prompt_version: str = PROMPT_VERSION
    guard_version: str = GUARD_VERSION
    untrusted_source: bool = False           # the run touched web pages (browser windows)
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Trajectory":
        t = Trajectory(**{k: v for k, v in d.items() if k != "steps"})
        t.steps = [Step(**s) for s in d.get("steps", [])]
        return t


def _app_of(title: str) -> str:
    """Coarse app tag from a window title ("Untitled - Notepad" -> notepad)."""
    t = (title or "").strip()
    if not t:
        return ""
    last = re.split(r"\s+[-\u2013\u2014]\s+", t)[-1].strip().lower()
    return re.sub(r"[^a-z0-9 ._+]", "", last)[:40]


class Recorder:
    def __init__(self, task: str, *, model: str = "", run_id: str = "") -> None:
        self.t0 = time.time()
        self.tr = Trajectory(task=clip(task, 300), model=model, run_id=run_id)

    def step(self, plan: Any, result: str, window_title: str = "") -> None:
        """``plan`` is a hybrid ``Plan``; typed text is reduced to its length."""
        raw = getattr(plan, "raw", {}) or {}
        el = getattr(plan, "element", None)
        s = Step(action=str(plan.action), result=result[:40], window=clip(window_title, 60))
        if el is not None:
            s.element, s.etype = clip(el.name, 60), el.ctype
        if plan.action == "shortcut":
            s.keys = clip(str(raw.get("keys", "")), 30)
        if plan.action == "launch":
            s.app = clip(str(raw.get("app", "")), 40)
        if plan.action in ("type", "type_xy"):
            s.text_len = len(str(raw.get("text", "")))
        self.tr.steps.append(s)
        app = _app_of(window_title) or s.app.lower()
        if app and app not in self.tr.apps:
            self.tr.apps.append(app)
        if _BROWSER.search(window_title or ""):
            self.tr.untrusted_source = True

    def finish(self, status: str, failure: Any = None) -> Trajectory:
        tr = self.tr
        tr.duration_s = round(time.time() - self.t0, 1)
        tr.outcome = {"completed": "success", "halted": "halted"}.get(status, "failure")
        tr.failure_reason = failure if failure else (None if tr.outcome == "success" else status)
        if tr.outcome == "success":
            tr.judgment, tr.confidence = "self", CONF_SELF
        elif isinstance(failure, dict) and failure.get("kind"):
            tr.judgment, tr.confidence = "system", CONF_SYSTEM_FAILURE
        else:
            tr.judgment, tr.confidence = "self", CONF_SELF
        return tr


def apply_objective(tr: Trajectory, ok: bool, check: str = "") -> Trajectory:
    """An objective check overrides the agent's own opinion (e.g. agent said done but the file is missing)."""
    tr.outcome = "success" if ok else "failure"
    tr.judgment, tr.confidence = "objective", CONF_OBJECTIVE
    if not ok and not tr.failure_reason:
        tr.failure_reason = {"kind": "objective_check_failed", "detail": clip(check, 160)}
    if ok:
        tr.failure_reason = None
    return tr
