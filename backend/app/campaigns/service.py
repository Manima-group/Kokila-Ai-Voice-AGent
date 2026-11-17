"""Consent-based outbound campaign engine: eligibility, compliance gates, dispatch, retries."""

import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.models import Agent
from app.billing.service import check_call_allowed, current_entitlement
from app.campaigns.models import CallAttempt, Campaign, CampaignContact
from app.contacts.models import Contact
from app.contacts.service import is_suppressed, valid_consent
from app.core.errors import AppError
from app.telephony.models import Call, PhoneNumber
from app.tenants.models import PlatformSetting, Tenant
from app.voice.base import OutboundRequest, ProviderError
from app.voice.registry import get_provider

log = logging.getLogger("kokila.campaigns")

# TRAI TCCCPR: commercial calls only between 09:00 and 21:00 IST. Enforced regardless of campaign settings.
LEGAL_START, LEGAL_END, LEGAL_TZ = time(9, 0), time(21, 0), ZoneInfo("Asia/Kolkata")
RETRYABLE_OUTCOMES = {"no_answer", "busy", "failed"}
ACTIVE_ATTEMPT = ("queued", "dispatched", "in_progress")


def kill_switch_on(db: Session) -> bool:
    s = db.get(PlatformSetting, "outbound_kill_switch")
    return bool(s and s.value.get("enabled"))


def _hm(v: str) -> time:
    h, m = v.split(":")
    return time(int(h), int(m))


def within_window(campaign: Campaign, at: datetime) -> tuple[bool, str | None]:
    legal = at.astimezone(LEGAL_TZ)
    if not (LEGAL_START <= legal.time() < LEGAL_END):
        return False, "outside_legal_hours_0900_2100_ist"
    local = at.astimezone(ZoneInfo(campaign.timezone))
    if local.weekday() not in (campaign.days_of_week or []):
        return False, "outside_campaign_days"
    if not (_hm(campaign.window_start) <= local.time() < _hm(campaign.window_end)):
        return False, "outside_campaign_window"
    if campaign.start_at and at < campaign.start_at:
        return False, "before_start"
    if campaign.end_at and at >= campaign.end_at:
        return False, "after_end"
    return True, None


def compliance_problems(db: Session, campaign: Campaign, tenant: Tenant, provider_name: str) -> list[str]:
    problems = []
    number = db.get(PhoneNumber, campaign.from_phone_number_id)
    if number is None or number.status != "active" or not number.outbound_enabled:
        problems.append("from_number_not_enabled_for_outbound")
    agent = db.get(Agent, campaign.agent_id)
    if agent is None or agent.status != "published" or not agent.provider_agent_id:
        problems.append("agent_not_published")
    if provider_name != "mock":
        comp = tenant.compliance or {}
        if not comp.get("outbound_approved"):
            problems.append("tenant_outbound_compliance_not_approved")
    return problems


def contact_eligibility(db: Session, campaign: Campaign, contact: Contact, at: datetime | None = None) -> str | None:
    """Return None if eligible, else the reason."""
    if is_suppressed(db, campaign.tenant_id, contact.phone_e164):
        return "suppressed"
    if not valid_consent(db, campaign.tenant_id, contact.id, campaign.purpose, at):
        return "no_valid_consent"
    return None


def evaluate_contacts(db: Session, campaign: Campaign) -> dict:
    counts = {"eligible": 0, "ineligible": 0}
    for cc, contact in db.execute(
        select(CampaignContact, Contact)
        .join(Contact, Contact.id == CampaignContact.contact_id)
        .where(CampaignContact.campaign_id == campaign.id, CampaignContact.status.in_(("pending", "eligible", "ineligible")))
    ).all():
        reason = contact_eligibility(db, campaign, contact)
        cc.status, cc.ineligible_reason = ("ineligible", reason) if reason else ("eligible", None)
        counts["ineligible" if reason else "eligible"] += 1
    return counts


def start_campaign(db: Session, campaign: Campaign) -> dict:
    tenant = db.get(Tenant, campaign.tenant_id)
    assert tenant is not None
    ent = current_entitlement(db, tenant.id)
    if ent is None or not ent.plan.features.get("outbound"):  # type: ignore[attr-defined]
        raise AppError("Your plan does not include outbound campaigns", code="feature_not_in_plan", status_code=402)
    problems = compliance_problems(db, campaign, tenant, get_provider().name)
    if problems:
        raise AppError("Compliance prerequisites not met: " + ", ".join(problems), code="compliance_blocked", status_code=409)
    counts = evaluate_contacts(db, campaign)
    if counts["eligible"] == 0:
        raise AppError("No eligible contacts (consent/suppression checks)", code="no_eligible_contacts", status_code=409)
    campaign.status = "running"
    return counts


def dispatch_campaign(db: Session, campaign: Campaign, now: datetime | None = None) -> dict:
    """Dispatch due eligible contacts up to concurrency. Safe to run concurrently (row locks + unique keys)."""
    now = now or datetime.now(UTC)
    stats: dict[str, Any] = {"dispatched": 0, "skipped": 0, "failed": 0, "reason": None}
    tenant = db.get(Tenant, campaign.tenant_id)
    assert tenant is not None
    if campaign.status != "running":
        stats["reason"] = "not_running"
        return stats
    if kill_switch_on(db) or tenant.outbound_paused or tenant.status != "active":
        stats["reason"] = "paused_by_kill_switch"
        return stats
    ok, why = within_window(campaign, now)
    if not ok:
        stats["reason"] = why
        return stats
    provider = get_provider()
    problems = compliance_problems(db, campaign, tenant, provider.name)
    if problems:
        stats["reason"] = ",".join(problems)
        return stats
    active = db.scalar(select(func.count()).select_from(CallAttempt).where(CallAttempt.campaign_id == campaign.id, CallAttempt.status.in_(ACTIVE_ATTEMPT))) or 0
    capacity = campaign.max_concurrency - active
    if capacity <= 0:
        stats["reason"] = "campaign_concurrency_limit"
        return stats
    due = db.scalars(
        select(CampaignContact)
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status == "eligible",
            (CampaignContact.next_attempt_at.is_(None)) | (CampaignContact.next_attempt_at <= now),
        )
        .order_by(CampaignContact.created_at)
        .limit(capacity)
        .with_for_update(skip_locked=True)
    ).all()
    agent = db.get(Agent, campaign.agent_id)
    number = db.get(PhoneNumber, campaign.from_phone_number_id)
    assert agent is not None and number is not None
    for cc in due:
        contact = db.get(Contact, cc.contact_id)
        assert contact is not None
        reason = contact_eligibility(db, campaign, contact, now)  # re-check at dial time
        if reason:
            cc.status, cc.ineligible_reason = "ineligible", reason
            stats["skipped"] += 1
            continue
        try:
            check_call_allowed(db, campaign.tenant_id)
        except AppError as exc:
            stats["reason"] = exc.code
            break
        attempt_no = cc.attempts + 1
        attempt = CallAttempt(
            tenant_id=campaign.tenant_id,
            campaign_id=campaign.id,
            campaign_contact_id=cc.id,
            attempt_no=attempt_no,
            idempotency_key=f"kk-{cc.id.hex}-{attempt_no}",
            status="queued",
            meta={},
        )
        db.add(attempt)
        cc.attempts, cc.status = attempt_no, "in_progress"
        db.commit()  # persist the attempt before contacting the provider (crash-safe, dedup by unique key)
        try:
            provider_call_id = provider.initiate_outbound_call(
                OutboundRequest(
                    from_number=number.e164,
                    to_number=contact.phone_e164,
                    provider_agent_id=agent.provider_agent_id or "",
                    idempotency_key=attempt.idempotency_key,
                    metadata={"kokila_tenant_id": str(campaign.tenant_id), "kokila_attempt_id": str(attempt.id), "kokila_campaign_id": str(campaign.id)},
                    dynamic_variables={"customer_name": contact.name or ""},
                )
            )
        except ProviderError as exc:
            attempt.status, attempt.error = "failed", str(exc)[:500]
            _schedule_retry(campaign, cc, "failed", now, retryable=exc.retryable)
            stats["failed"] += 1
            db.commit()
            continue
        call = Call(
            tenant_id=campaign.tenant_id,
            provider=provider.name,
            provider_call_id=provider_call_id,
            direction="outbound",
            agent_id=agent.id,
            agent_version_id=agent.published_version_id,
            phone_number_id=number.id,
            contact_id=contact.id,
            campaign_id=campaign.id,
            call_attempt_id=attempt.id,
            from_number=number.e164,
            to_number=contact.phone_e164,
            status="provider_accepted",
            is_mock=provider.name == "mock",
            extracted={},
        )
        db.add(call)
        db.flush()
        attempt.status, attempt.provider_call_id, attempt.call_id, attempt.dispatched_at = "dispatched", provider_call_id, call.id, now
        db.commit()
        stats["dispatched"] += 1
    _maybe_complete(db, campaign)
    db.commit()
    return stats


def _schedule_retry(campaign: Campaign, cc: CampaignContact, outcome: str | None, now: datetime, retryable: bool = True) -> None:
    cc.last_outcome = outcome
    if retryable and outcome in RETRYABLE_OUTCOMES and cc.attempts < campaign.max_attempts:
        cc.status, cc.next_attempt_at = "eligible", now + timedelta(minutes=campaign.retry_delay_minutes)
    elif outcome in RETRYABLE_OUTCOMES or not retryable:
        cc.status = "exhausted"
    else:
        cc.status = "completed"


def on_call_finished(db: Session, call: Call) -> None:
    from app.calls.service import TERMINAL

    if not call.call_attempt_id or call.status not in TERMINAL:
        return
    attempt = db.get(CallAttempt, call.call_attempt_id)
    if attempt is None or attempt.status in ("completed", "failed"):
        return
    attempt.status = "completed" if call.status == "completed" else "failed"
    attempt.outcome = call.outcome
    cc = db.get(CampaignContact, attempt.campaign_contact_id)
    campaign = db.get(Campaign, attempt.campaign_id)
    if cc and campaign:
        if call.outcome == "do_not_call":
            cc.status, cc.last_outcome = "cancelled", "do_not_call"
        else:
            _schedule_retry(campaign, cc, call.outcome or ("failed" if call.status == "failed" else None), datetime.now(UTC))
        _maybe_complete(db, campaign)


def _maybe_complete(db: Session, campaign: Campaign) -> None:
    if campaign.status != "running":
        return
    open_count = (
        db.scalar(
            select(func.count())
            .select_from(CampaignContact)
            .where(CampaignContact.campaign_id == campaign.id, CampaignContact.status.in_(("pending", "eligible", "in_progress")))
        )
        or 0
    )
    if open_count == 0:
        campaign.status = "completed"


def dispatch_all(db: Session) -> dict:
    results = {}
    for cid in db.scalars(select(Campaign.id).where(Campaign.status == "running")).all():
        campaign = db.get(Campaign, cid)
        if campaign is None:
            continue
        try:
            results[str(cid)] = dispatch_campaign(db, campaign)
        except Exception as exc:  # noqa: BLE001 - isolate tenants from each other's failures
            db.rollback()
            log.exception("dispatch failed for campaign %s", cid)
            results[str(cid)] = {"error": str(exc)[:200]}
    return results


def campaign_stats(db: Session, campaign_id: uuid.UUID) -> dict:
    by_status = dict(
        db.execute(select(CampaignContact.status, func.count()).where(CampaignContact.campaign_id == campaign_id).group_by(CampaignContact.status)).all()
    )
    by_outcome = dict(
        db.execute(select(Call.outcome, func.count()).where(Call.campaign_id == campaign_id, Call.outcome.is_not(None)).group_by(Call.outcome)).all()
    )
    attempts = db.scalar(select(func.count()).select_from(CallAttempt).where(CallAttempt.campaign_id == campaign_id)) or 0
    return {"contacts_by_status": by_status, "outcomes": by_outcome, "attempts": attempts}
