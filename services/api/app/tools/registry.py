"""Typed tool registry (§21.2, §24.3). Model-generated calls are untrusted and validated on every invocation.

Only tools whose capability is effective for the tenant are discoverable (§26.2).
External connector tools register here through the same contract once their
adapters are verified; none are registered until then, so the assistant never
claims an unsupported action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.capabilities import CapabilityKey
from app.domain.constants import Permission, SideEffect


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MemorySearchArgs(_Args):
    query: Annotated[str, Field(min_length=1, max_length=200)]
    limit: Annotated[int, Field(ge=1, le=20)] = 5


class MemorySaveArgs(_Args):
    content: Annotated[str, Field(min_length=3, max_length=500)]
    kind: Literal["semantic", "procedural"] = "semantic"


class MemoryDeleteMatchingArgs(_Args):
    query: Annotated[str, Field(min_length=2, max_length=120)]


class TimeNowArgs(_Args):
    pass


@dataclass(frozen=True, slots=True)
class ToolDef:
    key: str
    version: int
    description: str
    capability: str
    permission: Permission
    side_effect: SideEffect
    requires_approval: bool
    args_model: type[_Args]

    def json_schema(self) -> dict:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema


TOOLS: dict[str, ToolDef] = {
    t.key: t
    for t in (
        ToolDef(
            "time.now",
            1,
            "Get the current date and time in the user's timezone.",
            CapabilityKey.ASSISTANT_TEXT,
            Permission.ASSISTANT_USE,
            SideEffect.READ,
            False,
            TimeNowArgs,
        ),
        ToolDef(
            "memory.search",
            1,
            "Search the user's saved personal memory for relevant facts or preferences.",
            CapabilityKey.ASSISTANT_MEMORY,
            Permission.MEMORY_MANAGE,
            SideEffect.READ,
            False,
            MemorySearchArgs,
        ),
        ToolDef(
            "memory.save",
            1,
            "Save a durable fact or preference the user explicitly asked you to remember. "
            "Never save secrets, passwords, financial or health details.",
            CapabilityKey.ASSISTANT_MEMORY_WRITE,
            Permission.MEMORY_MANAGE,
            SideEffect.INTERNAL_WRITE,
            True,
            MemorySaveArgs,
        ),
        ToolDef(
            "memory.delete_matching",
            1,
            "Delete saved memory items matching a topic the user asked to forget.",
            CapabilityKey.ASSISTANT_MEMORY,
            Permission.MEMORY_MANAGE,
            SideEffect.CONSEQUENTIAL,
            True,
            MemoryDeleteMatchingArgs,
        ),
    )
}


def tool_summary(tool: ToolDef, args: dict) -> str:
    """Human-readable approval text: action, material parameters, consequence (§26.2)."""
    if tool.key == "memory.save":
        return f"Save to your memory: “{args.get('content', '')}”"
    if tool.key == "memory.delete_matching":
        return f"Permanently delete memory items matching “{args.get('query', '')}”"
    return f"Run {tool.key}"
