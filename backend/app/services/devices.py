import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Device, Server, User
from app.security.crypto import encrypt
from app.services.users import ACCESS_ERRORS, Access, access_state
from app.vpn import wireguard
from app.vpn.drivers import NodeError, get_driver
from app.vpn.protocols import get_protocol

log = logging.getLogger(__name__)

PLATFORMS = {"ios", "android", "windows", "macos", "linux", "other"}


class DeviceError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def active_devices(user: User) -> list[Device]:
    return [d for d in user.devices if d.status == "active"]


def is_online(device: Device, now: datetime | None = None) -> bool:
    if device.status != "active" or not device.last_handshake_at:
        return False
    now = now or datetime.now(UTC)
    return now - device.last_handshake_at < timedelta(seconds=get_settings().online_threshold_seconds)


async def _get_server(session: AsyncSession, server_id: int) -> Server:
    server = await session.get(Server, server_id)
    if server is None or not server.is_active:
        raise DeviceError("Сервер недоступен", 404)
    return server


async def _used_addresses(session: AsyncSession, server_id: int) -> set[str]:
    rows = await session.scalars(
        select(Device.address).where(Device.server_id == server_id, Device.status == "active")
    )
    return set(rows)


async def _provision(
    session: AsyncSession, server: Server, address: str | None = None
) -> tuple[wireguard.KeyPair, str, str]:
    """Generate keys (+ address unless given) and push the peer to the node. Nothing is saved yet."""
    if address is None:
        used = await _used_addresses(session, server.id)
        if len(used) >= server.max_peers:
            raise DeviceError("Сервер переполнен, выберите другой", 409)
        address = wireguard.allocate_address(server.subnet, used)
    keys = wireguard.generate_keypair()
    psk = wireguard.generate_psk()
    try:
        await get_driver(server).add_peer(keys.public_key, psk, address)
    except NodeError as e:
        log.warning("add_peer failed on %s: %s", server.code, e)
        raise DeviceError("Сервер не отвечает, попробуйте другой или позже", 503) from e
    return keys, psk, address


async def remove_peer_quietly(server: Server, public_key: str) -> None:
    try:
        await get_driver(server).remove_peer(public_key)
    except NodeError:
        pass  # reconcile will remove it later


def _check_access(user: User) -> None:
    state = access_state(user)
    if state is not Access.ACTIVE:
        raise DeviceError(ACCESS_ERRORS[state], 403)


async def create_device(
    session: AsyncSession, user: User, *, server_id: int, name: str, platform: str, enforce_limits: bool = True
) -> Device:
    if enforce_limits:
        _check_access(user)
        if len(active_devices(user)) >= user.device_limit:
            raise DeviceError(f"Достигнут лимит устройств ({user.device_limit})", 409)
    name = name.strip()[:48] or "Устройство"
    platform = platform if platform in PLATFORMS else "other"
    server = await _get_server(session, server_id)

    keys, psk, address = await _provision(session, server)
    device = Device(
        user_id=user.id,
        server_id=server.id,
        name=name,
        platform=platform,
        protocol=server.protocol,
        public_key=keys.public_key,
        private_key_enc=encrypt(keys.private_key),
        psk_enc=encrypt(psk),
        address=address,
    )
    device.server = server
    session.add(device)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        await remove_peer_quietly(server, keys.public_key)
        raise DeviceError("Конфликт адресов, повторите попытку", 409) from e
    user.devices.append(device)
    log.info("device %s created for user %s on %s", device.id, user.id, server.code)
    return device


async def revoke_device(session: AsyncSession, device: Device) -> None:
    if device.status != "active":
        return
    device.status = "revoked"
    device.revoked_at = datetime.now(UTC)
    device.session_started_at = None
    await session.commit()
    await remove_peer_quietly(device.server, device.public_key)
    log.info("device %s revoked", device.id)


async def regenerate_device(session: AsyncSession, device: Device, server_id: int | None = None) -> Device:
    """New keys (and optionally a new server). The old config stops working immediately."""
    if device.status != "active":
        raise DeviceError("Конфигурация отозвана", 409)
    _check_access(device.user)
    old_server, old_key = device.server, device.public_key
    server = await _get_server(session, server_id or device.server_id)

    # Same server: keep the IP. WireGuard moves an allowed-ip to the newest peer that claims it.
    same = server.id == old_server.id
    keys, psk, address = await _provision(session, server, device.address if same else None)
    device.server_id = server.id
    device.server = server
    device.protocol = server.protocol
    device.public_key = keys.public_key
    device.private_key_enc = encrypt(keys.private_key)
    device.psk_enc = encrypt(psk)
    device.address = address
    device.raw_rx = device.raw_tx = 0
    device.last_handshake_at = device.session_started_at = None
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        await remove_peer_quietly(server, keys.public_key)
        raise DeviceError("Конфликт адресов, повторите попытку", 409) from e
    await remove_peer_quietly(old_server, old_key)
    return device


def render_config(device: Device) -> tuple[str, str]:
    """Returns (config text, file name). Never log the result."""
    if device.status != "active":
        raise DeviceError("Конфигурация отозвана", 409)
    proto = get_protocol(device.protocol)
    # WireGuard derives the tunnel name from the file name: max 32 chars of [a-zA-Z0-9_=+.-]
    safe = "".join(c for c in device.name if c.isascii() and (c.isalnum() or c in "-_")) or str(device.id)
    stem = f"nova-{device.server.code}-{safe}"[:32]
    return proto.render(device, device.server), f"{stem}.{proto.file_ext}"
