"""Terminal-first routing: shell-shaped asks before vision GUI."""

from __future__ import annotations

from friday.agent.direct_tools import is_shell_first_candidate


def test_shell_first_positive():
    for msg in (
        "list files in the workspace",
        "git status",
        "show disk space",
        "run this in powershell: Get-Process",
        "what processes are using the most CPU",
        "install ripgrep with winget",
        "check my IP address",
    ):
        assert is_shell_first_candidate(msg), msg


def test_shell_first_skips_gui():
    for msg in (
        "click the Save button",
        "draw a circle in paint",
        "fill out the login form in Chrome",
        "open notepad and type hello",  # open app path — not shell-first detector's job
    ):
        assert not is_shell_first_candidate(msg), msg


def test_shell_first_skips_chatty():
    assert not is_shell_first_candidate("what do you think about rust")
    assert not is_shell_first_candidate("")
