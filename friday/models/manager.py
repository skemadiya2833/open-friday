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

    def same_chat_and_vision(self) -> bool:
        return resolve_chat_model() == resolve_vision_model()

    def ensure_loaded(self, role: Role) -> str:
        """Load the model for *role*, unloading a conflicting GPU resident first.

        When chat and vision resolve to the same tag, never unload — just re-label.
        """
        return self.ensure_tag(self.model_for(role), role=role)

    def ensure_tag(self, name: str, *, role: Role = "chat") -> str:
        """Warm a concrete Ollama tag and track it as the GPU resident."""
        name = (name or "").strip() or self.model_for(role)
        with self._lock:
            # Embeddings stay light / often CPU — never mark them as the GPU resident
            # (that forced a chat unload+warmup after every memory embed).
            if role == "embed":
                self._warmup(name, keep_alive=keep_alive_for_role("embed"))
                return name

            # Already hot with this exact model — skip another warmup round-trip.
            if self._loaded_name == name:
                self._loaded = role
                return name

            # Different GPU model → unload whoever is hot (chat↔vision swap on 16GB).
            if self._loaded_name and self._loaded_name != name:
                self._unload(self._loaded_name)
                self._loaded_name = None

            # Shared chat+vision tag: always use main keep_alive (never a short vision TTL).
            if role == "vision" and self.same_chat_and_vision():
                keep = keep_alive_for_role("main")
            else:
                keep = keep_alive_for_role("vision" if role == "vision" else "main")
            self._warmup(name, keep_alive=keep)
            self._loaded = role
            self._loaded_name = name
            return name

    def after_vision(self) -> None:
        """Finished a screen/camera look — drop VL-only residency; keep shared chat+vision hot.

        Screenshots are one-shot request payloads; chat history keeps text only.
        When chat≠vision, unload the VL tag so VRAM returns to chat.
        When chat==vision, do **not** unload — just mark the resident as chat.
        """
        chat = resolve_chat_model()
        vision = resolve_vision_model()
        with self._lock:
            if chat == vision:
                if self._loaded_name == chat or self._loaded_name == vision:
                    self._loaded = "chat"
                    self._loaded_name = chat
                return
            if self._loaded_name and self._loaded_name == vision:
                self._unload(self._loaded_name)
                self._loaded = None
                self._loaded_name = None
        # Prefer chat warm for the next turn (outside lock — ensure_loaded re-enters).
        try:
            self.ensure_loaded("chat")
        except Exception:  # noqa: BLE001
            pass

    def on_prefs_model_change(self) -> None:
        """Systems UI changed chat/vision tags — unload only if the hot tag is obsolete."""
        chat = resolve_chat_model()
        vision = resolve_vision_model()
        allowed = {chat, vision}
        with self._lock:
            if not self._loaded_name:
                return
            if self._loaded_name in allowed:
                # Still a valid resident (often the same gemma4 for both) — keep it.
                if chat == vision:
                    self._loaded = "chat"
                return
            self._unload(self._loaded_name)
            self._loaded = None
            self._loaded_name = None

    def unload(self, role: Role | None = None) -> None:
        """Unload the GPU resident. Prefer the actual loaded tag (survives prefs switches)."""
        with self._lock:
            name = self._loaded_name
            if role is not None and self._loaded != role:
                return
            if not name:
                return
            self._unload(name)
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
