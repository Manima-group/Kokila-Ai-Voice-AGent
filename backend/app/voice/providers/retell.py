"""Retell AI adapter built on the official retell-sdk. Live verification requires a Retell account (pending)."""

from datetime import UTC, datetime
from typing import Any

from app.voice.base import (
    AgentSpec,
    NormalizedEvent,
    OutboundRequest,
    ProviderAgentRef,
    ProviderError,
    UnsupportedCapability,
    VoiceProvider,
)

# Kokila language code -> Retell locale. Telugu (te-IN) is NOT in retell-sdk's language enum (checked v6.2.x),
# so it is reported as unsupported rather than silently falling back to another language.
RETELL_LANGS = {"en": "en-IN", "hi": "hi-IN", "kn": "kn-IN"}


def _ts(ms: Any) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if isinstance(ms, int | float) else None


def normalize_retell_payload(payload: dict, provider: str = "retell") -> NormalizedEvent:
    """Shared normalizer for Retell-shaped webhook payloads (also used by the mock provider)."""
    event = payload.get("event")
    if not isinstance(event, str):
        raise ValueError("payload.event missing")
    if event == "call_inbound":
        inbound = payload.get("call_inbound") or {}
        return NormalizedEvent(
            event_type="call_inbound",
            provider_call_id=None,
            dedupe_key=f"{provider}:inbound:{inbound.get('from_number')}:{inbound.get('to_number')}",
            provider_agent_id=inbound.get("agent_id"),
            direction="inbound",
            from_number=inbound.get("from_number"),
            to_number=inbound.get("to_number"),
        )
    call = payload.get("call")
    if not isinstance(call, dict) or not call.get("call_id"):
        raise ValueError("payload.call.call_id missing")
    analysis = call.get("call_analysis") or {}
    start, end = _ts(call.get("start_timestamp")), _ts(call.get("end_timestamp"))
    duration = None
    if call.get("duration_ms") is not None:
        duration = int(call["duration_ms"]) // 1000
    elif start and end:
        duration = int((end - start).total_seconds())
    cost = call.get("call_cost") or {}
    combined = cost.get("combined_cost")
    return NormalizedEvent(
        event_type=event,
        provider_call_id=call["call_id"],
        dedupe_key=f"{provider}:{call['call_id']}:{event}",
        provider_agent_id=call.get("agent_id"),
        direction=call.get("direction"),
        from_number=call.get("from_number"),
        to_number=call.get("to_number"),
        provider_status=call.get("call_status"),
        started_at=start,
        ended_at=end,
        duration_seconds=duration,
        transcript=call.get("transcript"),
        segments=call.get("transcript_object"),
        summary=analysis.get("call_summary"),
        sentiment=(analysis.get("user_sentiment") or None),
        analysis=analysis.get("custom_analysis_data") or {},
        disconnection_reason=call.get("disconnection_reason"),
        recording_url=call.get("recording_url"),
        cost_minor=int(round(combined)) if isinstance(combined, int | float) else None,  # Retell: USD cents
        metadata=call.get("metadata") or {},
    )


class RetellProvider(VoiceProvider):
    name = "retell"
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
    supported_languages = frozenset(RETELL_LANGS)

    def __init__(self, api_key: str):
        if not api_key:
            raise ProviderError("RETELL_API_KEY not configured", retryable=False)
        from retell import Retell

        self._key = api_key
        self._client = Retell(api_key=api_key, timeout=20.0, max_retries=2)

    def _lang(self, code: str) -> str:
        if code not in RETELL_LANGS:
            raise UnsupportedCapability(self.name, f"language:{code}")
        return RETELL_LANGS[code]

    def _wrap(self, fn, *a, **kw):
        import retell

        try:
            return fn(*a, **kw)
        except retell.APIStatusError as exc:
            raise ProviderError(f"Retell API error {exc.status_code}", retryable=exc.status_code >= 500) from exc
        except retell.APIConnectionError as exc:
            raise ProviderError("Retell connection error") from exc

    def _llm_params(self, spec: AgentSpec) -> dict:
        return {"general_prompt": spec.system_prompt, "begin_message": spec.greeting, "general_tools": spec.tools or None}

    def _agent_params(self, spec: AgentSpec) -> dict:
        p: dict[str, Any] = {
            "agent_name": spec.name,
            "voice_id": spec.voice_id,
            "language": self._lang(spec.language),
            "max_call_duration_ms": spec.max_call_seconds * 1000,
            "webhook_events": ["call_started", "call_ended", "call_analyzed"],
        }
        if spec.webhook_url:
            p["webhook_url"] = spec.webhook_url
        if spec.post_call_fields:
            p["post_call_analysis_data"] = spec.post_call_fields
        return p

    def create_agent(self, spec: AgentSpec) -> ProviderAgentRef:
        params = self._agent_params(spec)
        llm = self._wrap(self._client.llm.create, **self._llm_params(spec))
        agent = self._wrap(self._client.agent.create, response_engine={"type": "retell-llm", "llm_id": llm.llm_id}, **params)
        return ProviderAgentRef(agent_id=agent.agent_id, llm_id=llm.llm_id)

    def update_agent(self, ref: ProviderAgentRef, spec: AgentSpec) -> ProviderAgentRef:
        params = self._agent_params(spec)
        if ref.llm_id:
            self._wrap(self._client.llm.update, ref.llm_id, **self._llm_params(spec))
        self._wrap(self._client.agent.update, ref.agent_id, **params)
        return ref

    def initiate_outbound_call(self, req: OutboundRequest) -> str:
        resp = self._wrap(
            self._client.call.create_phone_call,
            from_number=req.from_number,
            to_number=req.to_number,
            override_agent_id=req.provider_agent_id,
            metadata=req.metadata,
            retell_llm_dynamic_variables=req.dynamic_variables,
            idempotency_key=req.idempotency_key,
        )
        return resp.call_id

    def configure_inbound_route(self, phone_e164: str, provider_agent_id: str | None, inbound_webhook_url: str) -> None:
        self._wrap(self._client.phone_number.update, phone_e164, inbound_webhook_url=inbound_webhook_url)

    def terminate_call(self, provider_call_id: str) -> None:
        self._wrap(self._client.call.stop, provider_call_id)

    def fetch_call(self, provider_call_id: str) -> NormalizedEvent:
        call = self._wrap(self._client.call.retrieve, provider_call_id)
        return normalize_retell_payload({"event": "call_fetched", "call": call.model_dump()})

    def verify_webhook(self, raw_body: str, signature: str | None) -> bool:
        if not signature:
            return False
        try:
            return bool(self._client.verify(raw_body, api_key=self._key, signature=signature))
        except Exception:  # noqa: BLE001 - malformed signature header
            return False

    def normalize_event(self, payload: dict) -> NormalizedEvent:
        return normalize_retell_payload(payload, "retell")
