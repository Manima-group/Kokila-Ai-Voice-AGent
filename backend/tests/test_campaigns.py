import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.campaigns.models import CallAttempt, Campaign, CampaignContact
from app.campaigns.service import compliance_problems, dispatch_campaign, within_window
from app.telephony.models import Call
from app.tenants.models import PlatformSetting, Tenant
from tests.conftest import grant_plan, make_published_agent, mock_provider, post_signed, register

# Monday 2030-01-07 11:00 IST == 05:30 UTC
IN_HOURS = datetime(2030, 1, 7, 5, 30, tzinfo=UTC)
NIGHT = datetime(2030, 1, 7, 17, 0, tzinfo=UTC)  # 22:30 IST


def _setup(client, db, *, consent=True, outbound=True):
    h, tid, _ = register(client)
    grant_plan(db, tid, outbound=outbound)
    agent = make_published_agent(client, h)
    num = client.post("/api/v1/phone-numbers", json={"e164": "+918041230000", "outbound_enabled": True, "number_type": "service"}, headers=h).json()
    contacts = []
    for i in range(3):
        c = client.post("/api/v1/contacts", json={"phone": f"98450000{i:02d}", "name": f"C{i}"}, headers=h).json()
        if consent:
            r = client.post(
                f"/api/v1/contacts/{c['id']}/consents", json={"purpose": "sales", "source": "web_form", "evidence": "Form #123 submitted 2026-11-01"}, headers=h
            )
            assert r.status_code == 201
        contacts.append(c)
    camp = client.post(
        "/api/v1/campaigns",
        json={
            "name": "Diwali follow-up",
            "purpose": "sales",
            "agent_id": agent["id"],
            "from_phone_number_id": num["id"],
            "max_concurrency": 2,
            "max_attempts": 2,
            "retry_delay_minutes": 15,
            "window_start": "09:00",
            "window_end": "20:00",
        },
        headers=h,
    ).json()
    r = client.post(f"/api/v1/campaigns/{camp['id']}/contacts", json={"contact_ids": [c["id"] for c in contacts]}, headers=h)
    assert r.status_code == 200, r.text
    return h, tid, camp, contacts


def test_missing_consent_blocks_start(client, db):
    h, _, camp, _ = _setup(client, db, consent=False)
    r = client.post(f"/api/v1/campaigns/{camp['id']}/start", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_eligible_contacts"
    items = client.get(f"/api/v1/campaigns/{camp['id']}/contacts", headers=h).json()["items"]
    assert {i["ineligible_reason"] for i in items} == {"no_valid_consent"}


def test_plan_without_outbound_blocks(client, db):
    h, _, camp, _ = _setup(client, db, outbound=False)
    r = client.post(f"/api/v1/campaigns/{camp['id']}/start", headers=h)
    assert r.status_code == 402


def test_dispatch_flow_suppression_retry_and_dedupe(client, db):
    h, tid, camp, contacts = _setup(client, db)
    client.post("/api/v1/suppression", json={"phone": contacts[2]["phone_e164"], "reason": "dnd"}, headers=h)
    assert client.post(f"/api/v1/campaigns/{camp['id']}/start", headers=h).status_code == 200
    c = db.get(Campaign, uuid.UUID(camp["id"]))
    assert dispatch_campaign(db, c, now=NIGHT)["reason"] == "outside_legal_hours_0900_2100_ist"
    stats = dispatch_campaign(db, c, now=IN_HOURS)
    assert stats["dispatched"] == 2
    assert len(mock_provider().placed) == 2
    # suppressed contact never dialled
    assert contacts[2]["phone_e164"] not in [p.to_number for p in mock_provider().placed]
    # concurrency limit reached -> no more dispatch
    assert dispatch_campaign(db, c, now=IN_HOURS)["reason"] == "campaign_concurrency_limit"
    # provider reports no answer for first call -> retry scheduled
    call = db.scalars(select(Call).where(Call.campaign_id == c.id)).first()
    payload = {
        "event": "call_ended",
        "call": {
            "call_id": call.provider_call_id,
            "direction": "outbound",
            "from_number": call.from_number,
            "to_number": call.to_number,
            "disconnection_reason": "dial_no_answer",
            "start_timestamp": 1,
            "end_timestamp": 1,
        },
    }
    assert post_signed(client, "/api/v1/webhooks/mock", payload).json()["status"] == "processed"
    db.expire_all()
    cc = db.scalar(select(CampaignContact).where(CampaignContact.contact_id == call.contact_id))
    assert cc.status == "eligible" and cc.next_attempt_at is not None and cc.last_outcome == "no_answer"
    # unique idempotency keys per attempt
    keys = db.scalars(select(CallAttempt.idempotency_key)).all()
    assert len(keys) == len(set(keys)) == 2


def test_pause_and_kill_switch(client, db):
    h, tid, camp, _ = _setup(client, db)
    client.post(f"/api/v1/campaigns/{camp['id']}/start", headers=h)
    assert client.post(f"/api/v1/campaigns/{camp['id']}/pause", headers=h).json()["status"] == "paused"
    c = db.get(Campaign, uuid.UUID(camp["id"]))
    db.refresh(c)
    assert dispatch_campaign(db, c, now=IN_HOURS)["reason"] == "not_running"
    client.post(f"/api/v1/campaigns/{camp['id']}/resume", headers=h)
    db.merge(PlatformSetting(key="outbound_kill_switch", value={"enabled": True}))
    db.commit()
    db.refresh(c)
    assert dispatch_campaign(db, c, now=IN_HOURS)["reason"] == "paused_by_kill_switch"
    assert mock_provider().placed == []


def test_provider_outage_schedules_retry(client, db):
    h, tid, camp, _ = _setup(client, db)
    client.post(f"/api/v1/campaigns/{camp['id']}/start", headers=h)
    mock_provider().fail_outbound = True
    c = db.get(Campaign, uuid.UUID(camp["id"]))
    stats = dispatch_campaign(db, c, now=IN_HOURS)
    assert stats["failed"] == 2 and stats["dispatched"] == 0
    statuses = db.scalars(select(CampaignContact.status).where(CampaignContact.campaign_id == c.id, CampaignContact.status == "eligible")).all()
    assert len(statuses) >= 2


def test_expired_and_revoked_consent(client, db):
    h, tid, camp, contacts = _setup(client, db, consent=False)
    past = datetime.now(UTC) - timedelta(days=30)
    client.post(
        f"/api/v1/contacts/{contacts[0]['id']}/consents",
        json={
            "purpose": "sales",
            "source": "ivr",
            "evidence": "IVR key 1",
            "granted_at": past.isoformat(),
            "expires_at": (past + timedelta(days=1)).isoformat(),
        },
        headers=h,
    )
    cons = client.post(f"/api/v1/contacts/{contacts[1]['id']}/consents", json={"purpose": "sales", "source": "ivr", "evidence": "IVR key 1"}, headers=h).json()
    client.post(f"/api/v1/contacts/{contacts[1]['id']}/consents/{cons['id']}/revoke", headers=h)
    client.post(f"/api/v1/contacts/{contacts[2]['id']}/consents", json={"purpose": "service", "source": "ivr", "evidence": "wrong purpose"}, headers=h)
    r = client.post(f"/api/v1/campaigns/{camp['id']}/start", headers=h)
    assert r.status_code == 409


def test_opt_out_during_campaign_call(client, db):
    h, tid, camp, contacts = _setup(client, db)
    client.post(f"/api/v1/campaigns/{camp['id']}/start", headers=h)
    c = db.get(Campaign, uuid.UUID(camp["id"]))
    dispatch_campaign(db, c, now=IN_HOURS)
    call = db.scalars(select(Call).where(Call.campaign_id == c.id)).first()
    analyzed = {
        "event": "call_analyzed",
        "call": {
            "call_id": call.provider_call_id,
            "direction": "outbound",
            "to_number": call.to_number,
            "from_number": call.from_number,
            "start_timestamp": 1_700_000_000_000,
            "end_timestamp": 1_700_000_030_000,
            "call_analysis": {"custom_analysis_data": {"outcome": "do_not_call"}},
        },
    }
    post_signed(client, "/api/v1/webhooks/mock", analyzed)
    sup = client.get("/api/v1/suppression", headers=h).json()
    assert call.to_number in [s["phone_e164"] for s in sup["items"]]
    db.expire_all()
    cc = db.scalar(select(CampaignContact).where(CampaignContact.contact_id == call.contact_id))
    assert cc.status == "cancelled"


def test_window_and_compliance_rules(client, db):
    h, tid, camp, _ = _setup(client, db)
    c = db.get(Campaign, uuid.UUID(camp["id"]))
    assert within_window(c, IN_HOURS) == (True, None)
    sunday = datetime(2030, 1, 6, 5, 30, tzinfo=UTC)
    assert within_window(c, sunday)[1] == "outside_campaign_days"
    t = db.get(Tenant, uuid.UUID(tid))
    assert "tenant_outbound_compliance_not_approved" in compliance_problems(db, c, t, "retell")
    assert compliance_problems(db, c, t, "mock") == []


def test_cross_tenant_campaign_contacts_rejected(client, db):
    h, tid, camp, _ = _setup(client, db)
    other_h, _, _ = register(client, "Other")
    foreign = client.post("/api/v1/contacts", json={"phone": "9811100000"}, headers=other_h).json()
    r = client.post(f"/api/v1/campaigns/{camp['id']}/contacts", json={"contact_ids": [foreign["id"]]}, headers=h).json()
    assert r["added"] == 0 and r["ignored"] == 1
    assert client.post(f"/api/v1/campaigns/{camp['id']}/start", headers=other_h).status_code == 404
