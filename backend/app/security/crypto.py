"""Secrets at rest (Fernet) and short-lived signed tokens (HMAC)."""

import base64
import hashlib
import hmac
import json
import logging
import time
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

log = logging.getLogger(__name__)


class TokenError(ValueError):
    pass


def _secret_key() -> bytes:
    settings = get_settings()
    if settings.secret_key:
        return settings.secret_key.encode()
    if settings.dev_mode:
        return b"nova-dev-only-secret"
    raise RuntimeError("SECRET_KEY is not set")


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode())
    if settings.dev_mode:
        log.warning("ENCRYPTION_KEY is empty, deriving a dev key from SECRET_KEY (dev mode only)")
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(_secret_key()).digest()))
    raise RuntimeError("ENCRYPTION_KEY is not set")


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("cannot decrypt secret: ENCRYPTION_KEY changed?") from e


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_token(purpose: str, payload: dict, ttl: int) -> str:
    body = _b64(json.dumps({**payload, "p": purpose, "exp": int(time.time()) + ttl}).encode())
    sig = _b64(hmac.new(_secret_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str, purpose: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError as e:
        raise TokenError("malformed token") from e
    expected = _b64(hmac.new(_secret_key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        raise TokenError("bad signature")
    try:
        data = json.loads(_unb64(body))
    except ValueError as e:  # bad base64 / utf-8 / json: a 4xx, not a 500
        raise TokenError("malformed token") from e
    if not isinstance(data, dict):
        raise TokenError("malformed token")
    if data.get("p") != purpose:
        raise TokenError("wrong purpose")
    if data.get("exp", 0) < time.time():
        raise TokenError("expired")
    return data
