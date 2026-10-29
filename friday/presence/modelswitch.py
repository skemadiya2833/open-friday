"""Voice/chat model switch — resolve aliases against installed Ollama tags."""

from __future__ import annotations

import re
from typing import Any

# Spoken aliases → substring match against installed tags (prefer multimodal / larger).
_ALIAS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
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


def _score_tag(tag: str) -> tuple[int, int, str]:
    """Prefer multimodal / larger-looking tags when alias matches many."""
    low = tag.lower()
    multi = (
        1
        if any(x in low for x in ("vl", "vision", "gemma4", "llava", "minicpm"))
        else 0
    )
    # crude size hint from :12b / :7b etc.
    size = 0
    m = re.search(r":(\d+(?:\.\d+)?)b", low)
    if m:
        try:
            size = int(float(m.group(1)) * 10)
        except ValueError:
            size = 0
    return (multi, size, low)


def resolve_model_alias(utterance: str, *, tags: list[str] | None = None) -> str | None:
    """Return best installed Ollama tag for 'qwen' / 'gemma' / full tag, or None."""
    raw = (utterance or "").strip()
    if not raw:
        return None
    installed = tags if tags is not None else list_installed_tags()
    if not installed:
        return None

    # Exact / prefix tag if they said a full name
    low = raw.lower()
    for t in installed:
        if (
            t.lower() == low
            or t.lower().startswith(low + ":")
            or low.startswith(t.lower())
        ):
            return t

    # Alias family
    family = None
    for name, pat in _ALIAS_PATTERNS:
        if re.search(rf"\b{re.escape(name)}\b", low) or low == name:
            family = pat
            break
    if family is None:
        # bare substring against tags
        hits = [t for t in installed if low in t.lower()]
        if hits:
            return sorted(hits, key=_score_tag, reverse=True)[0]
        return None

    hits = [t for t in installed if family.search(t)]
    if not hits:
        return None
    return sorted(hits, key=_score_tag, reverse=True)[0]


def parse_switch_model_utterance(message: str) -> str | None:
    """Extract model alias/tag from 'switch to qwen' / 'use gemma' etc."""
    msg = (message or "").strip()
    m = re.search(
        r"(?i)\b(?:switch|change|use|load|set)\b.{0,20}\b(?:to|model)?\s*"
        r"([a-z0-9][\w.:-]{1,40})",
        msg,
    )
    if m:
        token = m.group(1).strip().rstrip(".,!?")
        # Ignore skin names mistakenly caught here
        if token.lower() in {
            "friday",
            "jarvis",
            "ultron",
            "vision",
            "karen",
            "edith",
            "mode",
            "model",
            "chat",
            "voice",
        }:
            return None
        return token
    m2 = re.search(r"(?i)\b(?:model)\s*[:=]?\s*([a-z0-9][\w.:-]{1,40})", msg)
    if m2:
        return m2.group(1).strip().rstrip(".,!?")
    return None


def apply_chat_model(tag: str, *, emit=None) -> dict[str, Any]:
    """Set chat_model (and vision if tag looks multimodal)."""
    from friday.config import _name_looks_text_only, _name_looks_vision
    from friday.runtime.prefs import update

    patch: dict[str, Any] = {"chat_model": tag}
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
