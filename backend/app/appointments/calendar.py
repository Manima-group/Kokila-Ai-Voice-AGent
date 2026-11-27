"""Calendar adapters: Google Calendar (REST v3 via httpx) and an internal DB-only calendar."""

import json
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_API = "https://www.googleapis.com/calendar/v3"
SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.freebusy"


class CalendarError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def event_id_for(appointment_id) -> str:
    # Google event ids: base32hex chars [a-v0-9], 5-1024 long. UUID hex is a subset -> deterministic & idempotent.
    return "kk" + appointment_id.hex


def google_authorize_url(state: str) -> str:
    s = get_settings()
    q = httpx.QueryParams(
        {
            "client_id": s.google_client_id,
            "redirect_uri": s.google_redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GOOGLE_AUTH_URL}?{q}"


def google_exchange_code(code: str) -> dict:
    s = get_settings()
    r = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": s.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if r.status_code != 200:
        raise CalendarError("Google token exchange failed", status=r.status_code)
    return r.json()


class GoogleCalendar:
    def __init__(self, connection, http: httpx.Client | None = None):
        self.conn = connection
        self.http = http or httpx.Client(timeout=15)

    def _tokens(self) -> dict:
        return json.loads(decrypt_secret(self.conn.encrypted_tokens)) if self.conn.encrypted_tokens else {}

    def _access_token(self) -> str:
        tokens = self._tokens()
        exp = self.conn.token_expires_at
        if tokens.get("access_token") and exp and exp > datetime.now(UTC) + timedelta(seconds=60):
            return tokens["access_token"]
        if not tokens.get("refresh_token"):
            raise CalendarError("Calendar connection lacks a refresh token; reconnect required", status=401)
        s = get_settings()
        r = self.http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "refresh_token": tokens["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        if r.status_code != 200:
            raise CalendarError("Token refresh failed", status=r.status_code)
        data = r.json()
        tokens["access_token"] = data["access_token"]
        self.conn.encrypted_tokens = encrypt_secret(json.dumps(tokens))
        self.conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(data.get("expires_in", 3600)))
        return tokens["access_token"]

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            return self.http.request(method, f"{GOOGLE_API}{path}", headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise CalendarError(f"Google Calendar unreachable: {exc.__class__.__name__}") from exc

    def busy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        r = self._req(
            "POST",
            "/freeBusy",
            json={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "items": [{"id": self.conn.calendar_id}],
            },
        )
        if r.status_code != 200:
            raise CalendarError("freeBusy failed", status=r.status_code)
        cal = r.json().get("calendars", {}).get(self.conn.calendar_id, {})
        return [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in cal.get("busy", [])]

    def create_event(self, event_id: str, summary: str, start: datetime, end: datetime, tz: str) -> str:
        body = {
            "id": event_id,
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
        }
        r = self._req("POST", f"/calendars/{self.conn.calendar_id}/events", json=body)
        if r.status_code in (200, 201):
            return r.json()["id"]
        if r.status_code == 409:  # already created by an earlier attempt with the same deterministic id
            if self.event_exists(event_id):
                return event_id
        raise CalendarError("Event creation failed", status=r.status_code)

    def event_exists(self, event_id: str) -> bool:
        r = self._req("GET", f"/calendars/{self.conn.calendar_id}/events/{event_id}")
        if r.status_code == 200:
            return r.json().get("status") != "cancelled"
        if r.status_code in (404, 410):
            return False
        raise CalendarError("Event lookup failed", status=r.status_code)

    def update_event(self, event_id: str, start: datetime, end: datetime, tz: str) -> None:
        r = self._req(
            "PATCH",
            f"/calendars/{self.conn.calendar_id}/events/{event_id}",
            json={
                "start": {"dateTime": start.isoformat(), "timeZone": tz},
                "end": {"dateTime": end.isoformat(), "timeZone": tz},
            },
        )
        if r.status_code != 200:
            raise CalendarError("Event update failed", status=r.status_code)

    def delete_event(self, event_id: str) -> None:
        r = self._req("DELETE", f"/calendars/{self.conn.calendar_id}/events/{event_id}")
        if r.status_code not in (200, 204, 404, 410):
            raise CalendarError("Event delete failed", status=r.status_code)


_google_factory = GoogleCalendar


def calendar_for(connection):
    """Return an external adapter, or None for the internal (Kokila-DB-authoritative) calendar."""
    if connection.provider == "google":
        return _google_factory(connection)
    return None


def set_google_factory(factory) -> None:
    """Test hook to inject a fake Google client."""
    global _google_factory
    _google_factory = factory
