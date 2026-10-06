"""MCP client manager.

Launches configured MCP servers as isolated stdio subprocesses, discovers their
tools from the *running* server, and registers them in the tool registry with
namespaced names (``<server>__<tool>``) and mapped risk tiers.

All MCP I/O runs on one private asyncio loop thread so the rest of Friday (sync,
threaded) can call tools without caring about async.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import threading
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.mcp_client.config import McpConfig, McpConfigError, ServerConfig, load_config
from friday.tools.types import ToolResult, ToolSpec

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")


def _tool_name(server: str, tool: str) -> str:
    return f"{server}__{_SAFE_NAME.sub('_', tool)}"


def resolve_command(cmd: str) -> str:
    """PATH first, then the venv Scripts directory next to this interpreter (uv lives there)."""
    found = shutil.which(cmd)
    if found:
        return found
    scripts = Path(sys.executable).parent
    for cand in (scripts / f"{cmd}.exe", scripts / cmd):
        if cand.exists():
            return str(cand)
    raise FileNotFoundError(f"command not found: {cmd}")


def _blocks_to_result(result: Any, server: str) -> ToolResult:
    content: list[dict[str, Any]] = []
    for block in getattr(result, "content", None) or []:
        btype = getattr(block, "type", "")
        if btype == "text":
            content.append({"type": "text", "text": getattr(block, "text", "")})
        elif btype == "image":
            content.append({"type": "image", "data": getattr(block, "data", ""),
                            "mime": getattr(block, "mime_type", None) or "image/png"})
        else:
            content.append({"type": "text", "text": f"[{btype} content omitted]"})
    structured = getattr(result, "structured_content", None)
    res = ToolResult(
        content=content,
        structured=structured if isinstance(structured, dict) else None,
        is_error=bool(getattr(result, "is_error", False)),
        # Everything an MCP server returns (screen text, web pages, files) is untrusted DATA.
        metadata={"source": f"mcp:{server}", "untrusted": True},
    )
    return res


@dataclass
class ServerState:
    config: ServerConfig
    status: str = "stopped"          # stopped | starting | ready | stopping | error
    error: str = ""
    tools: list[str] = field(default_factory=list)       # registry names
    remote_tools: list[dict[str, Any]] = field(default_factory=list)
    server_info: dict[str, Any] = field(default_factory=dict)
    started_at: float | None = None
    calls: int = 0
    client: Any = None
    stop_event: asyncio.Event | None = None
    task: "asyncio.Future[Any] | None" = None


class McpManager:
    def __init__(self, config: McpConfig | None = None, *, registry: Any = None) -> None:
        self._config = config
        self._registry = registry
        self._states: dict[str, ServerState] = {}
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.config_error = ""

    # -- config ------------------------------------------------------------
    @property
    def registry(self):
        if self._registry is None:
            from friday.tools.registry import get_registry

            self._registry = get_registry()
        return self._registry

    def load(self) -> None:
        try:
            self._config = self._config or load_config()
            self.config_error = ""
        except McpConfigError as exc:
            self._config = McpConfig(inherit_env=[], servers={})
            self.config_error = str(exc)
        with self._lock:
            for name, sc in self._config.servers.items():
                self._states.setdefault(name, ServerState(config=sc))

    def reload_config(self) -> None:
        self._config = None
        self.load()
        with self._lock:
            for name, sc in self._config.servers.items():  # type: ignore[union-attr]
                st = self._states.get(name)
                if st is None:
                    self._states[name] = ServerState(config=sc)
                elif st.status in ("stopped", "error"):
                    st.config = sc

    # -- loop thread -------------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return self._loop
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run() -> None:
                asyncio.set_event_loop(loop)
                loop.call_soon(ready.set)
                loop.run_forever()

            self._loop = loop
            self._thread = threading.Thread(target=run, name="friday-mcp", daemon=True)
            self._thread.start()
            ready.wait(5)
            return loop

    # -- lifecycle ---------------------------------------------------------
    def start(self, name: str) -> None:
        """Begin starting a server (non-blocking). Poll :meth:`status`."""
        if self._config is None:
            self.load()
        with self._lock:
            st = self._states.get(name)
            if st is None:
                raise KeyError(f"unknown MCP server: {name}")
            if st.status in ("starting", "ready", "stopping"):
                return
            st.status, st.error, st.tools, st.remote_tools = "starting", "", [], []
        loop = self._ensure_loop()
        st.task = asyncio.run_coroutine_threadsafe(self._run_server(st), loop)

    def start_enabled(self) -> list[str]:
        if self._config is None:
            self.load()
        started = []
        for name, st in list(self._states.items()):
            if st.config.enabled:
                self.start(name)
                started.append(name)
        return started

    def wait_ready(self, name: str, timeout: float = 60.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            st = self._states.get(name)
            if st and st.status == "ready":
                return True
            if st and st.status in ("error", "stopped"):
                return False
            time.sleep(0.1)
        return False

    def stop(self, name: str, timeout: float = 15.0) -> bool:
        """Graceful stop (closes the subprocess). Returns True once stopped."""
        with self._lock:
            st = self._states.get(name)
        if st is None or st.status in ("stopped",):
            return True
        st.status = "stopping" if st.status != "error" else st.status
        loop = self._loop
        if loop is not None and st.stop_event is not None:
            loop.call_soon_threadsafe(st.stop_event.set)
        if st.task is not None:
            try:
                st.task.result(timeout)
            except Exception:  # noqa: BLE001
                st.task.cancel()
        self._unregister(st)
        if st.status != "error":
            st.status = "stopped"
        return True

    def kill_all(self) -> int:
        """Kill switch: stop every server and drop every MCP tool immediately."""
        names = [n for n, s in self._states.items() if s.status not in ("stopped",)]
        for n in names:
            st = self._states[n]
            self._unregister(st)       # tools disappear first, so nothing new can be called
            self.stop(n, timeout=5)
        return len(names)

    def shutdown(self) -> None:
        self.kill_all()
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)

    def _unregister(self, st: ServerState) -> None:
        self.registry.unregister_source(f"mcp:{st.config.name}")
        st.tools = []

    # -- server task -------------------------------------------------------
    def _build_params(self, cfg: ServerConfig):
        from mcp import StdioServerParameters

        inherit = self._config.inherit_env if self._config else []
        env = {k: os.environ[k] for k in inherit if k in os.environ}
        env.update(cfg.env)   # explicit config last (telemetry flags etc.)
        return StdioServerParameters(
            command=resolve_command(cfg.command), args=list(cfg.args), env=env, cwd=cfg.cwd,
        )

    async def _run_server(self, st: ServerState) -> None:
        from mcp import Client

        cfg = st.config
        st.stop_event = asyncio.Event()
        stack = AsyncExitStack()
        try:
            params = self._build_params(cfg)
            client = Client(params, read_timeout_seconds=cfg.call_timeout)
            await asyncio.wait_for(stack.enter_async_context(client), cfg.startup_timeout)
            listed = await asyncio.wait_for(client.list_tools(), cfg.startup_timeout)
            st.client = client
            info = getattr(client, "server_info", None)
            st.server_info = info.model_dump(exclude_none=True) if info is not None else {}
            self._register_tools(st, listed.tools)
            st.status, st.started_at = "ready", time.time()
            await st.stop_event.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - includes ExceptionGroup from anyio
            st.status, st.error = "error", f"{type(exc).__name__}: {exc}"[:500]
        finally:
            st.client = None
            self._unregister(st)
            try:
                await asyncio.wait_for(stack.aclose(), 10)
            except BaseException:  # noqa: BLE001
                pass
            if st.status != "error":
                st.status = "stopped"

    def _register_tools(self, st: ServerState, tools: list[Any]) -> None:
        cfg = st.config
        excluded = set(cfg.exclude_tools)
        for t in tools:
            if t.name in excluded:
                continue
            ann = t.annotations.model_dump(exclude_none=True) if getattr(t, "annotations", None) else {}
            schema = getattr(t, "input_schema", None) or {"type": "object", "properties": {}}
            risk = cfg.risk_for(t.name, ann)
            reg_name = _tool_name(cfg.name, t.name)
            spec = ToolSpec(
                name=reg_name,
                description=(t.description or t.name).strip()[:1200],
                input_schema=schema,
                handler=self._make_handler(cfg.name, t.name),
                risk=risk,
                source=f"mcp:{cfg.name}",
                title=getattr(t, "title", None) or t.name,
            )
            try:
                self.registry.register(spec, replace=True)
            except Exception as exc:  # noqa: BLE001 - one bad schema must not hide the rest
                st.error = f"skipped {t.name}: {exc}"[:300]
                continue
            st.tools.append(reg_name)
            st.remote_tools.append({"name": t.name, "registry_name": reg_name, "risk": risk.value, "annotations": ann})

    def _make_handler(self, server: str, tool: str):
        def handler(args: dict[str, Any]) -> ToolResult:
            st = self._states.get(server)
            loop = self._loop
            if st is None or st.client is None or loop is None or st.status != "ready":
                return ToolResult.error(f"MCP server '{server}' is not running")
            st.calls += 1
            fut = asyncio.run_coroutine_threadsafe(st.client.call_tool(tool, args), loop)
            try:
                result = fut.result(st.config.call_timeout + 5)
            except Exception as exc:  # noqa: BLE001
                fut.cancel()
                return ToolResult.error(f"MCP call failed ({server}.{tool}): {type(exc).__name__}: {exc}")
            return _blocks_to_result(result, server)

        return handler

    # -- introspection -----------------------------------------------------
    def status(self) -> list[dict[str, Any]]:
        if self._config is None:
            self.load()
        out = []
        with self._lock:
            for name, st in self._states.items():
                out.append({
                    "name": name,
                    "description": st.config.description,
                    "enabled": st.config.enabled,
                    "status": st.status,
                    "error": st.error,
                    "command": " ".join([st.config.command, *st.config.args])[:300],
                    "server_info": st.server_info,
                    "uptime_s": round(time.time() - st.started_at, 1) if st.started_at and st.status == "ready" else None,
                    "calls": st.calls,
                    "tools": [
                        {**rt, "tier_source": "config"} for rt in st.remote_tools
                    ],
                })
        return out


_manager: McpManager | None = None
_manager_lock = threading.Lock()


def get_mcp_manager() -> McpManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = McpManager()
            _manager.load()
        return _manager


def set_mcp_manager(m: McpManager | None) -> None:
    global _manager
    with _manager_lock:
        _manager = m
