from __future__ import annotations

import asyncio

import orjson

from app.core.ratelimit import redis_client
from app.worker import channel_for, dispatch_outbox_once
from tests.conftest import new_user


async def test_outbox_dispatch_publishes_once(client, super_admin):
    user, _ = await new_user(client)
    pubsub = redis_client().pubsub()
    await pubsub.subscribe(channel_for(user.workspace_id))
    await user.patch("/v1/assistant/preferences", json={"display_name": "Ben", "expected_revision": 0})
    sent = await dispatch_outbox_once()
    assert sent >= 1
    msg = None
    for _ in range(50):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg:
            break
        await asyncio.sleep(0.05)
    assert msg is not None
    assert orjson.loads(msg["data"])["type"] == "assistant.identity.changed"
    assert await dispatch_outbox_once() == 0  # nothing left to send: no duplicate publication
    await pubsub.aclose()
