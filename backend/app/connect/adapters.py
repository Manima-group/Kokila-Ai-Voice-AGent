"""Connector adapters. All network calls have explicit timeouts; responses are treated as untrusted data."""

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from app.core.security import decrypt_secret

MAX_ROWS = 20000
PAGE = 500

_http_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))  # noqa: E731


def set_http_factory(factory: Callable[[], httpx.Client] | None) -> None:
    """Test hook (inject httpx.MockTransport)."""
    global _http_factory
    _http_factory = factory or (lambda: httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)))


class ConnectorError(Exception):
    def __init__(self, message: str, *, code: str = "connector_error"):
        super().__init__(message)
        self.code = code


def credentials(conn) -> dict:
    return json.loads(decrypt_secret(conn.encrypted_credentials)) if conn.encrypted_credentials else {}


def _safe_base(url: str | None) -> str:
    if not url or not url.startswith(("https://", "http://")):
        raise ConnectorError("Connection has no valid base URL", code="invalid_config")
    return url.rstrip("/")


class ERPNextAdapter:
    """Frappe/ERPNext REST API: token auth `Authorization: token <api_key>:<api_secret>`."""

    def __init__(self, conn, http: httpx.Client | None = None):
        creds = credentials(conn)
        self.base = _safe_base(conn.base_url)
        self.headers = {"Authorization": f"token {creds.get('api_key', '')}:{creds.get('api_secret', '')}", "Accept": "application/json"}
        self.http = http or _http_factory()

    def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            r = self.http.get(f"{self.base}{path}", params=params, headers=self.headers)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"ERPNext unreachable ({exc.__class__.__name__})", code="connector_unreachable") from exc
        if r.status_code in (401, 403):
            raise ConnectorError("ERPNext rejected the credentials or permissions", code="connector_unauthorized")
        if r.status_code >= 400:
            raise ConnectorError(f"ERPNext returned HTTP {r.status_code}", code="connector_error")
        try:
            return r.json()
        except ValueError as exc:
            raise ConnectorError("ERPNext returned a non-JSON response", code="connector_error") from exc

    def verify(self) -> str:
        user = self._get("/api/method/frappe.auth.get_logged_user").get("message")
        if not user:
            raise ConnectorError("ERPNext did not return the authenticated user", code="connector_unauthorized")
        return str(user)

    def list_docs(self, doctype: str, fields: list[str], filters: list) -> list[dict]:
        rows: list[dict] = []
        start = 0
        while True:
            data = self._get(
                f"/api/resource/{doctype}",
                {
                    "fields": json.dumps(fields),
                    "filters": json.dumps(filters),
                    "limit_start": start,
                    "limit_page_length": PAGE,
                    "order_by": "creation asc",
                },
            ).get("data", [])
            if not isinstance(data, list):
                raise ConnectorError("Unexpected ERPNext response shape")
            rows += data
            if len(data) < PAGE:
                return rows
            start += PAGE
            if start >= MAX_ROWS:
                raise ConnectorError(f"More than {MAX_ROWS} {doctype} records match; narrow the period", code="too_many_rows")

    def company_currency(self) -> tuple[str | None, int]:
        companies = self._get("/api/resource/Company", {"fields": json.dumps(["name", "default_currency"]), "limit_page_length": 50}).get("data", [])
        currencies = {c.get("default_currency") for c in companies if c.get("default_currency")}
        return (currencies.pop() if len(currencies) == 1 else None), len(companies)

    def sales_invoices(self, start: date, end: date) -> list[dict]:
        return self.list_docs(
            "Sales Invoice",
            ["name", "posting_date", "customer", "base_net_total", "base_grand_total", "is_return"],
            [["docstatus", "=", 1], ["posting_date", "between", [start.isoformat(), end.isoformat()]]],
        )

    def overdue_invoices(self, today: date) -> list[dict]:
        return self.list_docs(
            "Sales Invoice",
            ["name", "customer", "due_date", "outstanding_amount"],
            [["docstatus", "=", 1], ["outstanding_amount", ">", 0], ["due_date", "<", today.isoformat()]],
        )

    def outstanding_invoices(self) -> list[dict]:
        return self.list_docs("Sales Invoice", ["name", "customer", "due_date", "outstanding_amount"], [["docstatus", "=", 1], ["outstanding_amount", ">", 0]])

    def low_stock(self, threshold: float) -> list[dict]:
        return self.list_docs("Bin", ["item_code", "warehouse", "actual_qty", "projected_qty"], [["actual_qty", "<=", threshold]])


class ManimaHubAdapter:
    """Kokila Connect host protocol (implemented by Manima Hub):
    GET  {base}/kokila/v1/manifest            -> {"host": str, "metrics": [{"key": str, "title": str}]}
    POST {base}/kokila/v1/metrics/{key}       -> MetricResult JSON (same shape Kokila renders)
    Auth: `Authorization: Bearer <access_token>`.
    """

    def __init__(self, conn, http: httpx.Client | None = None):
        self.base = _safe_base(conn.base_url)
        self.headers = {"Authorization": f"Bearer {credentials(conn).get('access_token', '')}", "Accept": "application/json"}
        self.http = http or _http_factory()

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            r = self.http.request(method, f"{self.base}{path}", json=body, headers=self.headers)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Manima Hub unreachable ({exc.__class__.__name__})", code="connector_unreachable") from exc
        if r.status_code in (401, 403):
            raise ConnectorError("Manima Hub rejected the token", code="connector_unauthorized")
        if r.status_code == 404:
            raise ConnectorError("Manima Hub does not expose the Kokila Connect endpoint", code="connector_unsupported")
        if r.status_code >= 400:
            raise ConnectorError(f"Manima Hub returned HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError as exc:
            raise ConnectorError("Manima Hub returned a non-JSON response") from exc
        if not isinstance(data, dict):
            raise ConnectorError("Unexpected Manima Hub response shape")
        return data

    def manifest(self) -> dict:
        m = self._req("GET", "/kokila/v1/manifest")
        if not isinstance(m.get("metrics"), list):
            raise ConnectorError("Manifest missing 'metrics'", code="invalid_manifest")
        return m

    def verify(self) -> str:
        return str(self.manifest().get("host", "manima-hub"))

    def metric(self, key: str, params: dict) -> dict:
        return self._req("POST", f"/kokila/v1/metrics/{key}", params)
