# NOVA VPN

**Быстрый. Приватный. Простой.** MVP VPN-сервиса: Telegram-бот, Telegram Mini App, backend, база, WireGuard-ноды, персональные конфигурации, устройства и админ-панель.

```
Telegram-бот → Mini App → backend выдаёт личную WireGuard-конфигурацию → QR / файл → клиент WireGuard → ваш VPN-сервер
```

Архитектура, ограничения и решения описаны в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Часть | Технология | Папка |
|---|---|---|
| API + раздача Mini App | Python, FastAPI, SQLAlchemy | `backend/app` |
| Бот | aiogram 3 (long polling) | `backend/bot` |
| База | SQLite (MVP) / PostgreSQL | — |
| Mini App + админка | React + Vite + TypeScript | `frontend` |
| VPN-нода | WireGuard + `nova-agent` | `vpn-agent` |

> **Важно о бесплатности.** Код, разработка и тесты полностью бесплатны. Для **настоящего** VPN нужна Linux-машина с публичным IPv4 и открытым UDP-портом. Бесплатные тарифы облаков существуют, но их условия меняются, часто нужна карта: проверяйте актуальные условия сами. До этого момента всё работает в **demo-режиме** с имитацией серверов.

> **О блокировках.** В некоторых странах (в т.ч. в РФ) WireGuard детектируется и блокируется DPI. Архитектура рассчитана на добавление протоколов (см. «Дальнейшее развитие»).

---

## 1. Что установить

- **Python 3.12+**, **Node.js 20+**, **Git**
- Для деплоя: **Docker** с Compose plugin
- Для HTTPS при локальном тесте в Telegram: [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) (бесплатно, аккаунт не нужен)

```bash
git clone <repo> nova-vpn && cd nova-vpn

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cd ../frontend && npm install
```

## 2. Создать Telegram-бота

1. Напишите [@BotFather](https://t.me/BotFather) → `/newbot` → имя и username.
2. Скопируйте токен в `BOT_TOKEN`.
3. Узнайте свой Telegram ID (например, у [@userinfobot](https://t.me/userinfobot)) и впишите в `ADMIN_TELEGRAM_IDS`: так в боте появится команда `/admin`.

```bash
cp .env.example .env
cd backend && python -m app.cli gen-secrets   # вставьте SECRET_KEY, ENCRYPTION_KEY, ADMIN_PASSWORD в .env
```

⚠️ `ENCRYPTION_KEY` шифрует приватные ключи клиентов. Если его потерять, все конфигурации придётся перевыпускать. Сделайте резервную копию.

## 3. Настроить Mini App

Telegram открывает Mini App **только по HTTPS**.

- **Локально:** бесплатный туннель Cloudflare (шаг 5) даёт адрес `https://xxxx.trycloudflare.com`.
- **В продакшене:** ваш домен, например `https://vpn.example.com`. Сертификат выпустит Caddy.

Впишите адрес в `WEBAPP_URL`. При старте бот сам ставит кнопку меню «NOVA VPN» и кнопки WebApp. Дополнительно можно зарегистрировать приложение в BotFather: `/newapp` (для прямых ссылок `t.me/<bot>/<app>`).

## 4. Запустить backend

```bash
cd backend && source .venv/bin/activate
python -m app.cli seed-demo --with-users   # 5 демо-серверов (mock) и 8 демо-пользователей
DEV_MODE=true uvicorn app.main:app --reload --port 8000
```

- `DEV_MODE=true` разрешает вход без Telegram (заголовок `X-Dev-User`), включает Swagger на `/api/docs` и позволяет не задавать секреты. **В продакшене он всегда выключен.**
- Таблицы создаются автоматически при первом запуске.
- Тесты: `pytest -q`

Бот запускается отдельным процессом (нужен реальный `BOT_TOKEN`):

```bash
python -m bot.main
```

## 5. Запустить frontend

```bash
cd frontend
npm run dev          # http://localhost:5173 — Mini App в браузере (demo)
                     # http://localhost:5173/admin — админка (пароль ADMIN_PASSWORD)
```

Vite проксирует `/api` на `localhost:8000`. Чтобы открыть приложение **внутри Telegram**:

```bash
cloudflared tunnel --url http://localhost:5173
# → https://random-words.trycloudflare.com: впишите в WEBAPP_URL и перезапустите бота
```

Внутри Telegram backend проверяет подпись `initData`, поэтому `BOT_TOKEN` в `.env` должен быть настоящим.

Продакшен-сборка: `npm run build` → `frontend/dist`. FastAPI раздаёт её сам: один домен, без CORS.

## 6. База данных

- По умолчанию SQLite: `DATABASE_URL=sqlite+aiosqlite:///./nova.db`. Для MVP на сотни пользователей этого хватает.
- PostgreSQL: `pip install` уже включает `asyncpg`, достаточно поменять строку:
  `DATABASE_URL=postgresql+asyncpg://nova:password@127.0.0.1:5432/nova`
- Бэкап SQLite: скопируйте файл `nova.db` (в Docker он лежит в volume `nova_data`) вместе с `.env`.

## 7. Подключить WireGuard (VPN-нода)

Нужен VPS или домашний сервер: Ubuntu 22.04/24.04 или Debian 12, **публичный IPv4**, открытый **UDP 51820**. Домашний интернет за CGNAT не подойдёт: нужен «белый» IP и проброс порта на роутере.

```bash
scp -r vpn-agent root@SERVER:/root/
ssh root@SERVER 'cd /root/vpn-agent && bash install.sh'
```

Скрипт:
- ставит WireGuard, включает IP forwarding и NAT;
- создаёт `wg0` (10.8.0.1/24). Приватный ключ сервера **не покидает сервер**;
- ставит `nova-agent` (systemd, по умолчанию слушает `127.0.0.1:8787`);
- печатает токен агента и готовую команду регистрации.

Альтернатива: Docker-образ ноды `vpn-agent/Dockerfile` (`--network host --cap-add NET_ADMIN`).

## 8. Создать первый VPN-сервер

**Вариант А: backend на той же машине (рекомендуется для старта).** Команду печатает `install.sh`:

```bash
python -m app.cli add-server --code de-fra-1 --name Germany --country DE --city Frankfurt \
  --host <PUBLIC_IP> --agent-url http://127.0.0.1:8787 --agent-token <TOKEN>
```

Или через админку: **Серверы → Добавить сервер**. Backend сам запросит у агента публичный ключ, порт и подсеть.

**Вариант Б: нода на отдельной машине.** Токен агента нельзя передавать по открытому HTTP, поэтому backend принимает для удалённых нод только `https://`. Поставьте агент с `AGENT_BIND=127.0.0.1`, а перед ним Caddy с доменом (подойдёт бесплатный поддомен, например DuckDNS):

```
node1.example.com {
	reverse_proxy 127.0.0.1:8787
}
```

Для каждой ноды задавайте свою подсеть: `WG_SUBNET=10.8.1.0/24 bash install.sh`.

Mock-серверы из `seed-demo` можно скрыть в админке (переключатель «Активен»).

## 9. Протестировать подключение

1. Откройте бота → **🚀 Открыть NOVA VPN** → **ПОДКЛЮЧИТЬ VPN**.
2. Установите WireGuard ([iOS](https://apps.apple.com/app/wireguard/id1441195209), [Android](https://play.google.com/store/apps/details?id=com.wireguard.android), [Windows/macOS](https://www.wireguard.com/install/)).
3. Импортируйте конфигурацию файлом или QR (QR удобно сканировать с экрана компьютера).
4. Включите туннель и откройте https://ifconfig.me: должен показаться IP сервера.
5. В течение минуты Mini App покажет «VPN подключён», а админка — активное подключение и трафик.

Автоматический end-to-end тест (Docker, настоящий WireGuard в ядре): нода + backend + клиент, handshake, пинг через туннель и проверка, что после отзыва туннель закрывается:

```bash
scripts/e2e_wireguard.sh
```

Диагностика на ноде: `wg show`, `journalctl -u nova-agent -f`, `systemctl status wg-quick@wg0`.

## 10. Развернуть проект

Всё на одном сервере (WireGuard + agent + API + бот + HTTPS):

```bash
# 1) нода: шаг 7
# 2) DNS: A-запись DOMAIN → IP сервера; открыть TCP 80/443 и UDP 51820
cp .env.example .env    # заполнить; DOMAIN=vpn.example.com, WEBAPP_URL=https://vpn.example.com
docker compose up -d --build
docker compose exec api python -m app.cli add-server ...   # шаг 8, вариант А
```

`docker compose` поднимает `api` (FastAPI + собранный Mini App), `bot` и `caddy` (бесплатный сертификат Let's Encrypt). Все контейнеры работают в host-сети, поэтому API видит агента на `127.0.0.1:8787`.

Бесплатные варианты по компонентам:

| Компонент | Local development | Free deployment |
|---|---|---|
| Бот | polling с ноутбука | тот же сервер (Docker) |
| API + база | uvicorn + SQLite | тот же сервер (Docker) |
| Mini App | Vite + Cloudflare Quick Tunnel | раздаёт FastAPI; альтернатива — Cloudflare Pages / GitHub Pages с `VITE_API_URL` и `CORS_ORIGINS` |
| HTTPS | Quick Tunnel | Caddy + свой домен или бесплатный поддомен |
| VPN | mock-драйвер | машина с публичным IP: free tier облака (проверьте условия), домашний сервер / Raspberry Pi с «белым» IP |

---

## Безопасность

- Mini App авторизуется через `initData`: backend проверяет HMAC-подпись Telegram и срок давности.
- Приватные ключи и PSK клиентов зашифрованы Fernet (`ENCRYPTION_KEY`), никогда не логируются и не попадают в списки API. Конфигурация отдаётся только своему владельцу, с `Cache-Control: no-store`.
- Бот **не пересылает** конфигурации: ключи не попадают в переписку Telegram.
- Ссылки на скачивание подписаны, живут 5 минут и перестают работать после перевыпуска ключей.
- Админка: пароль (сравнение за постоянное время, 5 попыток в минуту) или одноразовая ссылка `/admin` из бота (10 минут, только для `ADMIN_TELEGRAM_IDS`). Сессия подписана и живёт 12 часов, хранится в `sessionStorage`.
- Rate limiting на все `/api/*`, отдельно жёстче на логин и создание устройств.
- Агент: токен Bearer, ключи и адреса валидируются, `wg` вызывается без shell, IP клиентов (endpoint) наружу не отдаются. Для удалённых нод backend требует HTTPS.
- Reconcile: раз в `POLL_INTERVAL` набор peers на ноде приводится к базе. Бан, истечение срока, исчерпание трафика и отзыв отключают доступ автоматически, даже после перезагрузки ноды.
- `DEV_MODE` включает обходы для разработки: в продакшене держите `false`. Без `BOT_TOKEN`, `SECRET_KEY` и `ENCRYPTION_KEY` backend не стартует.

## Что честно умеет и не умеет MVP

- Кнопка «Подключить VPN» **не включает VPN сама**: Mini App физически не может управлять сетью телефона. Она выдаёт конфигурацию и ведёт через импорт, а статус «подключён» backend берёт из WireGuard handshake.
- **Ping** — это задержка backend → нода. Реальный ping с устройства показывает клиент WireGuard.
- **Скорость** — фактическая средняя скорость передачи за последний интервал опроса, а не speedtest.
- Rate limiter хранит состояние в памяти: для нескольких реплик API нужен Redis.
- Миграций схемы нет (таблицы создаются автоматически). При изменении моделей добавьте Alembic.
- Оплаты нет: срок и лимиты задаются в админке (+30 дней, лимиты устройств и трафика).

## Дальнейшее развитие

- **Обход DPI:** AmneziaWG (форк WireGuard с обфускацией; новая запись в `app/vpn/protocols.py` + агент с `awg`) или VLESS/Reality через Xray (новый драйвер ноды).
- Оплата (например, Telegram Stars), реферальная программа, уведомления о лимите трафика.
- Alembic-миграции, PostgreSQL, Redis для rate limit и нескольких реплик API.

## Структура

```
backend/app/        config, db, models, views, tasks (poller + reconcile), cli
backend/app/api/    user.py (Mini App), admin.py, deps.py (auth)
backend/app/security/  telegram initData, шифрование и токены, rate limit
backend/app/services/  users, devices, servers, stats: общие для API и бота
backend/app/vpn/    wireguard (ключи, IP, конфиг), protocols (реестр), drivers (agent/mock)
backend/bot/        aiogram-бот: тексты, клавиатуры, хендлеры, напоминания
backend/tests/      pytest: initData, крипто, жизненный цикл устройств, админка, бот
frontend/src/       lib (telegram, api, store), components, screens, admin
vpn-agent/          agent.py, install.sh, systemd unit, Dockerfile
scripts/            e2e_wireguard.sh
```
