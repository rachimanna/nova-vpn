"""Protocol registry. Adding e.g. AmneziaWG = new entry with its own config renderer."""

from dataclasses import dataclass
from typing import Callable

from app.models import Device, Server
from app.security.crypto import decrypt
from app.vpn import wireguard


@dataclass(frozen=True)
class Protocol:
    code: str
    title: str
    file_ext: str
    render: Callable[[Device, Server], str]


def _render_wireguard(device: Device, server: Server) -> str:
    return wireguard.render_client_config(
        private_key=decrypt(device.private_key_enc),
        address=device.address,
        dns=server.dns,
        server_public_key=server.public_key,
        psk=decrypt(device.psk_enc),
        endpoint_host=server.host,
        endpoint_port=server.port,
    )


PROTOCOLS: dict[str, Protocol] = {
    "wireguard": Protocol("wireguard", "WireGuard", "conf", _render_wireguard),
}


def get_protocol(code: str) -> Protocol:
    try:
        return PROTOCOLS[code]
    except KeyError as e:
        raise ValueError(f"unsupported protocol {code}") from e
