"""Background poller: collects peer stats and reconciles node state with the database."""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.models import Device, Server, TrafficSample
from app.security.crypto import decrypt
from app.services.users import Access, access_state
from app.vpn.drivers import NodeError, get_driver

log = logging.getLogger(__name__)

SAMPLE_RETENTION = timedelta(days=30)


def _delta(new: int, old: int) -> int:
    # WireGuard counters reset when a peer is re-added or the node reboots
    return new - old if new >= old else new


async def poll_server(session: AsyncSession, server: Server) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    driver = get_driver(server)
    try:
        ping = await driver.ping()
        peers = {p.public_key: p for p in await driver.peers()}
    except NodeError as e:
        if server.online:
            log.warning("server %s went offline: %s", server.code, e)
        server.online = False
        server.ping_ms = None
        server.peers_online = 0
        await session.commit()
        return

    devices = (
        await session.scalars(
            select(Device)
            .where(Device.server_id == server.id, Device.status == "active")
            .options(selectinload(Device.user))
        )
    ).all()

    threshold = timedelta(seconds=settings.online_threshold_seconds)
    online = 0
    desired: dict[str, Device] = {}
    for device in devices:
        if access_state(device.user, now) is Access.ACTIVE:
            desired[device.public_key] = device
        stat = peers.get(device.public_key)
        if stat is None:
            continue
        down, up = _delta(stat.tx, device.raw_tx), _delta(stat.rx, device.raw_rx)
        device.raw_tx, device.raw_rx = stat.tx, stat.rx
        if down or up:
            device.download_bytes += down
            device.upload_bytes += up
            device.user.traffic_used += down + up
            session.add(TrafficSample(user_id=device.user_id, device_id=device.id, ts=now, download=down, upload=up))

        device.last_handshake_at = stat.last_handshake or device.last_handshake_at
        is_on = stat.last_handshake is not None and now - stat.last_handshake < threshold
        if is_on:
            online += 1
            device.session_started_at = device.session_started_at or stat.last_handshake
        else:
            device.session_started_at = None

    # Reconcile: the database is the source of truth for which peers may exist
    for key, device in desired.items():
        if key not in peers:
            try:
                await driver.add_peer(key, decrypt(device.psk_enc), device.address)
                device.raw_rx = device.raw_tx = 0
            except NodeError as e:
                log.warning("reconcile add failed on %s: %s", server.code, e)
    for key in peers.keys() - desired.keys():
        try:
            await driver.remove_peer(key)
        except NodeError as e:
            log.warning("reconcile remove failed on %s: %s", server.code, e)
        known = next((d for d in devices if d.public_key == key), None)
        if known:
            known.session_started_at = None

    server.online = True
    server.ping_ms = round(ping)
    server.peers_online = online
    server.last_seen_at = now
    await session.commit()


async def _poll_server_id(server_id: int) -> None:
    async with SessionLocal() as session:
        server = await session.get(Server, server_id)
        if server is None or not server.is_active:
            return
        try:
            await poll_server(session, server)
        except Exception:
            log.exception("poll failed for server %s", server.code)
            await session.rollback()


async def poll_once() -> None:
    # One dead node used to delay the ping of every server after it.
    async with SessionLocal() as session:
        ids = list((await session.scalars(select(Server.id).where(Server.is_active.is_(True)))).all())
    if ids:
        await asyncio.gather(*(_poll_server_id(server_id) for server_id in ids))


async def prune_samples() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(TrafficSample).where(TrafficSample.ts < datetime.now(UTC) - SAMPLE_RETENTION))
        await session.commit()


async def poller_loop() -> None:
    interval = get_settings().poll_interval
    last_prune = 0.0
    while True:
        started = time.monotonic()
        try:
            await poll_once()
            if started - last_prune > 3600:
                await prune_samples()
                last_prune = started
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("poller iteration failed")
        await asyncio.sleep(max(1.0, interval - (time.monotonic() - started)))
