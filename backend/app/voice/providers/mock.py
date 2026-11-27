"""Deterministic MOCK voice provider for local development and CI.

It never places a real phone call. Events it emits are Retell-shaped and HMAC-signed with
MOCK_WEBHOOK_SECRET so the production webhook pipeline (verification, dedupe, state machine) is exercised.
"""

import json
import time
import uuid

from retell.lib.webhook_auth import symmetric

from app.voice.base import AgentSpec, NormalizedEvent, OutboundRequest, ProviderAgentRef, VoiceProvider
from app.voice.providers.retell import normalize_retell_payload


class MockVoiceProvider(VoiceProvider):
    name = "mock"
    capabilities = frozenset(
        {
            "create_agent",
            "update_agent",
            "outbound",
            "inbound_route",
            "terminate",
            "fetch_call",
            "webhook_verify",
            "inbound_webhook",
            "transfer",
        }
    )
    supported_languages = frozenset({"en", "hi", "kn", "te"})  # mock only; NOT evidence of real speech support

    def __init__(self, secret: str, fail_outbound: bool = False):
        self._secret = secret
        self.fail_outbound = fail_outbound
        self.placed: list[OutboundRequest] = []
        self._by_key: dict[str, str] = {}

    def create_agent(self, spec: AgentSpec) -> ProviderAgentRef:
        return ProviderAgentRef(agent_id=f"mock_agent_{uuid.uuid4().hex[:12]}", llm_id=f"mock_llm_{uuid.uuid4().hex[:8]}")

    def update_agent(self, ref: ProviderAgentRef, spec: AgentSpec) -> ProviderAgentRef:
        return ref

    def initiate_outbound_call(self, req: OutboundRequest) -> str:
        from app.voice.base import ProviderError

        if self.fail_outbound:
            raise ProviderError("mock provider outage")
        if req.idempotency_key in self._by_key:  # provider-side idempotency, like Retell's idempotency_key
            return self._by_key[req.idempotency_key]
        call_id = f"mock_call_{uuid.uuid4().hex[:16]}"
        self._by_key[req.idempotency_key] = call_id
        self.placed.append(req)
        return call_id

    def configure_inbound_route(self, phone_e164: str, provider_agent_id: str | None, inbound_webhook_url: str) -> None:
        return None

    def terminate_call(self, provider_call_id: str) -> None:
        return None

    def fetch_call(self, provider_call_id: str) -> NormalizedEvent:
        return NormalizedEvent(event_type="call_fetched", provider_call_id=provider_call_id, dedupe_key=f"fetch:{provider_call_id}")

    def sign(self, raw_body: str) -> str:
        return symmetric["sign"](raw_body, self._secret, int(time.time() * 1000))

    def verify_webhook(self, raw_body: str, signature: str | None) -> bool:
        return bool(signature) and bool(symmetric["verify"](raw_body, self._secret, signature))

    def normalize_event(self, payload: dict) -> NormalizedEvent:
        return normalize_retell_payload(payload, "mock")

    def signed(self, payload: dict) -> tuple[str, str]:
        body = json.dumps(payload, separators=(",", ":"))
        return body, self.sign(body)
