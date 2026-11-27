import hashlib
import hmac
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import razorpay
from sqlalchemy import select

from app.appointments import calendar as cal
from app.appointments.models import Appointment
from app.appointments.service import reconcile_pending
from app.billing import router as billing_router
from app.billing.models import Subscription, UsageRecord
from tests.conftest import grant_plan, register

IST = ZoneInfo("Asia/Kolkata")


def next_weekday_at(hour: int, days_ahead: int = 2) -> datetime:
    d = datetime.now(IST).date() + timedelta(days=days_ahead)
    while d.weekday() > 4:
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=IST)


def _calendar(client, h):
    r = client.post("/api/v1/calendar-connections", json={"label": "Front office"}, headers=h)
    assert r.status_code == 201
    return r.json()


def test_book_overlap_idempotency_and_timezone(client):
    h, _, _ = register(client)
    _calendar(client, h)
    start = next_weekday_at(11)
    utc_start = start.astimezone(UTC).isoformat()  # same instant expressed in UTC
    r = client.post("/api/v1/appointments", json={"start": utc_start, "title": "Site visit", "idempotency_key": "key-00000001"}, headers=h)
    assert r.status_code == 201 and r.json()["status"] == "confirmed"
    assert datetime.fromisoformat(r.json()["start_at"]).astimezone(IST).hour == 11
    again = client.post("/api/v1/appointments", json={"start": utc_start, "title": "Site visit", "idempotency_key": "key-00000001"}, headers=h)
    assert again.json()["id"] == r.json()["id"]
    clash = client.post("/api/v1/appointments", json={"start": start.isoformat(), "title": "Other", "idempotency_key": "key-00000002"}, headers=h)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "slot_unavailable"
    naive = client.post("/api/v1/appointments", json={"start": "2030-01-07T11:00:00", "title": "Xx call", "idempotency_key": "key-00000003"}, headers=h)
    assert naive.status_code == 422
    late = client.post(
        "/api/v1/appointments", json={"start": next_weekday_at(20).isoformat(), "title": "Xx call", "idempotency_key": "key-00000004"}, headers=h
    )
    assert late.json()["error"]["code"] == "outside_hours"
    slots = client.get(f"/api/v1/appointments/availability?day={start.date().isoformat()}", headers=h).json()["slots"]
    assert start.isoformat() not in slots and len(slots) > 0


def test_concurrent_booking_single_winner(client):
    h, _, _ = register(client)
    _calendar(client, h)
    start = next_weekday_at(12).isoformat()
    codes = []

    def go(i):
        codes.append(client.post("/api/v1/appointments", json={"start": start, "title": "Test", "idempotency_key": f"conc-key-{i:04d}"}, headers=h).status_code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes.count(201) == 1 and codes.count(409) == 5


def test_cancel_and_reschedule(client):
    h, _, _ = register(client)
    _calendar(client, h)
    a = client.post("/api/v1/appointments", json={"start": next_weekday_at(14).isoformat(), "title": "Demo", "idempotency_key": "resched-1"}, headers=h).json()
    r = client.post(f"/api/v1/appointments/{a['id']}/reschedule", json={"start": next_weekday_at(15).isoformat()}, headers=h)
    assert r.status_code == 200 and datetime.fromisoformat(r.json()["start_at"]).astimezone(IST).hour == 15
    assert client.post(f"/api/v1/appointments/{a['id']}/cancel", headers=h).json()["status"] == "cancelled"
    # cancelled slot is free again
    b = client.post("/api/v1/appointments", json={"start": next_weekday_at(15).isoformat(), "title": "New", "idempotency_key": "resched-2"}, headers=h)
    assert b.status_code == 201


class FakeGoogle:
    created: dict[str, str] = {}
    fail_create = False

    def __init__(self, conn):
        self.conn = conn

    def busy(self, start, end):
        return []

    def create_event(self, event_id, summary, start, end, tz):
        FakeGoogle.created[event_id] = summary
        if FakeGoogle.fail_create:
            raise cal.CalendarError("timeout after write")
        return event_id

    def event_exists(self, event_id):
        return event_id in FakeGoogle.created

    def delete_event(self, event_id):
        FakeGoogle.created.pop(event_id, None)

    def update_event(self, *a):
        pass


def test_google_external_success_local_failure_reconciled(client, db):
    from app.appointments.models import CalendarConnection

    h, tid, _ = register(client)
    conn = CalendarConnection(tenant_id=uuid.UUID(tid), provider="google", label="G", calendar_id="primary", encrypted_tokens=None)
    db.add(conn)
    db.commit()
    cal.set_google_factory(FakeGoogle)
    try:
        r = client.post("/api/v1/appointments", json={"start": next_weekday_at(11).isoformat(), "title": "G1", "idempotency_key": "g-key-0001"}, headers=h)
        assert r.json()["status"] == "confirmed" and r.json()["external_event_id"].startswith("kk")
        # Simulate crash after the Google write: appointment left pending_confirmation
        appt = Appointment(
            tenant_id=uuid.UUID(tid),
            calendar_connection_id=conn.id,
            title="G2",
            start_at=next_weekday_at(13),
            end_at=next_weekday_at(13) + timedelta(minutes=30),
            timezone="Asia/Kolkata",
            status="pending_confirmation",
            idempotency_key="g-key-0002",
            updated_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        db.add(appt)
        db.commit()
        FakeGoogle.created[cal.event_id_for(appt.id)] = "G2"
        orphan = Appointment(
            tenant_id=uuid.UUID(tid),
            calendar_connection_id=conn.id,
            title="G3",
            start_at=next_weekday_at(16),
            end_at=next_weekday_at(16) + timedelta(minutes=30),
            timezone="Asia/Kolkata",
            status="pending_confirmation",
            idempotency_key="g-key-0003",
            updated_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        db.add(orphan)
        db.commit()
        db.execute(Appointment.__table__.update().values(updated_at=datetime.now(UTC) - timedelta(minutes=10)))
        db.commit()
        assert reconcile_pending(db) == {"confirmed": 1, "failed": 1, "errors": 0}
        # external failure -> failed, slot released
        FakeGoogle.fail_create = True
        r = client.post("/api/v1/appointments", json={"start": next_weekday_at(17 - 2).isoformat(), "title": "G4", "idempotency_key": "g-key-0004"}, headers=h)
        assert r.json()["status"] == "failed"
    finally:
        FakeGoogle.fail_create = False
        cal.set_google_factory(cal.GoogleCalendar)


# ---- Billing -----------------------------------------------------------------------------------------------------
class FakeOrders:
    def create(self, data):
        return {"id": f"order_{uuid.uuid4().hex[:14]}", "amount": data["amount"]}


class FakeRzp:
    def __init__(self):
        self.order = FakeOrders()
        self.utility = razorpay.Client(auth=("rzp_test_dummy", "test_key_secret")).utility  # real signature logic


def _sign(secret: str, msg: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _webhook(client, body: dict, event_id: str, secret="test_webhook_secret"):
    raw = json.dumps(body)
    return client.post("/api/v1/webhooks/razorpay", content=raw, headers={"x-razorpay-signature": _sign(secret, raw), "x-razorpay-event-id": event_id})


def test_payment_lifecycle(client, db):
    from app.billing.models import Plan

    db.add(
        Plan(
            code="starter",
            name="Starter",
            price_minor=299900,
            included_minutes=500,
            max_agents=3,
            max_concurrent_calls=2,
            max_users=5,
            features={"outbound": True},
        )
    )
    db.commit()
    h, tid, _ = register(client)
    billing_router.set_client_factory(FakeRzp)
    try:
        co = client.post("/api/v1/billing/checkout", json={"plan_code": "starter"}, headers=h).json()
        assert co["amount_minor"] == 299900 + 53982  # 18% GST
        pay_id = "pay_TEST123"
        bad = client.post(
            "/api/v1/billing/verify", json={"razorpay_order_id": co["order_id"], "razorpay_payment_id": pay_id, "razorpay_signature": "bad"}, headers=h
        )
        assert bad.status_code == 400
        good = client.post(
            "/api/v1/billing/verify",
            json={
                "razorpay_order_id": co["order_id"],
                "razorpay_payment_id": pay_id,
                "razorpay_signature": _sign("test_key_secret", f"{co['order_id']}|{pay_id}"),
            },
            headers=h,
        )
        assert good.json()["status"] == "client_verified"
        # Browser success alone does NOT activate the plan
        assert client.get("/api/v1/billing/subscription", headers=h).json()["plan"]["code"] == "trial"
        event = {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": pay_id, "order_id": co["order_id"], "amount": co["amount_minor"], "status": "captured"}}},
        }
        assert _webhook(client, event, "evt_1", secret="wrong").status_code == 401
        assert _webhook(client, event, "evt_1").json()["status"] == "processed"
        assert _webhook(client, event, "evt_1").json()["status"] == "duplicate"
        sub = client.get("/api/v1/billing/subscription", headers=h).json()
        assert sub["status"] == "active" and sub["plan"]["code"] == "starter"
        inv = client.get("/api/v1/billing/invoices", headers=h).json()
        assert inv["total"] == 1 and inv["items"][0]["tax_minor"] == 53982
        assert db.scalar(select(Subscription).where(Subscription.tenant_id == uuid.UUID(tid), Subscription.is_current.is_(True))).status == "active"
    finally:
        billing_router.set_client_factory(None)


def test_subscription_expiry_and_usage_limits(client, db):
    from app.billing.service import check_call_allowed
    from app.core.errors import PaymentRequired

    h, tid, _ = register(client)
    plan = grant_plan(db, tid, minutes=1, code="tiny")
    db.add(UsageRecord(tenant_id=uuid.UUID(tid), kind="voice_minutes", quantity=1, occurred_at=datetime.now(UTC)))
    db.commit()
    try:
        check_call_allowed(db, uuid.UUID(tid))
        raise AssertionError("expected minutes_exhausted")
    except PaymentRequired as exc:
        assert exc.code == "minutes_exhausted"
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == uuid.UUID(tid), Subscription.is_current.is_(True)))
    sub.current_period_end = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    r = client.post("/api/v1/agents", json={"name": "After expiry", "template": "receptionist"}, headers=h)
    assert r.status_code == 402 and r.json()["error"]["code"] == "subscription_inactive"
    assert plan.code == "tiny"


def test_billing_not_configured_is_explicit(client, monkeypatch):
    from app.core.config import get_settings

    h, _, _ = register(client)
    monkeypatch.setattr(get_settings(), "razorpay_key_id", "")
    r = client.post("/api/v1/billing/checkout", json={"plan_code": "trial"}, headers=h)
    assert r.status_code == 404  # trial is free / not purchasable
