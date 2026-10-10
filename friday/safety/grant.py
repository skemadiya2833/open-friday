"""Run-level grants: a human-issued, scoped, expiring, revocable permission.

Why this exists
---------------
Every desktop tool (Click, Type, ...) is in the ``confirm`` tier, so by default each
call needs a human approval. An autonomous run cannot be driven that way. A *grant*
lets the owner say once: "for this task, Friday may use these tools". It is NOT a
policy change:

* ``deny`` decisions (policy file, dangerous tier, disabled shell) are never overridden.
* Only tools whose name matches one of the grant's prefixes are covered.
* A grant is bound to one run id, expires, and is revoked when the run ends,
  is cancelled, or the emergency stop fires.
* Every call made under a grant is audited with approver ``grant:<id>:<issuer>``.
* Irreversible actions still need a fresh approval (see ``friday.agent.guard``).

Grants can only be created by code paths that represent an explicit human act
(approval dialog, or an explicit CLI flag). Model output can never create one.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class RunGrant:
    run_id: str
    prefixes: tuple[str, ...]
    issuer: str                         # e.g. "owner-ui", "cli:--grant-desktop", "benchmark-cli"
    ttl_seconds: float = 1800.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created: float = field(default_factory=time.time)
    _revoked: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True

    @property
    def active(self) -> bool:
        with self._lock:
            return (not self._revoked) and (time.time() - self.created) < self.ttl_seconds

    def covers(self, tool: str, run_id: str | None) -> bool:
        if not self.active:
            return False
        if run_id != self.run_id:
            return False
        return any(tool.startswith(p) for p in self.prefixes)

    @property
    def approver(self) -> str:
        return f"grant:{self.id}:{self.issuer}"


_grants: dict[str, RunGrant] = {}
_glock = threading.Lock()


def issue(run_id: str, prefixes: tuple[str, ...] | list[str], issuer: str, ttl_seconds: float = 1800.0) -> RunGrant:
    if not issuer:
        raise ValueError("a grant needs an issuer")
    if not prefixes or any(not p for p in prefixes):
        raise ValueError("a grant needs explicit non-empty tool prefixes")
    g = RunGrant(run_id=run_id, prefixes=tuple(prefixes), issuer=issuer, ttl_seconds=ttl_seconds)
    with _glock:
        _grants[g.id] = g
    return g


def find(run_id: str | None, tool: str) -> RunGrant | None:
    with _glock:
        for g in _grants.values():
            if g.covers(tool, run_id):
                return g
    return None


def revoke_run(run_id: str) -> int:
    n = 0
    with _glock:
        for g in _grants.values():
            if g.run_id == run_id and g.active:
                g.revoke()
                n += 1
    return n


def revoke_all() -> int:
    n = 0
    with _glock:
        for g in _grants.values():
            if g.active:
                g.revoke()
                n += 1
        _grants.clear()
    return n
