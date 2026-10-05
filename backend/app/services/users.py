from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import User
from app.security.telegram import TelegramUser

GB = 1024**3


class Access(StrEnum):
    ACTIVE = "active"
    BANNED = "banned"
    EXPIRED = "expired"
    TRAFFIC = "traffic_exceeded"


async def get_or_create_user(session: AsyncSession, tg: TelegramUser) -> User:
    user = await session.scalar(
        select(User).where(User.tg_id == tg.id).options(selectinload(User.devices))
    )
    now = datetime.now(UTC)
    if user is None:
        s = get_settings()
        user = User(
            tg_id=tg.id,
            device_limit=s.default_device_limit,
            traffic_limit=int(s.default_traffic_limit_gb * GB),
            expires_at=now + timedelta(days=s.default_access_days),
            created_at=now,
            devices=[],
        )
        session.add(user)
    # Telegram is the source of truth for profile fields
    # the bot never knows photo_url, so do not wipe the one the Mini App sent
    fresh = (tg.username, tg.first_name, tg.language_code, tg.photo_url or user.photo_url)
    changed = (user.username, user.first_name, user.language, user.photo_url) != fresh
    if changed or user.id is None or now - user.last_seen_at > timedelta(minutes=5):
        user.username, user.first_name, user.language, user.photo_url = fresh
        user.last_seen_at = now
        await session.commit()
    return user


async def get_user_by_tg(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(
        select(User).where(User.tg_id == tg_id).options(selectinload(User.devices))
    )


def access_state(user: User, now: datetime | None = None) -> Access:
    now = now or datetime.now(UTC)
    if user.is_banned:
        return Access.BANNED
    if user.expires_at <= now:
        return Access.EXPIRED
    if user.traffic_limit and user.traffic_used >= user.traffic_limit:
        return Access.TRAFFIC
    return Access.ACTIVE


ACCESS_ERRORS = {
    Access.BANNED: "Аккаунт заблокирован",
    Access.EXPIRED: "Срок доступа истёк",
    Access.TRAFFIC: "Лимит трафика исчерпан",
}
