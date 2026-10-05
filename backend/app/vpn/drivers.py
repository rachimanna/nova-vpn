"""Drivers talk to VPN nodes. Add a new protocol/backend by implementing `NodeDriver`.

* AgentDriver — production: HTTPS calls to `vpn-agent` running next to WireGuard.
* MockDriver  — local development without any VPN server; simulates peers and traffic.
"""

import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from app.models import Server
from app.security.crypto import decrypt


class NodeError(RuntimeError):
    pass


@dataclass
class PeerStat:
    public_key: str
    rx: int  # bytes received by the server from the client (client upload)
    tx: int  # bytes sent by the server to the client (client download)
    last_handshake: datetime | None


@dataclass
class NodeInfo:
    public_key: str
    listen_port: int
    subnet: str | None = None
    protocol: str = "wireguard"
    params: dict = field(default_factory=dict)


class NodeDriver(Protocol):
    async def info(self) -> NodeInfo: ...
    async def peers(self) -> list[PeerStat]: ...
    async def add_peer(self, public_key: str, psk: str, address: str) -> None: ...
    async def remove_peer(self, public_key: str) -> None: ...
    async def ping(self) -> float: ...


class AgentDriver:
    def __init__(self, url: str, token: str, timeout: float = 8.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=timeout
        )

    async def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise NodeError(f"node unreachable: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise NodeError(f"node error {r.status_code}: {r.text[:200]}")
        return r.json()

    async def info(self) -> NodeInfo:
        d = await self._call("GET", "/info")
        return NodeInfo(
            public_key=d.get("public_key", ""),
            listen_port=d["listen_port"],
            subnet=d.get("subnet"),
            protocol=d.get("protocol", "wireguard"),
            params=d.get("params") or {},
        )

    async def peers(self) -> list[PeerStat]:
        d = await self._call("GET", "/peers")
        return [
            PeerStat(
                public_key=p["public_key"],
                rx=p["rx"],
                tx=p["tx"],
                last_handshake=datetime.fromtimestamp(p["last_handshake"], UTC) if p["last_handshake"] else None,
            )
            for p in d["peers"]
        ]

    async def add_peer(self, public_key: str, psk: str, address: str) -> None:
        await self._call("POST", "/peers", json={"public_key": public_key, "psk": psk, "address": address})

    async def remove_peer(self, public_key: str) -> None:
        await self._call("POST", "/peers/remove", json={"public_key": public_key})

    async def ping(self) -> float:
        start = time.perf_counter()
        await self._call("GET", "/health")
        return (time.perf_counter() - start) * 1000

    async def aclose(self) -> None:
        await self._client.aclose()


@dataclass
class _MockPeer:
    address: str
    rx: int = 0
    tx: int = 0
    last_handshake: datetime | None = None
    online: bool = field(default_factory=lambda: random.random() < 0.7)


class MockDriver:
    """In-memory fake node. Keeps state per server for the lifetime of the process."""

    _state: dict[str, dict[str, _MockPeer]] = {}

    def __init__(self, server: Server) -> None:
        self.server = server
        self.peers_map = self._state.setdefault(server.code, {})

    async def info(self) -> NodeInfo:
        return NodeInfo(public_key=self.server.public_key, listen_port=self.server.port, protocol=self.server.protocol)

    async def peers(self) -> list[PeerStat]:
        now = datetime.now(UTC)
        for p in self.peers_map.values():
            if random.random() < 0.05:
                p.online = not p.online
            if p.online:
                p.last_handshake = now - timedelta(seconds=random.randint(5, 110))
                p.tx += random.randint(2, 60) * 1024 * 1024
                p.rx += random.randint(1, 8) * 1024 * 1024
        return [PeerStat(k, p.rx, p.tx, p.last_handshake) for k, p in self.peers_map.items()]

    async def add_peer(self, public_key: str, psk: str, address: str) -> None:
        self.peers_map.setdefault(public_key, _MockPeer(address=address))

    async def remove_peer(self, public_key: str) -> None:
        self.peers_map.pop(public_key, None)

    async def ping(self) -> float:
        base = {"de": 18, "nl": 22, "fi": 31, "se": 35, "pl": 27, "us": 110, "tr": 48}.get(self.server.country, 40)
        return base + random.uniform(-3, 4)


_agent_cache: dict[int, tuple[str, AgentDriver]] = {}


def get_driver(server: Server) -> NodeDriver:
    if server.driver == "mock":
        return MockDriver(server)
    if server.driver == "agent":
        if not server.agent_url or not server.agent_token_enc:
            raise NodeError("agent_url/agent_token not configured")
        cache_key = f"{server.agent_url}|{server.agent_token_enc}"
        cached = _agent_cache.get(server.id)
        if cached and cached[0] == cache_key:
            return cached[1]
        driver = AgentDriver(server.agent_url, decrypt(server.agent_token_enc))
        _agent_cache[server.id] = (cache_key, driver)
        return driver
    raise NodeError(f"unknown driver {server.driver}")
