"""Import all models so Alembic and SQLAlchemy see the full metadata."""

from app.agents.models import Agent, AgentTool, AgentVersion, KnowledgeDocument, KnowledgeSource
from app.appointments.models import Appointment, CalendarConnection
from app.audit.models import AuditLog, DataRetentionPolicy, DeletionRequest
from app.billing.models import Invoice, PaymentTransaction, Plan, Subscription, UsageRecord
from app.campaigns.models import CallAttempt, Campaign, CampaignContact
from app.contacts.models import Contact, ContactConsent, Lead, LeadActivity, SuppressionEntry
from app.db.base import Base
from app.integrations.models import BackgroundJobFailure, IntegrationConnection, OutboxEvent, WebhookEvent
from app.telephony.models import Call, CallEvent, CallRecording, PhoneNumber, ProviderAccount
from app.tenants.models import PlatformSetting, RefreshToken, Tenant, TenantMembership, User

__all__ = [
    "Base",
    "Agent",
    "AgentTool",
    "AgentVersion",
    "KnowledgeDocument",
    "KnowledgeSource",
    "Appointment",
    "CalendarConnection",
    "AuditLog",
    "DataRetentionPolicy",
    "DeletionRequest",
    "Invoice",
    "PaymentTransaction",
    "Plan",
    "Subscription",
    "UsageRecord",
    "CallAttempt",
    "Campaign",
    "CampaignContact",
    "Contact",
    "ContactConsent",
    "Lead",
    "LeadActivity",
    "SuppressionEntry",
    "BackgroundJobFailure",
    "IntegrationConnection",
    "OutboxEvent",
    "WebhookEvent",
    "Call",
    "CallEvent",
    "CallRecording",
    "PhoneNumber",
    "ProviderAccount",
    "PlatformSetting",
    "RefreshToken",
    "Tenant",
    "TenantMembership",
    "User",
]
