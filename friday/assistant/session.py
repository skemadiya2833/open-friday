"""Conversation persistence and continuity."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.config import CONVERSATIONS_DIR, ensure_data_dirs


@dataclass
class ConversationTurn:
    role: str
    content: str
    skill_id: str | None = None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "skill_id": self.skill_id,
            "ts": self.ts,
        }


@dataclass
class ConversationSession:
    id: str
    title: str
    turns: list[ConversationTurn] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "turns": [t.to_dict() for t in self.turns],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SessionStore:
    def __init__(self) -> None:
        ensure_data_dirs()
        self._dir = Path(CONVERSATIONS_DIR)
        self._active: str | None = None

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def create(self, title: str = "New chat") -> ConversationSession:
        sid = str(uuid.uuid4())
        session = ConversationSession(id=sid, title=title)
        self.save(session)
        self._active = sid
        return session

    def save(self, session: ConversationSession) -> None:
        session.updated_at = time.time()
        from friday.atomic import write_text_atomic

        write_text_atomic(self._path(session.id), json.dumps(session.to_dict(), indent=2))
    def load(self, session_id: str) -> ConversationSession | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        turns = [
            ConversationTurn(
                role=t["role"],
                content=t["content"],
                skill_id=t.get("skill_id"),
                ts=t.get("ts", 0),
            )
            for t in raw.get("turns") or []
        ]
        return ConversationSession(
            id=raw["id"],
            title=raw.get("title") or "Chat",
            turns=turns,
            created_at=raw.get("created_at", 0),
            updated_at=raw.get("updated_at", 0),
        )

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                items.append({
                    "id": raw["id"],
                    "title": raw.get("title"),
                    "updated_at": raw.get("updated_at"),
                    "turns": len(raw.get("turns") or []),
                })
            except Exception:
                continue
        return items

    def delete_turn(self, session_id: str, ts: float) -> bool:
        session = self.load(session_id)
        if not session:
            return False
        before = len(session.turns)
        session.turns = [t for t in session.turns if abs((t.ts or 0) - ts) > 1e-4]
        if len(session.turns) == before:
            return False
        self.save(session)
        return True

    def get_or_create(self, session_id: str | None) -> ConversationSession:
        if session_id:
            existing = self.load(session_id)
            if existing:
                self._active = existing.id
                return existing
        # resume last if no id
        if not session_id:
            sessions = self.list_sessions(1)
            if sessions:
                loaded = self.load(sessions[0]["id"])
                if loaded:
                    self._active = loaded.id
                    return loaded
        return self.create()

    def append(
        self,
        session: ConversationSession,
        role: str,
        content: str,
        skill_id: str | None = None,
    ) -> None:
        session.turns.append(ConversationTurn(role=role, content=content, skill_id=skill_id))
        if session.title == "New chat" and role == "user":
            session.title = content[:48] + ("…" if len(content) > 48 else "")
        self.save(session)
        # Optional: indexing every reply costs an embed round-trip.
        from friday.config import INDEX_CHAT_TURNS
        if INDEX_CHAT_TURNS and role == "assistant" and content.strip():
            try:
                from friday.memory import get_memory
                get_memory().add(
                    content[:1500],
                    collection="conversation_chunks",
                    metadata={"session_id": session.id, "role": role},
                )
            except Exception:
                pass


_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
