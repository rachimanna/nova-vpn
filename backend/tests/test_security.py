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


def test_encryption_roundtrip():
    blob = encrypt("secret")
    assert "secret" not in blob and decrypt(blob) == "secret"


def test_wireguard_keys_and_addresses():
    kp = wireguard.generate_keypair()
    assert wireguard.public_from_private(kp.private_key) == kp.public_key
    assert wireguard.is_valid_key(kp.public_key) and not wireguard.is_valid_key("nope")
    assert wireguard.allocate_address("10.8.0.0/24", set()) == "10.8.0.2/32"
    assert wireguard.allocate_address("10.8.0.0/24", {"10.8.0.2/32", "10.8.0.3/32"}) == "10.8.0.4/32"
    with pytest.raises(RuntimeError):
        wireguard.allocate_address("10.8.0.0/30", {"10.8.0.2/32"})


def test_malformed_token_is_rejected_not_crashing():
    for bad in ("!!!.sig", "e30.sig", "bm90LWpzb24.sig"):
        with pytest.raises(TokenError):
            verify_token(bad, "dl")


def test_client_configs_tuned_for_latency():
    from app.vpn import vless, wireguard

    conf = wireguard.render_client_config(private_key="k", address="10.8.0.2/32", dns="1.1.1.1",
                                          server_public_key="p", psk="s", endpoint_host="h", endpoint_port=1, mtu=1280)
    assert "MTU = 1280\n" in conf
    link = vless.render_link(user_id="u", host="h", port=443, params={"path": "/x"}, name="n")
    assert "path=%2Fx%3Fed%3D2048" in link
