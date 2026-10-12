"""Stage V7: skill import scanning / trust tier enrichment."""

from __future__ import annotations

from friday.skills.skill_security import (
    TrustTier,
    classify_trust_tier,
    dangerous_from_tools,
    enrich_review,
)


def test_external_import_is_unreviewed():
    assert classify_trust_tier() == TrustTier.UNREVIEWED


def test_dangerous_shell_flagged():
    assert "run_shell" in dangerous_from_tools(["run_shell", "read_file"])


def test_enrich_never_auto_enables():
    r = enrich_review({"requests_tools": ["run_shell"], "runs_code": True, "notes": []})
    assert r["auto_enable"] is False
    assert r["requires_owner_approval"] is True
    assert r["trust_tier"] == "unreviewed"
    assert "scripts:present" in r["dangerous_capabilities"]
