"""Tiny stdio MCP server used by tests (real protocol, no mocks)."""

from __future__ import annotations

import os

from mcp.server import MCPServer

server = MCPServer("echo-test")


@server.tool()
def echo(text: str) -> str:
    """Echo text back."""
    return text


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
def dangerous_thing(path: str) -> str:
    """Pretend to delete something."""
    return f"deleted {path}"


@server.tool()
def fail(reason: str = "boom") -> str:
    """Always raises."""
    raise RuntimeError(reason)


@server.tool()
def env_flag() -> str:
    """Report the telemetry flag the manager is supposed to inject."""
    return os.environ.get("ANONYMIZED_TELEMETRY", "<unset>") + "|" + os.environ.get("GEMINI_API_KEY", "<no-secret>")


if __name__ == "__main__":
    server.run("stdio")
