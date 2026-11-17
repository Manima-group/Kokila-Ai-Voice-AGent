"""Provider-neutral voice interface. Each adapter declares the capabilities it actually supports."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class UnsupportedCapability(Exception):
    def __init__(self, provider: str, capability: str):
        super().__init__(f"Provider '{provider}' does not support '{capability}'")
        self.provider = provider
        self.capability = capability


class ProviderError(Exception):
    """Transient or permanent provider failure (network, 4xx/5xx)."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class AgentSpec:
    name: str
    system_prompt: str
    greeting: str
    language: str  # kokila code: en | hi | kn | te
    voice_id: str
    tools: list[dict] = field(default_factory=list)
    webhook_url: str | None = None
    post_call_fields: list[dict] = field(default_factory=list)
    max_call_seconds: int = 900


@dataclass
class ProviderAgentRef:
    agent_id: str
    llm_id: str | None = None


@dataclass
class OutboundRequest:
    from_number: str
    to_number: str
    provider_agent_id: str
    idempotency_key: str
    metadata: dict[str, str]
    dynamic_variables: dict[str, str] = field(default_factory=dict)


@dataclass
class NormalizedEvent:
    event_type: str  # call_started | call_ended | call_analyzed | transcript_updated | call_inbound | transfer_*
    provider_call_id: str | None
    dedupe_key: str
    provider_agent_id: str | None = None
    direction: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    provider_status: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    transcript: str | None = None
    segments: list[dict] | None = None
    summary: str | None = None
    sentiment: str | None = None
    analysis: dict[str, Any] = field(default_factory=dict)
    disconnection_reason: str | None = None
    recording_url: str | None = None
    cost_minor: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class VoiceProvider(ABC):
    name: str
    capabilities: frozenset[str]
    supported_languages: frozenset[str]

    def require(self, capability: str) -> None:
        if capability not in self.capabilities:
            raise UnsupportedCapability(self.name, capability)

    @abstractmethod
    def create_agent(self, spec: AgentSpec) -> ProviderAgentRef: ...

    @abstractmethod
    def update_agent(self, ref: ProviderAgentRef, spec: AgentSpec) -> ProviderAgentRef: ...

    @abstractmethod
    def initiate_outbound_call(self, req: OutboundRequest) -> str: ...

    @abstractmethod
    def configure_inbound_route(self, phone_e164: str, provider_agent_id: str | None, inbound_webhook_url: str) -> None: ...

    @abstractmethod
    def terminate_call(self, provider_call_id: str) -> None: ...

    @abstractmethod
    def fetch_call(self, provider_call_id: str) -> NormalizedEvent: ...

    def fetch_transcript(self, provider_call_id: str) -> str | None:
        return self.fetch_call(provider_call_id).transcript

    def fetch_usage(self, provider_call_id: str) -> tuple[int | None, int | None]:
        ev = self.fetch_call(provider_call_id)
        return ev.duration_seconds, ev.cost_minor

    @abstractmethod
    def verify_webhook(self, raw_body: str, signature: str | None) -> bool: ...

    @abstractmethod
    def normalize_event(self, payload: dict) -> NormalizedEvent: ...
