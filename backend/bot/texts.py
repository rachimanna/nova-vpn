from datetime import UTC, datetime
from html import escape

from app.models import User
from app.services.devices import active_devices, is_online

PLATFORM_ICONS = {"ios": "📱", "android": "🤖", "windows": "🪟", "macos": "💻", "linux": "🐧", "other": "🔌"}


def fmt_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def progress(part: float, total: float, width: int = 10) -> str:
    ratio = 0 if not total else min(1.0, part / total)
    filled = round(ratio * width)
    return "▰" * filled + "▱" * (width - filled) + f" {ratio:.0%}"


def fmt_date(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%d.%m.%Y")


WELCOME = (
    "<b>NOVA VPN</b>\n"
    "<i>Быстрый. Приватный. Простой.</i>\n\n"
    "🛡 Современный протокол WireGuard\n"
    "⚡️ Серверы в Европе с низким пингом\n"
    "📱 До нескольких устройств на один аккаунт\n\n"
    "Нажмите <b>«Открыть NOVA VPN»</b>, чтобы получить персональную конфигурацию."
)


def subscription_line(user: User) -> str:
    now = datetime.now(UTC)
    if user.is_banned:
        return "🔴 Заблокирован"
    if user.expires_at <= now:
        return "🔴 Истёк"
    if user.traffic_limit and user.traffic_used >= user.traffic_limit:
        return "🟠 Лимит трафика исчерпан"
    return f"🟢 Активен · ещё {(user.expires_at - now).days} дн."


def vpn_line(user: User) -> str:
    devices = active_devices(user)
    if any(is_online(d) for d in devices):
        return "🟢 Подключён"
    if devices:
        return "🟡 Готов к подключению"
    return "⚪ Не настроен"


def profile(user: User) -> str:
    name = escape(user.first_name or "Пользователь")
    username = f"@{escape(user.username)}" if user.username else "—"
    limit = fmt_bytes(user.traffic_limit) if user.traffic_limit else "∞"
    bar = progress(user.traffic_used, user.traffic_limit) if user.traffic_limit else "▱▱▱▱▱▱▱▱▱▱ безлимит"
    return (
        "👤 <b>Профиль</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>{name}</b>  ·  {username}\n"
        f"ID: <code>{user.tg_id}</code>\n\n"
        f"<b>Статус:</b> {subscription_line(user)}\n"
        f"<b>VPN:</b> {vpn_line(user)}\n"
        f"<b>Устройства:</b> {len(active_devices(user))}/{user.device_limit}\n\n"
        f"<b>Трафик:</b> {fmt_bytes(user.traffic_used)} / {limit}\n"
        f"<code>{bar}</code>\n\n"
        f"📅 Аккаунт создан: {fmt_date(user.created_at)}\n"
        f"⏳ Доступ до: {fmt_date(user.expires_at)}"
    )


def my_vpn(user: User) -> str:
    devices = active_devices(user)
    head = f"🔐 <b>Мой VPN</b>\n━━━━━━━━━━━━━━━━━━\nVPN: {vpn_line(user)}\n"
    if not devices:
        return head + "\nУ вас пока нет конфигураций.\nОткройте приложение и нажмите <b>«Подключить VPN»</b> — это займёт 10 секунд."
    lines = []
    for d in devices:
        state = "🟢 онлайн" if is_online(d) else "⚪ офлайн"
        lines.append(
            f"{PLATFORM_ICONS.get(d.platform, '🔌')} <b>{escape(d.name)}</b> — {state}\n"
            f"    {d.server.name} · ↓ {fmt_bytes(d.download_bytes)} ↑ {fmt_bytes(d.upload_bytes)}"
        )
    return (
        head
        + f"Устройства: {len(devices)}/{user.device_limit}\n\n"
        + "\n\n".join(lines)
        + "\n\n<i>Файлы конфигураций выдаются только в приложении — так приватные ключи не попадают в переписку.</i>"
    )


CONNECT = (
    "📱 <b>Как подключиться</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "<b>1.</b> Установите приложение <b>WireGuard</b> (кнопки ниже)\n"
    "<b>2.</b> Откройте NOVA VPN и нажмите <b>«Подключить VPN»</b>\n"
    "<b>3.</b> Импортируйте конфигурацию: файлом или QR-кодом\n"
    "<b>4.</b> Включите туннель в WireGuard — готово 🎉\n\n"
    "Подробные инструкции для iPhone, Android, Windows и macOS — в приложении, раздел «Подключение»."
)

HELP = (
    "ℹ️ <b>Помощь</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "<b>VPN не подключается?</b>\n"
    "• Проверьте, что туннель включён в WireGuard\n"
    "• Попробуйте другой сервер в разделе «Серверы»\n"
    "• Перевыпустите конфигурацию в профиле и импортируйте заново\n\n"
    "<b>Сменил телефон</b>\n"
    "Удалите старое устройство в профиле и создайте новое.\n\n"
    "<b>Безопасность</b>\n"
    "Каждое устройство получает собственные ключи. Удалённая конфигурация перестаёт работать сразу.\n\n"
    "Команды: /start · /profile · /vpn · /help"
)


def settings_text(user: User) -> str:
    notif = "🔔 включены" if user.notifications else "🔕 выключены"
    return (
        "⚙️ <b>Настройки</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Уведомления об окончании доступа: {notif}\n\n"
        "Управление устройствами и конфигурациями — в приложении."
    )


def expiry_reminder(user: User) -> str:
    days = max(0, (user.expires_at - datetime.now(UTC)).days)
    when = "сегодня" if days == 0 else f"через {days} дн."
    return f"⏳ <b>NOVA VPN</b>\nДоступ заканчивается {when} ({fmt_date(user.expires_at)})."
