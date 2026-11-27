"""LLM provider abstraction. The configured provider and model are explicit; there is no silent fallback."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings


class LLMError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict


# Neutral transcript format: {"role": "user"|"assistant", "content": str, "tool_calls": [...]} and
# {"role": "tool", "tool_call_id": str, "name": str, "content": str}


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def chat(self, system: str, messages: list[dict], tools: list[Tool]) -> LLMReply: ...


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None):
        self.key, self.model = api_key, model
        self.http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))

    def chat(self, system: str, messages: list[dict], tools: list[Tool]) -> LLMReply:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "tool":
                msgs.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            elif m.get("tool_calls"):
                msgs.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": json.dumps(t["args"])}} for t in m["tool_calls"]
                        ],
                    }
                )
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body: dict[str, Any] = {"model": self.model, "messages": msgs}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
        try:
            r = self.http.post("https://api.openai.com/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {self.key}"})
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI unreachable ({exc.__class__.__name__})") from exc
        if r.status_code >= 400:
            raise LLMError(f"OpenAI error HTTP {r.status_code}")
        msg = r.json()["choices"][0]["message"]
        calls = [ToolCall(c["id"], c["function"]["name"], json.loads(c["function"].get("arguments") or "{}")) for c in msg.get("tool_calls") or []]
        return LLMReply(msg.get("content") or "", calls)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None):
        self.key, self.model = api_key, model
        self.http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))

    def chat(self, system: str, messages: list[dict], tools: list[Tool]) -> LLMReply:
        msgs: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
                    msgs[-1]["content"].append(block)
                else:
                    msgs.append({"role": "user", "content": [block]})
            elif m.get("tool_calls"):
                content: list[dict] = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                content += [{"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["args"]} for t in m["tool_calls"]]
                msgs.append({"role": "assistant", "content": content})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body: dict[str, Any] = {"model": self.model, "max_tokens": 1500, "system": system, "messages": msgs}
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        try:
            r = self.http.post("https://api.anthropic.com/v1/messages", json=body, headers={"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic unreachable ({exc.__class__.__name__})") from exc
        if r.status_code >= 400:
            raise LLMError(f"Anthropic error HTTP {r.status_code}")
        blocks = r.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in blocks if b.get("type") == "tool_use"]
        return LLMReply(text, calls)


_override: LLMProvider | None = None


def set_provider_override(p: LLMProvider | None) -> None:
    """Test hook only."""
    global _override
    _override = p


def configured_provider() -> LLMProvider | None:
    if _override is not None:
        return _override
    s = get_settings()
    if s.llm_provider == "openai" and s.openai_api_key and s.llm_model:
        return OpenAIProvider(s.openai_api_key, s.llm_model)
    if s.llm_provider == "anthropic" and s.anthropic_api_key and s.llm_model:
        return AnthropicProvider(s.anthropic_api_key, s.llm_model)
    return None
