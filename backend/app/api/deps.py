import logging

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import User
from app.security.crypto import TokenError, verify_token
from app.security.telegram import InitDataError, TelegramUser, validate_init_data
from app.services.users import get_or_create_user

log = logging.getLogger(__name__)


async def current_user(
    authorization: str = Header(default=""),
    x_dev_user: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    settings = get_settings()
    if authorization.startswith("tma "):
        try:
            tg = validate_init_data(authorization[4:], settings.bot_token, settings.initdata_max_age)
        except InitDataError as e:
            log.info("rejected initData: %s", e)
            raise HTTPException(401, "Откройте приложение через Telegram") from e
    elif settings.dev_mode and x_dev_user:
        # Browser testing outside Telegram. Disabled unless DEV_MODE=true.
        tg = TelegramUser(id=int(x_dev_user) if x_dev_user.isdigit() else 1, first_name="Dev", username="dev_user")
    else:
        raise HTTPException(401, "Откройте приложение через Telegram")
    return await get_or_create_user(session, tg)


async def require_admin(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Требуется вход администратора")
    try:
        return verify_token(authorization[7:], "admin")
    except TokenError as e:
        raise HTTPException(401, "Сессия администратора истекла") from e
