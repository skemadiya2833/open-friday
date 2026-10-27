"""CAD / Taiga-S1 skill — planning and routing without FreeCAD."""

from __future__ import annotations

import json
from pathlib import Path

from friday.cad.planner import _coerce_goal, _heuristic_plan
from friday.cad.schema import Goal, GoalFeature, estimate_target, validate_goal
from friday.skills.agentskills import split_frontmatter, validate_frontmatter


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "skills" / "builtin-playbooks" / "freecad-taiga" / "SKILL.md"


def test_goal_validation_and_estimate():
    g = estimate_target(
        Goal(features=[
            GoalFeature("base_box", {"w": 40, "d": 30, "h": 10}),
            GoalFeature("hole", {"r": 3, "x": 10, "y": 0}),
            GoalFeature("fillet_top", {"r": 1}),
        ])
    )
    assert validate_goal(g) == []
    assert g.scale >= 40
    assert g.target.volume > 0
    assert "plate" in g.summarize()


def test_goal_rejects_bad_first_feature():
    g = Goal(features=[GoalFeature("hole", {"r": 3, "x": 0, "y": 0})])
    errs = validate_goal(g)
    assert errs and "base" in errs[0]


def test_heuristic_plate_with_hole_and_fillet():
    plan = _heuristic_plan("Make a 40x30x10 plate with a 6mm hole and fillet the top 1mm")
    assert plan is not None and plan.goal is not None
    kinds = [f.kind for f in plan.goal.features]
    assert kinds[0] == "base_box"
    assert "hole" in kinds
    assert "fillet_top" in kinds
    assert plan.goal.features[0].params["w"] == 40.0


def test_coerce_clarify():
    got = _coerce_goal({"clarify": "How thick should the plate be?", "features": []})
    assert got.goal is None
    assert got.clarify and "thick" in got.clarify.lower()


def test_coerce_valid_llm_payload():
    got = _coerce_goal({
        "clarify": None,
        "features": [
            {"kind": "base_cyl", "params": {"r": 20, "h": 8}},
            {"kind": "hole", "params": {"r": 3, "x": 10, "y": 0}},
            {"kind": "polar_pattern", "params": {"n": 6}},
        ],
    })
    assert got.goal is not None
    assert len(got.goal.features) == 3
    assert "polar" in got.summary.lower()


def test_intent_routes_freecad_to_cad():
    from friday.assistant import intent as intent_mod

    for msg in (
        "In FreeCAD build a 40x30x10 plate with a 6mm hole",
        "taiga status",
        "model a bracket in freecad with fillets",
        "design a cad part plate 50x40x5 mm with fillet",
        "how about we make a 3d model of a 40x30x10 plate, assume a 6mm hole and a small fillet",
        "let's make a 3d model for a bracket about 60mm wide",
        "make a 40x30x10 plate with a hole",
        "can we model a cylinder 30mm diameter 10mm tall",
        "make a cube",
        "create a freecad file on my desktop",
        "save an fcstd to the desktop",
        "how about a 3d model of a box",
    ):
        got = intent_mod._deterministic_intent(msg)
        assert got is not None, msg
        assert got.skill_id == "cad", msg
        assert got.mode == "cad", msg


def test_intent_does_not_steal_filament_research():
    from friday.assistant import intent as intent_mod

    # Must not match CAD; may be None (LLM) or research via other rules.
    got = intent_mod._deterministic_intent("best filament for outdoor 3d prints")
    assert got is None or got.skill_id != "cad"


def test_cad_skill_loads():
    from friday.skills.registry import SkillRegistry

    reg = SkillRegistry()
    skill = reg.get("cad")
    assert skill is not None
    assert skill.manifest.id == "cad"


def test_cad_status_reply(monkeypatch, tmp_path):
    import friday.runtime.prefs as prefs
    from friday.cad.status import CadStatus
    from friday.skills.base import SkillContext
    from friday.skills.builtin.cad.handler import SkillHandler

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({"cad_enabled": False})

    fake = CadStatus(
        enabled=False,
        freecad_install=r"C:\Program Files\FreeCAD 1.1",
        freecad_found=True,
        repo_ok=False,
        repo_path=None,
        socket_ok=False,
        port=8765,
        model="shhivv/taiga-s1",
        freecad_s1_importable=False,
        worker_python=None,
        worker_found=False,
        ready_to_build=False,
        blockers=["CAD is off"],
        can_auto_setup=True,
        can_launch=False,
    )
    monkeypatch.setattr("friday.cad.status.probe_status", lambda: fake)

    skill = SkillHandler()
    result = skill.run(SkillContext(message="cad status", session_id="t"))
    assert result.skill_id == "cad"
    assert "ready" in result.reply.lower() or "off" in result.reply.lower() or "CAD" in result.reply


def test_cad_plans_and_builds_when_ready(monkeypatch, tmp_path):
    import friday.runtime.prefs as prefs
    from friday.cad.ready import ReadyResult
    from friday.cad.runner import BuildResult
    from friday.cad.schema import Goal, GoalFeature, estimate_target
    from friday.skills.base import SkillContext
    from friday.skills.builtin.cad.handler import SkillHandler

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({"cad_enabled": True, "freecad_install": r"C:\Program Files\FreeCAD 1.1"})
    monkeypatch.setattr("friday.config.WORKSPACE_DIR", str(tmp_path))

    fake_goal = estimate_target(Goal(features=[
        GoalFeature("base_box", {"w": 40, "d": 30, "h": 10}),
    ]))

    class FakePlan:
        goal = fake_goal
        summary = fake_goal.summarize()
        clarify = None
        raw = {"source": "test"}
        error = None

    monkeypatch.setattr("friday.cad.planner.plan_goal", lambda *a, **k: FakePlan())
    monkeypatch.setattr(
        "friday.cad.ready.ensure_ready",
        lambda **k: ReadyResult(ok=True, message="ready", status={"ready_to_build": True}),
    )
    monkeypatch.setattr(
        "friday.cad.runner.build_part",
        lambda *a, **k: BuildResult(
            ok=True,
            message="ok",
            steps=12,
            iou=0.99,
            fcstd=str(tmp_path / "cad" / "part.FCStd"),
            goal_summary=fake_goal.summarize(),
        ),
    )

    skill = SkillHandler()
    result = skill.run(SkillContext(
        message="how about we make a 3d model of a 40x30x10 plate, assume a hole",
        session_id="t",
    ))
    assert result.metadata.get("planned") is True
    assert result.metadata.get("built") is True
    assert "Built" in result.reply or "40" in result.reply
    goals = list(Path(tmp_path).joinpath("cad").glob("*.goal.json"))
    assert goals
    data = json.loads(goals[0].read_text(encoding="utf-8"))
    assert data["features"][0]["kind"] == "base_box"


def test_cad_reports_when_ready_fails(monkeypatch, tmp_path):
    import friday.runtime.prefs as prefs
    from friday.cad.ready import ReadyResult
    from friday.cad.schema import Goal, GoalFeature, estimate_target
    from friday.skills.base import SkillContext
    from friday.skills.builtin.cad.handler import SkillHandler

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    monkeypatch.setattr("friday.config.WORKSPACE_DIR", str(tmp_path))
    fake_goal = estimate_target(Goal(features=[GoalFeature("base_box", {"w": 40, "d": 30, "h": 10})]))

    class FakePlan:
        goal = fake_goal
        summary = fake_goal.summarize()
        clarify = None
        raw = {}
        error = None

    monkeypatch.setattr("friday.cad.planner.plan_goal", lambda *a, **k: FakePlan())
    monkeypatch.setattr(
        "friday.cad.ready.ensure_ready",
        lambda **k: ReadyResult(ok=False, message="socket cold", status={}),
    )

    result = SkillHandler().run(SkillContext(message="make a 40x30x10 plate", session_id="t"))
    assert result.metadata.get("planned") is True
    assert result.metadata.get("built") is False
    assert "socket cold" in result.reply


def test_playbook_skill_md_parses():
    text = PLAYBOOK.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    errs = validate_frontmatter(fm, PLAYBOOK.parent.name)
    assert errs == []
    assert "Taiga" in body or "taiga" in body.lower()
