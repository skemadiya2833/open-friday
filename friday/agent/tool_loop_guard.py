# Copyright 2025 The OpenJarvis Authors
# Licensed under the Apache License, Version 2.0
# Source: open-jarvis/OpenJarvis src/openjarvis/agents/loop_guard.py
# Commit: f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c
# Changes for Friday: pure-Python only (no Rust bridge / EventBus); per-run ContextVar;
# no-change detection on consecutive identical tool results; audit-friendly reasons.

"""Tool-call loop guard — identical calls, ping-pong, poll budget, no-change results."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoopGuardConfig:
    enabled: bool = True
    max_identical_calls: int = 3
    ping_pong_window: int = 6
    poll_tool_budget: int = 8
    max_no_change: int = 3
    warn_before_block: bool = True


@dataclass
class LoopVerdict:
    blocked: bool = False
    reason: str = ""
    warned: bool = False


@dataclass
class ToolLoopGuard:
    """Detect degenerate tool-calling loops (not GUI stall — that is StallDetector)."""

    config: LoopGuardConfig = field(default_factory=LoopGuardConfig)
    _call_counts: dict[str, int] = field(default_factory=dict)
    _tool_sequence: deque[str] = field(default_factory=lambda: deque(maxlen=24))
    _per_tool_counts: dict[str, int] = field(default_factory=dict)
    _warned: set[str] = field(default_factory=set)
    _last_result_hash: str | None = None
    _no_change: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        with self._lock:
            self._call_counts.clear()
            self._tool_sequence.clear()
            self._per_tool_counts.clear()
            self._warned.clear()
            self._last_result_hash = None
            self._no_change = 0

    def check_call(self, tool_name: str, arguments: Any) -> LoopVerdict:
        if not self.config.enabled:
            return LoopVerdict()
        arg_s = _canon_args(arguments)
        with self._lock:
            verdict, cycle_key = self._check_locked(tool_name, arg_s)
            if verdict.blocked and self.config.warn_before_block:
                if cycle_key not in self._warned:
                    self._warned.add(cycle_key)
                    return LoopVerdict(blocked=False, warned=True, reason=verdict.reason)
            return verdict

    def record_result(self, tool_name: str, result_text: str) -> LoopVerdict:
        """Block if the same tool returns an identical result too many times in a row."""
        if not self.config.enabled:
            return LoopVerdict()
        h = hashlib.sha256(f"{tool_name}:{result_text or ''}".encode("utf-8", "replace")).hexdigest()[:16]
        with self._lock:
            if h == self._last_result_hash:
                self._no_change += 1
            else:
                self._last_result_hash = h
                self._no_change = 1
            if self._no_change > self.config.max_no_change:
                reason = (
                    f"Tool '{tool_name}' returned the same result "
                    f"{self._no_change} times (max {self.config.max_no_change})."
                )
                cycle_key = f"nochange:{tool_name}:{h}"
                if self.config.warn_before_block and cycle_key not in self._warned:
                    self._warned.add(cycle_key)
                    return LoopVerdict(blocked=False, warned=True, reason=reason)
                return LoopVerdict(blocked=True, reason=reason)
        return LoopVerdict()

    def _check_locked(self, tool_name: str, arg_s: str) -> tuple[LoopVerdict, str]:
        call_hash = hashlib.sha256(f"{tool_name}:{arg_s}".encode()).hexdigest()[:16]
        self._call_counts[call_hash] = self._call_counts.get(call_hash, 0) + 1
        if self._call_counts[call_hash] > self.config.max_identical_calls:
            return (
                LoopVerdict(
                    blocked=True,
                    reason=(
                        f"Identical call to '{tool_name}' repeated "
                        f"{self._call_counts[call_hash]} times "
                        f"(max {self.config.max_identical_calls})."
                    ),
                ),
                f"identical:{call_hash}",
            )

        self._per_tool_counts[tool_name] = self._per_tool_counts.get(tool_name, 0) + 1
        # Poll budget only for tools marked polling via name heuristic (list/status/get).
        if _looks_polling(tool_name) and self._per_tool_counts[tool_name] > self.config.poll_tool_budget:
            return (
                LoopVerdict(
                    blocked=True,
                    reason=(
                        f"Tool '{tool_name}' exceeded poll budget "
                        f"({self.config.poll_tool_budget})."
                    ),
                ),
                f"poll:{tool_name}",
            )

        self._tool_sequence.append(tool_name)
        if len(self._tool_sequence) >= self.config.ping_pong_window and self._detect_ping_pong():
            return (
                LoopVerdict(
                    blocked=True,
                    reason="Repetitive tool-calling pattern detected (ping-pong).",
                ),
                "ping_pong",
            )
        return LoopVerdict(), ""

    def _detect_ping_pong(self) -> bool:
        seq = list(self._tool_sequence)
        n = self.config.ping_pong_window
        if len(seq) < n:
            return False
        window = seq[-n:]
        # A-B-A-B…
        if n >= 4 and len(set(window)) == 2:
            a, b = window[0], window[1]
            if a != b and all(window[i] == (a if i % 2 == 0 else b) for i in range(n)):
                return True
        # A-B-C-A-B-C…
        if n >= 6 and len(set(window)) == 3:
            period = window[:3]
            if period[0] != period[1] != period[2] != period[0]:
                if window[3:6] == period:
                    return True
        return False


def _canon_args(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments or {}, sort_keys=True, default=str)
    except Exception:
        return str(arguments)


def _looks_polling(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in ("list", "status", "get_", "read_", "snapshot", "observe"))


_run_guards: dict[str, ToolLoopGuard] = {}
_guards_lock = threading.Lock()
_current_run: ContextVar[str | None] = ContextVar("friday_tool_loop_run", default=None)


def bind_run(run_id: str | None) -> None:
    _current_run.set(run_id)


def get_tool_loop_guard(run_id: str | None = None) -> ToolLoopGuard:
    rid = run_id if run_id is not None else _current_run.get()
    key = rid or "_default"
    with _guards_lock:
        g = _run_guards.get(key)
        if g is None:
            g = ToolLoopGuard()
            _run_guards[key] = g
        return g


def reset_tool_loop_guard(run_id: str | None = None) -> None:
    rid = run_id if run_id is not None else _current_run.get()
    key = rid or "_default"
    with _guards_lock:
        g = _run_guards.get(key)
        if g:
            g.reset()
