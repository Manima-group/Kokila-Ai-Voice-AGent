import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contacts.models import Contact, ContactConsent, Lead, LeadActivity, SuppressionEntry

POSITIVE = {"interested", "qualified", "appointment_requested", "appointment_confirmed", "callback_requested"}

# Deterministic business rules: call outcome -> (lead status, score delta)
OUTCOME_RULES: dict[str, tuple[str | None, int]] = {
    "qualified": ("qualified", 40),
    "appointment_confirmed": ("qualified", 50),
    "appointment_requested": ("qualified", 30),
    "interested": ("contacted", 20),
    "callback_requested": ("contacted", 10),
    "human_transfer": ("contacted", 5),
    "not_interested": ("unqualified", -20),
    "do_not_call": ("lost", -100),
}


def get_or_create_contact(db: Session, tenant_id: uuid.UUID, phone_e164: str, *, name: str | None = None, source: str = "manual") -> Contact:
    stmt = (
        insert(Contact)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, phone_e164=phone_e164, name=name, source=source, tags=[], attributes={})
        .on_conflict_do_nothing(index_elements=["tenant_id", "phone_e164"])
    )
    db.execute(stmt)
    contact = db.scalar(select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone_e164 == phone_e164))
    assert contact is not None
    if name and not contact.name:
        contact.name = name
    return contact


def is_suppressed(db: Session, tenant_id: uuid.UUID, phone_e164: str) -> SuppressionEntry | None:
    return db.scalar(select(SuppressionEntry).where(SuppressionEntry.tenant_id == tenant_id, SuppressionEntry.phone_e164 == phone_e164))


def valid_consent(db: Session, tenant_id: uuid.UUID, contact_id: uuid.UUID, purpose: str, at: datetime | None = None) -> ContactConsent | None:
    at = at or datetime.now(UTC)
    for c in db.scalars(
        select(ContactConsent).where(
            ContactConsent.tenant_id == tenant_id,
            ContactConsent.contact_id == contact_id,
            ContactConsent.purpose == purpose,
            ContactConsent.channel == "voice",
            ContactConsent.status == "granted",
        )
    ):
        if c.granted_at <= at and (c.expires_at is None or c.expires_at > at):
            return c
    return None


def suppress(db: Session, tenant_id: uuid.UUID, phone_e164: str, reason: str, source: str) -> None:
    """Opt-out: suppress number, revoke all voice consents, cancel pending campaign contacts. Immediate."""
    from app.campaigns.models import CampaignContact

    db.execute(
        insert(SuppressionEntry)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, phone_e164=phone_e164, reason=reason, source=source, attributes={})
        .on_conflict_do_nothing(index_elements=["tenant_id", "phone_e164"])
    )
    contact = db.scalar(select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone_e164 == phone_e164))
    if contact:
        now = datetime.now(UTC)
        for c in db.scalars(select(ContactConsent).where(ContactConsent.contact_id == contact.id, ContactConsent.status == "granted")):
            c.status, c.revoked_at = "revoked", now
        for cc in db.scalars(select(CampaignContact).where(CampaignContact.contact_id == contact.id, CampaignContact.status.in_(("pending", "eligible")))):
            cc.status, cc.ineligible_reason = "cancelled", "opted_out"


def apply_outcome_to_lead(
    db: Session, tenant_id: uuid.UUID, contact: Contact, outcome: str | None, call_id: uuid.UUID, source: str, summary: str | None, analysis: dict
) -> Lead | None:
    lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.contact_id == contact.id).order_by(Lead.created_at.desc()))
    if lead is None and (source == "inbound_call" or (outcome in POSITIVE)):
        lead = Lead(tenant_id=tenant_id, contact_id=contact.id, source=source, status="new", qualification={})
        db.add(lead)
        db.flush()
    if lead is None:
        return None
    rule = OUTCOME_RULES.get(outcome or "")
    if rule:
        status, delta = rule
        if status and status != lead.status and lead.status != "converted":
            db.add(LeadActivity(tenant_id=tenant_id, lead_id=lead.id, kind="status_change", body=f"{lead.status} -> {status}", call_id=call_id))
            lead.status = status
        lead.score = max(0, min(100, lead.score + delta))
    if outcome:
        lead.last_outcome = outcome
    if outcome == "callback_requested":
        lead.next_follow_up_at = datetime.now(UTC) + timedelta(days=1)
        db.add(
            LeadActivity(
                tenant_id=tenant_id, lead_id=lead.id, kind="task", body="Callback requested by customer", due_at=lead.next_follow_up_at, call_id=call_id
            )
        )
    if outcome == "human_transfer":
        db.add(
            LeadActivity(
                tenant_id=tenant_id,
                lead_id=lead.id,
                kind="task",
                body="Human follow-up required",
                call_id=call_id,
                due_at=datetime.now(UTC) + timedelta(hours=2),
            )
        )
    if analysis:
        lead.qualification = {**(lead.qualification or {}), **{k: v for k, v in analysis.items() if k != "outcome"}}
    db.add(LeadActivity(tenant_id=tenant_id, lead_id=lead.id, kind="call", body=summary or f"Call outcome: {outcome}", call_id=call_id))
    return lead
