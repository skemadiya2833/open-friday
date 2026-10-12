"""Tool layer v2 types: schema-described tools with structured results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ToolRisk(str, Enum):
    SAFE = "safe"            # read-only or confined, reversible
    CONFIRM = "confirm"      # changes state; owner approval by default
    DANGEROUS = "dangerous"  # code execution / destructive; denied unless explicitly enabled


@dataclass
class ToolResult:
    """What a tool returns. Text-only tools can still return a plain ``str``."""

    content: list[dict[str, Any]] = field(default_factory=list)   # {"type":"text","text":..} | {"type":"image","data":b64,"mime":..}
    structured: dict[str, Any] | None = None
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text_result(cls, text: str, *, is_error: bool = False, **metadata: Any) -> "ToolResult":
        return cls(content=[{"type": "text", "text": text}], is_error=is_error, metadata=dict(metadata))

    @classmethod
    def error(cls, message: str, **metadata: Any) -> "ToolResult":
        return cls.text_result(message, is_error=True, **metadata)

    def text(self) -> str:
        parts = [b.get("text", "") for b in self.content if b.get("type") == "text"]
        images = sum(1 for b in self.content if b.get("type") == "image")
        out = "\n".join(p for p in parts if p)
        if images:
            out = (out + "\n" if out else "") + f"[{images} image(s) attached]"
        if not out and self.structured is not None:
            import json

            out = json.dumps(self.structured, ensure_ascii=False)[:4000]
        return out

    def images(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "image"]

    def to_dict(self, *, include_image_data: bool = False) -> dict[str, Any]:
        blocks = []
        for b in self.content:
            if b.get("type") == "image" and not include_image_data:
                blocks.append({"type": "image", "mime": b.get("mime"), "bytes_b64": len(b.get("data", ""))})
            else:
                blocks.append(b)
        return {
            "content": blocks,
            "structured": self.structured,
            "is_error": self.is_error,
            "metadata": self.metadata,
        }


Handler = Callable[[dict[str, Any]], "ToolResult | str"]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]            # JSON Schema (draft 2020-12)
    handler: Handler
    risk: ToolRisk = ToolRisk.SAFE
    source: str = "builtin"                 # "builtin" or "mcp:<server>"
    title: str = ""
    # Legacy compatibility (v1 API exposed `.parameters` and `.risky`).
    @property
    def parameters(self) -> dict[str, Any]:
        return dict(self.input_schema.get("properties", {}))

    @property
    def risky(self) -> bool:
        return self.risk != ToolRisk.SAFE

    def to_public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "risk": self.risk.value,
            "source": self.source,
        }


def object_schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    """Small helper for building strict object schemas."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema
