import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Device, Server, User
from app.security.crypto import decrypt, encrypt
from app.services.users import ACCESS_ERRORS, Access, access_state
from app.vpn import vless, wireguard
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


@dataclass
class Credentials:
    key: str  # WireGuard public key | VLESS user label
    private: str  # what goes into the client config: WireGuard private key | VLESS uuid
    secret: str  # what the node needs besides the key: WireGuard psk | VLESS uuid
    address: str  # WireGuard tunnel IP | VLESS label


async def _new_credentials(session: AsyncSession, server: Server, keep: Device | None) -> Credentials:
    """`keep` = device whose identity may be reused (same WireGuard IP / same VLESS uuid)."""
    if server.protocol == "vless":
        if keep is not None and keep.protocol == "vless":
            uid = decrypt(keep.private_key_enc)
            return Credentials(keep.public_key, uid, uid, keep.public_key)
        label, uid = vless.new_label(), vless.new_uuid()
        return Credentials(label, uid, uid, label)

    if keep is not None and keep.protocol == "wireguard" and keep.server_id == server.id:
        address = keep.address  # WireGuard moves an allowed-ip to the newest peer that claims it
    else:
        used = await _used_addresses(session, server.id)
        if len(used) >= server.max_peers:
            raise DeviceError("Сервер переполнен, выберите другой", 409)
        address = wireguard.allocate_address(server.subnet, used)
    keys = wireguard.generate_keypair()
    return Credentials(keys.public_key, keys.private_key, wireguard.generate_psk(), address)


async def _provision(session: AsyncSession, server: Server, keep: Device | None = None) -> Credentials:
    """Create credentials and push them to the node. Nothing is saved yet."""
    if server.protocol == "vless":
        active = await session.scalar(
            select(func.count(Device.id)).where(Device.server_id == server.id, Device.status == "active")
        )
        if active >= server.max_peers and (keep is None or keep.server_id != server.id):
            raise DeviceError("Сервер переполнен, выберите другой", 409)
    creds = await _new_credentials(session, server, keep)
    try:
        await get_driver(server).add_peer(creds.key, creds.secret, creds.address)
    except NodeError as e:
        log.warning("add_peer failed on %s: %s", server.code, e)
        raise DeviceError("Сервер не отвечает, попробуйте другой или позже", 503) from e
    return creds


def _apply(device: Device, server: Server, creds: Credentials) -> None:
    device.server_id = server.id
    device.server = server
    device.protocol = server.protocol
    device.public_key = creds.key
    device.private_key_enc = encrypt(creds.private)
    device.psk_enc = encrypt(creds.secret)
    device.address = creds.address


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

    creds = await _provision(session, server)
    device = Device(user_id=user.id, name=name, platform=platform, sub_token=secrets.token_urlsafe(24))
    _apply(device, server, creds)
    session.add(device)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        await remove_peer_quietly(server, creds.key)
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
    """Same server (or no server given): rotate credentials, the old config stops working.
    Another server: move the device. VLESS keeps its uuid and subscription URL, so apps like Happ
    pick up the new server on the next subscription refresh without re-import."""
    if device.status != "active":
        raise DeviceError("Конфигурация отозвана", 409)
    _check_access(device.user)
    old_server, old_key = device.server, device.public_key
    server = await _get_server(session, server_id or device.server_id)
    rotate = server.id == old_server.id

    if rotate:
        # same identity slot (WireGuard IP), fresh secrets
        creds = await _provision(session, server, keep=device if device.protocol == "wireguard" else None)
    else:
        creds = await _provision(session, server, keep=device)
    _apply(device, server, creds)
    if rotate:
        device.sub_token = secrets.token_urlsafe(24)
    device.raw_rx = device.raw_tx = 0
    device.last_handshake_at = device.session_started_at = None
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        await remove_peer_quietly(server, creds.key)
        raise DeviceError("Конфликт адресов, повторите попытку", 409) from e
    if old_server.id != server.id or old_key != creds.key:
        await remove_peer_quietly(old_server, old_key)
    return device


def render_config(device: Device) -> tuple[str, str]:
    """Returns (config text, file name). Never log the result."""
    if device.status != "active":
        raise DeviceError("Конфигурация отозвана", 409)
    proto = get_protocol(device.protocol)
    # WireGuard derives the tunnel name from the file name: max 32 chars of [a-zA-Z0-9_=+.-]
    safe = "".join(c for c in device.name if c.isascii() and (c.isalnum() or c in "-_")) or str(device.id)
    stem = f"nova-{device.server.code}-{safe}"[:32]  # WireGuard tunnel name limit
    return proto.render(device, device.server), f"{stem}.{proto.file_ext}"
