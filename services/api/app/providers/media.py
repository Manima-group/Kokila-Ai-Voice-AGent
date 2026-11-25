"""Scoped, short-lived media credentials issued only by the backend (§4 step 1, §27.4).

* LiveKit: room-scoped access token (HS256 JWT per LiveKit's token format). ``canPublish``
  mirrors the server-side microphone mute flag, so a muted session cannot obtain publish rights.
* OpenAI Realtime: ephemeral client secret minted server-side; the permanent key never reaches clients.

Both require authorized credentials and are reported as unavailable (503) when not configured.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt

from app.core.config import get_settings
from app.core.errors import ProviderUnavailable


def livekit_token(*, session_id: uuid.UUID, user_id: uuid.UUID, display_name: str, can_publish: bool) -> dict:
    s = get_settings()
    if not (s.livekit_url and s.livekit_api_key and s.livekit_api_secret):
        raise ProviderUnavailable("realtime media (LiveKit) is not configured for this deployment", retryable=False)
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=s.media_token_ttl_s)
    room = f"kokila-{session_id}"
    claims = {
        "iss": s.livekit_api_key,
        "sub": str(user_id),
        "name": display_name,
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": can_publish,
            "canSubscribe": True,
            "canPublishData": True,
            "canPublishSources": ["microphone"] if can_publish else [],
        },
    }
    token = jwt.encode(claims, s.livekit_api_secret.get_secret_value(), algorithm="HS256")
    return {
        "provider": "livekit",
        "url": s.livekit_url,
        "room": room,
        "token": token,
        "expires_at": exp.isoformat(),
        "can_publish": can_publish,
    }


async def openai_realtime_client_secret(*, locale: str, instructions: str) -> dict:
    """Mint an ephemeral Realtime client secret. Endpoint/shape must be re-verified against current
    OpenAI documentation before release (tracked in docs/implementation-status.md)."""
    s = get_settings()
    if not (s.openai_api_key and s.openai_realtime_model):
        raise ProviderUnavailable(
            "realtime speech (OpenAI Realtime) is not configured for this deployment", retryable=False
        )
    body = {"session": {"type": "realtime", "model": s.openai_realtime_model, "instructions": instructions}}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            r = await client.post(
                f"{s.openai_base_url}/realtime/client_secrets",
                json=body,
                headers={"Authorization": f"Bearer {s.openai_api_key.get_secret_value()}"},
            )
    except httpx.TransportError as exc:
        raise ProviderUnavailable("realtime speech provider unreachable") from exc
    if r.status_code >= 400:
        raise ProviderUnavailable(f"realtime speech provider refused the session ({r.status_code})")
    data = r.json()
    return {
        "provider": "openai_realtime",
        "model": s.openai_realtime_model,
        "locale": locale,
        "client_secret": data.get("value"),
        "expires_at": data.get("expires_at"),
    }
