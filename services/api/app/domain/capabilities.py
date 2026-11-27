"""Stable capability registry (spec §25, §26.4).

This module is the canonical, checked-in source of capability keys. Keys are
immutable once published (§29.1). The registry is seeded into
``capability_catalog`` by migration and by ``python -m app.cli sync-catalog``.

A parent module never implicitly grants its children: each granular key is
evaluated on its own and only *depends on* its parent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final


class Product(StrEnum):
    ASSISTANT = "assistant"
    VOICE = "voice"
    CONNECT = "connect"
    PRO = "pro"
    PLATFORM = "platform"


@dataclass(frozen=True, slots=True)
class CapabilityDef:
    key: str
    requirement_id: str
    module: str
    description: str
    product: Product
    dependencies: tuple[str, ...] = ()
    quota_metric: str | None = None
    # Platform infrastructure (security, identity, audit) is mandatory and not
    # a purchasable feature; it cannot be toggled per tenant (§26.4).
    purchasable: bool = True
    deployment_types: tuple[str, ...] = ("hosted", "dedicated", "private")
    tags: tuple[str, ...] = field(default_factory=tuple)


_DEFS: Final[tuple[CapabilityDef, ...]] = (
    # --- Assistant (B2C) ------------------------------------------------------
    CapabilityDef(
        "assistant.text",
        "KOK-02",
        "assistant",
        "Text conversation, reasoning and history",
        Product.ASSISTANT,
        quota_metric="assistant.turns",
    ),
    CapabilityDef(
        "assistant.voice",
        "KOK-01",
        "assistant",
        "Real-time browser voice, interruption and multilingual speech",
        Product.ASSISTANT,
        ("assistant.text",),
        quota_metric="assistant.voice_seconds",
    ),
    CapabilityDef(
        "assistant.memory",
        "KOK-03",
        "assistant",
        "User-editable personal memory and controls",
        Product.ASSISTANT,
        ("assistant.text",),
    ),
    CapabilityDef(
        "assistant.memory.write",
        "KOK-03-WRITE",
        "assistant",
        "Assistant may propose and save memory items",
        Product.ASSISTANT,
        ("assistant.memory",),
    ),
    CapabilityDef(
        "assistant.research",
        "KOK-04",
        "assistant",
        "Web research with citations, coding, content",
        Product.ASSISTANT,
        ("assistant.text",),
        quota_metric="assistant.research_queries",
    ),
    CapabilityDef(
        "assistant.handsfree",
        "KOK-14",
        "assistant",
        "Wake word, cross-device continuity, software routines",
        Product.ASSISTANT,
        ("assistant.voice",),
    ),
    CapabilityDef(
        "assistant.identity",
        "KOK-20",
        "assistant",
        "Custom assistant names, wake phrases and identity preferences",
        Product.ASSISTANT,
        ("assistant.text",),
    ),
    # --- Voice (B2B) ----------------------------------------------------------
    CapabilityDef(
        "voice.agents", "KOK-07", "voice", "Agent builder, versions, knowledge, call analytics", Product.VOICE
    ),
    CapabilityDef(
        "voice.inbound",
        "KOK-05",
        "voice",
        "Inbound reception, transfer, consented recordings",
        Product.VOICE,
        ("voice.agents",),
        quota_metric="voice.minutes",
    ),
    CapabilityDef(
        "voice.outbound",
        "KOK-06",
        "voice",
        "Consent-based campaigns and suppression",
        Product.VOICE,
        ("voice.agents",),
        quota_metric="voice.minutes",
    ),
    CapabilityDef(
        "voice.crm",
        "KOK-05",
        "voice",
        "Contacts, consent ledger, suppression, leads and activities",
        Product.VOICE,
        ("voice.agents",),
    ),
    CapabilityDef(
        "voice.appointments",
        "KOK-05",
        "voice",
        "Appointment booking from calls, calendar availability",
        Product.VOICE,
        ("voice.crm",),
    ),
    # --- Connect --------------------------------------------------------------
    CapabilityDef(
        "connect.embed", "KOK-08", "connect", "SDK, host identity delegation, embeddable widget", Product.CONNECT
    ),
    CapabilityDef(
        "connect.analytics",
        "KOK-09",
        "connect",
        "Governed metric queries, dashboards, exports",
        Product.CONNECT,
        ("connect.embed",),
        quota_metric="analytics.queries",
    ),
    # --- Pro modules ----------------------------------------------------------
    CapabilityDef(
        "vision.documents",
        "KOK-10",
        "vision",
        "Images, documents, invoices, camera ingestion",
        Product.PRO,
        quota_metric="vision.pages",
    ),
    CapabilityDef(
        "automate.workflows",
        "KOK-11",
        "automate",
        "Versioned workflows, approvals, n8n",
        Product.PRO,
        quota_metric="automate.runs",
    ),
    CapabilityDef(
        "proactive.alerts",
        "KOK-12",
        "proactive",
        "Scheduled briefings and KPI alerts",
        Product.PRO,
        ("connect.analytics", "automate.workflows"),
    ),
    CapabilityDef(
        "meetings.intelligence",
        "KOK-13",
        "meetings",
        "Consent-aware transcription and minutes",
        Product.PRO,
        quota_metric="meetings.minutes",
    ),
    CapabilityDef(
        "deployment.private",
        "KOK-15",
        "deployment",
        "Dedicated and private operation",
        Product.PRO,
        deployment_types=("dedicated", "private"),
    ),
    CapabilityDef(
        "developer.marketplace",
        "KOK-16",
        "marketplace",
        "Connector SDK, review, distribution",
        Product.PRO,
        ("connect.embed",),
    ),
    # --- Platform infrastructure (not purchasable) ----------------------------
    CapabilityDef(
        "platform.admin",
        "KOK-17",
        "platform",
        "Tenants, packages, controls, quotas, audit",
        Product.PLATFORM,
        purchasable=False,
    ),
    CapabilityDef(
        "platform.billing",
        "KOK-18",
        "platform",
        "Subscriptions, usage, reconciliation",
        Product.PLATFORM,
        purchasable=False,
    ),
    CapabilityDef(
        "platform.security",
        "KOK-19",
        "platform",
        "Isolation, privacy, reliability, compliance",
        Product.PLATFORM,
        purchasable=False,
    ),
)

_CONNECTORS: Final[tuple[tuple[str, str], ...]] = (
    ("tally", "Tally ledger, vouchers and stock"),
    ("zoho", "Zoho CRM"),
    ("salesforce", "Salesforce CRM"),
    ("sap", "SAP business objects"),
    ("dynamics", "Microsoft Dynamics / Dataverse"),
    ("gmail", "Gmail"),
    ("outlook", "Outlook mail and calendar"),
    ("whatsapp", "WhatsApp Business"),
    ("teams", "Microsoft Teams"),
    ("slack", "Slack"),
    ("n8n", "n8n workflow triggers"),
    ("manima", "Manima Hub / Manima One"),
    ("erpnext", "ERPNext / Frappe"),
)

CONNECTOR_DEFS: Final[tuple[CapabilityDef, ...]] = tuple(
    CapabilityDef(
        f"connector.{k}",
        f"KOK-CONN-{k.upper()}",
        "connectors",
        desc,
        Product.CONNECT,
        ("connect.embed",),
        tags=("connector",),
    )
    for k, desc in _CONNECTORS
)

ALL_CAPABILITIES: Final[tuple[CapabilityDef, ...]] = _DEFS + CONNECTOR_DEFS
CAPABILITIES: Final[dict[str, CapabilityDef]] = {c.key: c for c in ALL_CAPABILITIES}
INFRASTRUCTURE_KEYS: Final[frozenset[str]] = frozenset(c.key for c in ALL_CAPABILITIES if not c.purchasable)
CATALOG_VERSION: Final[int] = 2


class CapabilityKey(StrEnum):
    """Typed handles for capabilities referenced directly from code."""

    ASSISTANT_TEXT = "assistant.text"
    ASSISTANT_VOICE = "assistant.voice"
    ASSISTANT_MEMORY = "assistant.memory"
    ASSISTANT_MEMORY_WRITE = "assistant.memory.write"
    ASSISTANT_RESEARCH = "assistant.research"
    ASSISTANT_HANDSFREE = "assistant.handsfree"
    ASSISTANT_IDENTITY = "assistant.identity"
    VOICE_AGENTS = "voice.agents"
    VOICE_INBOUND = "voice.inbound"
    VOICE_OUTBOUND = "voice.outbound"
    VOICE_CRM = "voice.crm"
    VOICE_APPOINTMENTS = "voice.appointments"
    CONNECT_EMBED = "connect.embed"
    CONNECT_ANALYTICS = "connect.analytics"
    PLATFORM_ADMIN = "platform.admin"


def find_dependency_cycle(deps: dict[str, tuple[str, ...] | list[str]]) -> list[str] | None:
    """Return a cycle path if the dependency graph contains one, else None."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = dict.fromkeys(deps, WHITE)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = GREY
        stack.append(node)
        for nxt in deps.get(node, ()):
            if colour.get(nxt, WHITE) == GREY:
                return stack[stack.index(nxt) :] + [nxt]
            if colour.get(nxt, WHITE) == WHITE and nxt in deps:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        colour[node] = BLACK
        return None

    for n in deps:
        if colour[n] == WHITE:
            cyc = visit(n)
            if cyc:
                return cyc
    return None


def validate_registry() -> None:
    """Fail fast on unknown dependency references or cycles (checked in CI)."""
    for c in ALL_CAPABILITIES:
        for d in c.dependencies:
            if d not in CAPABILITIES:
                raise ValueError(f"capability {c.key} depends on unknown {d}")
    if len(CAPABILITIES) != len(ALL_CAPABILITIES):
        raise ValueError("duplicate capability key in registry")
    cyc = find_dependency_cycle({c.key: c.dependencies for c in ALL_CAPABILITIES})
    if cyc:
        raise ValueError(f"capability dependency cycle: {' -> '.join(cyc)}")


validate_registry()
