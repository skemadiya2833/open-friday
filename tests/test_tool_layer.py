"""Tool layer v2: sandbox, schema validation, policy, approvals, audit, shell."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import pytest

from friday.safety.audit import AuditLog
from friday.safety.policy import Policy, PolicyError
from friday.safety.redact import REDACTED, redact
from friday.tools.paths import PathEscapeError, resolve_within
from friday.tools.registry import ToolRegistry, get_registry
from friday.tools.types import ToolResult, ToolRisk, ToolSpec, object_schema


# --------------------------------------------------------------------------- paths
class TestSandbox:
    def test_sibling_prefix_escape_is_blocked(self, tmp_path):
        """Regression for the old startswith() check."""
        root = tmp_path / "workspace"
        root.mkdir()
        (tmp_path / "workspace_evil").mkdir()
        with pytest.raises(PathEscapeError):
            resolve_within(root, "../workspace_evil/secret.txt")

    @pytest.mark.parametrize("bad", ["../x", "a/../../x", "..\\x", "/etc/passwd", "\\Windows\\win.ini"])
    def test_traversal_and_absolute(self, tmp_path, bad):
        with pytest.raises(PathEscapeError):
            resolve_within(tmp_path, bad)

    @pytest.mark.parametrize("bad", ["C:\\Windows\\win.ini", "D:secret.txt", "c:foo", "\\\\server\\share\\x", "//server/share/x"])
    def test_drive_letter_and_unc_tricks(self, tmp_path, bad):
        with pytest.raises(PathEscapeError):
            resolve_within(tmp_path, bad)

    @pytest.mark.parametrize("bad", ["file.txt:hidden", "CON", "nul.txt", "sub/COM1", "LPT3.log", "a\x00b"])
    def test_streams_devices_nul(self, tmp_path, bad):
        with pytest.raises(PathEscapeError):
            resolve_within(tmp_path, bad)

    def test_inside_paths_ok(self, tmp_path):
        assert resolve_within(tmp_path, "a/b/c.txt") == (tmp_path.resolve() / "a" / "b" / "c.txt")
        assert resolve_within(tmp_path, ".") == tmp_path.resolve()
        assert resolve_within(tmp_path, "a/../b.txt") == (tmp_path.resolve() / "b.txt")

    @pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
    def test_junction_pointing_outside_is_blocked(self, tmp_path):
        root = tmp_path / "ws"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        (outside / "secret.txt").write_text("x")
        link = root / "link"
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True)
        if proc.returncode != 0:
            pytest.skip(f"cannot create junction: {proc.stderr.strip()}")
        with pytest.raises(PathEscapeError):
            resolve_within(root, "link/secret.txt")
        with pytest.raises(PathEscapeError):
            resolve_within(root, "link/new_file.txt")

    def test_symlink_pointing_outside_is_blocked(self, tmp_path):
        root = tmp_path / "ws"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        try:
            os.symlink(outside, root / "sl", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not permitted (needs Developer Mode/admin)")
        with pytest.raises(PathEscapeError):
            resolve_within(root, "sl/x.txt")

    def test_read_write_tools_use_the_fix(self, isolated):
        sibling = isolated.workspace.parent / "workspace_evil"
        sibling.mkdir()
        (sibling / "secret.txt").write_text("TOP SECRET")
        reg = get_registry()
        res = reg.call("read_file", {"path": "../workspace_evil/secret.txt"})
        assert res.is_error and "TOP SECRET" not in res.text()
        res = reg.call("write_file", {"path": "../workspace_evil/pwn.txt", "content": "x"})
        assert not (sibling / "pwn.txt").exists()


# --------------------------------------------------------------------------- redaction
def test_redaction_masks_keys_and_values():
    data = {
        "api_key": "abc",
        "nested": {"Authorization": "Bearer abcdefgh12345678", "note": "token=zzz123 ok"},
        "text": "my key sk-ABCDEFGHIJKLMNOPQRSTUV is here",
    }
    out = redact(data)
    assert out["api_key"] == REDACTED
    assert out["nested"]["Authorization"] == REDACTED
    assert "zzz123" not in out["nested"]["note"]
    assert "sk-ABCDEF" not in out["text"]


# --------------------------------------------------------------------------- registry
def _echo_spec(name="echo", risk=ToolRisk.SAFE, source="builtin"):
    return ToolSpec(
        name, "echo", object_schema({"msg": {"type": "string"}}, ["msg"]),
        lambda a: ToolResult.text_result(a["msg"]), risk, source,
    )


class TestRegistry:
    def test_schema_validation_rejects_bad_args(self, isolated):
        reg = get_registry()
        res = reg.call("memory_search", {"query": "x", "limit": 9999})
        assert res.is_error and "Invalid arguments" in res.text()
        res = reg.call("read_file", {})
        assert res.is_error and "path" in res.text()
        res = reg.call("read_file", {"path": "a.txt", "extra": 1})
        assert res.is_error  # additionalProperties false

    def test_unknown_tool(self, isolated):
        assert get_registry().call("nope", {}).is_error

    def test_runtime_register_unregister(self, isolated):
        reg = ToolRegistry()
        v0 = reg.version
        reg.register(_echo_spec("a", source="mcp:x"))
        reg.register(_echo_spec("b", source="mcp:x"))
        assert reg.version > v0
        with pytest.raises(ValueError):
            reg.register(_echo_spec("a"))
        assert reg.unregister_source("mcp:x") == 2
        assert reg.get("a") is None

    def test_registry_is_thread_safe(self, isolated):
        reg = ToolRegistry()
        errors: list[Exception] = []

        def worker(i: int) -> None:
            try:
                for j in range(50):
                    n = f"t{i}_{j}"
                    reg.register(_echo_spec(n, source=f"s{i}"))
                    reg.list()
                    reg.unregister(n)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert not errors and reg.list() == []

    def test_structured_and_images_roundtrip(self):
        r = ToolResult(content=[{"type": "text", "text": "hi"}, {"type": "image", "data": "AAAA", "mime": "image/png"}])
        assert "1 image" in r.text() and r.images()[0]["mime"] == "image/png"
        assert r.to_dict()["content"][1]["bytes_b64"] == 4

    def test_handler_exception_becomes_error_result(self, isolated):
        reg = ToolRegistry()
        reg.register(ToolSpec("boom", "x", object_schema(), lambda a: 1 / 0, ToolRisk.SAFE))
        from friday.tools import registry as r

        r._registry = reg
        res = reg.call("boom", {})
        assert res.is_error and "division" in res.text()


# --------------------------------------------------------------------------- policy + approval
class TestPolicyAndApproval:
    def _registry_with(self, spec):
        reg = ToolRegistry()
        reg.register(spec)
        return reg

    def test_safe_runs_without_approval(self, isolated):
        reg = self._registry_with(_echo_spec("e", ToolRisk.SAFE))
        assert reg.call("e", {"msg": "hi"}).text() == "hi"
        rec = isolated.audit.tail(1)[0]
        assert rec["outcome"] == "ok" and rec["approver"] == "policy:allow"

    def test_confirm_denied_when_no_responder(self, isolated):
        reg = self._registry_with(_echo_spec("c", ToolRisk.CONFIRM))
        res = reg.call("c", {"msg": "hi"})
        assert res.is_error and res.metadata.get("denied")
        assert isolated.audit.tail(1)[0]["approver"] == "denied:no-responder"

    def test_confirm_approved_by_user(self, isolated):
        isolated.approvals.set_responders(1)
        reg = self._registry_with(_echo_spec("c", ToolRisk.CONFIRM))
        out: list[ToolResult] = []
        t = threading.Thread(target=lambda: out.append(reg.call("c", {"msg": "hi"})))
        t.start()
        for _ in range(100):
            pend = isolated.approvals.list_pending()
            if pend:
                break
            time.sleep(0.02)
        assert pend and pend[0]["tool"] == "c"
        assert isolated.approvals.resolve(pend[0]["id"], True, "tester")
        t.join(5)
        assert out and out[0].text() == "hi"
        rec = isolated.audit.tail(1)[0]
        assert rec["approver"] == "user:tester" and rec["outcome"] == "ok"

    def test_confirm_denied_by_user(self, isolated):
        isolated.approvals.set_responders(1)
        reg = self._registry_with(_echo_spec("c", ToolRisk.CONFIRM))
        out: list[ToolResult] = []
        t = threading.Thread(target=lambda: out.append(reg.call("c", {"msg": "hi"})))
        t.start()
        for _ in range(100):
            pend = isolated.approvals.list_pending()
            if pend:
                break
            time.sleep(0.02)
        isolated.approvals.resolve(pend[0]["id"], False, "tester")
        t.join(5)
        assert out[0].is_error and out[0].metadata.get("denied")
        assert isolated.audit.tail(1)[0]["outcome"] == "denied"

    def test_confirm_times_out_closed(self, isolated):
        isolated.approvals.default_timeout = 0.2
        isolated.approvals.set_responders(1)
        reg = self._registry_with(_echo_spec("c", ToolRisk.CONFIRM))
        res = reg.call("c", {"msg": "hi"})
        assert res.is_error
        assert isolated.audit.tail(1)[0]["approver"] == "denied:timeout"

    def test_dangerous_denied_by_default(self, isolated):
        reg = self._registry_with(_echo_spec("d", ToolRisk.DANGEROUS))
        assert reg.call("d", {"msg": "x"}).metadata.get("denied")

    def test_policy_override_allows_confirm_tool(self, isolated):
        from friday.safety.policy import set_policy

        set_policy(Policy.from_dict({"tools": {"c": "allow"}}))
        reg = self._registry_with(_echo_spec("c", ToolRisk.CONFIRM))
        assert reg.call("c", {"msg": "yo"}).text() == "yo"

    def test_policy_rejects_bad_values(self):
        with pytest.raises(PolicyError):
            Policy.from_dict({"tiers": {"safe": "maybe"}})
        with pytest.raises(PolicyError):
            Policy.from_dict({"tiers": {"nope": "allow"}})
        with pytest.raises(PolicyError):
            Policy.from_dict({"shell": {"mode": "yolo"}})
        with pytest.raises(PolicyError):
            Policy.from_dict({"shell": {"allowlist": ["("]}})

    def test_shipped_policy_file_is_valid(self):
        from friday.safety.policy import load_policy

        p = load_policy()
        assert p.tiers["dangerous"] == "deny" and p.tools.get("write_file") == "allow"

    def test_run_shell_never_allowed_by_yaml_typo(self, isolated):
        pol = Policy.from_dict({"tools": {"run_shell": "allow"}})
        d = pol.decide("run_shell", ToolRisk.DANGEROUS, shell_enabled=True)
        assert d.action == "ask"
        assert pol.decide("run_shell", ToolRisk.DANGEROUS, shell_enabled=False).action == "deny"


# --------------------------------------------------------------------------- audit
class TestAudit:
    def test_chain_verifies_and_redacts(self, tmp_path):
        log = AuditLog(tmp_path / "a.jsonl")
        log.record(tool="t", args={"password": "hunter2", "q": "ok"}, outcome="ok", approver="policy:allow", risk="safe")
        log.record(tool="t2", args={}, outcome="denied", approver="denied:user:me", risk="confirm")
        ok, msg = log.verify()
        assert ok, msg
        raw = (tmp_path / "a.jsonl").read_text()
        assert "hunter2" not in raw

    def test_tampering_is_detected(self, tmp_path):
        log = AuditLog(tmp_path / "a.jsonl")
        for i in range(3):
            log.record(tool=f"t{i}", args={}, outcome="ok", approver="policy:allow", risk="safe")
        p = tmp_path / "a.jsonl"
        lines = p.read_text().splitlines()
        lines[1] = lines[1].replace('"t1"', '"tX"')
        p.write_text("\n".join(lines) + "\n")
        ok, msg = AuditLog(p).verify()
        assert not ok and "altered" in msg

    def test_deleted_middle_line_detected(self, tmp_path):
        log = AuditLog(tmp_path / "a.jsonl")
        for i in range(3):
            log.record(tool=f"t{i}", args={}, outcome="ok", approver="policy:allow", risk="safe")
        p = tmp_path / "a.jsonl"
        lines = p.read_text().splitlines()
        del lines[1]
        p.write_text("\n".join(lines) + "\n")
        ok, msg = AuditLog(p).verify()
        assert not ok and "chain" in msg

    def test_survives_restart_and_torn_line(self, tmp_path):
        p = tmp_path / "a.jsonl"
        log = AuditLog(p)
        log.record(tool="a", args={}, outcome="ok", approver="x", risk="safe")
        with p.open("a") as fh:
            fh.write('{"torn": ')  # crash mid-write, no newline
        log2 = AuditLog(p)  # must not raise
        log2.record(tool="b", args={}, outcome="ok", approver="x", risk="safe")
        assert any(r.get("tool") == "b" for r in log2.iter_records())

    def test_concurrent_writers_keep_chain(self, tmp_path):
        log = AuditLog(tmp_path / "a.jsonl")

        def w(i):
            for j in range(20):
                log.record(tool=f"w{i}", args={"j": j}, outcome="ok", approver="x", risk="safe")

        ts = [threading.Thread(target=w, args=(i,)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert log.verify()[0]


# --------------------------------------------------------------------------- shell
@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell runner is Windows-specific")
class TestShell:
    def test_disabled_by_default(self, isolated, monkeypatch):
        import friday.tools.registry as r

        monkeypatch.setattr(r, "_shell_enabled", lambda: False)
        res = get_registry().call("run_shell", {"command": "Write-Output hi"})
        assert res.metadata.get("denied")

    def test_allowlisted_command_runs_without_prompt(self, isolated, monkeypatch):
        import friday.tools.registry as r
        from friday.safety.policy import set_policy

        monkeypatch.setattr(r, "_shell_enabled", lambda: True)
        set_policy(Policy.from_dict({"shell": {"mode": "allowlist", "allowlist": ["Write-Output hello"]}}))
        res = get_registry().call("run_shell", {"command": "Write-Output hello"})
        assert not res.is_error and "hello" in res.text()
        assert isolated.audit.tail(1)[0]["approver"] == "policy:allowlist"

    def test_non_allowlisted_needs_approval(self, isolated, monkeypatch):
        import friday.tools.registry as r
        from friday.safety.policy import set_policy

        monkeypatch.setattr(r, "_shell_enabled", lambda: True)
        set_policy(Policy.from_dict({"shell": {"mode": "allowlist", "allowlist": ["Write-Output hello"]}}))
        res = get_registry().call("run_shell", {"command": "Write-Output other"})
        assert res.metadata.get("denied")  # no responder -> fail closed

    def test_cwd_cannot_escape_and_timeout_kills(self, isolated, monkeypatch):
        import friday.tools.registry as r
        from friday.safety.policy import set_policy

        monkeypatch.setattr(r, "_shell_enabled", lambda: True)
        set_policy(Policy.from_dict({"shell": {"mode": "allowlist", "allowlist": [".*"], "timeout_seconds": 1, "max_timeout_seconds": 2}}))
        res = get_registry().call("run_shell", {"command": "Get-Location", "cwd": ".."})
        assert res.is_error and "Invalid cwd" in res.text()
        t0 = time.time()
        res = get_registry().call("run_shell", {"command": "Start-Sleep -Seconds 20"})
        assert res.metadata.get("timed_out") and time.time() - t0 < 10

    def test_output_secrets_redacted(self, isolated, monkeypatch):
        import friday.tools.registry as r
        from friday.safety.policy import set_policy

        monkeypatch.setattr(r, "_shell_enabled", lambda: True)
        set_policy(Policy.from_dict({"shell": {"mode": "allowlist", "allowlist": [".*"]}}))
        res = get_registry().call("run_shell", {"command": "Write-Output 'password=hunter2'"})
        assert "hunter2" not in res.text()
