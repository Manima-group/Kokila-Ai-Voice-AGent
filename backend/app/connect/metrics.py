"""Governed metric catalog. Deterministic calculations only; results carry provenance. Never fabricates values."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connect.adapters import ConnectorError, ERPNextAdapter, ManimaHubAdapter
from app.connect.models import ConnectorConnection
from app.core.errors import AppError
from app.platform.entitlements import has as has_capability
from app.platform.registry import PRODUCT_CALLING_AGENT

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class MetricSpec:
    key: str
    title: str
    source: str  # kokila | erpnext | manima_hub
    description: str
    params: tuple[str, ...] = ()
    write: bool = False


METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("kokila.calls_summary", "Call summary", "kokila", "Calls, answer rate and qualified leads from Kokila Calling Agent", ("date_from", "date_to")),
    MetricSpec("kokila.appointments_upcoming", "Upcoming appointments", "kokila", "Confirmed appointments in the next N days", ("days",)),
    MetricSpec("kokila.followups_open", "Open follow-ups", "kokila", "Open lead follow-up tasks"),
    MetricSpec(
        "erpnext.sales_total",
        "Sales",
        "erpnext",
        "Net sales = sum of base_net_total of submitted Sales Invoices (returns are negative) by posting date",
        ("date_from", "date_to"),
    ),
    MetricSpec(
        "erpnext.sales_compare", "Sales comparison", "erpnext", "Net sales for a period versus the previous period of equal length", ("date_from", "date_to")
    ),
    MetricSpec("erpnext.overdue_invoices", "Overdue invoices", "erpnext", "Submitted invoices with outstanding amount and due date before today"),
    MetricSpec("erpnext.customer_outstanding", "Customer outstanding", "erpnext", "Outstanding amount grouped by customer"),
    MetricSpec("erpnext.low_stock", "Low stock", "erpnext", "Bins with actual quantity at or below a threshold", ("threshold",)),
)
BY_KEY = {m.key: m for m in METRICS}


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:  # noqa: BLE001
        return Decimal(0)


def _num(v: Decimal) -> float:
    return float(round(v, 2))


def _period(params: dict) -> tuple[date, date]:
    today = datetime.now(IST).date()
    try:
        start = date.fromisoformat(params["date_from"]) if params.get("date_from") else today
        end = date.fromisoformat(params["date_to"]) if params.get("date_to") else start
    except ValueError:
        raise AppError("Dates must be YYYY-MM-DD", code="invalid_period", status_code=422)
    if end < start:
        raise AppError("date_to is before date_from", code="invalid_period", status_code=422)
    if (end - start).days > 366:
        raise AppError("Period longer than 366 days; narrow the range", code="invalid_period", status_code=422)
    return start, end


def _result(spec: MetricSpec, *, period=None, kpis=None, table=None, chart=None, source=None, warnings=None) -> dict:
    return {
        "metric": spec.key,
        "title": spec.title,
        "definition": spec.description,
        "period": {"from": period[0].isoformat(), "to": period[1].isoformat()} if period else None,
        "kpis": kpis or [],
        "table": table,
        "chart": chart,
        "warnings": warnings or [],
        "source": {"fetched_at": datetime.now(UTC).isoformat(), **(source or {})},
    }


def connection_for(db: Session, tenant_id: uuid.UUID, connector_key: str, connection_id: str | None = None) -> ConnectorConnection:
    stmt = select(ConnectorConnection).where(
        ConnectorConnection.tenant_id == tenant_id, ConnectorConnection.connector_key == connector_key, ConnectorConnection.status == "connected"
    )
    if connection_id:
        stmt = stmt.where(ConnectorConnection.id == uuid.UUID(str(connection_id)))
    conn = db.scalar(stmt.order_by(ConnectorConnection.created_at))
    if conn is None:
        raise AppError(f"No verified {connector_key} connection. Connect it under Integrations first.", code="connector_not_connected", status_code=409)
    return conn


def run_metric(db: Session, tenant_id: uuid.UUID, key: str, params: dict | None = None) -> dict:
    params = params or {}
    spec = BY_KEY.get(key)
    if spec is None:
        raise AppError(f"Unknown metric '{key}'", code="unknown_metric", status_code=422)
    if spec.source == "kokila":
        return _kokila_metric(db, tenant_id, spec, params)
    conn = connection_for(db, tenant_id, spec.source, params.get("connection_id"))
    src = {"connector": spec.source, "connection_id": str(conn.id), "connection_name": conn.name}
    try:
        if spec.source == "erpnext":
            return _erpnext_metric(ERPNextAdapter(conn), spec, params, src)
        return ManimaHubAdapter(conn).metric(key.split(".", 1)[1], params)
    except ConnectorError as exc:
        raise AppError(f"{conn.name}: {exc}", code=exc.code, status_code=502)


def _erpnext_metric(a: ERPNextAdapter, spec: MetricSpec, params: dict, src: dict) -> dict:
    currency, companies = a.company_currency()
    warnings = [] if currency else [f"{companies} companies with different currencies; totals are in each company's base currency"]
    today = datetime.now(IST).date()

    def sales(start: date, end: date) -> tuple[Decimal, Decimal, int, int, dict]:
        rows = a.sales_invoices(start, end)
        net = sum((_d(r.get("base_net_total")) for r in rows), Decimal(0))
        gross = sum((_d(r.get("base_grand_total")) for r in rows), Decimal(0))
        by_day: dict[str, Decimal] = defaultdict(Decimal)
        for r in rows:
            by_day[str(r.get("posting_date"))] += _d(r.get("base_net_total"))
        returns = sum(1 for r in rows if r.get("is_return")) or 0
        return net, gross, len(rows), returns, by_day

    if spec.key == "erpnext.sales_total":
        start, end = _period(params)
        net, gross, n, returns, by_day = sales(start, end)
        if end >= today:
            warnings.append("Period includes today; figures are partial")
        days = sorted(by_day)
        return _result(
            spec,
            period=(start, end),
            source={**src, "records": n},
            warnings=warnings,
            kpis=[
                {"label": "Net sales", "value": _num(net), "unit": currency},
                {"label": "Gross (incl. tax)", "value": _num(gross), "unit": currency},
                {"label": "Invoices", "value": n - returns, "unit": None},
                {"label": "Returns", "value": returns, "unit": None},
            ],
            chart={"type": "bar", "x": days, "series": [{"name": "Net sales", "values": [_num(by_day[d]) for d in days]}]} if days else None,
        )
    if spec.key == "erpnext.sales_compare":
        start, end = _period(params)
        length = (end - start).days + 1
        pstart, pend = start - timedelta(days=length), start - timedelta(days=1)
        cur, _, n1, _, _ = sales(start, end)
        prev, _, n2, _, _ = sales(pstart, pend)
        change = (cur - prev) / prev * 100 if prev else None
        return _result(
            spec,
            period=(start, end),
            source={**src, "records": n1 + n2},
            warnings=warnings,
            kpis=[
                {"label": "This period", "value": _num(cur), "unit": currency},
                {"label": f"Previous ({pstart.isoformat()} – {pend.isoformat()})", "value": _num(prev), "unit": currency},
                {"label": "Change", "value": _num(change) if change is not None else None, "unit": "%"},
            ],
            chart={"type": "bar", "x": ["Previous", "This period"], "series": [{"name": "Net sales", "values": [_num(prev), _num(cur)]}]},
        )
    if spec.key == "erpnext.overdue_invoices":
        rows = a.overdue_invoices(today)
        total = sum((_d(r.get("outstanding_amount")) for r in rows), Decimal(0))
        rows.sort(key=lambda r: str(r.get("due_date")))
        return _result(
            spec,
            source={**src, "records": len(rows)},
            warnings=warnings + ["Outstanding amounts are in each invoice's party currency"],
            kpis=[{"label": "Overdue invoices", "value": len(rows), "unit": None}, {"label": "Overdue amount", "value": _num(total), "unit": currency}],
            table={
                "columns": ["Invoice", "Customer", "Due date", "Outstanding"],
                "rows": [[r.get("name"), r.get("customer"), r.get("due_date"), _num(_d(r.get("outstanding_amount")))] for r in rows[:200]],
            },
        )
    if spec.key == "erpnext.customer_outstanding":
        rows = a.outstanding_invoices()
        by_c: dict[str, Decimal] = defaultdict(Decimal)
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            by_c[str(r.get("customer"))] += _d(r.get("outstanding_amount"))
            counts[str(r.get("customer"))] += 1
        ranked = sorted(by_c.items(), key=lambda kv: kv[1], reverse=True)
        return _result(
            spec,
            source={**src, "records": len(rows)},
            warnings=warnings,
            kpis=[
                {"label": "Customers with dues", "value": len(ranked), "unit": None},
                {"label": "Total outstanding", "value": _num(sum(by_c.values(), Decimal(0))), "unit": currency},
            ],
            table={"columns": ["Customer", "Invoices", "Outstanding"], "rows": [[c, counts[c], _num(v)] for c, v in ranked[:200]]},
            chart={"type": "bar", "x": [c for c, _ in ranked[:10]], "series": [{"name": "Outstanding", "values": [_num(v) for _, v in ranked[:10]]}]},
        )
    if spec.key == "erpnext.low_stock":
        try:
            threshold = float(params.get("threshold", 10))
        except (TypeError, ValueError):
            raise AppError("threshold must be a number", code="invalid_params", status_code=422)
        rows = a.low_stock(threshold)
        rows.sort(key=lambda r: float(r.get("actual_qty") or 0))
        return _result(
            spec,
            source={**src, "records": len(rows)},
            warnings=warnings + [f"Low stock = actual quantity <= {threshold:g} per warehouse"],
            kpis=[{"label": "Low-stock item/warehouse pairs", "value": len(rows), "unit": None}],
            table={
                "columns": ["Item", "Warehouse", "Actual qty", "Projected qty"],
                "rows": [[r.get("item_code"), r.get("warehouse"), r.get("actual_qty"), r.get("projected_qty")] for r in rows[:200]],
            },
        )
    raise AppError("Metric not implemented", code="unknown_metric", status_code=422)


def _kokila_metric(db: Session, tenant_id: uuid.UUID, spec: MetricSpec, params: dict) -> dict:
    from app.appointments.models import Appointment
    from app.contacts.models import Lead, LeadActivity
    from app.telephony.models import Call

    if not has_capability(db, tenant_id, PRODUCT_CALLING_AGENT):
        raise AppError("This report uses Calling Agent data, which is not enabled for your organization", code="capability_disabled", status_code=403)
    src = {"connector": "kokila"}
    if spec.key == "kokila.calls_summary":
        start, end = _period(params)
        lo = datetime.combine(start, datetime.min.time(), IST)
        hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), IST)
        base = [Call.tenant_id == tenant_id, Call.is_mock.is_(False), Call.created_at >= lo, Call.created_at < hi]
        total, answered = db.execute(select(func.count(), func.count().filter(Call.status == "completed")).where(*base)).one()
        qualified = (
            db.scalar(
                select(func.count())
                .select_from(Lead)
                .where(Lead.tenant_id == tenant_id, Lead.status == "qualified", Lead.updated_at >= lo, Lead.updated_at < hi)
            )
            or 0
        )
        return _result(
            spec,
            period=(start, end),
            source={**src, "records": total},
            kpis=[
                {"label": "Calls", "value": total, "unit": None},
                {"label": "Answered", "value": answered, "unit": None},
                {"label": "Qualified leads", "value": qualified, "unit": None},
            ],
        )
    if spec.key == "kokila.appointments_upcoming":
        days = max(1, min(int(params.get("days", 7) or 7), 60))
        now = datetime.now(UTC)
        appts = db.scalars(
            select(Appointment)
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.status == "confirmed",
                Appointment.start_at >= now,
                Appointment.start_at < now + timedelta(days=days),
            )
            .order_by(Appointment.start_at)
            .limit(200)
        ).all()
        return _result(
            spec,
            source={**src, "records": len(appts)},
            kpis=[{"label": f"Next {days} days", "value": len(appts), "unit": None}],
            table={"columns": ["When", "Title"], "rows": [[a.start_at.astimezone(ZoneInfo(a.timezone)).strftime("%d %b %Y %H:%M"), a.title] for a in appts]},
        )
    if spec.key == "kokila.followups_open":
        rows = (
            db.execute(
                select(LeadActivity)
                .where(LeadActivity.tenant_id == tenant_id, LeadActivity.kind == "task", LeadActivity.completed_at.is_(None))
                .order_by(LeadActivity.due_at.nulls_last())
                .limit(200)
            )
            .scalars()
            .all()
        )
        return _result(
            spec,
            source={**src, "records": len(rows)},
            kpis=[{"label": "Open follow-ups", "value": len(rows), "unit": None}],
            table={"columns": ["Task", "Due"], "rows": [[t.body, t.due_at.astimezone(IST).strftime("%d %b %H:%M") if t.due_at else "—"] for t in rows]},
        )
    raise AppError("Metric not implemented", code="unknown_metric", status_code=422)
