"""WireGuard primitives: key generation, address allocation, client config."""

import base64
import ipaddress
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


@dataclass(frozen=True)
class KeyPair:
    private_key: str
    public_key: str


def generate_keypair() -> KeyPair:
    """Curve25519 keys, identical to `wg genkey | wg pubkey` output."""
    priv = X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return KeyPair(base64.b64encode(priv_raw).decode(), base64.b64encode(pub_raw).decode())


def public_from_private(private_key: str) -> str:
    priv = X25519PrivateKey.from_private_bytes(base64.b64decode(private_key))
    return base64.b64encode(
        priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode()


def generate_psk() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def is_valid_key(key: str) -> bool:
    try:
        return len(base64.b64decode(key, validate=True)) == 32
    except ValueError:
        return False


def allocate_address(subnet: str, used: set[str]) -> str:
    """First free host address. `.1` is reserved for the server itself."""
    net = ipaddress.ip_network(subnet, strict=False)
    taken = {str(ipaddress.ip_interface(a).ip) for a in used}
    hosts = net.hosts()
    next(hosts, None)  # server address
    for ip in hosts:
        if str(ip) not in taken:
            return f"{ip}/32"
    raise RuntimeError(f"subnet {subnet} is full")


def render_client_config(
    *,
    private_key: str,
    address: str,
    dns: str,
    server_public_key: str,
    psk: str,
    endpoint_host: str,
    endpoint_port: int,
    mtu: int | None = None,
) -> str:
    host = f"[{endpoint_host}]" if ":" in endpoint_host else endpoint_host
    return (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {address}\n"
        f"DNS = {dns}\n"
        + (f"MTU = {mtu}\n" if mtu else "")
        + "\n"
        "[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"PresharedKey = {psk}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        f"Endpoint = {host}:{endpoint_port}\n"
        "PersistentKeepalive = 25\n"
    )
