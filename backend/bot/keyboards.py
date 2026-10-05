from urllib.parse import urlencode

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import get_settings

CLIENTS = {
    "📱 iPhone": "https://apps.apple.com/app/wireguard/id1441195209",
    "🤖 Android": "https://play.google.com/store/apps/details?id=com.wireguard.android",
    "💻 Windows / macOS": "https://www.wireguard.com/install/",
}


def webapp_url(screen: str | None = None) -> str | None:
    """Telegram requires HTTPS for Mini Apps. Screens go in the query: the hash carries launch params."""
    base = get_settings().webapp_url.rstrip("/")
    if not base.startswith("https://"):
        return None
    return f"{base}/?{urlencode({'screen': screen})}" if screen else f"{base}/"


def open_app(text: str = "🚀 Открыть NOVA VPN", screen: str | None = None) -> list[InlineKeyboardButton]:
    url = webapp_url(screen)
    if url is None:
        return [InlineKeyboardButton(text="⚠️ WEBAPP_URL не настроен (нужен https)", callback_data="noop")]
    return [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


BACK = [_btn("← Назад", "menu")]


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            open_app(),
            [_btn("🔐 Мой VPN", "vpn"), _btn("👤 Профиль", "profile")],
            [_btn("📱 Подключить", "connect"), _btn("ℹ️ Помощь", "help")],
            [_btn("⚙️ Настройки", "settings")],
        ]
    )


def profile() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[open_app("📊 Статистика и устройства", "profile"), [_btn("🔄 Обновить", "profile")], BACK]
    )


def my_vpn(has_devices: bool) -> InlineKeyboardMarkup:
    action = open_app("⚙️ Управлять устройствами", "profile") if has_devices else open_app("⚡️ Подключить VPN", "connect")
    return InlineKeyboardMarkup(inline_keyboard=[action, [_btn("🔄 Обновить", "vpn")], BACK])


def connect() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *[[InlineKeyboardButton(text=t, url=u)] for t, u in CLIENTS.items()],
            open_app("⚡️ Получить конфигурацию", "connect"),
            BACK,
        ]
    )


def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[open_app("📖 Инструкции", "connect"), BACK])


def settings(notifications: bool, is_admin: bool) -> InlineKeyboardMarkup:
    rows = [[_btn("🔕 Выключить уведомления" if notifications else "🔔 Включить уведомления", "toggle_notif")]]
    if is_admin:
        rows.append([_btn("🛠 Админ-панель", "admin")])
    rows.append(BACK)
    return InlineKeyboardMarkup(inline_keyboard=rows)
