"""Assistant rhythm API — inbox, nudges, focus, decisions, EOD, weekly."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class InboxAdd(BaseModel):
    text: str


class NudgeConfigure(BaseModel):
    opt_in: bool | None = None
    quiet_start: int | None = Field(None, ge=0, le=23)
    quiet_end: int | None = Field(None, ge=0, le=23)
    daily_cap: int | None = Field(None, ge=0, le=20)


class DecisionRequest(BaseModel):
    question: str
    option_a: str
    option_b: str
    context: str = ""
    recommendation: str | None = None
    cost_of_delay: str | None = None
    needs_from_owner: list[str] | None = None


class FocusStart(BaseModel):
    minutes: int = Field(25, ge=5, le=180)
    label: str = ""


class ParkingLotAdd(BaseModel):
    text: str


class EodToggle(BaseModel):
    enabled: bool
    cron: str | None = None
    speak: bool | None = None


class WeeklyToggle(BaseModel):
    enabled: bool
    cron: str | None = None


class TomorrowAnchor(BaseModel):
    text: str


@router.get("/api/assistant/inbox")
def inbox_review(limit: int = 20) -> dict[str, Any]:
    from friday.assistant.inbox import review_summary

    return review_summary(limit=limit)


@router.post("/api/assistant/inbox")
def inbox_add(body: InboxAdd) -> dict[str, Any]:
    from friday.assistant.inbox import add

    try:
        return add(body.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/assistant/nudges")
def nudges_status() -> dict[str, Any]:
    from friday.assistant.nudges import status

    return status()


@router.post("/api/assistant/nudges")
def nudges_configure(body: NudgeConfigure) -> dict[str, Any]:
    from friday.assistant.nudges import configure

    return configure(
        opt_in=body.opt_in,
        quiet_start=body.quiet_start,
        quiet_end=body.quiet_end,
        daily_cap=body.daily_cap,
    )


@router.post("/api/assistant/nudges/snooze")
def nudges_snooze(minutes: int = 60) -> dict[str, Any]:
    from friday.assistant.nudges import snooze

    return snooze(minutes=minutes)


@router.post("/api/assistant/nudges/stop")
def nudges_stop(reason: str = "") -> dict[str, Any]:
    from friday.assistant.nudges import stop_suggesting

    return stop_suggesting(reason=reason)


@router.get("/api/assistant/nudges/may")
def nudges_may(reason: str = "check-in") -> dict[str, Any]:
    from friday.assistant.nudges import may_nudge

    return may_nudge(reason=reason)


@router.post("/api/assistant/decision")
def decision_build(body: DecisionRequest) -> dict[str, Any]:
    from friday.assistant.decision import build_decision

    try:
        return build_decision(
            question=body.question,
            option_a=body.option_a,
            option_b=body.option_b,
            context=body.context,
            recommendation=body.recommendation,
            cost_of_delay=body.cost_of_delay,
            needs_from_owner=body.needs_from_owner,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/assistant/focus")
def focus_get() -> dict[str, Any]:
    from friday.focus.session import focus_status, get_settings

    return {**get_settings(), **focus_status()}


@router.post("/api/assistant/focus/start")
def focus_start(body: FocusStart) -> dict[str, Any]:
    from friday.focus.session import start_focus

    return start_focus(minutes=body.minutes, label=body.label)


@router.post("/api/assistant/focus/stop")
def focus_stop() -> dict[str, Any]:
    from friday.focus.session import stop_focus

    return stop_focus()


@router.post("/api/assistant/focus/quiet")
def focus_quiet(enabled: bool = True) -> dict[str, Any]:
    from friday.focus.session import set_quiet_mode

    return set_quiet_mode(enabled)


@router.get("/api/assistant/focus/parking")
def focus_parking_list() -> list[dict[str, Any]]:
    from friday.focus.session import parking_lot_list

    return parking_lot_list()


@router.post("/api/assistant/focus/parking")
def focus_parking_add(body: ParkingLotAdd) -> dict[str, Any]:
    from friday.focus.session import parking_lot_add

    try:
        return parking_lot_add(body.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/briefing/eod")
def eod_status() -> dict[str, Any]:
    from friday.briefing.eod import status

    return status()


@router.post("/api/briefing/eod")
def eod_set(body: EodToggle) -> dict[str, Any]:
    from friday.briefing.eod import set_enabled

    return set_enabled(body.enabled, cron=body.cron, speak=body.speak)


@router.post("/api/briefing/eod/run")
def eod_run() -> dict[str, Any]:
    from friday.briefing.eod import run_eod_shutdown

    return run_eod_shutdown()


@router.post("/api/briefing/eod/tomorrow")
def eod_tomorrow(body: TomorrowAnchor) -> dict[str, Any]:
    from friday.briefing.eod import confirm_tomorrow_first

    return confirm_tomorrow_first(body.text)


@router.get("/api/briefing/weekly")
def weekly_status() -> dict[str, Any]:
    from friday.briefing.weekly import status

    return status()


@router.post("/api/briefing/weekly")
def weekly_set(body: WeeklyToggle) -> dict[str, Any]:
    from friday.briefing.weekly import set_enabled

    return set_enabled(body.enabled, cron=body.cron)


@router.post("/api/briefing/weekly/run")
def weekly_run() -> dict[str, Any]:
    from friday.briefing.weekly import run_weekly_review

    return run_weekly_review()
