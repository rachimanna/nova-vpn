"""Management commands.

    python -m app.cli gen-secrets
    python -m app.cli seed-demo
    python -m app.cli add-server --code de-fra-1 --name Germany --country DE --city Frankfurt \
        --host 203.0.113.10 --agent-url https://203.0.113.10:8443 --agent-token XXX
    python -m app.cli list-servers
"""

import argparse
import asyncio
import secrets

from cryptography.fernet import Fernet

from app.db import SessionLocal, init_db
from app.services.servers import create_server, flag, list_servers

DEMO_SERVERS = [
    ("de-fra-1", "Germany", "DE", "Frankfurt", "10.8.0.0/24", "vless"),
    ("nl-ams-1", "Netherlands", "NL", "Amsterdam", "10.8.1.0/24", "vless"),
    ("fi-hel-1", "Finland", "FI", "Helsinki", "10.8.2.0/24", "vless"),
    ("se-sto-1", "Sweden", "SE", "Stockholm", "10.8.3.0/24", "wireguard"),
    ("pl-waw-1", "Poland", "PL", "Warsaw", "10.8.4.0/24", "wireguard"),
]


def gen_secrets() -> None:
    print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    print(f"ADMIN_PASSWORD={secrets.token_urlsafe(18)}")
    print(f"AGENT_TOKEN={secrets.token_urlsafe(32)}  # для vpn-agent")


DEMO_USERS = [
    ("alex", "Alex", "ios"), ("maria", "Maria", "android"), ("dmitry", "Dmitry", "windows"),
    ("kate", "Kate", "macos"), ("ivan", "Ivan", "ios"), ("olga", "Olga", "android"),
    ("sergey", "Sergey", "ios"), ("nina", "Nina", "windows"),
]


async def seed_demo(with_users: bool = False) -> None:
    await init_db()
    async with SessionLocal() as session:
        for code, name, country, city, subnet, protocol in DEMO_SERVERS:
            try:
                await create_server(
                    session, code=code, name=name, country=country, city=city,
                    host=f"{code}.demo.invalid", driver="mock", subnet=subnet, protocol=protocol,
                )
                print(f"+ {flag(country)} {name} ({code}) [mock, {protocol}]")
            except ValueError as e:
                print(f"= {code}: {e}")
        if with_users:
            await _seed_users(session)


async def _seed_users(session) -> None:
    """Mock users with configs on mock servers, so the admin panel has something to show."""
    from sqlalchemy import select

    from app.models import Server
    from app.security.telegram import TelegramUser
    from app.services.devices import create_device
    from app.services.users import get_or_create_user

    servers = (await session.scalars(select(Server).where(Server.driver == "mock"))).all()
    for i, (username, name, platform) in enumerate(DEMO_USERS):
        user = await get_or_create_user(session, TelegramUser(id=900_000 + i, first_name=name, username=username))
        if not user.devices:
            await create_device(session, user, server_id=servers[i % len(servers)].id, name=name + " phone", platform=platform)
    print(f"+ {len(DEMO_USERS)} demo users")


async def add_server(args: argparse.Namespace) -> None:
    await init_db()
    async with SessionLocal() as session:
        server = await create_server(
            session, code=args.code, name=args.name, country=args.country, city=args.city, host=args.host,
            driver="agent", agent_url=args.agent_url, agent_token=args.agent_token, subnet=args.subnet,
            max_peers=args.max_peers,
        )
        print(f"Added {flag(server.country)} {server.name}: {server.protocol} {server.host}:{server.port}")


async def show_servers() -> None:
    await init_db()
    async with SessionLocal() as session:
        for s, configs in await list_servers(session, include_inactive=True):
            state = "online" if s.online else "offline"
            print(f"{s.id:>3} {flag(s.country)} {s.code:<12} {s.protocol:<9} {s.driver:<5} {s.host}:{s.port} "
                  f"{state:<7} configs={configs}/{s.max_peers} active={s.is_active}")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-secrets", help="print fresh secrets for .env")
    seed = sub.add_parser("seed-demo", help="add mock servers for local development")
    seed.add_argument("--with-users", action="store_true", help="also create demo users with configs")
    sub.add_parser("list-servers")
    a = sub.add_parser("add-server", help="register a real node running vpn-agent")
    a.add_argument("--code", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--country", required=True, help="ISO code, e.g. DE")
    a.add_argument("--city")
    a.add_argument("--host", required=True, help="public IP (WireGuard) or the node domain (VLESS)")
    a.add_argument("--agent-url", required=True)
    a.add_argument("--agent-token", required=True)
    a.add_argument("--subnet", default="10.8.0.0/24")
    a.add_argument("--max-peers", type=int, default=250)
    args = p.parse_args()

    if args.cmd == "gen-secrets":
        gen_secrets()
    elif args.cmd == "seed-demo":
        asyncio.run(seed_demo(args.with_users))
    elif args.cmd == "list-servers":
        asyncio.run(show_servers())
    else:
        asyncio.run(add_server(args))


if __name__ == "__main__":
    main()
