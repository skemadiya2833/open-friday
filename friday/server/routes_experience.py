"""Owner UI/API for experience memory: view, edit, delete, disable, export, per-app switches, growth limits (L6).
Changes need the same same-origin browser bar as approvals; reads are open to the local UI."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from friday.experience.store import get_experience

router = APIRouter()


def _require_ui(request: Request) -> None:
    if not request.headers.get("origin") or request.headers.get("sec-fetch-site") != "same-origin":
        raise HTTPException(403, "This action can only be taken from the Friday UI page")
    from friday.safety.physical import check_physical

    ok, why = check_physical()
    if not ok:
        raise HTTPException(403, why)


class Text(BaseModel):
    text: str


class Flag(BaseModel):
    enabled: bool


class Limits(BaseModel):
    max_entries: int | None = None
    max_trajectories: int | None = None
    retention_days: int | None = None
    min_confidence: float | None = None
    token_cap: int | None = None
    enabled: bool | None = None


@router.get("/api/experience")
def overview() -> dict[str, Any]:
    s = get_experience()
    return {"stats": s.stats(), "entries": s.list_entries(limit=300)}


@router.get("/api/experience/export", response_class=PlainTextResponse)
def export() -> str:
    s = get_experience()
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "traj.jsonl"
        s.export_trajectories(p)
        return p.read_text(encoding="utf-8")


@router.post("/api/experience/{eid}/edit")
def edit(eid: str, body: Text, request: Request) -> dict[str, Any]:
    _require_ui(request)
    if not get_experience().edit(eid, body.text):
        raise HTTPException(404, "no such entry")
    return {"ok": True}


@router.post("/api/experience/{eid}/enabled")
def enabled(eid: str, body: Flag, request: Request) -> dict[str, Any]:
    _require_ui(request)
    if not get_experience().set_enabled(eid, body.enabled):
        raise HTTPException(404, "no such entry")
    return {"ok": True}


@router.delete("/api/experience/{eid}")
def delete(eid: str, request: Request) -> dict[str, Any]:
    _require_ui(request)
    if not get_experience().delete(eid):
        raise HTTPException(404, "no such entry")
    return {"ok": True}


@router.post("/api/experience/apps/{app}")
def app_switch(app: str, body: Flag, request: Request) -> dict[str, Any]:
    _require_ui(request)
    get_experience().set_app_enabled(app, body.enabled)
    return {"settings": get_experience().settings()}


@router.post("/api/experience/limits")
def limits(body: Limits, request: Request) -> dict[str, Any]:
    _require_ui(request)
    s = get_experience()
    s.update_settings(**{k: v for k, v in body.model_dump().items() if v is not None})
    s.enforce_limits()
    return {"settings": s.settings()}


@router.post("/api/experience/propose-skills")
def propose(request: Request) -> dict[str, Any]:
    _require_ui(request)
    return {"proposed": get_experience().propose_skills()}      # proposals still need owner approval in Skills


_PAGE = """<!doctype html><meta charset=utf-8><title>Friday - Experience memory</title>
<style>body{font:14px system-ui;margin:24px;max-width:960px}td,th{border-bottom:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}
button{margin-right:4px}.off{opacity:.45}</style>
<h2>Experience memory</h2><p id=st></p>
<p><button onclick="lim()">Set limits</button><a href="/api/experience/export" download="trajectories.jsonl">Export trajectories</a></p>
<table id=t><tr><th>kind<th>apps<th>conf<th>hits<th>text<th></table>
<script>
async function post(u,b,m){const r=await fetch(u,{method:m||'POST',headers:{'content-type':'application/json'},body:b?JSON.stringify(b):undefined});
 if(!r.ok)alert(await r.text());load()}
async function load(){const d=await (await fetch('/api/experience')).json();
 st.textContent=JSON.stringify(d.stats);
 t.innerHTML='<tr><th>kind<th>apps<th>conf<th>hits<th>text<th>';
 for(const e of d.entries){const tr=t.insertRow();tr.className=e.enabled?'':'off';
  for(const v of [e.kind,e.apps,(+e.confidence).toFixed(2),e.hit_count,e.text])tr.insertCell().textContent=v;
  const c=tr.insertCell();
  c.innerHTML='<button>'+(e.enabled?'disable':'enable')+'</button><button>edit</button><button>delete</button>';
  const [b1,b2,b3]=c.children;
  b1.onclick=()=>post('/api/experience/'+e.id+'/enabled',{enabled:!e.enabled});
  b2.onclick=()=>{const x=prompt('Edit',e.text);if(x)post('/api/experience/'+e.id+'/edit',{text:x})};
  b3.onclick=()=>confirm('Delete?')&&post('/api/experience/'+e.id,null,'DELETE');}}
function lim(){const n=prompt('max entries per memory',300);if(n)post('/api/experience/limits',{max_entries:+n})}
load()</script>"""


@router.get("/experience", response_class=HTMLResponse)
def page() -> str:
    return _PAGE
