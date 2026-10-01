"""Persistent local vector memory via ChromaDB."""

from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from friday.config import CHROMA_DIR, EMBED_MODEL, OLLAMA_HOST, ensure_data_dirs

# nomic-embed-text is 768-d. Hash fallback matches so Ollama recovery never
# fights an older 64-d collection left from early Friday builds.
_FALLBACK_DIM = 768
_SCHEMA_VERSION = "2"  # bump to force a clean Chroma wipe on breaking changes
_EMBED_DIM: int | None = None


@dataclass
class MemoryHit:
    id: str
    text: str
    score: float
    metadata: dict[str, Any]


def _hash_embed(text: str, dim: int = _FALLBACK_DIM) -> list[float]:
    seed = text.encode("utf-8")
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        h = hashlib.sha256(seed + counter.to_bytes(4, "little")).digest()
        out.extend(b / 255.0 for b in h)
        counter += 1
    return out[:dim]


def _ollama_embed(texts: list[str]) -> list[list[float]]:
    global _EMBED_DIM
    vectors: list[list[float]] = []
    for text in texts:
        try:
            resp = httpx.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=60.0,
            )
            resp.raise_for_status()
            vec = list(resp.json()["embedding"])
            _EMBED_DIM = len(vec)
            vectors.append(vec)
        except Exception as exc:
            print(f"[Memory] Embed failed, using hash fallback: {exc}")
            dim = _EMBED_DIM or _FALLBACK_DIM
            vectors.append(_hash_embed(text, dim))
    return vectors


def _is_dim_mismatch(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "dimension" in msg or "expecting embedding" in msg


def _is_missing_collection(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    return name == "NotFoundError" or "does not exist" in msg


def _migrate_chroma_dir_if_needed() -> None:
    """Wipe Chroma once when schema/version changes (e.g. 64-d → 768-d)."""
    ensure_data_dirs()
    marker = Path(CHROMA_DIR) / ".friday_schema"
    current = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    if current == _SCHEMA_VERSION:
        return
    root = Path(CHROMA_DIR)
    if root.exists():
        # Keep the directory, wipe contents except we recreate fresh.
        for child in list(root.iterdir()):
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except Exception:
                pass
        print(
            f"[Memory] Cleared Chroma store for schema {_SCHEMA_VERSION} "
            "(fixes old 64-d collections)."
        )
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(_SCHEMA_VERSION, encoding="utf-8")


class VectorMemory:
    COLLECTIONS = ("memories", "skills_index", "conversation_chunks")

    def __init__(self) -> None:
        _migrate_chroma_dir_if_needed()
        self._client = None
        self._collections: dict[str, Any] = {}

    def _open_client(self) -> None:
        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=Settings(anonymized_telemetry=False),
        )

    def _ensure(self) -> None:
        if self._client is not None and self._collections:
            return
        self._open_client()
        self._reload_collections()

    def _reload_collections(self) -> None:
        assert self._client is not None
        self._collections = {}
        for name in self.COLLECTIONS:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine", "friday_schema": _SCHEMA_VERSION},
            )

    def _collection(self, name: str) -> Any:
        self._ensure()
        col = self._collections.get(name)
        if col is None:
            self._reload_collections()
            col = self._collections[name]
        return col

    def _reset_all(self, reason: str) -> None:
        """Drop every collection and refresh handles (dim mismatch / stale IDs)."""
        self._ensure()
        assert self._client is not None
        for name in list(self.COLLECTIONS):
            try:
                self._client.delete_collection(name)
            except Exception:
                pass
        self._reload_collections()
        try:
            from friday.skills.router import get_router
            get_router()._skills_indexed = False
        except Exception:
            pass
        print(f"[Memory] Reset all collections ({reason}).")

    def _reset_collection(self, name: str) -> None:
        self._ensure()
        assert self._client is not None
        try:
            self._client.delete_collection(name)
        except Exception:
            pass
        self._collections[name] = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine", "friday_schema": _SCHEMA_VERSION},
        )
        if name == "skills_index":
            try:
                from friday.skills.router import get_router
                get_router()._skills_indexed = False
            except Exception:
                pass
        print(f"[Memory] Recreated collection '{name}'.")

    def add(
        self,
        text: str,
        *,
        collection: str = "memories",
        metadata: dict[str, Any] | None = None,
        doc_id: str | None = None,
    ) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Empty memory text")
        cid = doc_id or str(uuid.uuid4())
        meta = dict(metadata or {})
        meta.setdefault("created_at", time.time())
        meta.setdefault("pinned", False)
        clean = {
            k: (v if isinstance(v, (str, int, float, bool)) else str(v))
            for k, v in meta.items()
        }
        emb = _ollama_embed([text])[0]

        for attempt in range(2):
            try:
                self._collection(collection).upsert(
                    ids=[cid],
                    documents=[text],
                    embeddings=[emb],
                    metadatas=[clean],
                )
                return cid
            except Exception as exc:
                if attempt == 0 and (_is_dim_mismatch(exc) or _is_missing_collection(exc)):
                    if _is_dim_mismatch(exc):
                        self._reset_all("embedding dimension mismatch")
                    else:
                        self._reset_collection(collection)
                    continue
                raise
        return cid

    def search(
        self,
        query: str,
        *,
        collection: str = "memories",
        limit: int = 8,
    ) -> list[MemoryHit]:
        if not query.strip():
            return []
        emb = _ollama_embed([query])[0]
        try:
            result = self._collection(collection).query(
                query_embeddings=[emb],
                n_results=max(1, limit),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            if _is_dim_mismatch(exc) or _is_missing_collection(exc):
                if _is_dim_mismatch(exc):
                    self._reset_all("embedding dimension mismatch")
                else:
                    self._reset_collection(collection)
                return []
            raise

        hits: list[MemoryHit] = []
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        for i, doc_id in enumerate(ids):
            dist = float(dists[i]) if i < len(dists) else 1.0
            score = max(0.0, 1.0 - dist)
            hits.append(
                MemoryHit(
                    id=doc_id,
                    text=docs[i] if i < len(docs) else "",
                    score=score,
                    metadata=metas[i] if i < len(metas) else {},
                )
            )
        return hits

    def list_all(self, collection: str = "memories", limit: int = 100) -> list[MemoryHit]:
        try:
            raw = self._collection(collection).get(
                include=["documents", "metadatas"], limit=limit,
            )
        except Exception as exc:
            if _is_missing_collection(exc):
                self._reset_collection(collection)
                return []
            raise
        hits: list[MemoryHit] = []
        for i, doc_id in enumerate(raw.get("ids") or []):
            hits.append(
                MemoryHit(
                    id=doc_id,
                    text=(raw.get("documents") or [""])[i],
                    score=1.0,
                    metadata=(raw.get("metadatas") or [{}])[i] or {},
                )
            )
        return hits

    def delete(self, doc_id: str, collection: str = "memories") -> bool:
        try:
            self._collection(collection).delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for name in self.COLLECTIONS:
            try:
                out[name] = int(self._collection(name).count())
            except Exception as exc:
                if _is_missing_collection(exc) or _is_dim_mismatch(exc):
                    self._reset_collection(name)
                    out[name] = 0
                else:
                    raise
        return out


_memory: VectorMemory | None = None


def get_memory() -> VectorMemory:
    global _memory
    if _memory is None:
        _memory = VectorMemory()
    return _memory


def reset_memory_singleton() -> None:
    """Force re-open after a hard wipe (tests / recovery)."""
    global _memory
    _memory = None
