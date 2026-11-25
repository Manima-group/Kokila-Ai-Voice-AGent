"""Fixed-window rate limiting in Redis, with a bounded in-process fallback if Redis is unreachable."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import KokilaError
from app.domain.constants import ErrorCode

log = logging.getLogger("kokila.ratelimit")
_client: aioredis.Redis | None = None
_local: OrderedDict[str, tuple[int, int]] = OrderedDict()
_LOCAL_MAX = 10_000


def redis_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def _key(bucket: str, ident: str, window: int) -> str:
    env = get_settings().env.value
    return f"kokila:{env}:rl:v1:{bucket}:{ident}:{int(time.time()) // window}"


async def hit(bucket: str, ident: str, *, limit: int, window_s: int) -> None:
    key = _key(bucket, ident, window_s)
    try:
        r = redis_client()
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window_s)
    except (RedisError, OSError):
        log.warning("ratelimit_redis_unavailable", extra={"bucket": bucket})
        win = int(time.time()) // window_s
        prev = _local.get(key)
        count = (prev[1] + 1) if prev and prev[0] == win else 1
        _local[key] = (win, count)
        _local.move_to_end(key)
        while len(_local) > _LOCAL_MAX:
            _local.popitem(last=False)
    if count > int(limit * get_settings().rate_limit_scale):
        raise KokilaError(
            "too many requests; try again later", code=ErrorCode.RATE_LIMITED, status_code=429, retryable=True
        )
