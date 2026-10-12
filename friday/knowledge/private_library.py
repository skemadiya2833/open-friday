"""Owner-private markdown/text library outside the repo (.private_library/)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = _REPO_ROOT / ".private_library"

_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst"}


def library_root() -> Path:
    raw = os.getenv("FRIDAY_PRIVATE_LIBRARY", str(DEFAULT_ROOT))
    return Path(raw).expanduser().resolve()


def _embed_available() -> bool:
    try:
        from friday.memory import _ollama_embed

        vec = _ollama_embed(["probe"])[0]
        return bool(vec)
    except Exception:
        return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:20000]
    except OSError:
        return ""


def index_documents(*, force: bool = False) -> dict[str, Any]:
    """Walk library folder; embed only when Ollama embed model is already usable."""
    root = library_root()
    root.mkdir(parents=True, exist_ok=True)
    use_embed = _embed_available()
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".pdf":
            continue  # skip unless a pure-python PDF parser is added
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        text = _read_text(path)
        entry: dict[str, Any] = {"path": rel, "absolute": str(path), "chars": len(text)}
        if use_embed and text.strip():
            try:
                from friday.memory import _ollama_embed

                entry["embedding_dim"] = len(_ollama_embed([text[:4000]])[0])
            except Exception:
                entry["embedding_dim"] = 0
        entries.append(entry)
    return {
        "root": str(root),
        "indexed": len(entries),
        "embed_enabled": use_embed,
        "entries": entries[:200],
        "note": "Files are cited by path only; content is never copied into the git repo.",
    }


def search(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Keyword search with path citations (embedding optional)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    root = library_root()
    if not root.is_dir():
        return []
    hits: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        text = _read_text(path)
        if q not in text.lower():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        idx = text.lower().find(q)
        snippet = text[max(0, idx - 40) : idx + 120].replace("\n", " ")
        hits.append({"path": rel, "cite": str(path), "snippet": snippet})
        if len(hits) >= limit:
            break
    return hits
