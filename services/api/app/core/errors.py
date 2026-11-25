"""Canonical error envelope: {error:{code,message,trace_id,retryable}} (§24.3)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import current_trace_id
from app.domain.constants import ErrorCode

log = logging.getLogger("kokila.errors")


class KokilaError(Exception):
    status_code = 400
    code: ErrorCode = ErrorCode.VALIDATION_FAILED
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable
        self.details = details or {}


class Unauthenticated(KokilaError):
    status_code, code = 401, ErrorCode.UNAUTHENTICATED


class Forbidden(KokilaError):
    status_code, code = 403, ErrorCode.FORBIDDEN


class CapabilityDisabled(KokilaError):
    status_code, code = 403, ErrorCode.CAPABILITY_DISABLED


class MfaRequired(KokilaError):
    status_code, code = 403, ErrorCode.MFA_REQUIRED


class NotFound(KokilaError):
    """404 is also used for inaccessible resources so tenant existence never leaks."""

    status_code, code = 404, ErrorCode.NOT_FOUND


class Conflict(KokilaError):
    status_code, code = 409, ErrorCode.STATE_CONFLICT


class RevisionConflict(Conflict):
    code = ErrorCode.REVISION_CONFLICT


class QuotaExceeded(KokilaError):
    status_code, code = 429, ErrorCode.QUOTA_EXCEEDED


class ProviderUnavailable(KokilaError):
    status_code, code, retryable = 503, ErrorCode.PROVIDER_UNAVAILABLE, True


def _envelope(code: str, message: str, retryable: bool, details: dict[str, Any] | None = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message, "trace_id": current_trace_id(), "retryable": retryable}
    if details:
        body["details"] = details
    return {"error": body}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(KokilaError)
    async def _kokila(_: Request, exc: KokilaError) -> JSONResponse:
        return JSONResponse(_envelope(exc.code, exc.message, exc.retryable, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Strip input values from the echo so payloads (possibly sensitive) are not reflected.
        errs = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(
            _envelope(ErrorCode.VALIDATION_FAILED, "request validation failed", False, {"errors": errs}),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: ErrorCode.UNAUTHENTICATED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.VALIDATION_FAILED,
            429: ErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ErrorCode.INTERNAL)
        return JSONResponse(_envelope(code, str(exc.detail), False), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(_envelope(ErrorCode.INTERNAL, "internal error", True), status_code=500)
