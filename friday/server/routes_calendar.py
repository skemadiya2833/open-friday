"""Calendar API — secret iCal URL, agenda, free slots, create preview/open."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["calendar"])


class SecretBody(BaseModel):
    url: str = Field(..., min_length=8)


class FreeSlotsBody(BaseModel):
    day: str = Field(..., description="ISO date YYYY-MM-DD")
    duration_min: int = Field(30, ge=5, le=480)


class CreatePreviewBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    start: str = Field(..., description="ISO datetime")
    end: str = Field(..., description="ISO datetime")
    details: str = ""
    location: str = ""
    guests: list[str] = Field(default_factory=list)
    all_day: bool = False
    ctz: str | None = None


def _parse_day(s: str) -> date:
    try:
        return date.fromisoformat(s[:10])
    except ValueError as exc:
        raise HTTPException(400, "Invalid day; use YYYY-MM-DD") from exc


def _parse_dt(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "Invalid datetime") from exc


@router.get("/api/calendar/secret")
def calendar_secret_get() -> dict[str, Any]:
    from friday.calendar.secrets import configured, redact_url, get_ical_url

    url = get_ical_url()
    return {
        "configured": configured(),
        "url_redacted": redact_url(url),
        "note": (
            "Editing or deleting existing events requires the Google Calendar API or browser automation; "
            "Friday only proposes new slots and opens Calendar views."
        ),
    }


@router.post("/api/calendar/secret")
def calendar_secret_set(body: SecretBody) -> dict[str, Any]:
    from friday.calendar.fetch import clear_cache
    from friday.calendar.secrets import redact_url, set_ical_url

    if not body.url.strip().lower().startswith(("http://", "https://")):
        raise HTTPException(400, "URL must be http(s)")
    set_ical_url(body.url.strip())
    clear_cache()
    return {"configured": True, "url_redacted": redact_url(body.url)}


@router.delete("/api/calendar/secret")
def calendar_secret_delete() -> dict[str, Any]:
    from friday.calendar.fetch import clear_cache
    from friday.calendar.secrets import clear_ical_url

    clear_ical_url()
    clear_cache()
    return {"configured": False}


@router.get("/api/calendar/agenda")
def calendar_agenda(range: Literal["today", "week"] = "today") -> dict[str, Any]:
    from friday.calendar import agenda as cal_agenda
    from friday.calendar.secrets import configured

    if not configured():
        raise HTTPException(400, "Calendar iCal URL is not configured")
    try:
        if range == "week":
            return cal_agenda.week_agenda()
        return cal_agenda.today_agenda()
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/api/calendar/next")
def calendar_next() -> dict[str, Any]:
    from friday.calendar import agenda as cal_agenda
    from friday.calendar.secrets import configured

    if not configured():
        raise HTTPException(400, "Calendar iCal URL is not configured")
    try:
        return cal_agenda.next_event()
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/api/calendar/free-slots")
def calendar_free_slots(body: FreeSlotsBody) -> dict[str, Any]:
    from friday.calendar import agenda as cal_agenda
    from friday.calendar.secrets import configured

    if not configured():
        raise HTTPException(400, "Calendar iCal URL is not configured")
    d = _parse_day(body.day)
    try:
        slots = cal_agenda.free_slots(d, body.duration_min)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"day": d.isoformat(), "duration_min": body.duration_min, "slots": slots}


@router.post("/api/calendar/create-preview")
def calendar_create_preview(body: CreatePreviewBody) -> dict[str, Any]:
    from friday.calendar.create import build_template_url

    start = _parse_dt(body.start)
    end = _parse_dt(body.end)
    if end <= start:
        raise HTTPException(400, "end must be after start")
    template_url = build_template_url(
        body.text,
        start,
        end,
        details=body.details,
        location=body.location,
        guests=body.guests,
        all_day=body.all_day,
        ctz=body.ctz,
    )
    preview = {
        "title": body.text,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": body.location or None,
        "details": body.details or None,
        "guests": body.guests,
        "all_day": body.all_day,
    }
    return {
        "preview": preview,
        "template_url": template_url,
        "note": "Confirm in browser; Friday does not auto-submit the event.",
    }


@router.post("/api/calendar/create-open")
def calendar_create_open(body: CreatePreviewBody) -> dict[str, Any]:
    from friday.calendar.create import build_template_url, open_in_chrome

    start = _parse_dt(body.start)
    end = _parse_dt(body.end)
    if end <= start:
        raise HTTPException(400, "end must be after start")
    template_url = build_template_url(
        body.text,
        start,
        end,
        details=body.details,
        location=body.location,
        guests=body.guests,
        all_day=body.all_day,
        ctz=body.ctz,
    )
    opened = open_in_chrome(template_url)
    return {
        "preview": {
            "title": body.text,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "template_url": template_url,
        "opened": opened,
        "note": "Complete save in Google Calendar; Friday did not auto-submit.",
    }


@router.get("/api/calendar/open/{view}")
def calendar_open_view(view: Literal["day", "week", "agenda"]) -> dict[str, Any]:
    from friday.calendar.create import (
        google_calendar_agenda_url,
        google_calendar_day_url,
        google_calendar_week_url,
        open_in_chrome,
    )

    if view == "day":
        url = google_calendar_day_url()
    elif view == "week":
        url = google_calendar_week_url()
    else:
        url = google_calendar_agenda_url()
    opened = open_in_chrome(url)
    return {"view": view, "url": url, "opened": opened}


@router.get("/api/calendar/export.ics", response_class=PlainTextResponse)
def calendar_export_ics() -> str:
    from friday.calendar.fetch import cached_body, fetch_ical
    from friday.calendar.secrets import configured

    if not configured():
        raise HTTPException(400, "Calendar iCal URL is not configured")
    body = cached_body()
    if not body:
        try:
            body, _ = fetch_ical()
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc
    return body
