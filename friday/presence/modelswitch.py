"""Voice/chat model switch — resolve aliases against installed Ollama tags."""

from __future__ import annotations

import re
from typing import Any

# Spoken aliases → substring match against installed tags (prefer multimodal / larger).
_ALIAS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("saluki", re.compile(r"(?i)^saluki")),
    ("gemma", re.compile(r"(?i)^gemma")),
    ("qwen", re.compile(r"(?i)^qwen")),
    ("llama", re.compile(r"(?i)^llama")),
    ("mistral", re.compile(r"(?i)^mistral")),
    ("phi", re.compile(r"(?i)^phi")),
    ("deepseek", re.compile(r"(?i)^deepseek")),
    ("codellama", re.compile(r"(?i)^codellama")),
    ("llava", re.compile(r"(?i)^llava")),
    ("minicpm", re.compile(r"(?i)^minicpm")),
]

_STOP_TOKENS = frozenset(
    {
        "friday",
        "jarvis",
        "ultron",
        "vision",
        "karen",
        "edith",
        "mode",
        "model",
        "models",
        "chat",
        "voice",
        "from",
        "into",
        "the",
        "a",
        "an",
        "my",
        "your",
        "local",
        "please",
        "coin",  # ASR junk before "qwen"
        "gamma",  # handled via normalize → gemma
        "when",  # handled via normalize → qwen in switch phrases
    }
)


def list_installed_tags() -> list[str]:
    from friday.config import OLLAMA_HOST

    try:
        import httpx

        r = httpx.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=5.0)
        r.raise_for_status()
        out: list[str] = []
        for m in (r.json() or {}).get("models") or []:
            name = str(m.get("name") or "").strip()
            if name:
                out.append(name)
        return sorted(out, key=str.lower)
    except Exception:  # noqa: BLE001
        return []


def normalize_model_utterance(text: str) -> str:
    """Fix common ASR / spaced spellings before alias match."""
    t = (text or "").strip().lower()
    if not t:
        return ""
    # "q w e n" / "g e m m a"
    t = re.sub(r"\bq\s+w\s+e\s+n\b", "qwen", t)
    t = re.sub(r"\bg\s+e\s+m\s+m\s+a\b", "gemma", t)
    t = re.sub(r"\bs\s+a\s+l\s+u\s+k\s+i\b", "saluki", t)
    t = re.sub(r"\bsalooki\b", "saluki", t)
    # ASR: "saluki space 27b" / "saluki 27 b"
    t = re.sub(r"\bsaluki\s+(?:space\s+)?27\s*b\b", "saluki", t)
    t = re.sub(r"\bsaluki\s+27\b", "saluki", t)
    # Mishearings in switch phrases
    t = re.sub(r"\bgamma\b", "gemma", t)
    t = re.sub(r"\bwhen\s+(?=3)", "qwen ", t)  # "when 3.5…" ASR for qwen 3.5
    t = re.sub(r"\b(?:to|use|load|set)\s+when\b", "to qwen", t)
    t = re.sub(r"\bcoin\s+(?=qwen)", "", t)
    # "3.59 billion" / "3.5 9b" ASR for qwen3.5:9b (optional leading qwen — don't double it)
    t = re.sub(r"\b(?:qwen\s*)?3\s*\.\s*59\s*(?:billion|b)\b", "qwen3.5:9b", t)
    t = re.sub(r"\b(?:qwen\s*)?3\s*\.\s*5\s*9\s*(?:billion|b)\b", "qwen3.5:9b", t)
    # "qwen 3.5 9b" / "qwen3.5 9 billion" → compact hints
    t = re.sub(r"\bqwen\s*3\s*\.\s*5\b", "qwen3.5", t)
    t = re.sub(r"\bqwen\s*3\s*\.\s*8\b", "qwen3.8", t)
    t = re.sub(r"\b(\d+)\s*billion\b", r"\1b", t)
    t = re.sub(r"\bqwen3\.5\s*[:=]?\s*(\d+)\s*b\b", r"qwen3.5:\1b", t)
    t = re.sub(r"\bqwen3\.5\s+(\d+)b\b", r"qwen3.5:\1b", t)
    t = re.sub(r"\bqwen3\.8\s*[:=]?\s*(\d+)\s*b\b", r"qwen3.8:\1b", t)
    t = re.sub(r"\bqwen\s+qwen\b", "qwen", t)
    return t


def _score_tag(tag: str, *, prefer: str = "") -> tuple[int, ...]:
    """Rank installed tags. Higher is better for the spoken request."""
    low = tag.lower()
    pref = (prefer or "").lower()
    compact_pref = re.sub(r"\s+", "", pref)
    # Exact-ish preference for version / size tokens in the utterance
    version_hit = 0
    for tok in ("qwen3.5", "gemma4", "qwen3-vl", "qwen3-coder"):
        if tok in compact_pref and tok in low:
            version_hit += 3
    # Chat switches: prefer general chat tags; demote VL/coder unless asked
    want_vl = bool(re.search(r"(?i)\b(vl|vision|multimodal|llava)\b", pref))
    want_coder = bool(re.search(r"(?i)\b(coder|code)\b", pref))
    multi = 1 if any(x in low for x in ("vl", "vision", "llava", "minicpm")) else 0
    coder = 1 if "coder" in low or "-code" in low else 0
    if not want_vl:
        multi = -2 * multi
    if not want_coder:
        coder = -2 * coder
    # Prefer qwen3.5 chat when they just say qwen
    family_boost = 0
    if "gemma4" in compact_pref or re.search(r"gemma\s*4", pref):
        family_boost = 2 if "gemma4" in low else 0
    if "qwen3.5" in compact_pref:
        family_boost = 4 if "qwen3.5" in low else 0
    elif re.search(r"(?i)\bqwen\b", pref) and not want_vl and not want_coder:
        family_boost = 3 if "qwen3.5" in low else (1 if low.startswith("qwen") else 0)
    size = 0
    m = re.search(r":(\d+(?:\.\d+)?)b", low)
    if m:
        try:
            size = int(float(m.group(1)) * 10)
        except ValueError:
            size = 0
    # If they named a size (9b), prefer that size strongly
    size_pref = 0
    sm = re.search(r"(\d+(?:\.\d+)?)b", compact_pref)
    if sm and m and sm.group(1) == m.group(1):
        size_pref = 50
    return (version_hit + family_boost, size_pref, multi, coder, size, low)


def resolve_model_alias(utterance: str, *, tags: list[str] | None = None) -> str | None:
    """Return best installed Ollama tag for 'qwen' / 'gemma' / full tag, or None."""
    raw = normalize_model_utterance(utterance)
    if not raw:
        return None
    installed = tags if tags is not None else list_installed_tags()
    if not installed:
        return None

    # Exact / prefix tag if they said a full name
    compact = re.sub(r"\s+", "", raw)
    for t in installed:
        tl = t.lower()
        if (
            tl == raw
            or tl == compact
            or tl.startswith(raw + ":")
            or tl.startswith(compact + ":")
            or raw.startswith(tl)
            or compact.startswith(tl)
        ):
            return t

    # Alias family
    family = None
    family_name = ""
    for name, pat in _ALIAS_PATTERNS:
        if re.search(rf"\b{re.escape(name)}\b", raw) or compact.startswith(name):
            family = pat
            family_name = name
            break
    if family is None:
        hits = [t for t in installed if raw in t.lower() or compact in t.lower()]
        if hits:
            return sorted(hits, key=lambda x: _score_tag(x, prefer=raw), reverse=True)[0]
        return None

    hits = [t for t in installed if family.search(t)]
    if not hits:
        return None
    return sorted(hits, key=lambda x: _score_tag(x, prefer=raw or family_name), reverse=True)[0]


def parse_switch_model_utterance(message: str) -> str | None:
    """Extract model alias/tag from 'switch to qwen' / 'use gemma' etc."""
    msg = normalize_model_utterance(message)
    if not msg:
        return None

    # Prefer an explicit family mention (handles "switch … from gemma to qwen3.5").
    for name, _ in _ALIAS_PATTERNS:
        m = re.search(rf"\b({re.escape(name)}[\w.:-]*)\b", msg, re.IGNORECASE)
        if m:
            # If both gemma and qwen appear, prefer the one after "to"
            after_to = re.search(
                rf"(?i)\bto\s+({re.escape(name)}[\w.:-]*)\b",
                msg,
            )
            if after_to:
                return after_to.group(1).strip().rstrip(".,!?")
            # Fall through — may still find a better "to X" below

    m_to = re.search(r"(?i)\bto\s+([a-z0-9][\w.:-]{1,40})", msg)
    if m_to:
        token = m_to.group(1).strip().rstrip(".,!?")
        if token.lower() not in _STOP_TOKENS:
            return token

    m = re.search(
        r"(?i)\b(?:switch|change|use|load|set)\b.{0,48}\b(?:to|model)?\s*"
        r"([a-z0-9][\w.:-]{1,40})",
        msg,
    )
    if m:
        token = m.group(1).strip().rstrip(".,!?")
        if token.lower() not in _STOP_TOKENS:
            return token

    # Family present anywhere in a switch-ish sentence
    if re.search(r"(?i)\b(switch|change|use|load|set|model)\b", msg):
        for name, _ in _ALIAS_PATTERNS:
            if re.search(rf"\b{re.escape(name)}\b", msg):
                rich = re.search(rf"\b({re.escape(name)}[\w.:-]*)\b", msg)
                return (rich.group(1) if rich else name).strip().rstrip(".,!?")

    m2 = re.search(r"(?i)\b(?:model)\s*[:=]?\s*([a-z0-9][\w.:-]{1,40})", msg)
    if m2:
        token = m2.group(1).strip().rstrip(".,!?")
        if token.lower() not in _STOP_TOKENS:
            return token
    return None


def apply_chat_model(tag: str, *, emit=None) -> dict[str, Any]:
    """Set chat_model (and vision if tag looks multimodal)."""
    from friday.config import _name_looks_text_only, _name_looks_vision
    from friday.runtime.prefs import update

    patch: dict[str, Any] = {"chat_model": tag}
    # Only retarget vision when the new tag is actually a VLM — keep qwen3-vl etc.
    if _name_looks_vision(tag) and not _name_looks_text_only(tag):
        patch["vision_model"] = tag
    update(patch)
    try:
        from friday import config as C

        C._ollama_tags_cache = None
    except Exception:  # noqa: BLE001
        pass
    try:
        from friday.models.manager import get_model_manager

        get_model_manager().on_prefs_model_change()
    except Exception:  # noqa: BLE001
        pass
    from friday.config import resolve_chat_model, resolve_vision_model

    result = {
        "ok": True,
        "chat_model": resolve_chat_model(),
        "vision_model": resolve_vision_model(),
        "requested": tag,
    }
    if emit:
        try:
            emit("model", result)
        except Exception:  # noqa: BLE001
            pass
    return result


def current_models() -> dict[str, str]:
    from friday.config import resolve_chat_model, resolve_vision_model

    return {
        "chat_model": resolve_chat_model(),
        "vision_model": resolve_vision_model(),
    }


def looks_like_model_switch(message: str) -> bool:
    """True when the utterance is about changing chat/vision models (not callsigns)."""
    msg = normalize_model_utterance(message)
    if not msg:
        return False
    # Versioned tags anywhere: "qwen3.5", "qwen3.8-27b", "gemma4" — local switch, not web.
    if re.search(r"(?i)\bsaluki\b", msg):
        return True
    if re.search(
        r"(?i)\b(qwen|gemma|llama|mistral|phi|deepseek|llava|minicpm)"
        r"[\w.:-]*\d[\w.:-]*\b",
        msg,
    ):
        return True
    if re.search(
        r"(?i)(?:\b|_)(qwen|gemma|llama|mistral|phi|deepseek|llava|minicpm|ollama|saluki)",
        msg,
    ):
        if re.search(r"(?i)\b(switch|change|use|load|set|model|from|to|install|pull)\b", msg):
            return True
    if re.search(r"(?i)\b(switch|change|use|load|set)\b.{0,40}\bmodel\b", msg):
        return True
    return False


def looks_like_model_talk(message: str) -> bool:
    """Local model/Ollama talk — must never become a web research query."""
    if looks_like_model_switch(message):
        return True
    msg = normalize_model_utterance(message)
    if not msg:
        return False
    if re.search(
        r"(?i)\b(qwen|gemma|llama|mistral|phi|deepseek|llava|minicpm|ollama|gguf|"
        r"open-?weight|open weight)\b",
        msg,
    ) and re.search(
        r"(?i)\b(model|install|pull|download|switch|use|load|vision|chat|"
        r"saluki|alibaba|turned down|rebrand)\b",
        msg,
    ):
        return True
    return bool(
        re.search(
            r"(?i)\b(qwen|gemma|llama|mistral|phi|deepseek)[\w.:-]*\d[\w.:-]*\b",
            msg,
        )
    )
