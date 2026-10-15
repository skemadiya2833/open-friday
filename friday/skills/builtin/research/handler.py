"""Research skill — short briefing or structured report pipeline."""

from __future__ import annotations

import re

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_REPORT = re.compile(
    r"\b(research report|deep research|full report|structured report|"
    r"write (me )?a report|think (through|about)|compare .+ (vs|versus|and))\b",
    re.I,
)
_OPEN = re.compile(r"\bopen (the |my )?(research )?report\b", re.I)


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="research",
        name="Research",
        description="Web research and structured reports",
        tools=["web_search", "memory_search"],
        system_overlay=(
            "You look things up for the owner. Call web_search ONCE with a precise query. "
            "The observation is the actual results — titles and snippets. Then output FINAL: "
            "as a short briefing of what you found (what happened, who, when). "
            "Never search the same query twice. Never mention tabs or Google. "
            "If results are empty, say so in FINAL:; do not keep searching."
        ),
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        msg = ctx.message or ""
        try:
            from friday.runtime.blackout import blocks_research
            from friday.persona import owner_name

            if blocks_research():
                return SkillResult(
                    reply=(
                        f"Blackout is on, {owner_name()} — web research is paused. "
                        "Turn it off in Systems → Safety, or ask me something I can answer from local memory."
                    ),
                    skill_id="research",
                    metadata={"blackout": True},
                )
        except Exception:  # noqa: BLE001
            pass
        if _OPEN.search(msg):
            from friday.reports.store import list_reports

            rows = list_reports(limit=1)
            if not rows:
                return SkillResult(
                    reply="I don't have a report on file yet. Ask me to research something first.",
                    skill_id="research",
                    metadata={"open_report": None},
                )
            rid = rows[0]["id"]
            return SkillResult(
                reply="Opening the latest report on screen.",
                skill_id="research",
                metadata={"open_report": rid},
            )

        # Visual / reference hunts → quick HTML brief (search + gallery), not chat theater.
        want_refs = bool(
            re.search(
                r"\b(references?|inspiration|examples?|mood ?boards?|design\s+refs?)\b",
                msg,
                re.I,
            )
        )
        want_report = (
            bool(_REPORT.search(msg))
            or want_refs
            or (ctx.metadata or {}).get("report_mode")
        )
        mode = "quick"
        if re.search(r"\bdeep\b", msg, re.I):
            mode = "deep"
        if re.search(r"\bthink\b", msg, re.I) and not re.search(r"\bdeep\b", msg, re.I):
            mode = "think"
        if want_report:
            from friday.humor import maybe_append_quip
            from friday.persona import owner_name
            from friday.reports.pipeline import run_research_report

            def _emit(typ: str, payload=None, **kw):
                data = dict(payload or {})
                data.update(kw)
                ctx.emit(f"report_{typ}", data)  # type: ignore[arg-type]

            doc = run_research_report(msg, mode=mode, emit=_emit)
            tldr = (doc.get("summary") or {}).get("tldr") or "Report ready."
            spoken = (
                f"{tldr} The full report is on screen, {owner_name()}."
            )
            spoken = maybe_append_quip(
                spoken,
                user_text=msg,
                is_error=bool(doc.get("fallback_plain")),
                is_security=False,
            )
            return SkillResult(
                reply=spoken,
                skill_id="research",
                metadata={
                    "report_id": doc.get("id"),
                    "mode": mode,
                    "fallback_plain": bool(doc.get("fallback_plain")),
                    "open_report": doc.get("id"),
                    "claims": len(doc.get("claims") or []),
                },
            )

        from friday.tools.react import run_react

        reply, meta = run_react(
            ctx.message,
            allowed_tools=self.manifest.tools or ["web_search", "memory_search"],
            system_overlay=self.manifest.system_overlay,
            history=ctx.history,
            emit=ctx.emit,
        )
        return SkillResult(reply=reply, skill_id="research", metadata=meta)
