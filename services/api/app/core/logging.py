"""Structured, redacted JSON logging with trace propagation (§29.5)."""

from __future__ import annotations

import contextvars
import logging
import re
import sys
import uuid
from datetime import UTC, datetime

import orjson

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_REDACT_KEYS = re.compile(r"(password|secret|token|authorization|api_key|cookie|otp|code)", re.I)
_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def new_trace_id() -> str:
    return uuid.uuid4().hex


def set_trace(trace_id: str, request_id: str) -> None:
    _trace_id.set(trace_id)
    _request_id.set(request_id)


def current_trace_id() -> str | None:
    return _trace_id.get()


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, build: str) -> None:
        super().__init__()
        self.service, self.build = service, build

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": self.service,
            "build": self.build,
            "trace_id": _trace_id.get(),
            "request_id": _request_id.get(),
        }
        for k, v in record.__dict__.items():
            if k in _STD_ATTRS or k.startswith("_"):
                continue
            payload[k] = "[redacted]" if _REDACT_KEYS.search(k) else v
        if record.exc_info:
            # Exception type only; stack traces stay out of public responses but are kept for operators.
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(payload, default=str).decode()


def configure_logging(service: str, build: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service, build))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
