import json
import time

import pytest

from app.security.crypto import TokenError, decrypt, encrypt, sign_token, verify_token
from app.security.telegram import InitDataError, sign_init_data, validate_init_data
from app.vpn import wireguard

TOKEN = "123456:TEST-TOKEN"


def _init(user_id=7, auth_date=None):
    return sign_init_data(
        {"user": json.dumps({"id": user_id, "first_name": "Ann", "username": "ann"}),
         "auth_date": str(auth_date or int(time.time())), "query_id": "AAA"},
        TOKEN,
    )


def test_valid_init_data():
    u = validate_init_data(_init(), TOKEN)
    assert (u.id, u.username) == (7, "ann")


def test_tampered_init_data():
    with pytest.raises(InitDataError):
        validate_init_data(_init().replace("ann", "bob"), TOKEN)
    with pytest.raises(InitDataError):
        validate_init_data(_init(), "999:OTHER")


def test_expired_init_data():
    with pytest.raises(InitDataError):
        validate_init_data(_init(auth_date=int(time.time()) - 90000), TOKEN, max_age=86400)


def test_tokens():
    t = sign_token("dl", {"d": 1}, 60)
    assert verify_token(t, "dl")["d"] == 1
    with pytest.raises(TokenError):
        verify_token(t, "admin")
    with pytest.raises(TokenError):
        verify_token(t[:-2] + "xx", "dl")
    with pytest.raises(TokenError):
        verify_token(sign_token("dl", {}, -1), "dl")


def test_token_with_valid_signature_but_garbage_body():
    import hashlib
    import hmac

    from app.security.crypto import _b64, _secret_key

    body = _b64(b"not-json")
    sig = _b64(hmac.new(_secret_key(), body.encode(), hashlib.sha256).digest())
    with pytest.raises(TokenError):
        verify_token(f"{body}.{sig}", "dl")


def test_encryption_roundtrip():
    blob = encrypt("secret")
    assert "secret" not in blob and decrypt(blob) == "secret"


def test_latest_bucket_ignores_previous_poll():
    from datetime import UTC, datetime, timedelta

    from app.services.stats import latest_bucket

    now = datetime.now(UTC)
    rows = [
        (now - timedelta(seconds=60), 6000, 60),
        (now, 6000, 0),
        (now - timedelta(seconds=1), 3000, 30),
    ]
    assert latest_bucket(rows, timedelta(seconds=30)) == (9000, 30)


def test_rate_limit_evicts_idle_keys_and_keeps_the_offender():
    from collections import deque

    from app.security.ratelimit import SlidingWindow, strict_limit

    assert strict_limit("/api/devices", "POST") == ("/api/devices", 10)
    assert strict_limit("/api/devices/5/regenerate", "POST") is None
    assert strict_limit("/api/admin/login", "POST") == ("/api/admin/login", 5)

    window = SlidingWindow()
    now = time.monotonic()
    window._hits["hot"] = deque([now - 50, now - 50, now - 50])
    for i in range(20):
        window._hits[f"k{i}"] = deque([now - 10])
    # "hot" is already over the limit and older than the other keys. Eviction must not free it.
    assert window.allow("hot", 3, max_keys=10) is False
    assert len(window._hits["hot"]) == 3
    assert len(window._hits) <= 10


async def test_mock_ping_respects_country_case():
    from app.models import Server
    from app.vpn.drivers import MockDriver

    server = Server(code="de-ping", name="Germany", country="DE", host="de.example", public_key="k")
    samples = [await MockDriver(server).ping() for _ in range(20)]
    assert all(15 <= sample <= 22 for sample in samples)


def test_wireguard_keys_and_addresses():
    kp = wireguard.generate_keypair()
    assert wireguard.public_from_private(kp.private_key) == kp.public_key
    assert wireguard.is_valid_key(kp.public_key) and not wireguard.is_valid_key("nope")
    assert wireguard.allocate_address("10.8.0.0/24", set()) == "10.8.0.2/32"
    assert wireguard.allocate_address("10.8.0.0/24", {"10.8.0.2/32", "10.8.0.3/32"}) == "10.8.0.4/32"
    with pytest.raises(RuntimeError):
        wireguard.allocate_address("10.8.0.0/30", {"10.8.0.2/32"})
