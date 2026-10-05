import json
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device, Server
from app.security.crypto import encrypt
from app.vpn.drivers import AgentDriver, NodeError
from app.vpn.protocols import PROTOCOLS
from app.vpn.wireguard import is_valid_key


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}


def check_agent_url(url: str) -> None:
    """The agent token travels in a header: plain HTTP is only fine on the same machine."""
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS:
        return
    raise ValueError("Агент на другом сервере должен быть доступен по https:// (см. README, раздел про Caddy)")


def flag(country: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper()[:2]) if len(country) == 2 else "🌐"


def load_level(percent: int) -> str:
    return "low" if percent < 50 else "medium" if percent < 80 else "high"


async def active_counts(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(
        select(Device.server_id, func.count(Device.id)).where(Device.status == "active").group_by(Device.server_id)
    )
    return dict(rows.all())


async def list_servers(session: AsyncSession, include_inactive: bool = False) -> list[tuple[Server, int]]:
    q = select(Server).order_by(Server.id)
    if not include_inactive:
        q = q.where(Server.is_active.is_(True))
    servers = (await session.scalars(q)).all()
    counts = await active_counts(session)
    return [(s, counts.get(s.id, 0)) for s in servers]


def server_view(server: Server, configs: int) -> dict:
    # Load mixes live connections and allocated slots so an idle but full node still looks busy
    percent = min(100, round(100 * max(server.peers_online * 2, configs) / max(server.max_peers, 1)))
    status = "offline" if not server.online else "online"
    return {
        "id": server.id,
        "code": server.code,
        "name": server.name,
        "city": server.city,
        "country": server.country,
        "flag": flag(server.country),
        "protocol": server.protocol,
        "ping_ms": server.ping_ms,
        "load": percent,
        "load_level": load_level(percent),
        "status": status,
    }


async def create_server(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    country: str,
    city: str | None,
    host: str,
    driver: str,
    agent_url: str | None = None,
    agent_token: str | None = None,
    public_key: str | None = None,
    port: int = 51820,
    subnet: str = "10.8.0.0/24",
    dns: str = "1.1.1.1, 1.0.0.1",
    max_peers: int = 250,
    protocol: str = "wireguard",
    params: dict | None = None,
) -> Server:
    """For agent nodes protocol, keys, port and client params are fetched from the node itself."""
    if driver == "agent":
        if not agent_url or not agent_token:
            raise ValueError("agent_url и agent_token обязательны")
        check_agent_url(agent_url)
        agent = AgentDriver(agent_url, agent_token)
        try:
            info = await agent.info()
        except NodeError as e:
            raise ValueError(f"Агент недоступен: {e}") from e
        finally:
            await agent.aclose()
        public_key, port, protocol = info.public_key, info.listen_port, info.protocol
        subnet = info.subnet or subnet
        params = info.params
    elif driver == "mock":
        from app.vpn.wireguard import generate_keypair

        if protocol == "wireguard":
            public_key = public_key or generate_keypair().public_key
        else:
            port, params = 443, params or {"transport": "ws", "path": "/demo", "sni": host, "security": "tls"}
    else:
        raise ValueError("driver: agent | mock")

    if protocol not in PROTOCOLS:
        raise ValueError(f"Неизвестный протокол {protocol}")
    if protocol == "wireguard" and (not public_key or not is_valid_key(public_key)):
        raise ValueError("Некорректный публичный ключ сервера")
    if await session.scalar(select(Server.id).where(Server.code == code)):
        raise ValueError(f"Сервер с кодом {code} уже существует")

    server = Server(
        code=code,
        name=name,
        country=country.upper(),
        city=city,
        host=host,
        port=port,
        driver=driver,
        agent_url=agent_url,
        agent_token_enc=encrypt(agent_token) if agent_token else None,
        public_key=public_key or "",
        protocol=protocol,
        params=json.dumps(params or {}),
        subnet=subnet,
        dns=dns,
        max_peers=max_peers,
        online=driver == "mock",
    )
    session.add(server)
    await session.commit()
    return server
