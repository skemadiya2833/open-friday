# ADR-0006: MCP Python SDK version

Status: accepted. Evidence date: 2026-10-06 (PyPI JSON API, installed metadata).

## Facts
- `mcp` 2.0.0 was released stable on 2026-07-28 (after a/b/rc builds from 2026-06-11). Later releases: 2.0.1 (08-26), 2.1.0 (08-24), 2.1.1 (08-25), 2.2.0 (09-07), 2.3.0 (10-02). v1.x is maintenance-only.
- 2.3.0 declares: `anyio>=4.10` on Python >= 3.14 (`>=4.9` below), `pydantic>=2.12.0`, `starlette>=0.48.0` on 3.14, `httpx2>=2.10.0`, `jsonschema>=4.20.0`, `mcp-types==2.3.0`, `pywin32>=311` on Windows. Python `>=3.10`.
- Resolved lock on Python 3.14 / Windows (`requirements/core.lock.txt`): `mcp==2.3.0`, `anyio==4.15.1`, `pydantic==2.13.5`, `starlette==1.7.0`. All four floors are met with margin.

## Decision
Pin `mcp==2.3.0` (in `requirements/core.in` and the lock), not 2.0.0 and not v1.x.

Reasoning: all Friday MCP code and tests were written and run against 2.3.0 (`Client`, `StdioServerParameters`, `.structured_content`, snake_case annotations). 2.0.0 was never exercised here, so pinning it would be an untested configuration. Staying on v1.x would mean building on a maintenance-only line.

## Consequences
- Upgrades are deliberate: re-run `tests/test_mcp_manager.py` and `scripts/live_mcp_acceptance.py` before bumping the pin.
- `mcp` pulls in `httpx2` and `pywin32`; the project's own `httpx` use is unchanged.
- Alternative (recorded in DECISIONS_NEEDED D-002): pin 2.0.0 to match "stable" literally; rejected for being untested.
