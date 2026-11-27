"""Canonical capability registry (single source of truth for capability keys).

Products are licensed through `product.*` keys; every feature key depends on its product key, and a parent
never implicitly grants its children. Effective access is computed in `app.platform.entitlements`.
"""

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True)
class Capability:
    key: str
    req_id: str
    product: str  # calling_agent | business_assistant | platform
    label: str
    description: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    quota_metric: str | None = None


PRODUCT_CALLING_AGENT: Final = "product.calling_agent"
PRODUCT_BUSINESS_ASSISTANT: Final = "product.business_assistant"

CAPABILITIES: Final[tuple[Capability, ...]] = (
    Capability(PRODUCT_CALLING_AGENT, "KOK-P1", "calling_agent", "Calling Agent", "Access to the Calling Agent workspace"),
    Capability(PRODUCT_BUSINESS_ASSISTANT, "KOK-P2", "business_assistant", "Business Assistant", "Access to the Business Assistant workspace"),
    Capability("assistant.voice", "KOK-01", "business_assistant", "Assistant voice", "Voice conversations in the assistant", (PRODUCT_BUSINESS_ASSISTANT,)),
    Capability(
        "assistant.text",
        "KOK-02",
        "business_assistant",
        "Assistant text",
        "Text conversations and history",
        (PRODUCT_BUSINESS_ASSISTANT,),
        "assistant_messages",
    ),
    Capability("assistant.memory", "KOK-03", "business_assistant", "Personal memory", "User-approved long-term memory", ("assistant.text",)),
    Capability("assistant.research", "KOK-04", "business_assistant", "Web research", "Web research with citations", ("assistant.text",)),
    Capability("voice.inbound", "KOK-05", "calling_agent", "Inbound calls", "AI reception of inbound calls", ("voice.agents",), "voice_minutes"),
    Capability("voice.outbound", "KOK-06", "calling_agent", "Outbound campaigns", "Consent-based outbound campaigns", ("voice.agents",), "voice_minutes"),
    Capability("voice.agents", "KOK-07", "calling_agent", "Agent builder", "Agent builder, knowledge and call analytics", (PRODUCT_CALLING_AGENT,)),
    Capability("connect.embed", "KOK-08", "business_assistant", "Embedded widget", "SDK and embedded widget", (PRODUCT_BUSINESS_ASSISTANT,)),
    Capability("connect.analytics", "KOK-09", "business_assistant", "Business analytics", "Metric queries, charts and exports", (PRODUCT_BUSINESS_ASSISTANT,)),
    Capability("vision.documents", "KOK-10", "business_assistant", "Vision", "Images, documents and invoices", (PRODUCT_BUSINESS_ASSISTANT,)),
    Capability("automate.workflows", "KOK-11", "business_assistant", "Automations", "Workflows, webhooks and n8n", (PRODUCT_BUSINESS_ASSISTANT,)),
    Capability("proactive.alerts", "KOK-12", "business_assistant", "Proactive alerts", "Scheduled briefings and alerts", ("connect.analytics",)),
    Capability("meetings.intelligence", "KOK-13", "business_assistant", "Meetings", "Consented meeting summaries", (PRODUCT_BUSINESS_ASSISTANT,)),
    Capability("assistant.handsfree", "KOK-14", "business_assistant", "Hands-free", "Wake phrase and routines", ("assistant.voice",)),
    Capability("deployment.private", "KOK-15", "platform", "Private deployment", "Dedicated / private deployment"),
    Capability("developer.marketplace", "KOK-16", "platform", "Marketplace", "Connector SDK and marketplace"),
    Capability("assistant.identity", "KOK-20", "business_assistant", "Custom assistant name", "Custom name, voice and wake phrase", ("assistant.text",)),
    Capability("assistant.personal", "KOK-P3", "business_assistant", "Personal mode", "Personal assistant mode inside Business Assistant", ("assistant.text",)),
)

# KOK-17 platform.admin, KOK-18 platform.billing and KOK-19 platform.security are mandatory infrastructure,
# not purchasable capabilities, and are therefore not tenant-toggleable.

BY_KEY: Final[dict[str, Capability]] = {c.key: c for c in CAPABILITIES}

# Default packages applied by migration 0003 (Super Admin can change them per plan / tenant).
TRIAL_CAPABILITIES: Final[tuple[str, ...]] = (
    PRODUCT_CALLING_AGENT,
    "voice.agents",
    "voice.inbound",
    PRODUCT_BUSINESS_ASSISTANT,
    "assistant.text",
    "assistant.voice",
    "assistant.personal",
    "assistant.memory",
    "connect.analytics",
)


def closure_problems(enabled: set[str]) -> list[str]:
    """Return dependency violations for a set of enabled keys."""
    problems = []
    for key in sorted(enabled):
        cap = BY_KEY.get(key)
        if cap is None:
            problems.append(f"unknown capability '{key}'")
            continue
        problems += [f"{key} requires {dep}" for dep in cap.depends_on if dep not in enabled]
    return problems
