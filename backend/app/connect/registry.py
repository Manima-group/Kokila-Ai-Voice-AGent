"""Kokila Connect connector catalog.

`adapter` = "implemented" means Kokila ships a working adapter that can be connected and verified with real
credentials. "planned" connectors are listed truthfully as not yet available (never shown as connected).
"""

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True)
class ConnectorSpec:
    key: str
    name: str
    category: str
    auth: str  # api_key | oauth2 | bearer | internal | webhook
    adapter: str  # implemented | planned
    description: str
    credential_fields: tuple[str, ...] = field(default_factory=tuple)
    read_scopes: tuple[str, ...] = field(default_factory=tuple)
    write_scopes: tuple[str, ...] = field(default_factory=tuple)
    docs: str = ""


CONNECTORS: Final[tuple[ConnectorSpec, ...]] = (
    ConnectorSpec(
        "manima_hub",
        "Manima Hub",
        "crm_erp",
        "bearer",
        "implemented",
        "First-party connector using the Kokila Connect host protocol (manifest + metric endpoints).",
        ("base_url", "access_token"),
        ("metrics.read",),
        ("tasks.write",),
        "docs/INTEGRATION_GUIDE.md#manima-hub",
    ),
    ConnectorSpec(
        "erpnext",
        "ERPNext",
        "crm_erp",
        "api_key",
        "implemented",
        "Sales invoices, receivables and stock levels via the Frappe REST API.",
        ("base_url", "api_key", "api_secret"),
        ("sales.read", "receivables.read", "inventory.read"),
        (),
        "https://docs.frappe.io/framework/user/en/api/rest",
    ),
    ConnectorSpec(
        "google_calendar",
        "Google Calendar",
        "productivity",
        "oauth2",
        "implemented",
        "Appointment availability and booking (connected from the Calling Agent appointments flow).",
        (),
        ("calendar.read",),
        ("calendar.write",),
    ),
    ConnectorSpec(
        "n8n", "n8n", "automation", "webhook", "implemented", "Signed Kokila event webhooks delivered to n8n workflows.", (), (), ("events.deliver",)
    ),
    ConnectorSpec("zoho_crm", "Zoho CRM", "crm_erp", "oauth2", "planned", "Leads, accounts and deals."),
    ConnectorSpec("tally", "Tally", "accounting", "api_key", "planned", "Ledgers, vouchers and stock."),
    ConnectorSpec("salesforce", "Salesforce", "crm_erp", "oauth2", "planned", "Accounts, leads and opportunities."),
    ConnectorSpec("sap", "SAP", "crm_erp", "oauth2", "planned", "Sales and inventory business objects."),
    ConnectorSpec("dynamics", "Microsoft Dynamics", "crm_erp", "oauth2", "planned", "Dataverse entities."),
    ConnectorSpec("gmail", "Gmail", "communication", "oauth2", "planned", "Mail search, drafts and approved sends."),
    ConnectorSpec("outlook", "Outlook", "communication", "oauth2", "planned", "Mail and calendar via Microsoft Graph."),
    ConnectorSpec("whatsapp", "WhatsApp Business", "communication", "api_key", "planned", "Opt-in messaging and templates."),
    ConnectorSpec("teams", "Microsoft Teams", "communication", "oauth2", "planned", "Messages and meeting metadata."),
    ConnectorSpec("slack", "Slack", "communication", "oauth2", "planned", "Channel messages and approved posts."),
)

BY_KEY: Final[dict[str, ConnectorSpec]] = {c.key: c for c in CONNECTORS}
