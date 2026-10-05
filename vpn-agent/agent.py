"""NOVA VPN node agent.

Runs next to the VPN server and manages its users. One agent = one protocol:

* NODE_PROTOCOL=wireguard — peers of a WireGuard interface via the `wg` CLI.
  The server private key never leaves this machine.
* NODE_PROTOCOL=vless — users of an Xray VLESS inbound via the Xray API (`xray api ...`).
  TLS is terminated by Caddy in front of Xray (VLESS over WebSocket on the node's domain).

Common env:
    AGENT_TOKEN    shared secret with the backend (required, 24+ chars)
    STATE_FILE     default /var/lib/nova-agent/peers.json (re-applied on start)
WireGuard env:
    WG_INTERFACE   default wg0
    WG_SUBNET      default 10.8.0.0/24 (must match Address in wg0.conf)
VLESS env:
    NODE_DOMAIN    public domain clients connect to (TLS certificate is issued for it)
    WS_PATH        secret WebSocket path, e.g. /nv-3f9a…
    XRAY_BIN       default xray
    XRAY_API       default 127.0.0.1:10085
    XRAY_TAG       default vless-in
    XRAY_PORT      default 10000 (port of the VLESS inbound in Xray config)
    NODE_TLS       default true; false only for local tests without Caddy
"""

import base64
import binascii
import hmac
import ipaddress
import json
import logging
import os
import re
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, field_validator

TOKEN = os.environ.get("AGENT_TOKEN", "")
PROTOCOL = os.environ.get("NODE_PROTOCOL", "wireguard")
STATE_FILE = Path(os.environ.get("STATE_FILE", "/var/lib/nova-agent/peers.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s agent: %(message)s")
log = logging.getLogger("agent")
lock = threading.Lock()

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")


def run(cmd: list[str], stdin: str | None = None) -> str:
    # argument list, never a shell; inputs are validated before they get here
    res = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=10)
    if res.returncode != 0:
        raise HTTPException(500, f"{cmd[0]} failed: {(res.stderr or res.stdout).strip()[:200]}")
    return res.stdout


def _load_state() -> dict[str, dict]:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, dict]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.chmod(tmp, 0o600)  # contains client secrets
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------- WireGuard
class WireGuard:
    def __init__(self) -> None:
        self.iface = os.environ.get("WG_INTERFACE", "wg0")
        self.subnet = ipaddress.ip_network(os.environ.get("WG_SUBNET", "10.8.0.0/24"))

    @staticmethod
    def _key(v: str) -> str:
        try:
            if len(base64.b64decode(v, validate=True)) != 32:
                raise ValueError
        except (binascii.Error, ValueError) as e:
            raise HTTPException(422, "invalid WireGuard key") from e
        return v

    def validate(self, key: str, secret: str, address: str) -> str:
        self._key(key)
        self._key(secret)
        try:
            iface = ipaddress.ip_interface(address)
        except ValueError as e:
            raise HTTPException(422, "invalid address") from e
        if iface.network.prefixlen != 32 or iface.ip not in self.subnet or iface.ip == next(self.subnet.hosts()):
            raise HTTPException(422, "address outside of node subnet")
        return f"{iface.ip}/32"

    def info(self) -> dict:
        return {
            "protocol": "wireguard",
            "public_key": run(["wg", "show", self.iface, "public-key"]).strip(),
            "listen_port": int(run(["wg", "show", self.iface, "listen-port"]).strip()),
            "subnet": str(self.subnet),
            "params": {},
        }

    def add(self, key: str, secret: str, address: str) -> None:
        run(["wg", "set", self.iface, "peer", key, "preshared-key", "/dev/stdin", "allowed-ips", address],
            stdin=secret + "\n")

    def remove(self, key: str) -> None:
        run(["wg", "set", self.iface, "peer", self._key(key), "remove"])

    def peers(self) -> list[dict]:
        out = []
        for line in run(["wg", "show", self.iface, "dump"]).splitlines()[1:]:
            f = line.split("\t")
            if len(f) >= 8:
                # f[1] (psk) and f[2] (client IP) are deliberately not exposed
                out.append({"public_key": f[0], "last_handshake": int(f[4]), "rx": int(f[5]), "tx": int(f[6])})
        return out


# ---------------------------------------------------------------- Xray VLESS
class Xray:
    def __init__(self) -> None:
        self.bin = os.environ.get("XRAY_BIN", "xray")
        self.api = os.environ.get("XRAY_API", "127.0.0.1:10085")
        self.tag = os.environ.get("XRAY_TAG", "vless-in")
        self.port = int(os.environ.get("XRAY_PORT", "10000"))
        self.domain = os.environ.get("NODE_DOMAIN", "")
        self.path = os.environ.get("WS_PATH", "")
        self.tls = os.environ.get("NODE_TLS", "true").lower() != "false"
        # Xray has no handshake time: remember when a user's counters last moved
        self.seen: dict[str, tuple[int, int, int]] = {}

    def _api(self, command: str, *args: str, stdin: str | None = None) -> str:
        # Go flag parsing stops at the first positional argument: --server must come first
        return run([self.bin, "api", command, f"--server={self.api}", *args], stdin=stdin)

    def validate(self, key: str, secret: str, address: str) -> str:
        if not LABEL_RE.match(key):
            raise HTTPException(422, "invalid user label")
        if not UUID_RE.match(secret):
            raise HTTPException(422, "invalid uuid")
        return address

    def info(self) -> dict:
        if not self.domain or not self.path.startswith("/"):
            raise HTTPException(500, "NODE_DOMAIN and WS_PATH must be set")
        self._api("inboundusercount", f"-tag={self.tag}")  # proves the API is reachable
        return {
            "protocol": "vless",
            "public_key": "",
            "listen_port": 443 if self.tls else self.port,
            "subnet": None,
            "params": {"transport": "ws", "path": self.path, "sni": self.domain,
                       "security": "tls" if self.tls else "none", "fp": "chrome"},
        }

    def add(self, key: str, secret: str, address: str) -> None:
        if key in self._users():
            return
        payload = {"inbounds": [{"tag": self.tag, "port": self.port, "protocol": "vless",
                                 "settings": {"clients": [{"id": secret, "email": key}], "decryption": "none"}}]}
        # via stdin: the uuid never touches the disk outside the state file
        self._api("adu", "/dev/stdin", stdin=json.dumps(payload))

    def remove(self, key: str) -> None:
        if not LABEL_RE.match(key):
            raise HTTPException(422, "invalid user label")
        if key in self._users():
            self._api("rmu", f"-tag={self.tag}", key)

    def _users(self) -> set[str]:
        data = json.loads(self._api("inbounduser", f"-tag={self.tag}") or "{}")
        return {u["email"] for u in data.get("users", [])}

    def peers(self) -> list[dict]:
        stats: dict[str, dict[str, int]] = {}
        raw = json.loads(self._api("statsquery", "-pattern", "user>>>") or "{}")
        for s in raw.get("stat", []):
            _, email, _, direction = s["name"].split(">>>")
            stats.setdefault(email, {})[direction] = int(s.get("value", 0))
        now = int(time.time())
        out = []
        for email in self._users():
            up = stats.get(email, {}).get("uplink", 0)
            down = stats.get(email, {}).get("downlink", 0)
            prev = self.seen.get(email)
            if prev is None:
                last = now if up or down else 0
            elif (up, down) != prev[:2]:
                last = now
            else:
                last = prev[2]
            self.seen[email] = (up, down, last)
            # uplink = client -> server (rx on the node), downlink = server -> client (tx)
            out.append({"public_key": email, "last_handshake": last, "rx": up, "tx": down})
        return out


backend = Xray() if PROTOCOL == "vless" else WireGuard()


class PeerIn(BaseModel):
    public_key: str  # WireGuard public key or Xray user label (email)
    psk: str  # WireGuard preshared key or VLESS uuid
    address: str  # WireGuard /32 address; ignored by Xray

    @field_validator("public_key", "psk", "address")
    @classmethod
    def short(cls, v: str) -> str:
        if len(v) > 64:
            raise ValueError("too long")
        return v


class PeerKey(BaseModel):
    public_key: str


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(TOKEN) < 24:
        raise SystemExit("AGENT_TOKEN must be set (24+ chars)")
    state = _load_state()
    for attempt in range(30):  # Xray may still be starting
        try:
            with lock:
                for key, peer in state.items():
                    backend.add(key, peer["psk"], peer["address"])
            break
        except HTTPException as e:
            if attempt == 29:
                log.error("could not restore peers: %s", e.detail)
            time.sleep(1)
    log.info("%s agent ready, restored %d users", PROTOCOL, len(state))
    yield


app = FastAPI(title="nova-agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def auth(authorization: str = Header(default="")) -> None:
    if not hmac.compare_digest(authorization.encode(), f"Bearer {TOKEN}".encode()):
        raise HTTPException(401, "unauthorized")


@app.get("/health")
def health(_: None = Depends(auth)):
    return {"ok": True, "protocol": PROTOCOL}


@app.get("/info")
def info(_: None = Depends(auth)):
    return backend.info()


@app.get("/peers")
def peers(_: None = Depends(auth)):
    with lock:
        return {"peers": backend.peers()}


@app.post("/peers")
def add_peer(peer: PeerIn, _: None = Depends(auth)):
    address = backend.validate(peer.public_key, peer.psk, peer.address)
    with lock:
        backend.add(peer.public_key, peer.psk, address)
        state = _load_state()
        if PROTOCOL == "wireguard":
            # WireGuard moves an allowed-ip to the newest peer; mirror that in the state file
            state = {k: v for k, v in state.items() if v["address"] != address}
        state[peer.public_key] = {"psk": peer.psk, "address": address}
        _save_state(state)
    log.info("user added %s…", peer.public_key[:8])
    return {"ok": True}


@app.post("/peers/remove")
def remove_peer(peer: PeerKey, _: None = Depends(auth)):
    with lock:
        backend.remove(peer.public_key)
        state = _load_state()
        if state.pop(peer.public_key, None) is not None:
            _save_state(state)
    log.info("user removed %s…", peer.public_key[:8])
    return {"ok": True}
