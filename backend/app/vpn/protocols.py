"""Protocol registry. A protocol knows how to turn a device into something a client app imports."""

from dataclasses import dataclass
from typing import Callable

from app.models import Device, Server
from app.security.crypto import decrypt
from app.vpn import vless, wireguard


@dataclass(frozen=True)
class Protocol:
    code: str
    title: str
    file_ext: str
    render: Callable[[Device, Server], str]
    subscription: bool  # can be delivered as a subscription URL (Happ & co.)


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


def _render_vless(device: Device, server: Server) -> str:
    from app.services.servers import flag

    return vless.render_link(
        user_id=decrypt(device.private_key_enc),
        host=server.host,
        port=server.port,
        params=vless.parse_params(server.params),
        name=f"{flag(server.country)} NOVA {server.name}",
    )


PROTOCOLS: dict[str, Protocol] = {
    "wireguard": Protocol("wireguard", "WireGuard", "conf", _render_wireguard, subscription=False),
    "vless": Protocol("vless", "VLESS", "txt", _render_vless, subscription=True),
}


def get_protocol(code: str) -> Protocol:
    try:
        return PROTOCOLS[code]
    except KeyError as e:
        raise ValueError(f"unsupported protocol {code}") from e
