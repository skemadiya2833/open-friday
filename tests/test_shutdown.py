"""Ctrl+C must stop Friday even when the tray owns the main thread."""

from __future__ import annotations

from friday import shutdown as S


def setup_function() -> None:
    S.reset_for_tests()
    S._grace_s = 0


def teardown_function() -> None:
    S.reset_for_tests()


def test_console_c_and_close_are_owned():
    died: list[int] = []
    S._exit_fn = died.append
    assert S.handle_console_event(S.CTRL_C_EVENT) is True
    assert died == [0]
    S.reset_for_tests()
    S._grace_s = 0
    S._exit_fn = died.append
    died.clear()
    assert S.handle_console_event(S.CTRL_CLOSE_EVENT) is True
    assert died == [0]


def test_other_console_events_are_ignored():
    died: list[int] = []
    S._exit_fn = died.append
    assert S.handle_console_event(5) is False  # CTRL_LOGOFF
    assert died == []


def test_second_stop_exits_immediately():
    died: list[int] = []
    stopped: list[int] = []
    S._on_stop = lambda: stopped.append(1)
    S._exit_fn = died.append
    S.request_stop(0, delay=0)
    S.request_stop(1, delay=10)
    assert stopped == [1]
    assert died == [0, 1]


def test_install_ctrl_c_is_idempotent(monkeypatch):
    bound: list[int] = []
    monkeypatch.setattr(S, "_bind_console_handler", lambda: bound.append(1))
    S.install_ctrl_c(exit_fn=lambda _c: None)
    S.install_ctrl_c(exit_fn=lambda _c: None)
    assert S._installed is True
    assert bound == [1]
