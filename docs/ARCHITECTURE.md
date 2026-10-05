# NOVA VPN — архитектура MVP

## 1. Анализ требований и честные ограничения

| Идея | Реальность | Решение в MVP |
|---|---|---|
| Кнопка «Подключить VPN» в Mini App включает VPN | Веб-страница (и Mini App) **не может** управлять сетевыми интерфейсами телефона. VPN включает только нативный клиент (WireGuard). | Кнопка создаёт/выдаёт конфигурацию и ведёт пользователя через импорт. Статус «Подключён» вычисляется на сервере по свежему WireGuard handshake (< 3 мин). |
| Ping до сервера | Браузер не умеет ICMP. | Показываем RTT «backend → VPN-нода» (измеряется агентом/пуллером). Реальный ping с устройства показывает сам клиент WireGuard. |
| Скорость | Реальную скорость канала не измерить без speedtest-трафика. | Показываем фактическую скорость передачи данных по счётчикам WireGuard (байт/интервал). |
| Бесплатный VPS навсегда | Free tier у облаков меняются, требуют карту и могут закончиться. | Никаких обещаний. Для разработки VPS не нужен: есть **Mock-драйвер**. Для реального VPN нужен хост с публичным IP и открытым UDP-портом. |
| Отправка конфигурации через бота | Telegram — сторонний сервис, приватный ключ не должен туда уходить. | Конфигурация (с приватным ключом) отдаётся **только** нашим backend по HTTPS в Mini App. Бот конфиги не пересылает. |
| WireGuard «везде работает» | В ряде стран (в т.ч. РФ) WireGuard детектируется DPI и блокируется. | Архитектура протоколов расширяемая (`protocol` у устройства, драйверы нод). Следующие кандидаты — AmneziaWG (обфусцированный форк WireGuard) или VLESS/Reality (Xray). |

## 2. Выбранный стек (самый простой бесплатный вариант)

| Компонент | Технология | Почему |
|---|---|---|
| Backend API | Python 3.12+ / FastAPI / SQLAlchemy 2 (async) | Один язык с ботом, общий слой сервисов |
| База | **SQLite** (MVP) → PostgreSQL заменой `DATABASE_URL` | Ноль настройки, 0 ₽ |
| Bot | aiogram 3, long polling | Не нужен вебхук и домен для бота |
| Mini App + Admin | React + Vite + TypeScript (статический SPA) | Next.js не нужен: SSR не требуется, статику можно хостить бесплатно где угодно или отдавать из FastAPI |
| VPN | WireGuard (kernel) | Open-source, быстрый, клиенты на всех платформах, есть импорт по QR |
| Управление VPN-нодой | `vpn-agent` — маленький FastAPI-сервис на каждой ноде | Backend никогда не видит приватный ключ сервера; ноды добавляются через админку |
| HTTPS | Caddy (Let's Encrypt) или Cloudflare Tunnel | Оба бесплатны |

Next.js отклонён осознанно: Mini App — это клиентское приложение внутри Telegram, SSR лишь усложнит хостинг.

## 3. Схема

```
 Telegram ──/start──► Bot (aiogram) ──┐
    │                                  │ общий слой app/services
    └─ WebApp кнопка ─► Mini App (React SPA)
                          │ HTTPS, Authorization: tma <initData>
                          ▼
                     FastAPI backend ──► SQLite/PostgreSQL
                          │  (ключи клиентов зашифрованы Fernet)
                          │ HTTPS + Bearer token
                          ▼
                     vpn-agent на VPN-ноде ──► wg0 (WireGuard)
                                                    ▲
                     Клиент WireGuard на устройстве ┘ UDP 51820
```

### Поток выдачи конфигурации
1. Mini App → `POST /api/devices {name, platform, server_id}`.
2. Backend проверяет initData, бан, срок доступа, лимит устройств.
3. Генерирует X25519-ключи клиента + preshared key, выделяет IP в подсети ноды.
4. Шифрует приватный ключ и PSK (Fernet, `ENCRYPTION_KEY`), сохраняет.
5. Через драйвер ноды добавляет peer (публичный ключ + PSK + IP).
6. Mini App запрашивает `GET /api/devices/{id}/config` → показывает QR / скачивание.

### Reconcile (самовосстановление)
Фоновый поллер раз в `POLL_INTERVAL` секунд для каждой ноды:
- снимает статистику peers (rx/tx/handshake) → трафик, сессии, графики;
- приводит набор peers на ноде к «желаемому» (активные устройства неблокированных пользователей с непросроченным доступом и неисчерпанным трафиком). Бан, истечение срока, превышение трафика, отзыв — всё отключается автоматически, даже если нода перезагрузилась.

## 4. Структура файлов

```
nova-vpn/
├── .env.example            # все секреты и настройки
├── docker-compose.yml      # backend + bot + caddy
├── Caddyfile
├── README.md
├── docs/ARCHITECTURE.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py         # FastAPI, middleware, статика SPA
│   │   ├── config.py       # настройки из env
│   │   ├── db.py, models.py, schemas.py
│   │   ├── cli.py          # add-server, gen-keys
│   │   ├── tasks.py        # поллер статистики + reconcile
│   │   ├── security/       # initData, шифрование, admin-токены, rate limit
│   │   ├── vpn/            # протоколы (WireGuard) и драйверы нод (mock/agent)
│   │   ├── services/       # бизнес-логика (общая для API и бота)
│   │   └── api/            # роутеры: user, admin
│   ├── bot/                # aiogram-бот
│   └── tests/
├── vpn-agent/              # агент на VPN-ноде + install.sh + systemd unit
└── frontend/               # React SPA: Mini App + /admin
    └── src/{lib,components,screens,admin}
```

## 5. Что бесплатно

| Компонент | Local development | Free deployment |
|---|---|---|
| Bot | polling с ноутбука | на том же хосте, что backend |
| Backend + DB | `uvicorn` + SQLite | на VPN-ноде (Docker) или бесплатные PaaS (проверяйте актуальные условия) |
| Mini App | `vite` + Cloudflare Quick Tunnel (HTTPS без аккаунта) | статикой из FastAPI, либо Cloudflare Pages / GitHub Pages |
| HTTPS | Quick Tunnel | Caddy + бесплатный поддомен (DuckDNS) или свой домен |
| VPN | **Mock-драйвер** (без WireGuard, данные имитируются) | Нужна Linux-машина с публичным IPv4 и открытым UDP: free tier облака (условия проверять самостоятельно), домашний сервер/Raspberry Pi с белым IP и пробросом порта |

Единственное, что нельзя гарантированно получить бесплатно, — это **публичный IP с открытым UDP-портом**. Без него настоящий VPN не заработает — это физическое ограничение сети, а не проекта.
