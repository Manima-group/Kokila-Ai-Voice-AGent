"""Provider-neutral reasoning adapters with bounded retries, circuit breaker and safe-boundary failover (§15).

Vendor specifics stay behind this interface. Model IDs come from configuration.
Live verification against each vendor requires authorized credentials and is
tracked as a blocker in docs/implementation-status.md until performed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import ReasoningProvider as ProviderName
from app.core.config import Settings, get_settings
from app.core.errors import ProviderUnavailable

log = logging.getLogger("kokila.providers.reasoning")


@dataclass(slots=True)
class ChatMessage:
    role: str  # user | assistant | tool
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCallRequest] | None = None


@dataclass(slots=True)
class ToolSpec:
    key: str
    description: str
    parameters: dict[str, Any]

    @property
    def wire_name(self) -> str:
        return self.key.replace(".", "__")


@dataclass(slots=True)
class ToolCallRequest:
    id: str
    key: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ReasoningResult:
    text: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class ReasoningAdapter(Protocol):
    name: str
    model: str

    async def complete(
        self, *, system: str, messages: list[ChatMessage], tools: list[ToolSpec], max_output_tokens: int
    ) -> ReasoningResult: ...


class _Transient(Exception):
    pass


def _wire_to_key(name: str) -> str:
    return name.replace("__", ".")


class OpenAIChatAdapter:
    """OpenAI-compatible Chat Completions with function tools."""

    name = "openai"

    def __init__(self, s: Settings, client: httpx.AsyncClient) -> None:
        if not s.openai_api_key or not s.openai_model:
            raise ProviderUnavailable("OpenAI adapter is not configured")
        self.model, self._s, self._client = s.openai_model, s, client

    async def complete(
        self, *, system: str, messages: list[ChatMessage], tools: list[ToolSpec], max_output_tokens: int
    ) -> ReasoningResult:
        wire: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "tool":
                wire.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            elif m.tool_calls:
                wire.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {"name": c.key.replace(".", "__"), "arguments": json.dumps(c.arguments)},
                            }
                            for c in m.tool_calls
                        ],
                    }
                )
            else:
                wire.append({"role": m.role, "content": m.content})
        body: dict[str, Any] = {"model": self.model, "messages": wire, "max_completion_tokens": max_output_tokens}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.wire_name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        assert self._s.openai_api_key is not None
        r = await self._client.post(
            f"{self._s.openai_base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self._s.openai_api_key.get_secret_value()}"},
        )
        if r.status_code in (408, 409, 429) or r.status_code >= 500:
            raise _Transient(f"openai status {r.status_code}")
        if r.status_code >= 400:
            raise ProviderUnavailable(f"reasoning provider rejected the request ({r.status_code})", retryable=False)
        data = r.json()
        msg = data["choices"][0]["message"]
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"__invalid__": True}
            calls.append(ToolCallRequest(id=c["id"], key=_wire_to_key(c["function"]["name"]), arguments=args))
        usage = data.get("usage") or {}
        return ReasoningResult(
            text=msg.get("content") or "",
            tool_calls=calls,
            provider=self.name,
            model=self.model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


class AnthropicMessagesAdapter:
    name = "anthropic"

    def __init__(self, s: Settings, client: httpx.AsyncClient) -> None:
        if not s.anthropic_api_key or not s.anthropic_model:
            raise ProviderUnavailable("Anthropic adapter is not configured")
        self.model, self._s, self._client = s.anthropic_model, s, client

    async def complete(
        self, *, system: str, messages: list[ChatMessage], tools: list[ToolSpec], max_output_tokens: int
    ) -> ReasoningResult:
        wire: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                wire.append(
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}],
                    }
                )
            elif m.tool_calls:
                blocks: list[dict[str, Any]] = [{"type": "text", "text": m.content}] if m.content else []
                blocks += [
                    {"type": "tool_use", "id": c.id, "name": c.key.replace(".", "__"), "input": c.arguments}
                    for c in m.tool_calls
                ]
                wire.append({"role": "assistant", "content": blocks})
            else:
                wire.append({"role": m.role, "content": m.content})
        body: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": wire,
            "max_tokens": max_output_tokens,
        }
        if tools:
            body["tools"] = [
                {"name": t.wire_name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
        assert self._s.anthropic_api_key is not None
        r = await self._client.post(
            f"{self._s.anthropic_base_url}/messages",
            json=body,
            headers={
                "x-api-key": self._s.anthropic_api_key.get_secret_value(),
                "anthropic-version": self._s.anthropic_version,
            },
        )
        if r.status_code in (408, 409, 429, 529) or r.status_code >= 500:
            raise _Transient(f"anthropic status {r.status_code}")
        if r.status_code >= 400:
            raise ProviderUnavailable(f"reasoning provider rejected the request ({r.status_code})", retryable=False)
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        calls = [
            ToolCallRequest(id=b["id"], key=_wire_to_key(b["name"]), arguments=b.get("input") or {})
            for b in data.get("content", [])
            if b.get("type") == "tool_use"
        ]
        usage = data.get("usage") or {}
        return ReasoningResult(
            text=text,
            tool_calls=calls,
            provider=self.name,
            model=self.model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )


class DevMockAdapter:
    """Development/test-only deterministic provider. Config validation forbids it in staging/production.

    Every reply is prefixed with "[dev mock]" so it can never be mistaken for live intelligence.
    """

    name = "dev_mock"
    model = "dev-mock-1"
    _REMEMBER = re.compile(r"^\s*remember(?: that)?\s+(.{3,300})$", re.I)
    _FORGET = re.compile(r"^\s*forget (?:everything|all) about\s+(.{2,120})$", re.I)

    async def complete(
        self, *, system: str, messages: list[ChatMessage], tools: list[ToolSpec], max_output_tokens: int
    ) -> ReasoningResult:
        last = messages[-1]
        names = {t.key for t in tools}
        if last.role == "tool":
            return ReasoningResult(
                text=f"[dev mock] Tool finished: {last.content[:200]}", provider=self.name, model=self.model
            )
        m = self._REMEMBER.match(last.content)
        if m and "memory.save" in names:
            return ReasoningResult(
                text="",
                provider=self.name,
                model=self.model,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{int(time.time() * 1000)}",
                        key="memory.save",
                        arguments={"content": m.group(1).strip(), "kind": "semantic"},
                    )
                ],
            )
        m = self._FORGET.match(last.content)
        if m and "memory.delete_matching" in names:
            return ReasoningResult(
                text="",
                provider=self.name,
                model=self.model,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{int(time.time() * 1000)}",
                        key="memory.delete_matching",
                        arguments={"query": m.group(1).strip()},
                    )
                ],
            )
        name = re.search(r"You are (.+?), an AI", system)
        return ReasoningResult(
            text=f"[dev mock] {name.group(1) if name else 'Assistant'} received: {last.content[:300]}",
            provider=self.name,
            model=self.model,
            input_tokens=len(last.content) // 4,
            output_tokens=12,
        )


class _Breaker:
    def __init__(self, threshold: int = 5, cooldown_s: float = 30.0) -> None:
        self.failures, self.threshold, self.cooldown_s, self.opened_at = 0, threshold, cooldown_s, 0.0

    def allow(self) -> bool:
        return self.failures < self.threshold or time.monotonic() - self.opened_at > self.cooldown_s

    def record(self, ok: bool) -> None:
        if ok:
            self.failures = 0
        else:
            self.failures += 1
            if self.failures >= self.threshold:
                self.opened_at = time.monotonic()


class ReasoningRouter:
    """Primary + configured fallback. Failover happens only before any tool has executed (safe boundary)."""

    def __init__(self, adapters: list[ReasoningAdapter]) -> None:
        self.adapters = adapters
        self._breakers = {a.name: _Breaker() for a in adapters}

    @property
    def configured(self) -> bool:
        return bool(self.adapters)

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        max_output_tokens: int = 800,
        allow_failover: bool = True,
        deadline_s: float | None = None,
    ) -> ReasoningResult:
        if not self.adapters:
            raise ProviderUnavailable("no reasoning provider is configured for this deployment")
        deadline = time.monotonic() + (deadline_s or get_settings().provider_timeout_s)
        candidates = self.adapters if allow_failover else self.adapters[:1]
        last_err: str = "unavailable"
        for adapter in candidates:
            br = self._breakers[adapter.name]
            if not br.allow():
                last_err = f"{adapter.name} circuit open"
                continue
            for attempt in range(3):
                remaining = deadline - time.monotonic()
                if remaining <= 0.2:
                    break
                try:
                    res = await asyncio.wait_for(
                        adapter.complete(
                            system=system, messages=messages, tools=tools, max_output_tokens=max_output_tokens
                        ),
                        timeout=remaining,
                    )
                    br.record(True)
                    return res
                except (_Transient, httpx.TransportError, TimeoutError) as exc:
                    br.record(False)
                    last_err = f"{adapter.name}: {type(exc).__name__}"
                    log.warning("reasoning_transient_failure", extra={"provider": adapter.name, "attempt": attempt})
                    await asyncio.sleep(
                        min(
                            2**attempt * 0.25 + random.random() * 0.2,  # noqa: S311
                            max(0.0, deadline - time.monotonic() - 0.2),
                        )
                    )
        raise ProviderUnavailable(f"reasoning provider unavailable ({last_err})")


_router: ReasoningRouter | None = None
_http: httpx.AsyncClient | None = None


def _build(name: ProviderName, s: Settings, client: httpx.AsyncClient) -> ReasoningAdapter | None:
    try:
        if name is ProviderName.OPENAI:
            return OpenAIChatAdapter(s, client)
        if name is ProviderName.ANTHROPIC:
            return AnthropicMessagesAdapter(s, client)
        if name is ProviderName.DEV_MOCK:
            return DevMockAdapter()
    except ProviderUnavailable:
        log.error("reasoning_provider_misconfigured", extra={"provider": name.value})
    return None


def get_reasoning_router() -> ReasoningRouter:
    global _router, _http
    if _router is None:
        s = get_settings()
        _http = httpx.AsyncClient(timeout=httpx.Timeout(s.provider_timeout_s, connect=5.0))
        adapters = [
            a
            for a in (_build(s.reasoning_provider, s, _http), _build(s.reasoning_fallback_provider, s, _http))
            if a is not None
        ]
        _router = ReasoningRouter(adapters)
    return _router


def set_reasoning_router(router: ReasoningRouter | None) -> None:
    """Test seam; also used to reset after configuration changes."""
    global _router
    _router = router


async def close_reasoning() -> None:
    global _http, _router
    if _http is not None:
        await _http.aclose()
    _http, _router = None, None
