"""Owner facts in SQLite (source of truth). Optional short mirror into Chroma for semantic recall."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from friday.store.db import connect, ensure_schema


def _fact_id(text: str, *, prefix: str = "fact") -> str:
    digest = hashlib.sha1(re.sub(r"\W+", " ", text.lower()).strip().encode()).hexdigest()[:20]
    return f"{prefix}-{digest}"


def add_fact(
    text: str,
    *,
    source: str = "manual",
    kind: str = "fact",
    fact_id: str | None = None,
    mirror_chroma: bool = True,
) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("text required")
    ensure_schema()
    fid = fact_id or _fact_id(text, prefix="auto" if source == "auto" else "fact")
    now = time.time()
    chroma_id: str | None = None
    if mirror_chroma:
        try:
            from friday.memory import get_memory

            chroma_id = get_memory().add(
                text[:500],
                metadata={"source": source, "kind": kind, "fact_id": fid},
                doc_id=fid,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[Facts] chroma mirror skipped: {exc}")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO owner_facts (id, text, source, kind, created_at, chroma_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                text = excluded.text,
                source = excluded.source,
                kind = excluded.kind,
                chroma_id = COALESCE(excluded.chroma_id, owner_facts.chroma_id)
            """,
            (fid, text[:500], source, kind, now, chroma_id),
        )
        conn.commit()
    return {"id": fid, "text": text[:500], "source": source, "kind": kind, "chroma_id": chroma_id}


def list_facts(limit: int = 12, *, exclude_sources: tuple[str, ...] = ("computer_use",)) -> list[str]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT text, source, created_at FROM owner_facts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(limit * 3, 40),),
        ).fetchall()
    out: list[str] = []
    for r in rows:
        if (r["source"] or "") in exclude_sources:
            continue
        out.append(r["text"])
        if len(out) >= limit:
            break
    return out


def list_facts_rows(limit: int = 200) -> list[dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, text, source, kind, created_at, chroma_id
            FROM owner_facts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "text": r["text"],
            "source": r["source"],
            "kind": r["kind"],
            "created_at": float(r["created_at"] or 0),
            "chroma_id": r["chroma_id"],
        }
        for r in rows
    ]


def delete_fact(fact_id: str) -> bool:
    ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT chroma_id FROM owner_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM owner_facts WHERE id = ?", (fact_id,))
        conn.commit()
    cid = row["chroma_id"] or fact_id
    try:
        from friday.memory import get_memory

        get_memory().delete(cid, collection="memories")
    except Exception:  # noqa: BLE001
        pass
    return True


def clear_facts() -> int:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute("SELECT id, chroma_id FROM owner_facts").fetchall()
        conn.execute("DELETE FROM owner_facts")
        conn.commit()
    try:
        from friday.memory import get_memory

        mem = get_memory()
        for r in rows:
            try:
                mem.delete(r["chroma_id"] or r["id"], collection="memories")
            except Exception:
                pass
    except Exception:
        pass
    return len(rows)
