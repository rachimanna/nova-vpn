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


def latest_bucket(rows: list[tuple], gap: timedelta) -> tuple[int, int]:
    """Sum of the newest poll only. Samples from one pass land close together; the previous pass does not."""
    if not rows:
        return 0, 0
    latest = max(row[0] for row in rows)
    download = upload = 0
    for ts, down, up in rows:
        if latest - ts <= gap:
            download += int(down)
            upload += int(up)
    return download, upload


async def last_rate(session: AsyncSession, user_id: int, window_s: int) -> dict:
    """Average speed over the last poll, bytes/s."""
    since = datetime.now(UTC) - timedelta(seconds=window_s * 1.5)
    rows = (
        await session.execute(
            select(TrafficSample.ts, TrafficSample.download, TrafficSample.upload).where(
                TrafficSample.user_id == user_id, TrafficSample.ts >= since
            )
        )
    ).all()
    # Wide enough to include a slow node from the same pass, narrow enough to exclude the previous one.
    gap = timedelta(seconds=min(max(window_s * 0.5, 1), 30))
    down, up = latest_bucket(rows, gap)
    span = max(window_s, 1)
    return {"download": int(down / span), "upload": int(up / span)}


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
