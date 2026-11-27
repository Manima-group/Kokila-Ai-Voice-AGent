import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import audit, audit_ctx
from app.auth.deps import TenantContext, require
from app.billing.models import Invoice, PaymentTransaction, Plan, Subscription, UsageRecord
from app.billing.service import current_entitlement, gst_breakup
from app.core.config import get_settings
from app.core.errors import AppError, NotFound, ServiceUnavailable, Unauthorized
from app.db.session import SessionLocal, get_db
from app.integrations.models import WebhookEvent
from app.schemas.common import ORM, paginate

router = APIRouter(prefix="/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class PlanOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    price_minor: int
    currency: str
    interval_months: int
    included_minutes: int
    overage_per_minute_minor: int | None
    max_agents: int
    max_concurrent_calls: int
    max_users: int
    features: dict


class CheckoutIn(BaseModel):
    plan_code: str


class VerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentOut(ORM):
    id: uuid.UUID
    razorpay_order_id: str
    razorpay_payment_id: str | None
    amount_minor: int
    currency: str
    status: str
    created_at: datetime
    captured_at: datetime | None


class InvoiceOut(ORM):
    id: uuid.UUID
    number: str
    period_start: datetime
    period_end: datetime
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    currency: str
    status: str
    line_items: list
    created_at: datetime


_client_factory = None


def razorpay_client():
    s = get_settings()
    if _client_factory:
        return _client_factory()
    if not s.billing_configured:
        raise ServiceUnavailable("Payments are not configured (RAZORPAY_KEY_ID/SECRET/WEBHOOK_SECRET)")
    import razorpay

    return razorpay.Client(auth=(s.razorpay_key_id, s.razorpay_key_secret))


def set_client_factory(factory) -> None:
    global _client_factory
    _client_factory = factory


@router.get("/plans", response_model=list[PlanOut])
def plans(_: TenantContext = Depends(require("billing:read")), db: Session = Depends(get_db)):
    return db.scalars(select(Plan).where(Plan.is_active.is_(True), Plan.is_public.is_(True)).order_by(Plan.price_minor)).all()


@router.get("/subscription")
def subscription(ctx: TenantContext = Depends(require("billing:read")), db: Session = Depends(get_db)) -> dict:
    ent = current_entitlement(db, ctx.tenant_id)
    db.commit()
    if ent is None:
        return {"subscription": None}
    sub, plan = ent.subscription, ent.plan
    return {
        "status": sub.status,
        "plan": PlanOut.model_validate(plan).model_dump(mode="json"),  # type: ignore[attr-defined]
        "current_period_start": sub.current_period_start.isoformat(),
        "current_period_end": sub.current_period_end.isoformat(),  # type: ignore[attr-defined]
        "minutes_used": ent.minutes_used,
        "minutes_included": plan.included_minutes,
        "billing_configured": get_settings().billing_configured,  # type: ignore[attr-defined]
    }


@router.get("/usage")
def usage(ctx: TenantContext = Depends(require("billing:read")), db: Session = Depends(get_db), days: int = Query(30, le=366)) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(func.date_trunc("day", UsageRecord.occurred_at).label("d"), func.sum(UsageRecord.quantity), func.count())
        .where(UsageRecord.tenant_id == ctx.tenant_id, UsageRecord.occurred_at >= since, UsageRecord.is_mock.is_(False))
        .group_by("d")
        .order_by("d")
    ).all()
    mock = db.scalar(
        select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
            UsageRecord.tenant_id == ctx.tenant_id, UsageRecord.occurred_at >= since, UsageRecord.is_mock.is_(True)
        )
    )
    return {"daily": [{"day": d.date().isoformat(), "minutes": float(m), "calls": c} for d, m, c in rows], "mock_minutes_excluded": float(mock or 0)}


@router.post("/checkout")
def checkout(body: CheckoutIn, ctx: TenantContext = Depends(require("billing:write")), db: Session = Depends(get_db)) -> dict:
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code, Plan.is_active.is_(True)))
    if plan is None or plan.price_minor <= 0:
        raise NotFound("Plan not available for purchase")
    client = razorpay_client()
    tax, total = gst_breakup(plan.price_minor)
    tx_id = uuid.uuid4()
    try:
        order = client.order.create(
            {"amount": total, "currency": plan.currency, "receipt": tx_id.hex[:40], "notes": {"tenant_id": str(ctx.tenant_id), "plan": plan.code}}
        )
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"Payment provider error: {exc.__class__.__name__}", code="payment_provider_error", status_code=502)
    db.add(
        PaymentTransaction(
            id=tx_id,
            tenant_id=ctx.tenant_id,
            razorpay_order_id=order["id"],
            plan_id=plan.id,
            amount_minor=total,
            currency=plan.currency,
            status="created",
            meta={"subtotal": plan.price_minor, "tax": tax},
        )
    )
    audit_ctx(db, ctx, "billing.checkout_created", "payment", tx_id, plan=plan.code)
    db.commit()
    return {"order_id": order["id"], "amount_minor": total, "currency": plan.currency, "key_id": get_settings().razorpay_key_id}


@router.post("/verify")
def verify(body: VerifyIn, ctx: TenantContext = Depends(require("billing:write")), db: Session = Depends(get_db)) -> dict:
    """Client-side checkout callback. Verifies the signature but does NOT activate the plan; the signed webhook does."""
    tx = db.scalar(
        select(PaymentTransaction).where(PaymentTransaction.razorpay_order_id == body.razorpay_order_id, PaymentTransaction.tenant_id == ctx.tenant_id)
    )
    if tx is None:
        raise NotFound("Order not found")
    client = razorpay_client()
    try:
        client.utility.verify_payment_signature(body.model_dump())
    except Exception:  # noqa: BLE001 - razorpay raises SignatureVerificationError
        audit_ctx(db, ctx, "billing.signature_invalid", "payment", tx.id)
        db.commit()
        raise AppError("Payment signature verification failed", code="invalid_signature", status_code=400)
    if tx.status == "created":
        tx.status = "client_verified"
    db.commit()
    return {"status": tx.status, "message": "Payment received; activation completes when Razorpay confirms capture."}


@router.get("/payments")
def payments(ctx: TenantContext = Depends(require("billing:read")), db: Session = Depends(get_db), limit: int = Query(50, le=200), offset: int = 0):
    return paginate(
        db,
        select(PaymentTransaction).where(PaymentTransaction.tenant_id == ctx.tenant_id).order_by(PaymentTransaction.created_at.desc()),
        limit,
        offset,
        PaymentOut,
    )


@router.get("/invoices")
def invoices(ctx: TenantContext = Depends(require("billing:read")), db: Session = Depends(get_db), limit: int = Query(50, le=200), offset: int = 0):
    return paginate(db, select(Invoice).where(Invoice.tenant_id == ctx.tenant_id).order_by(Invoice.created_at.desc()), limit, offset, InvoiceOut)


@router.post("/cancel")
def cancel_subscription(ctx: TenantContext = Depends(require("billing:write")), db: Session = Depends(get_db)) -> dict:
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id, Subscription.is_current.is_(True)))
    if sub is None or sub.status != "active":
        raise AppError("No active paid subscription", code="invalid_state", status_code=409)
    sub.cancel_at_period_end = True
    audit_ctx(db, ctx, "billing.cancel_requested", "subscription", sub.id)
    db.commit()
    return {"status": "cancels_at_period_end", "current_period_end": sub.current_period_end.isoformat()}


# ---- Razorpay webhook --------------------------------------------------------------------------------------------
def activate_from_payment(db: Session, tx: PaymentTransaction, payment_id: str, amount: int) -> None:
    if tx.status == "captured":
        return
    if amount != tx.amount_minor:
        raise AppError("Captured amount mismatch", code="amount_mismatch")
    plan = db.get(Plan, tx.plan_id) if tx.plan_id else None
    now = datetime.now(UTC)
    tx.status, tx.razorpay_payment_id, tx.captured_at = "captured", payment_id, now
    if plan:
        for old in db.scalars(select(Subscription).where(Subscription.tenant_id == tx.tenant_id, Subscription.is_current.is_(True))):
            old.is_current = False
            if old.status in ("trialing", "active"):
                old.status = "cancelled"
        db.flush()
        end = now + timedelta(days=30 * plan.interval_months)
        db.add(Subscription(tenant_id=tx.tenant_id, plan_id=plan.id, status="active", current_period_start=now, current_period_end=end, is_current=True))
        sub_total = int(tx.meta.get("subtotal", plan.price_minor))
        tax = int(tx.meta.get("tax", tx.amount_minor - sub_total))
        db.add(
            Invoice(
                tenant_id=tx.tenant_id,
                number=f"KOK-{now:%Y%m}-{tx.id.hex[:8].upper()}",
                payment_id=tx.id,
                period_start=now,
                period_end=end,
                subtotal_minor=sub_total,
                tax_minor=tax,
                total_minor=tx.amount_minor,
                currency=tx.currency,
                status="paid",
                line_items=[
                    {"description": f"{plan.name} subscription", "amount_minor": sub_total},
                    {"description": f"GST {get_settings().gst_rate_percent}%", "amount_minor": tax},
                ],
            )
        )
    audit(db, "billing.payment_captured", tenant_id=tx.tenant_id, actor_type="provider", resource_type="payment", resource_id=tx.id)


def _razorpay_webhook(raw: bytes, signature: str | None, event_id: str | None) -> dict:
    s = get_settings()
    if not s.razorpay_webhook_secret:
        raise ServiceUnavailable("Razorpay webhook secret not configured")
    body = raw.decode("utf-8")
    if not signature:
        raise Unauthorized("Missing signature", code="invalid_signature")
    import razorpay

    try:
        razorpay.Utility(None).verify_webhook_signature(body, signature, s.razorpay_webhook_secret)
    except Exception:  # noqa: BLE001
        raise Unauthorized("Invalid signature", code="invalid_signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise AppError("Malformed JSON", code="malformed_payload")
    event = payload.get("event", "")
    payment = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    dedupe = f"razorpay:{event_id or (payment.get('id', '') + ':' + event)}"
    with SessionLocal() as db:
        we = WebhookEvent(source="razorpay", dedupe_key=dedupe, event_type=event, payload=payload)
        db.add(we)
        try:
            db.commit()
        except IntegrityError:
            return {"status": "duplicate"}
        tx = (
            db.scalar(select(PaymentTransaction).where(PaymentTransaction.razorpay_order_id == payment.get("order_id")).with_for_update())
            if payment.get("order_id")
            else None
        )
        if tx is None:
            we.status, we.error = "ignored", "unknown order"
        elif event in ("payment.captured", "order.paid"):
            activate_from_payment(db, tx, payment["id"], int(payment.get("amount", 0)))
            we.tenant_id, we.status = tx.tenant_id, "processed"
        elif event == "payment.failed":
            if tx.status != "captured":
                tx.status = "failed"
            we.tenant_id, we.status = tx.tenant_id, "processed"
        else:
            we.status = "ignored"
        we.processed_at = datetime.now(UTC)
        db.commit()
        return {"status": we.status}


@webhook_router.post("/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    raw = await request.body()
    return await run_in_threadpool(_razorpay_webhook, raw, request.headers.get("x-razorpay-signature"), request.headers.get("x-razorpay-event-id"))
