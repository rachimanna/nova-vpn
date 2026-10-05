
**Быстрый. Приватный. Простой.** MVP VPN-сервиса: Telegram-бот, Telegram Mini App, backend, база, собственные VPN-серверы (VLESS и WireGuard), персональные ключи, устройства и админ-панель.

```
Telegram-бот → Mini App → личная ссылка-подписка → Happ (v2RayTun, Hiddify…) → ваш сервер
                        → или WireGuard-конфиг (файл / QR) → WireGuard  → ваш сервер
```

| Протокол | Клиенты | Чем хорош |
|---|---|---|
| **VLESS over WebSocket + TLS** (Xray) — основной | Happ, v2RayTun, Hiddify, Streisand, v2rayNG | Подписка: пользователь добавляет ссылку один раз, смена сервера и трафик/срок обновляются в приложении сами. Трафик идёт по 443 как обычный HTTPS вашего домена |
| **WireGuard** | WireGuard | Максимальная скорость, но легко определяется DPI |

Архитектура, ограничения и решения описаны в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Часть | Технология | Папка |
|---|---|---|
| API + раздача Mini App | Python, FastAPI, SQLAlchemy | `backend/app` |
| Бот | aiogram 3 (long polling) | `backend/bot` |
| База | SQLite (MVP) / PostgreSQL | — |
| Mini App + админка | React + Vite + TypeScript | `frontend` |
| VPN-нода | Xray (VLESS) или WireGuard + `nova-agent` | `vpn-agent` |

> **Важно о бесплатности.** Код, разработка и тесты полностью бесплатны. Для **настоящего** VPN нужна Linux-машина с публичным IPv4 (для VLESS — открытые TCP 80/443 и домен, подойдёт бесплатный поддомен; для WireGuard — открытый UDP-порт). Бесплатные тарифы облаков существуют, но их условия меняются, часто нужна карта: проверяйте актуальные условия сами. До этого момента всё работает в **demo-режиме** с имитацией серверов.

> **О блокировках.** В некоторых странах (в т.ч. в РФ) WireGuard детектируется и блокируется DPI, поэтому основной протокол — VLESS через TLS на вашем домене. Гарантий от блокировок не даёт ни один протокол.

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

## 7. Поднять VPN-сервер (ноду)

Нужен VPS или домашний сервер: Ubuntu 22.04/24.04 или Debian 12, **публичный IPv4**.

### Вариант A — VLESS для Happ (рекомендуется)

1. Домен: A-запись `vpn.example.com` → IP сервера. Бесплатно — поддомен [DuckDNS](https://www.duckdns.org).
2. Открыть TCP **80** и **443**.
3. Установить:

```bash
scp -r vpn-agent root@SERVER:/root/
ssh root@SERVER 'cd /root/vpn-agent && DOMAIN=vpn.example.com bash install.sh vless'
```

Скрипт ставит **Xray** (официальный установщик XTLS), **Caddy** с бесплатным сертификатом Let's Encrypt и `nova-agent`. Снаружи открыт только 443: секретный путь WebSocket ведёт в Xray, всё остальное — Mini App (если `PANEL=1`, по умолчанию) или нейтральная страница (`PANEL=0` для дополнительных нод). Пользователи Xray добавляются и удаляются на лету через его API, без перезапуска.

### Вариант B — WireGuard

Нужен открытый **UDP 51820**:

```bash
ssh root@SERVER 'cd /root/vpn-agent && bash install.sh wireguard'
```

Приватный ключ сервера не покидает сервер. Альтернатива — Docker-образ `vpn-agent/Dockerfile` (`--network host --cap-add NET_ADMIN`). Для каждой WireGuard-ноды задавайте свою подсеть: `WG_SUBNET=10.8.1.0/24`.

## 8. Добавить сервер в NOVA

`install.sh` в конце печатает готовую команду:

```bash
python -m app.cli add-server --code nl-ams-1 --name Netherlands --country NL --city Amsterdam \
  --host vpn.example.com --agent-url http://127.0.0.1:8787 --agent-token <TOKEN>
```

Или через админку: **Серверы → Добавить сервер**. Протокол, порт, путь, ключи backend получает у агента сам.

- Нода на **том же** сервере, что и backend: `--agent-url http://127.0.0.1:8787`.
- **Отдельная** VLESS-нода (`PANEL=0`): `--agent-url https://node.example.com/nova-agent` — Caddy на ноде уже проксирует агента по HTTPS. Для удалённых нод backend принимает только `https://`, чтобы токен не шёл открытым текстом.

Mock-серверы из `seed-demo` скройте в админке (переключатель «Активен»).

## 9. Протестировать подключение

**VLESS / Happ:**
1. Установите Happ ([iOS](https://apps.apple.com/app/happ-proxy-utility/id6504287215), [Android](https://play.google.com/store/apps/details?id=com.happproxy), [Windows/macOS](https://www.happ.su/main)).
2. Бот → **🚀 Открыть NOVA VPN** → **ПОДКЛЮЧИТЬ VPN** → **Скопировать подписку**.
3. Откройте Happ — он предложит добавить подписку из буфера (или «+» → вставить). Можно отсканировать QR.
4. Подключитесь и откройте https://ifconfig.me — должен показаться IP сервера. В Happ видны трафик и срок доступа.

**WireGuard:** установите WireGuard, скачайте `.conf` (или QR) в Mini App, импортируйте, включите туннель.

В течение минуты Mini App покажет «VPN подключён», а админка — подключение и трафик.

Автоматические end-to-end тесты (настоящие Xray и WireGuard):

```bash
scripts/e2e_vless.sh       # Xray + агент + backend → подписка → клиент по ссылке → HTTPS через туннель → отзыв
scripts/e2e_wireguard.sh   # Docker: нода WireGuard + клиент, handshake, пинг через туннель → отзыв
```

Диагностика на ноде: `journalctl -u nova-agent -f`, `systemctl status xray caddy` (VLESS), `wg show` (WireGuard).

## 10. Развернуть проект

Всё на одном сервере (WireGuard + agent + API + бот + HTTPS):

```bash
# 1) нода: шаг 7, вариант A (DOMAIN=vpn.example.com bash install.sh vless) — Caddy уже отдаёт HTTPS
cp .env.example .env    # заполнить; WEBAPP_URL=https://vpn.example.com
docker compose up -d --build                                # api + bot
docker compose exec api python -m app.cli add-server ...   # шаг 8
```

`docker compose` поднимает `api` (FastAPI + собранный Mini App) и `bot` в host-сети: API видит агента на `127.0.0.1:8787`, Caddy — API на `127.0.0.1:8000`. Для схемы только с WireGuard (Caddy на хосте нет) запускайте `docker compose --profile caddy up -d` — поднимется ещё и Caddy из `Caddyfile`.

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
- Агент: токен Bearer, ключи, UUID и адреса валидируются, `wg`/`xray` вызываются без shell, UUID передаётся в Xray через stdin, IP клиентов наружу не отдаются. Для удалённых нод backend требует HTTPS.
- Ссылка-подписка (`/api/sub/<token>`) — секрет устройства, как у любого VPN-сервиса. Перевыпуск ключа меняет и UUID, и ссылку; перенос на другой сервер сохраняет ссылку, Happ подтягивает новый сервер сам.
- Reconcile: раз в `POLL_INTERVAL` набор peers на ноде приводится к базе. Бан, истечение срока, исчерпание трафика и отзыв отключают доступ автоматически, даже после перезагрузки ноды.
- `DEV_MODE` включает обходы для разработки: в продакшене держите `false`. Без `BOT_TOKEN`, `SECRET_KEY` и `ENCRYPTION_KEY` backend не стартует.

## Что честно умеет и не умеет MVP

- Кнопка «Подключить VPN» **не включает VPN сама**: Mini App физически не может управлять сетью телефона. Она выдаёт конфигурацию и ведёт через импорт, а статус «подключён» backend берёт из WireGuard handshake.
- **Ping** — это задержка backend → нода. Реальный ping с устройства показывает клиент (Happ / WireGuard).
- «Подключён» для VLESS означает, что за последние ~3 минуты по ключу шёл трафик (у Xray нет handshake, как у WireGuard).
- **Скорость** — фактическая средняя скорость передачи за последний интервал опроса, а не speedtest.
- Rate limiter хранит состояние в памяти: для нескольких реплик API нужен Redis.
- Миграций схемы нет (таблицы создаются автоматически). При изменении моделей добавьте Alembic.
- Оплаты нет: срок и лимиты задаются в админке (+30 дней, лимиты устройств и трафика).

## Дальнейшее развитие

- **Сильнее против DPI:** VLESS + Reality или XHTTP-транспорт (новые параметры в `app/vpn/vless.py` и шаблоне `xray-config.json`), AmneziaWG вместо WireGuard.
- Одна подписка на все серверы сразу (сейчас устройство привязано к одному серверу, переключение — в Mini App).
- Оплата (например, Telegram Stars), реферальная программа, уведомления о лимите трафика.
- Alembic-миграции, PostgreSQL, Redis для rate limit и нескольких реплик API.

## Структура

```
backend/app/        config, db, models, views, tasks (poller + reconcile), cli
backend/app/api/    user.py (Mini App), admin.py, deps.py (auth)
backend/app/security/  telegram initData, шифрование и токены, rate limit
backend/app/services/  users, devices, servers, stats: общие для API и бота
backend/app/vpn/    wireguard, vless (ссылки), protocols (реестр), drivers (agent/mock)
backend/bot/        aiogram-бот: тексты, клавиатуры, хендлеры, напоминания
backend/tests/      pytest: initData, крипто, жизненный цикл устройств, админка, бот
frontend/src/       lib (telegram, api, store), components, screens, admin
vpn-agent/          agent.py (wireguard|vless), install.sh, xray-config.json, systemd unit, Dockerfile (WireGuard)
scripts/            e2e_vless.sh, e2e_wireguard.sh
```
