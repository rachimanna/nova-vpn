import asyncio
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
# Columns that decide whether a user may receive a config. Refreshed explicitly so a
# concurrent request sees a ban, a new limit or spent traffic without dropping the
# already-loaded devices collection (that would lazy-load inside async code).
_ACCESS_FIELDS = ["is_banned", "expires_at", "traffic_used", "traffic_limit", "device_limit"]
# One process, one loop: serialise config mutations so two requests cannot take the same
# WireGuard address. WireGuard silently moves an allowed-ip to the newest peer.
_mutation_lock = asyncio.Lock()


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


async def _seen_snapshot(session: AsyncSession) -> None:
    """Close the open read transaction so the next query sees other requests' commits."""
    await session.commit()


async def _active_count(session: AsyncSession, user_id: int) -> int:
    value = await session.scalar(
        select(func.count(Device.id)).where(Device.user_id == user_id, Device.status == "active")
    )
    return int(value or 0)


async def _drop_peer_and_heal(session: AsyncSession, server: Server, creds: Credentials) -> None:
    """Drop a peer that lost the DB race and give the address back to its owner.

    Adding a WireGuard peer removes that allowed-ip from whoever had it. If our insert then
    loses the unique index, the winner's tunnel is left with no address until we push it again.
    """
    await remove_peer_quietly(server, creds.key)
    owner = await session.scalar(
        select(Device).where(
            Device.server_id == server.id,
            Device.address == creds.address,
            Device.status == "active",
            Device.public_key != creds.key,
        )
    )
    if owner is None:
        return
    try:
        await get_driver(server).add_peer(owner.public_key, decrypt(owner.psk_enc), owner.address)
    except NodeError as e:
        log.warning("restore peer failed on %s: %s", server.code, e)


def _check_access(user: User) -> None:
    state = access_state(user)
    if state is not Access.ACTIVE:
        raise DeviceError(ACCESS_ERRORS[state], 403)


async def create_device(
    session: AsyncSession, user: User, *, server_id: int, name: str, platform: str, enforce_limits: bool = True
) -> Device:
    async with _mutation_lock:
        await _seen_snapshot(session)
        await session.refresh(user, attribute_names=_ACCESS_FIELDS)
        if enforce_limits:
            _check_access(user)
            if await _active_count(session, user.id) >= user.device_limit:
                raise DeviceError(f"Достигнут лимит устройств ({user.device_limit})", 409)
        name = name.strip()[:48] or "Устройство"
        platform = platform if platform in PLATFORMS else "other"
        server = await _get_server(session, server_id)

        creds = await _provision(session, server)
        device = Device(user_id=user.id, name=name, platform=platform, sub_token=secrets.token_urlsafe(24))
        _apply(device, server, creds)
        session.add(device)
        kept_server_id = server.id
        try:
            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            fresh = await session.get(Server, kept_server_id)
            if fresh is not None:
                await _drop_peer_and_heal(session, fresh, creds)
            raise DeviceError("Конфликт адресов, повторите попытку", 409) from e
        user.devices.append(device)
        log.info("device %s created for user %s on %s", device.id, user.id, server.code)
        return device


async def revoke_device(session: AsyncSession, device: Device) -> None:
    async with _mutation_lock:
        await _seen_snapshot(session)
        await session.refresh(device, attribute_names=["status"])
        if device.status != "active":
            return
        device.status = "revoked"
        device.revoked_at = datetime.now(UTC)
        device.session_started_at = None
        server, public_key = device.server, device.public_key
        await session.commit()
        await remove_peer_quietly(server, public_key)
        log.info("device %s revoked", device.id)


async def regenerate_device(session: AsyncSession, device: Device, server_id: int | None = None) -> Device:
    """Same server (or no server given): rotate credentials, the old config stops working.
    Another server: move the device. VLESS keeps its uuid and subscription URL, so apps like Happ
    pick up the new server on the next subscription refresh without re-import."""
    async with _mutation_lock:
        await _seen_snapshot(session)
        await session.refresh(
            device,
            attribute_names=["status", "public_key", "server_id", "protocol", "address", "private_key_enc", "psk_enc"],
        )
        if device.status != "active":
            raise DeviceError("Конфигурация отозвана", 409)
        owner = await session.get(User, device.user_id)
        if owner is None:
            raise DeviceError("Пользователь не найден", 404)
        await session.refresh(owner, attribute_names=_ACCESS_FIELDS)
        _check_access(owner)

        old_key = device.public_key
        old_server = await session.get(Server, device.server_id)
        if old_server is None:
            raise DeviceError("Сервер недоступен", 404)
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
        kept_server_id = server.id
        try:
            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            fresh = await session.get(Server, kept_server_id)
            if fresh is not None:
                await _drop_peer_and_heal(session, fresh, creds)
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
