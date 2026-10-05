"""Validation of Telegram Mini App initData.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> TelegramUser:
    if not init_data or not bot_token:
        raise InitDataError("missing init data")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("bad signature")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as e:
        raise InitDataError("bad auth_date") from e
    if max_age and time.time() - auth_date > max_age:
        raise InitDataError("init data expired")

    try:
        raw = json.loads(pairs["user"])
        return TelegramUser(
            id=int(raw["id"]),
            first_name=raw.get("first_name"),
            username=raw.get("username"),
            language_code=raw.get("language_code"),
            photo_url=raw.get("photo_url"),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise InitDataError("bad user payload") from e


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Build a valid initData string. Used by tests and local tooling only."""
    from urllib.parse import urlencode

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})
