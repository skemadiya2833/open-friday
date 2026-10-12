"""Local secrets pre-push scanner."""

from __future__ import annotations

from pathlib import Path

from scripts import pre_push_secrets_check as S


def test_forbidden_env_basename():
    assert S.path_forbidden(".env")
    assert S.path_forbidden("data/tls/lan.key")
    assert S.path_forbidden("data/audit/tool_calls.jsonl")
    assert S.path_forbidden(".env.example") is None


def test_detects_private_key_and_sk(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(S, "ROOT", tmp_path)
    (tmp_path / "leak.txt").write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n", encoding="utf-8")
    (tmp_path / "ok.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setattr(S, "list_files", lambda staged_only=False: [tmp_path / "leak.txt", tmp_path / "ok.txt"])
    assert S.main([]) == 1
    monkeypatch.setattr(S, "list_files", lambda staged_only=False: [tmp_path / "ok.txt"])
    assert S.main([]) == 0


def test_example_env_placeholders_are_ignored():
    text = "GEMINI_API_KEY=your_gemini_api_key_here\nOPENAI_API_KEY=your_openai_key_if_using_openai\n"
    assert S.scan_content(".env.example", text) == []


def test_real_looking_key_assignment_is_flagged():
    text = "GEMINI_API_KEY=AIzaSyFakeKeyValue1234567890abcd\n"
    assert "gemini_key_assign" in S.scan_content("config/local.env", text)
