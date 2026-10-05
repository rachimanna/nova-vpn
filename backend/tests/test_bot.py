from datetime import UTC, datetime, timedelta

from aiogram import Dispatcher

from app.models import User
from bot import keyboards as kb
from bot import texts
from bot.main import router


def _user(**kw) -> User:
    now = datetime.now(UTC)
    base = dict(tg_id=1, username="ann", first_name="Ann <b>", device_limit=3, traffic_limit=50 * 1024**3,
                traffic_used=int(2.4 * 1024**3), is_banned=False, notifications=True,
                created_at=now, expires_at=now + timedelta(days=30), devices=[])
    return User(**(base | kw))


def test_profile_text_escapes_and_formats():
    t = texts.profile(_user())
    assert "Ann &lt;b&gt;" in t and "@ann" in t
    assert "2.4 GB / 50.0 GB" in t and "1/3" not in t and "0/3" in t
    assert "🟢 Активен" in t and "⚪ Не настроен" in t
    assert "🔴 Заблокирован" in texts.profile(_user(is_banned=True))


def test_my_vpn_empty():
    assert "нет конфигураций" in texts.my_vpn(_user())


def test_keyboards(monkeypatch):
    menu = kb.main_menu()
    assert "WEBAPP_URL" in menu.inline_keyboard[0][0].text  # no https url configured in tests
    monkeypatch.setattr(kb.get_settings(), "webapp_url", "https://nova.example.com")
    menu = kb.main_menu()
    assert menu.inline_keyboard[0][0].web_app.url == "https://nova.example.com/"
    labels = [b.text for row in menu.inline_keyboard for b in row]
    assert labels[1:] == ["🔐 Мой VPN", "👤 Профиль", "📱 Подключить", "ℹ️ Помощь", "⚙️ Настройки"]
    assert kb.connect().inline_keyboard[-2][0].web_app.url.endswith("/?screen=connect")


def test_router_registers():
    dp = Dispatcher()
    dp.include_router(router)
    assert {"message", "callback_query"} <= set(dp.resolve_used_update_types())
