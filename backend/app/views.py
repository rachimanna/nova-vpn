"""Serialisation shared by the user API, the admin API and the bot. Never includes key material."""

from datetime import UTC, datetime

from app.models import Device, Server, User
from app.services.devices import active_devices, is_online
from app.services.servers import flag
from app.services.users import access_state


def short_server(server: Server) -> dict:
    return {"id": server.id, "code": server.code, "name": server.name, "city": server.city, "flag": flag(server.country)}


def device_view(d: Device, now: datetime | None = None) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "platform": d.platform,
        "protocol": d.protocol,
        "status": d.status,
        "online": is_online(d, now),
        "address": d.address,
        "server": short_server(d.server),
        "created_at": d.created_at,
        "last_handshake_at": d.last_handshake_at,
        "session_started_at": d.session_started_at,
        "download": d.download_bytes,
        "upload": d.upload_bytes,
    }


def user_view(u: User, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    return {
        "id": u.id,
        "tg_id": u.tg_id,
        "username": u.username,
        "first_name": u.first_name,
        "photo_url": u.photo_url,
        "status": access_state(u, now).value,
        "is_banned": u.is_banned,
        "created_at": u.created_at,
        "expires_at": u.expires_at,
        "days_left": max(0, (u.expires_at - now).days),
        "device_limit": u.device_limit,
        "devices_active": len(active_devices(u)),
        "traffic_used": u.traffic_used,
        "traffic_limit": u.traffic_limit,
        "notifications": u.notifications,
        "last_seen_at": u.last_seen_at,
    }


def vpn_view(u: User, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    devices = active_devices(u)
    online = [d for d in devices if is_online(d, now)]
    primary = online[0] if online else (devices[-1] if devices else None)
    sessions = [d.session_started_at for d in online if d.session_started_at]
    return {
        "state": "connected" if online else "ready" if devices else "none",
        "online_devices": len(online),
        "server": short_server(primary.server) | {"ping_ms": primary.server.ping_ms} if primary else None,
        "session_started_at": min(sessions) if sessions else None,
        "download": sum(d.download_bytes for d in u.devices),
        "upload": sum(d.upload_bytes for d in u.devices),
    }
