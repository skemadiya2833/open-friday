"""Friday Control Center — FastAPI backend."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from friday.config import (
    API_TOKEN, EXTRA_ALLOWED_HOSTS, EXTRA_ALLOWED_ORIGINS, SERVER_HOST, SERVER_PORT, VOICE_ENABLED,
    ensure_data_dirs, resolve_chat_model,
)
from friday.config import VISION_MODEL, EMBED_MODEL, MODEL_NAME
from friday.server.routes_tools import router as tools_router
from friday.server.security import RequestGuard, default_allowed_hosts, is_loopback

ensure_data_dirs()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Start MCP servers marked `enabled: true` in config/mcp_servers.yaml (none by default).
    try:
        from friday.mcp_client import get_mcp_manager

        get_mcp_manager().start_enabled()
    except Exception as exc:  # noqa: BLE001 - never block the UI on an MCP problem
        print(f"[MCP] startup skipped: {exc}")
    yield
    try:
        from friday.mcp_client import get_mcp_manager

        get_mcp_manager().shutdown()
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(title="Friday", version="3.1.0", lifespan=lifespan)
# No CORS: the UI is served same-origin. The guard rejects foreign Host/Origin headers
# (DNS rebinding / CSRF) and enforces a bearer token for non-loopback binds.
app.add_middleware(
    RequestGuard,
    allowed_hosts=default_allowed_hosts(EXTRA_ALLOWED_HOSTS),
    token=API_TOKEN or None,
    extra_origins=EXTRA_ALLOWED_ORIGINS,
)
app.include_router(tools_router)

_ws_clients: list[WebSocket] = []


async def broadcast(event: dict[str, Any]) -> None:
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    skill_override: str | None = None
    voice_mode: bool = False


class MemoryAddRequest(BaseModel):
    text: str
    collection: str = "memories"


class SkillPatch(BaseModel):
    description: str | None = None
    triggers: list[str] | None = None
    priority: int | None = None
    enabled: bool | None = None


class TaskCreate(BaseModel):
    prompt: str
    title: str = "Friday task"
    skill_id: str = "chat"
    delay_seconds: float | None = None
    run_at: str | None = None
    cron: str | None = None


class TTSRequest(BaseModel):
    text: str


class PlanAddRequest(BaseModel):
    text: str
    note: str = ""


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "vision_model": VISION_MODEL or MODEL_NAME,
        "chat_model": resolve_chat_model(),
        "embed_model": EMBED_MODEL,
        "voice": VOICE_ENABLED,
    }


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    from friday.assistant.orchestrator import handle_message

    return handle_message(
        req.message,
        session_id=req.session_id,
        skill_override=req.skill_override,
        voice_mode=req.voice_mode,
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    from friday.assistant.orchestrator import stream_message

    def _safe(obj: Any) -> Any:
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        if isinstance(obj, dict):
            return {str(k): _safe(v) for k, v in obj.items() if str(k) not in {"image", "pil_image", "frame", "screenshot"}}
        if isinstance(obj, (list, tuple)):
            return [_safe(v) for v in obj]
        if "Image" in type(obj).__name__:
            return None
        try:
            json.dumps(obj)
            return obj
        except TypeError:
            return str(obj)

    def event_gen():
        for ev in stream_message(
            req.message,
            session_id=req.session_id,
            skill_override=req.skill_override,
            voice_mode=req.voice_mode,
        ):
            yield f"data: {json.dumps(_safe(ev), default=str)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/api/sessions")
def sessions() -> list[dict[str, Any]]:
    from friday.assistant.session import get_session_store
    return get_session_store().list_sessions()


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str) -> dict[str, Any]:
    from friday.assistant.session import get_session_store
    s = get_session_store().load(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s.to_dict()


@app.post("/api/sessions")
def new_session() -> dict[str, Any]:
    from friday.assistant.session import get_session_store
    return get_session_store().create().to_dict()


@app.get("/api/skills")
def skills() -> list[dict[str, Any]]:
    from friday.skills.registry import get_registry
    return [m.to_dict() for m in get_registry().list()]


@app.patch("/api/skills/{skill_id}")
def patch_skill(skill_id: str, body: SkillPatch) -> dict[str, Any]:
    from friday.skills.registry import get_registry
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    m = get_registry().update_manifest(skill_id, patch)
    if not m:
        raise HTTPException(404, "Skill not found")
    return m.to_dict()


@app.post("/api/skills/{skill_id}/enabled")
def set_skill_enabled(skill_id: str, enabled: bool = True) -> dict[str, Any]:
    from friday.skills.registry import get_registry
    if not get_registry().set_enabled(skill_id, enabled):
        raise HTTPException(404, "Skill not found")
    return {"id": skill_id, "enabled": enabled}


@app.get("/api/memory")
def memory_list(collection: str = "memories", limit: int = 100) -> list[dict[str, Any]]:
    from friday.memory import get_memory
    return [
        {"id": h.id, "text": h.text, "score": h.score, "metadata": h.metadata}
        for h in get_memory().list_all(collection=collection, limit=limit)
    ]


@app.get("/api/memory/search")
def memory_search(q: str, collection: str = "memories", limit: int = 8) -> list[dict[str, Any]]:
    from friday.memory import get_memory
    return [
        {"id": h.id, "text": h.text, "score": h.score, "metadata": h.metadata}
        for h in get_memory().search(q, collection=collection, limit=limit)
    ]


@app.post("/api/memory")
def memory_add(body: MemoryAddRequest) -> dict[str, Any]:
    from friday.memory import get_memory
    cid = get_memory().add(body.text, collection=body.collection)
    return {"id": cid}


@app.delete("/api/memory/{doc_id}")
def memory_delete(doc_id: str, collection: str = "memories") -> dict[str, Any]:
    from friday.memory import get_memory
    ok = get_memory().delete(doc_id, collection=collection)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"deleted": True}


@app.get("/api/memory/stats")
def memory_stats() -> dict[str, int]:
    from friday.memory import get_memory
    try:
        return get_memory().stats()
    except Exception as exc:
        print(f"[Memory] stats recovery: {exc}")
        from friday.memory import reset_memory_singleton, get_memory as gm
        reset_memory_singleton()
        return gm().stats()


@app.get("/api/tasks")
def tasks_list() -> list[dict[str, Any]]:
    from friday.tasks.scheduler import get_scheduler
    return get_scheduler().list_jobs()


@app.post("/api/tasks")
def tasks_create(body: TaskCreate) -> dict[str, Any]:
    from friday.tasks.scheduler import get_scheduler
    return get_scheduler().add_job(
        prompt=body.prompt,
        title=body.title,
        skill_id=body.skill_id,
        delay_seconds=body.delay_seconds,
        run_at=body.run_at,
        cron=body.cron,
    )


@app.delete("/api/tasks/{job_id}")
def tasks_cancel(job_id: str) -> dict[str, Any]:
    from friday.tasks.scheduler import get_scheduler
    if not get_scheduler().cancel(job_id):
        raise HTTPException(404, "Not found")
    return {"cancelled": True}


@app.post("/api/tasks/{job_id}/run")
def tasks_run(job_id: str) -> dict[str, Any]:
    from friday.tasks.scheduler import get_scheduler
    if not get_scheduler().run_now(job_id):
        raise HTTPException(404, "Not found")
    return {"started": True}


@app.get("/api/plan/today")
def plan_today() -> dict[str, Any]:
    from friday.tasks.plan import get_plan
    return get_plan()


@app.post("/api/plan/today")
def plan_add(body: PlanAddRequest) -> dict[str, Any]:
    from friday.tasks.plan import add_item
    try:
        return add_item(body.text, note=body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/plan/today/{item_id}/done")
def plan_done(item_id: str, done: bool = True) -> dict[str, Any]:
    from friday.tasks.plan import set_done
    item = set_done(item_id, done)
    if not item:
        raise HTTPException(404, "Not found")
    return item


@app.delete("/api/plan/today/{item_id}")
def plan_delete(item_id: str) -> dict[str, Any]:
    from friday.tasks.plan import remove_item
    if not remove_item(item_id):
        raise HTTPException(404, "Not found")
    return {"deleted": True}


@app.post("/api/agent/cancel")
def agent_cancel() -> dict[str, Any]:
    """Hard-stop the active computer-use / agent loop (and abort Ollama streams)."""
    from friday.agent.control import cancel_active_agent

    stopped = cancel_active_agent()
    return {"cancelled": stopped, "message": "halt requested" if stopped else "no agent running"}


@app.get("/api/agent/status")
def agent_status() -> dict[str, Any]:
    from friday.agent.control import get_controller

    ctrl = get_controller()
    return {
        "running": ctrl is not None,
        "cancel_requested": bool(ctrl and ctrl.should_stop()),
        "paused": bool(ctrl and ctrl.is_paused),
    }


@app.post("/api/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...)) -> dict[str, Any]:
    if not VOICE_ENABLED:
        raise HTTPException(400, "Voice disabled")
    from friday.voice.stt import transcribe_bytes

    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty audio upload")
    suffix = Path(file.filename or "speech.webm").suffix or ".webm"
    try:
        text = transcribe_bytes(data, suffix=suffix)
    except Exception as exc:
        print(f"[Voice] Transcribe failed: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                "Speech recognition failed. Install ffmpeg (and add it to PATH), "
                f"then retry. ({exc})"
            ),
        ) from exc
    return {"text": text or ""}


@app.post("/api/voice/speak")
def voice_speak(body: TTSRequest):
    if not VOICE_ENABLED:
        raise HTTPException(400, "Voice disabled")
    from friday.voice.tts import synthesize_bytes
    from fastapi.responses import Response

    data, mime = synthesize_bytes(body.text)
    if mime.startswith("text"):
        raise HTTPException(
            503,
            "TTS backend unavailable. Install edge-tts (`pip install edge-tts`) or ensure Windows SAPI voices work.",
        )
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "no-store", "Content-Length": str(len(data))},
    )


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            msg = await ws.receive_text()
            # ping/pong or client events
            if msg == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


def _mount_frontend(application: FastAPI) -> None:
    root = Path(__file__).resolve().parents[2]
    dist = root / "web" / "dist"
    static_fallback = root / "web" / "public"
    if dist.exists():
        application.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")
    elif (static_fallback / "index.html").exists():
        application.mount("/", StaticFiles(directory=str(static_fallback), html=True), name="ui")


_mount_frontend(app)


def run_server(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    bind = host or SERVER_HOST
    if not is_loopback(bind) and not API_TOKEN:
        raise SystemExit(
            f"Refusing to bind to non-loopback address {bind!r} without FRIDAY_API_TOKEN. "
            "Friday can control this desktop; set a long random token or bind to 127.0.0.1."
        )
    uvicorn.run(
        "friday.server.app:app",
        host=bind,
        port=port or SERVER_PORT,
        reload=False,
        log_level="info",
    )
