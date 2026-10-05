from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device, Server, TrafficSample, User


async def traffic_series(session: AsyncSession, user_id: int | None, hours: int, buckets: int = 24) -> list[dict]:
    """Download/upload per time bucket. user_id=None aggregates the whole service (admin)."""
    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)
    step = timedelta(hours=hours) / buckets
    q = select(TrafficSample.ts, TrafficSample.download, TrafficSample.upload).where(TrafficSample.ts >= start)
    if user_id is not None:
        q = q.where(TrafficSample.user_id == user_id)
    series = [
        {"ts": (start + step * i).isoformat(), "download": 0, "upload": 0} for i in range(buckets)
    ]
    for ts, down, up in await session.execute(q):
        i = min(int((ts - start) / step), buckets - 1)
        series[i]["download"] += down
        series[i]["upload"] += up
    return series


async def last_rate(session: AsyncSession, user_id: int, window_s: int) -> dict:
    """Average speed over the last poll window, bytes/s."""
    since = datetime.now(UTC) - timedelta(seconds=window_s * 1.5)
    row = (
        await session.execute(
            select(func.coalesce(func.sum(TrafficSample.download), 0), func.coalesce(func.sum(TrafficSample.upload), 0))
            .where(TrafficSample.user_id == user_id, TrafficSample.ts >= since)
        )
    ).one()
    return {"download": int(row[0] / window_s), "upload": int(row[1] / window_s)}


async def overview(session: AsyncSession, online_threshold: int) -> dict:
    now = datetime.now(UTC)
    online_since = now - timedelta(seconds=online_threshold)
    total_users = await session.scalar(select(func.count(User.id)))
    active_users = await session.scalar(
        select(func.count(User.id)).where(User.is_banned.is_(False), User.expires_at > now)
    )
    banned = await session.scalar(select(func.count(User.id)).where(User.is_banned.is_(True)))
    active_configs = await session.scalar(select(func.count(Device.id)).where(Device.status == "active"))
    connections = await session.scalar(
        select(func.count(Device.id)).where(Device.status == "active", Device.last_handshake_at >= online_since)
    )
    total_traffic = await session.scalar(select(func.coalesce(func.sum(User.traffic_used), 0)))
    new_24h = await session.scalar(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=1)))
    servers = (await session.scalars(select(Server).order_by(Server.id))).all()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "banned_users": banned,
        "new_users_24h": new_24h,
        "active_configs": active_configs,
        "active_connections": connections,
        "total_traffic": int(total_traffic),
        "servers_total": len(servers),
        "servers_online": sum(1 for s in servers if s.online and s.is_active),
    }
