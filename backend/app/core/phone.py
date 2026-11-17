import phonenumbers

from app.core.errors import AppError


def normalize_e164(raw: str, default_region: str = "IN") -> str:
    """Normalize to E.164 or raise AppError. Defaults to India for national-format numbers."""
    try:
        parsed = phonenumbers.parse(raw.strip(), default_region)
    except phonenumbers.NumberParseException as exc:
        raise AppError(f"Invalid phone number: {raw!r}", code="invalid_phone") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise AppError(f"Invalid phone number: {raw!r}", code="invalid_phone")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def try_normalize(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return normalize_e164(raw)
    except AppError:
        return None


def mask_phone(e164: str | None) -> str:
    if not e164:
        return ""
    return e164[:4] + "*" * max(len(e164) - 7, 0) + e164[-3:]
