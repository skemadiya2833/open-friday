import json
import logging
import os

import pytest

from friday import diagnostics as D
from friday.atomic import write_text_atomic
from friday.logs import JsonFormatter
from friday.ui.events import current_run_id


def _errs(env):
    return {i.key for i in D.validate_config(env) if i.level == "error"}


def test_valid_default_config_has_no_errors():
    assert _errs({}) == set()


@pytest.mark.parametrize("env,key", [
    ({"FRIDAY_PORT": "abc"}, "FRIDAY_PORT"),
    ({"FRIDAY_PORT": "70000"}, "FRIDAY_PORT"),
    ({"VOICE_ENABLED": "maybe"}, "VOICE_ENABLED"),
    ({"CLOUD_PROVIDER": "bing"}, "CLOUD_PROVIDER"),
    ({"AGENT_BACKEND": "magic"}, "AGENT_BACKEND"),
    ({"OLLAMA_HOST": "localhost:11434"}, "OLLAMA_HOST"),
    ({"FRIDAY_HOST": "0.0.0.0"}, "FRIDAY_HOST"),
])
def test_invalid_values_give_clear_errors(env, key):
    assert key in _errs(env)
    assert all(str(i) for i in D.validate_config(env))


def test_nonloopback_with_token_is_ok_and_short_token_warns():
    iss = D.validate_config({"FRIDAY_HOST": "0.0.0.0", "FRIDAY_API_TOKEN": "short"})
    assert not [i for i in iss if i.level == "error"]
    assert any(i.key == "FRIDAY_API_TOKEN" and i.level == "warn" for i in iss)


def test_enforce_exits_on_error_but_not_warning(capsys):
    with pytest.raises(SystemExit):
        D.enforce(D.validate_config({"FRIDAY_PORT": "x"}))
    D.enforce(D.validate_config({"CLOUD_PROVIDER": "gemini"}))   # missing key = warning only


def test_atomic_write_replaces_and_leaves_no_temp(tmp_path):
    p = tmp_path / "s.json"
    write_text_atomic(p, "one")
    write_text_atomic(p, "two")
    assert p.read_text() == "two" and [x.name for x in tmp_path.iterdir()] == ["s.json"]


def test_atomic_write_failure_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    write_text_atomic(p, "old")
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        write_text_atomic(p, "new")
    monkeypatch.undo()
    assert p.read_text() == "old" and [x.name for x in tmp_path.iterdir()] == ["s.json"]


def test_json_log_carries_run_id_and_redacts():
    tok = current_run_id.set("run-123")
    try:
        rec = logging.LogRecord("friday.x", logging.INFO, "f", 1, "key sk-abcdefghijklmnopqrstuvwxyz0123456789", None, None)
        out = json.loads(JsonFormatter().format(rec))
    finally:
        current_run_id.reset(tok)
    assert out["run_id"] == "run-123" and out["level"] == "INFO"
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in out["msg"]


def test_health_report_never_raises(isolated):
    rep = D.health_report(probe_ollama=False)
    assert "ok" in rep and "audit" in rep and "estop" in rep
    json.dumps(rep, default=str)
