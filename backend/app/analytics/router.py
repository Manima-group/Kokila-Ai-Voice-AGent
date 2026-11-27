from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.agents.models import Agent
from app.auth.deps import TenantContext, require, require_capability
from app.campaigns.models import Campaign
from app.contacts.models import Lead
from app.db.session import get_db
from app.platform.registry import PRODUCT_CALLING_AGENT
from app.telephony.models import Call

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_capability(PRODUCT_CALLING_AGENT, "voice.agents"))])
ANSWERED = Call.status == "completed"


@router.get("/overview")
def overview(
    ctx: TenantContext = Depends(require("analytics:read")), db: Session = Depends(get_db), days: int = Query(30, ge=1, le=366), include_mock: bool = False
) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    base = [Call.tenant_id == ctx.tenant_id, Call.created_at >= since]
    if not include_mock:
        base.append(Call.is_mock.is_(False))
    row = db.execute(
        select(
            func.count(),
            func.count().filter(ANSWERED),
            func.count().filter(Call.status == "failed"),
            func.coalesce(func.sum(Call.duration_seconds), 0),
            func.coalesce(func.avg(Call.duration_seconds).filter(ANSWERED), 0),
            func.count().filter(Call.direction == "inbound"),
            func.count().filter(Call.direction == "outbound"),
            func.count().filter(Call.handoff_requested.is_(True)),
        ).where(*base)
    ).one()
    total, answered, failed, secs, avg, inbound, outbound, handoffs = row
    leads = db.execute(
        select(func.count(), func.count().filter(Lead.status == "qualified"), func.count().filter(Lead.status == "converted")).where(
            Lead.tenant_id == ctx.tenant_id, Lead.created_at >= since
        )
    ).one()
    outcomes = dict(db.execute(select(Call.outcome, func.count()).where(*base, Call.outcome.is_not(None)).group_by(Call.outcome)).all())
    daily = db.execute(
        select(func.date_trunc("day", Call.created_at).label("d"), func.count(), func.count().filter(ANSWERED)).where(*base).group_by("d").order_by("d")
    ).all()
    cost = db.execute(
        select(Call.provider, func.sum(Call.provider_cost_minor), func.count().filter(Call.provider_cost_minor.is_(None))).where(*base).group_by(Call.provider)
    ).all()
    return {
        "period_days": days,
        "include_mock": include_mock,
        "calls": {
            "total": total,
            "answered": answered,
            "failed": failed,
            "inbound": inbound,
            "outbound": outbound,
            "answer_rate": round(answered / total, 4) if total else None,
            "handoffs": handoffs,
        },
        "duration": {"total_minutes": round(secs / 60, 1), "avg_answered_seconds": round(float(avg), 1)},
        "leads": {"created": leads[0], "qualified": leads[1], "converted": leads[2], "qualification_rate": round(leads[1] / leads[0], 4) if leads[0] else None},
        "outcomes": outcomes,
        "daily": [{"day": d.date().isoformat(), "calls": c, "answered": a} for d, c, a in daily],
        "provider_cost": [
            {
                "provider": p,
                "amount_minor": int(s) if s is not None else None,
                "currency_note": "USD cents" if p == "retell" else "n/a",
                "calls_without_cost_data": n,
            }
            for p, s, n in cost
        ],
    }


@router.get("/agents")
def agent_performance(ctx: TenantContext = Depends(require("analytics:read")), db: Session = Depends(get_db), days: int = Query(30, le=366)) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(
            Agent.id,
            Agent.name,
            func.count(Call.id),
            func.count(Call.id).filter(ANSWERED),
            func.coalesce(func.avg(Call.duration_seconds).filter(ANSWERED), 0),
            func.count(Call.id).filter(Call.outcome.in_(("qualified", "appointment_confirmed", "interested"))),
        )
        .join(Call, (Call.agent_id == Agent.id) & (Call.created_at >= since) & (Call.is_mock.is_(False)), isouter=True)
        .where(Agent.tenant_id == ctx.tenant_id)
        .group_by(Agent.id, Agent.name)
    ).all()
    return [{"agent_id": str(i), "name": n, "calls": c, "answered": a, "avg_seconds": round(float(s), 1), "positive_outcomes": p} for i, n, c, a, s, p in rows]


@router.get("/campaigns")
def campaign_performance(ctx: TenantContext = Depends(require("analytics:read")), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(
            Campaign.id,
            Campaign.name,
            Campaign.status,
            func.count(Call.id),
            func.count(Call.id).filter(ANSWERED),
            func.sum(case((Call.outcome.in_(("qualified", "appointment_confirmed", "appointment_requested")), 1), else_=0)),
            func.sum(case((Call.outcome == "do_not_call", 1), else_=0)),
        )
        .join(Call, Call.campaign_id == Campaign.id, isouter=True)
        .where(Campaign.tenant_id == ctx.tenant_id)
        .group_by(Campaign.id, Campaign.name, Campaign.status)
    ).all()
    return [
        {
            "campaign_id": str(i),
            "name": n,
            "status": st,
            "calls": c,
            "answered": a,
            "conversions": int(cv or 0),
            "opt_outs": int(o or 0),
            "conversion_rate": round(int(cv or 0) / a, 4) if a else None,
        }
        for i, n, st, c, a, cv, o in rows
    ]
