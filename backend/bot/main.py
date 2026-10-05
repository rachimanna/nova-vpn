"""NOVA VPN Telegram bot (aiogram 3, long polling — no webhook or domain needed).

Run: python -m bot.main
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    User as TgUser,
    WebAppInfo,
)
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import User
from app.security.crypto import sign_token
from app.security.telegram import TelegramUser
from app.services.devices import active_devices
from app.services.users import get_or_create_user
from bot import keyboards as kb
from bot import texts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nova.bot")
router = Router()


async def load_user(tg: TgUser) -> User:
    async with SessionLocal() as session:
        return await get_or_create_user(
            session, TelegramUser(id=tg.id, first_name=tg.first_name, username=tg.username, language_code=tg.language_code)
        )


async def show(target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    """Edit the current screen in place for callbacks, send a new message otherwise."""
    if isinstance(target, CallbackQuery):
        with contextlib.suppress(TelegramBadRequest):  # "message is not modified"
            await target.message.edit_text(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


@router.message(CommandStart())
async def start(message: Message) -> None:
    await load_user(message.from_user)
    await message.answer(texts.WELCOME, reply_markup=kb.main_menu())


@router.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery) -> None:
    await show(cb, texts.WELCOME, kb.main_menu())


@router.message(Command("profile"))
@router.callback_query(F.data == "profile")
async def profile(event: Message | CallbackQuery) -> None:
    user = await load_user(event.from_user)
    await show(event, texts.profile(user), kb.profile())


@router.message(Command("vpn"))
@router.callback_query(F.data == "vpn")
async def my_vpn(event: Message | CallbackQuery) -> None:
    user = await load_user(event.from_user)
    await show(event, texts.my_vpn(user), kb.my_vpn(bool(active_devices(user))))


@router.message(Command("connect"))
@router.callback_query(F.data == "connect")
async def connect(event: Message | CallbackQuery) -> None:
    await show(event, texts.CONNECT, kb.connect())


@router.message(Command("help"))
@router.callback_query(F.data == "help")
async def help_(event: Message | CallbackQuery) -> None:
    await show(event, texts.HELP, kb.help_kb())


@router.callback_query(F.data == "settings")
async def settings(cb: CallbackQuery) -> None:
    user = await load_user(cb.from_user)
    await show(cb, texts.settings_text(user), kb.settings(user.notifications, cb.from_user.id in get_settings().admin_ids))


@router.callback_query(F.data == "toggle_notif")
async def toggle_notifications(cb: CallbackQuery) -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.tg_id == cb.from_user.id))
        user.notifications = not user.notifications
        await session.commit()
    await settings(cb)


async def send_admin_link(message: Message, tg_id: int) -> None:
    base = get_settings().webapp_url.rstrip("/")
    token = sign_token("admin_link", {"tg": tg_id}, ttl=600)
    await message.answer(
        "🛠 <b>Админ-панель</b>\nСсылка действует 10 минут. Никому её не пересылайте.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть админ-панель", url=f"{base}/admin?t={token}")]]
        ),
    )


@router.message(Command("admin"))
async def admin_cmd(message: Message) -> None:
    if message.from_user.id not in get_settings().admin_ids:
        return  # do not reveal that the command exists
    await send_admin_link(message, message.from_user.id)


@router.callback_query(F.data == "admin")
async def admin_cb(cb: CallbackQuery) -> None:
    if cb.from_user.id in get_settings().admin_ids:
        await send_admin_link(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer("Администратор ещё не настроил HTTPS-адрес приложения", show_alert=True)


async def expiry_reminders(bot: Bot) -> None:
    """Once per day per user, 3 days before access ends."""
    while True:
        try:
            now = datetime.now(UTC)
            async with SessionLocal() as session:
                users = (
                    await session.scalars(
                        select(User).where(
                            User.notifications.is_(True),
                            User.is_banned.is_(False),
                            User.expires_at > now,
                            User.expires_at < now + timedelta(days=3),
                        )
                    )
                ).all()
                for user in users:
                    if user.expiry_notified_at and now - user.expiry_notified_at < timedelta(days=1):
                        continue
                    with contextlib.suppress(TelegramForbiddenError, TelegramBadRequest):
                        await bot.send_message(user.tg_id, texts.expiry_reminder(user))
                    user.expiry_notified_at = now
                    await asyncio.sleep(0.05)  # stay well below Telegram flood limits
                await session.commit()
        except Exception:
            log.exception("expiry reminder iteration failed")
        await asyncio.sleep(3600)


async def setup(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="profile", description="Профиль"),
            BotCommand(command="vpn", description="Мой VPN"),
            BotCommand(command="connect", description="Как подключиться"),
            BotCommand(command="help", description="Помощь"),
        ]
    )
    if url := kb.webapp_url():
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="NOVA VPN", web_app=WebAppInfo(url=url)))
    else:
        log.warning("WEBAPP_URL is not an https:// URL, Mini App buttons are disabled")


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set. Create a bot with @BotFather and put the token into .env")
    await init_db()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await setup(bot)
    reminders = asyncio.create_task(expiry_reminders(bot))
    me = await bot.get_me()
    log.info("bot @%s started", me.username)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        reminders.cancel()


if __name__ == "__main__":
    asyncio.run(main())
