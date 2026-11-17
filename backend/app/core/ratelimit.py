import logging
import time

import redis
from fastapi import Request

from app.core.config import get_settings
from app.core.errors import AppError

log = logging.getLogger("kokila.ratelimit")
_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
    return _client


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


def check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    """Fixed-window limiter in Redis. Fails open (logged) if Redis is unreachable."""
    bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
    try:
        r = get_redis()
        count = r.incr(bucket)
        if count == 1:
            r.expire(bucket, window_seconds + 1)
    except redis.RedisError:
        log.warning("rate limiter unavailable; allowing request", extra={"key": key})
        return
    if int(count) > limit:  # type: ignore[arg-type]
        raise RateLimited("Too many requests, slow down")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def auth_rate_limit(request: Request) -> None:
    check_rate_limit(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)


def webhook_rate_limit(request: Request) -> None:
    check_rate_limit(f"wh:{client_ip(request)}", get_settings().rate_limit_webhook_per_minute)
