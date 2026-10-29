"""Schedule listing vs plan-my-day routing."""

from __future__ import annotations

from friday.skills.builtin.tasks.handler import _LIST_TODAY, _PLAN_DAY
from friday.tasks.day_plan import is_meta_plan_request, is_schedule_list_request


def test_what_on_schedule_is_list_not_meta():
    msg = "What do we have on schedule today"
    assert is_schedule_list_request(msg)
    assert not is_meta_plan_request(msg)
    assert _LIST_TODAY.search(msg)
    assert not _PLAN_DAY.search(msg)


def test_plan_my_day_still_meta():
    msg = "help me plan my day"
    assert is_meta_plan_request(msg)
    assert not is_schedule_list_request(msg)
    assert _PLAN_DAY.search(msg)


def test_schedule_my_day_is_meta():
    msg = "schedule my day"
    assert is_meta_plan_request(msg)
    assert not is_schedule_list_request(msg)
