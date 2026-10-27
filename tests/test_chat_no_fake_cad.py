"""Chat must not invent FreeCAD / Desktop file side effects."""

from __future__ import annotations

from friday.assistant.reply_guard import claims_unbacked_pc_action


def test_detects_fake_desktop_fcstd_claims():
    assert claims_unbacked_pc_action("I've created the FCStd on your desktop.")
    assert claims_unbacked_pc_action("I saved the model to the Desktop for you.")
    assert claims_unbacked_pc_action("Opened FreeCAD and built the part, then saved it.")


def test_allows_honest_offers():
    assert not claims_unbacked_pc_action("I can build that in FreeCAD if you want.")
    assert not claims_unbacked_pc_action("Say the sizes and I'll run the CAD skill.")
