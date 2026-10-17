"""16GB-aware Ollama model residency — never keep two large GPU models hot."""

from __future__ import annotations

import threading
from typing import Literal

import httpx

from friday.config import (
    EMBED_MODEL,
    OLLAMA_HOST,
    resolve_chat_model,
    resolve_vision_model,
)
from friday.runtime.resource_policy import keep_alive_for_role

Role = Literal["vision", "chat", "embed"]


class ModelManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded: Role | None = None
        self._loaded_name: str | None = None

    def model_for(self, role: Role) -> str:
        if role == "vision":
            return resolve_vision_model()
        if role == "embed":
            return EMBED_MODEL
        return resolve_chat_model()

    def ensure_loaded(self, role: Role) -> str:
        """Load the model for *role*, unloading a conflicting GPU resident first."""
        name = self.model_for(role)
        with self._lock:
            # Embeddings stay light / often CPU — don't displace vision/chat.
            if role == "embed":
                if self._loaded_name != name:
                    self._warmup(name, keep_alive=keep_alive_for_role("embed"))
                    self._loaded_name = name
                return name

            # Already hot with this exact model — skip another warmup round-trip.
            if self._loaded_name == name:
                self._loaded = role
                return name

            # Different GPU model → unload whoever is hot (chat↔vision swap on 16GB).
            if self._loaded_name and self._loaded_name != name:
                self._unload(self._loaded_name)
                self._loaded_name = None

            keep = keep_alive_for_role("vision" if role == "vision" else "main")
            self._warmup(name, keep_alive=keep)
            self._loaded = role
            self._loaded_name = name
            return name

    def unload(self, role: Role | None = None) -> None:
        with self._lock:
            target_role = role or self._loaded
            if not target_role or target_role == "embed":
                return
            self._unload(self.model_for(target_role))
            if self._loaded == target_role:
                self._loaded = None
                self._loaded_name = None

    def mark_used(self, role: Role) -> None:
        """Note that Ollama already has this model resident (no warmup)."""
        with self._lock:
            self._loaded = role
            self._loaded_name = self.model_for(role)

    def _warmup(self, model: str, keep_alive: str | int) -> None:
        try:
            httpx.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": model, "prompt": "", "keep_alive": keep_alive},
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            print(f"[ModelManager] Warmup failed for {model}: {exc}")

    def _unload(self, model: str) -> None:
        try:
            httpx.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": model, "prompt": "", "keep_alive": 0},
                timeout=30.0,
            )
            print(f"[ModelManager] Unloaded {model}")
        except httpx.HTTPError as exc:
            print(f"[ModelManager] Unload failed for {model}: {exc}")


_manager: ModelManager | None = None


def get_model_manager() -> ModelManager:
    global _manager
    if _manager is None:
        _manager = ModelManager()
    return _manager
