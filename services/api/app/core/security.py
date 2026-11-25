"""Password hashing (Argon2id), JWT access tokens, refresh tokens, MFA secrets (§32.1)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.core.errors import Unauthenticated

# Parameters follow argon2-cffi's RFC 9106 "low memory" profile; recalibrate per deployment hardware.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)
# Constant-time dummy verification for unknown accounts (anti-enumeration).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    mfa: bool
    session_family: uuid.UUID
    platform: bool


def issue_access_token(
    *, user_id: uuid.UUID, tenant_id: uuid.UUID | None, mfa: bool, family_id: uuid.UUID, platform: bool
) -> tuple[str, datetime]:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=s.access_token_ttl_s)
    payload: dict[str, Any] = {
        "iss": s.jwt_issuer,
        "aud": "kokila-api",
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
        "tid": str(tenant_id) if tenant_id else None,
        "amr": ["pwd", "otp"] if mfa else ["pwd"],
        "fam": str(family_id),
        "plt": platform,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256"), exp


def decode_access_token(token: str) -> AccessClaims:
    s = get_settings()
    try:
        p = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="kokila-api",
            issuer=s.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
        return AccessClaims(
            user_id=uuid.UUID(p["sub"]),
            tenant_id=uuid.UUID(p["tid"]) if p.get("tid") else None,
            mfa="otp" in p.get("amr", []),
            session_family=uuid.UUID(p["fam"]),
            platform=bool(p.get("plt")),
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise Unauthenticated("invalid or expired access token") from exc


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    key = get_settings().jwt_secret.get_secret_value().encode()
    return hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()


def _aead() -> AESGCM:
    key = base64.urlsafe_b64decode(get_settings().data_encryption_key.get_secret_value())
    return AESGCM(key)


def encrypt_secret(plaintext: str, aad: str) -> str:
    nonce = os.urandom(12)
    ct = _aead().encrypt(nonce, plaintext.encode(), aad.encode())
    return "v1:" + base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt_secret(token: str, aad: str) -> str:
    if not token.startswith("v1:"):
        raise ValueError("unknown secret envelope")
    raw = base64.urlsafe_b64decode(token[3:])
    return _aead().decrypt(raw[:12], raw[12:], aad.encode()).decode()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().mfa_issuer_name)


def args_hash(args: dict[str, Any]) -> str:
    import orjson

    return hashlib.sha256(orjson.dumps(args, option=orjson.OPT_SORT_KEYS)).hexdigest()
