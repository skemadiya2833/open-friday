"""Tool registry for ReAct-lite agentic skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from friday.config import SHELL_TOOLS_ENABLED, WORKSPACE_DIR, ensure_data_dirs


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]
    risky: bool = False


def _safe_workspace_path(rel: str) -> Path:
    ensure_data_dirs()
    root = Path(WORKSPACE_DIR).resolve()
    target = (root / rel).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Path escapes workspace sandbox")
    return target


def _web_search(args: dict[str, Any]) -> str:
    from friday.knowledge.search import perform_knowledge_search

    query = str(args.get("query") or "").strip()
    if not query:
        return "Missing query"
    note = perform_knowledge_search(query)
    return note.summary


def _memory_search(args: dict[str, Any]) -> str:
    from friday.memory import get_memory

    hits = get_memory().search(str(args.get("query") or ""), limit=int(args.get("limit") or 5))
    if not hits:
        return "No memories found."
    return "\n".join(f"- ({h.score:.2f}) [{h.id[:8]}] {h.text[:200]}" for h in hits)


def _memory_add(args: dict[str, Any]) -> str:
    from friday.memory import get_memory

    text = str(args.get("text") or "").strip()
    if not text:
        return "Missing text"
    cid = get_memory().add(text, metadata={"source": "tool"})
    return f"Stored memory id={cid}"


def _memory_delete(args: dict[str, Any]) -> str:
    from friday.memory import get_memory

    doc_id = str(args.get("id") or "").strip()
    ok = get_memory().delete(doc_id)
    return "Deleted." if ok else "Not found."


def _read_file(args: dict[str, Any]) -> str:
    path = _safe_workspace_path(str(args.get("path") or ""))
    if not path.exists():
        return f"File not found: {path.name}"
    return path.read_text(encoding="utf-8")[:8000]


def _write_file(args: dict[str, Any]) -> str:
    path = _safe_workspace_path(str(args.get("path") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    content = str(args.get("content") or "")
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path.name}"


def _list_files(args: dict[str, Any]) -> str:
    ensure_data_dirs()
    root = Path(WORKSPACE_DIR)
    rel = str(args.get("path") or ".")
    folder = _safe_workspace_path(rel)
    if not folder.exists():
        return "Folder empty / missing"
    entries = []
    for p in sorted(folder.iterdir())[:100]:
        entries.append(("dir " if p.is_dir() else "file") + f" {p.name}")
    return "\n".join(entries) or "(empty)"


def _schedule_task(args: dict[str, Any]) -> str:
    from friday.tasks.scheduler import get_scheduler

    job = get_scheduler().add_job(
        prompt=str(args.get("prompt") or args.get("message") or ""),
        skill_id=str(args.get("skill_id") or "chat"),
        delay_seconds=args.get("delay_seconds"),
        run_at=args.get("run_at"),
        cron=args.get("cron"),
        title=str(args.get("title") or "Friday task"),
    )
    return f"Scheduled task id={job['id']} title={job['title']}"


def _list_tasks(args: dict[str, Any]) -> str:
    from friday.tasks.scheduler import get_scheduler

    jobs = get_scheduler().list_jobs()
    if not jobs:
        return "No scheduled tasks."
    return "\n".join(
        f"- {j['id'][:8]} [{j['status']}] {j['title']} skill={j['skill_id']}" for j in jobs
    )


def _cancel_task(args: dict[str, Any]) -> str:
    from friday.tasks.scheduler import get_scheduler

    ok = get_scheduler().cancel(str(args.get("id") or ""))
    return "Cancelled." if ok else "Task not found."


def _start_computer_use(args: dict[str, Any]) -> str:
    return (
        "Use the computer_use skill for desktop automation. "
        f"Objective would be: {args.get('objective') or args.get('prompt')}"
    )


def _plan_list(_args: dict[str, Any]) -> str:
    from friday.tasks.plan import format_for_prompt, get_plan

    data = get_plan()
    return f"Today ({data.get('date')}):\n{format_for_prompt()}"


def _plan_add(args: dict[str, Any]) -> str:
    from friday.tasks.plan import add_item

    text = str(args.get("text") or args.get("item") or "").strip()
    if not text:
        return "Missing agenda text"
    note = str(args.get("note") or "")
    item = add_item(text, note=note)
    return f"Added to today's plan: {item['text']}"


def _plan_done(args: dict[str, Any]) -> str:
    from friday.tasks.plan import get_plan, set_done

    item_id = str(args.get("id") or "").strip()
    text = str(args.get("text") or "").strip().lower()
    data = get_plan()
    if not item_id and text:
        for it in data.get("items") or []:
            if text in str(it.get("text") or "").lower():
                item_id = it["id"]
                break
    if not item_id:
        return "Could not find that agenda item"
    item = set_done(item_id, True)
    return f"Marked done: {item['text']}" if item else "Not found"


def _plan_remove(args: dict[str, Any]) -> str:
    from friday.tasks.plan import remove_item

    ok = remove_item(str(args.get("id") or ""))
    return "Removed." if ok else "Not found"


def _run_shell(args: dict[str, Any]) -> str:
    if not SHELL_TOOLS_ENABLED:
        return "Shell tools disabled. Set SHELL_TOOLS_ENABLED=true to allow."
    import subprocess

    cmd = str(args.get("command") or "")
    if not cmd:
        return "Missing command"
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
        )
        out = (proc.stdout or "")[:4000]
        err = (proc.stderr or "")[:1000]
        return f"exit={proc.returncode}\n{out}\n{err}".strip()
    except Exception as exc:
        return f"Shell error: {exc}"


_TOOLS: dict[str, ToolSpec] = {}


def _register_defaults() -> None:
    specs = [
        ToolSpec("web_search", "Open a browser Google search for a query", {"query": "str"}, _web_search),
        ToolSpec("memory_search", "Search vector memory", {"query": "str", "limit": "int?"}, _memory_search),
        ToolSpec("memory_add", "Store a note in vector memory", {"text": "str"}, _memory_add),
        ToolSpec("memory_delete", "Delete a memory by id", {"id": "str"}, _memory_delete, risky=True),
        ToolSpec("read_file", "Read a workspace file", {"path": "str"}, _read_file),
        ToolSpec("write_file", "Write a workspace file", {"path": "str", "content": "str"}, _write_file),
        ToolSpec("list_files", "List workspace files", {"path": "str?"}, _list_files),
        ToolSpec(
            "schedule_task",
            "Schedule a future Friday job",
            {"prompt": "str", "skill_id": "str?", "delay_seconds": "int?", "run_at": "str?", "cron": "str?", "title": "str?"},
            _schedule_task,
        ),
        ToolSpec("list_tasks", "List scheduled tasks", {}, _list_tasks),
        ToolSpec("cancel_task", "Cancel a scheduled task", {"id": "str"}, _cancel_task),
        ToolSpec("plan_list", "List today's agenda / plan items", {}, _plan_list),
        ToolSpec("plan_add", "Add an item to today's plan", {"text": "str", "note": "str?"}, _plan_add),
        ToolSpec("plan_done", "Mark a today's plan item done", {"id": "str?", "text": "str?"}, _plan_done),
        ToolSpec("plan_remove", "Remove a today's plan item", {"id": "str"}, _plan_remove),
        ToolSpec("start_computer_use", "Hint to launch computer use", {"objective": "str"}, _start_computer_use),
        ToolSpec("run_shell", "Run a shell command (gated)", {"command": "str"}, _run_shell, risky=True),
    ]
    for s in specs:
        _TOOLS[s.name] = s


def get_tool(name: str) -> ToolSpec | None:
    if not _TOOLS:
        _register_defaults()
    return _TOOLS.get(name)


def list_tools(allowed: list[str] | None = None) -> list[ToolSpec]:
    if not _TOOLS:
        _register_defaults()
    if allowed is None:
        return list(_TOOLS.values())
    return [_TOOLS[n] for n in allowed if n in _TOOLS]


def call_tool(name: str, args: dict[str, Any]) -> str:
    tool = get_tool(name)
    if tool is None:
        return f"Unknown tool: {name}"
    try:
        return tool.handler(args or {})
    except Exception as exc:
        return f"Tool error ({name}): {exc}"


def tools_prompt_block(allowed: list[str]) -> str:
    lines = []
    for t in list_tools(allowed):
        lines.append(f"- {t.name}: {t.description} params={json.dumps(t.parameters)}")
    return "\n".join(lines)
