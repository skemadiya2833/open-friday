"""Memory skill — RAG ingest / query via tools."""

from __future__ import annotations

import re

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_STORE = re.compile(
    r"(?i)^\s*(?:(?:hey|hi|okay|ok|uh|um)\s+)*(?:friday\s*[,:]?\s*)?"
    r"(?:please\s+)?"
    r"(?:remember\s+that|remember\s+this|don'?t\s+forget\s+(?:that|this)|"
    r"(?:store|save|note)\s+(?:this\s+|that\s+)?(?:in\s+)?(?:your\s+)?(?:memory|notes)|"
    r"(?:add|put)\s+(?:this\s+|that\s+)?(?:to|in)\s+(?:your\s+)?(?:memory|notes)|"
    r"make\s+a\s+note\s+(?:that|of))\s*[,:]?\s*(.+)$"
)
_RECALL_TOPIC = re.compile(
    r"(?i)\b(?:"
    r"what\s+do\s+you\s+(?:remember|know|have)\s+(?:about|on|regarding)\s+(.+?)(?:\?|$)|"
    r"do\s+you\s+remember\s+(.+?)(?:\?|$)|"
    r"(?:search|check|scan|look(?:\s+in)?|dig|query)\b.{0,40}\b(?:memory|memories|notes)\b"
    r"(?:\s+for|\s+about|\s+on)?\s*(.+?)(?:\?|$)|"
    r"(?:from|in)\s+(?:your\s+)?(?:memory|notes)\b(?:\s+about|\s+for|\s+on)?\s*(.+?)(?:\?|$)|"
    r"recall\s+(?:what\s+)?(?:you\s+know\s+about\s+)?(.+?)(?:\?|$)"
    r")"
)


def _direct_store(message: str) -> str | None:
    m = _STORE.search((message or "").strip())
    if not m:
        return None
    text = (m.group(1) or "").strip().rstrip(".!?")
    return text or None


def _direct_query(message: str) -> str | None:
    m = _RECALL_TOPIC.search((message or "").strip())
    if not m:
        # Whole utterance as query when it's clearly recall-shaped.
        from friday.assistant.intent import is_memory_utterance

        if is_memory_utterance(message) and not _STORE.search(message or ""):
            q = re.sub(
                r"(?i)^\s*(?:(?:hey|hi|okay|ok|uh|um)\s+)*(?:friday\s*[,:]?\s*)?"
                r"(?:please\s+)?(?:what\s+do\s+you\s+(?:remember|know|have)\s+(?:about|on)?|"
                r"do\s+you\s+remember|search\s+(?:your\s+)?memory\s+for|"
                r"check\s+(?:your\s+)?(?:memory|notes)\s+for)\s*",
                "",
                (message or "").strip(),
            )
            q = q.strip(" ?.!,")
            return q or (message or "").strip()
        return None
    for g in m.groups():
        if g and g.strip():
            return g.strip().rstrip(".!?")
    return (message or "").strip()


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="memory",
        name="Memory",
        description="Vector memory",
        tools=["memory_search", "memory_add", "memory_delete"],
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from friday.persona import owner_name

        # Fast path: store/search without a ReAct chat loop.
        store_text = _direct_store(ctx.message)
        if store_text:
            ctx.emit("activity", {"step": "memory", "message": "Storing note…"})
            from friday.store.facts import add_fact

            row = add_fact(store_text, source="voice", kind="note", mirror_chroma=True)
            reply = f"Got it, {owner_name()} — locked in: {store_text}"
            return SkillResult(
                reply=reply,
                skill_id="memory",
                metadata={"stored_id": row.get("id"), "fastpath": "store"},
            )

        query = _direct_query(ctx.message)
        if query:
            ctx.emit("activity", {"step": "memory", "message": "Searching memory…"})
            from friday.memory import get_memory

            hits = get_memory().search(query, collection="memories", limit=5)
            if not hits:
                reply = f"Nothing useful in memory on that, {owner_name()}."
            else:
                lines = [f"- {h.text[:220]}" for h in hits if (h.text or "").strip()]
                reply = (
                    f"From memory, {owner_name()}:\n" + "\n".join(lines[:4])
                    if not ctx.voice_mode
                    else f"From memory, {owner_name()}: " + "; ".join(
                        h.text[:120] for h in hits[:2] if (h.text or "").strip()
                    )
                )
            return SkillResult(
                reply=reply,
                skill_id="memory",
                metadata={"fastpath": "search", "hits": len(hits)},
            )

        from friday.prompts import overlay_memory
        from friday.tools.react import run_react

        overlay = (self.manifest.system_overlay or "").strip() + overlay_memory(
            owner_name()
        )
        reply, meta = run_react(
            ctx.message,
            allowed_tools=self.manifest.tools,
            system_overlay=overlay,
            history=ctx.history,
            emit=ctx.emit,
        )
        if not (reply or "").strip():
            reply = f"Nothing useful in memory on that, {owner_name()}."
        return SkillResult(reply=reply, skill_id="memory", metadata=meta)
