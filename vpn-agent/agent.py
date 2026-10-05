"""NOVA VPN node agent.

Runs on the WireGuard server as root, manages peers of one interface via the `wg` CLI.
The server private key never leaves this machine. The backend only knows the public key.

Env:
    AGENT_TOKEN   shared secret with the backend (required)
    WG_INTERFACE  default wg0
    WG_SUBNET     default 10.8.0.0/24 (must match Address in wg0.conf)
    STATE_FILE    default /var/lib/nova-agent/peers.json (re-applied on start)
"""

import base64
import binascii
import hmac
import ipaddress
import json
import logging
import os
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, field_validator

TOKEN = os.environ.get("AGENT_TOKEN", "")
IFACE = os.environ.get("WG_INTERFACE", "wg0")
SUBNET = ipaddress.ip_network(os.environ.get("WG_SUBNET", "10.8.0.0/24"))
STATE_FILE = Path(os.environ.get("STATE_FILE", "/var/lib/nova-agent/peers.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s agent: %(message)s")
log = logging.getLogger("agent")
lock = threading.Lock()


def _valid_key(v: str) -> str:
    try:
        if len(base64.b64decode(v, validate=True)) != 32:
            raise ValueError
    except (binascii.Error, ValueError) as e:
        raise ValueError("invalid WireGuard key") from e
    return v


class PeerIn(BaseModel):
    public_key: str
    psk: str
    address: str

    @field_validator("public_key", "psk")
    @classmethod
    def key(cls, v: str) -> str:
        return _valid_key(v)

    @field_validator("address")
    @classmethod
    def addr(cls, v: str) -> str:
        iface = ipaddress.ip_interface(v)
        if iface.network.prefixlen != 32 or iface.ip not in SUBNET or iface.ip == next(SUBNET.hosts()):
            raise ValueError("address outside of node subnet")
        return f"{iface.ip}/32"


class PeerKey(BaseModel):
    public_key: str

    @field_validator("public_key")
    @classmethod
    def key(cls, v: str) -> str:
        return _valid_key(v)


def wg(*args: str, stdin: str | None = None) -> str:
    # argument list, never a shell: inputs are validated above anyway
    res = subprocess.run(["wg", *args], input=stdin, capture_output=True, text=True, timeout=10)
    if res.returncode != 0:
        raise HTTPException(500, f"wg failed: {res.stderr.strip()[:200]}")
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
    os.chmod(tmp, 0o600)  # contains preshared keys
    tmp.replace(STATE_FILE)


def _set_peer(public_key: str, psk: str, address: str) -> None:
    wg("set", IFACE, "peer", public_key, "preshared-key", "/dev/stdin", "allowed-ips", address, stdin=psk + "\n")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(TOKEN) < 24:
        raise SystemExit("AGENT_TOKEN must be set (24+ chars)")
    with lock:
        state = _load_state()
        for key, peer in state.items():
            _set_peer(key, peer["psk"], peer["address"])
    log.info("restored %d peers on %s", len(state), IFACE)
    yield


app = FastAPI(title="nova-agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def auth(authorization: str = Header(default="")) -> None:
    if not hmac.compare_digest(authorization.encode(), f"Bearer {TOKEN}".encode()):
        raise HTTPException(401, "unauthorized")


@app.get("/health")
def health(_: None = Depends(auth)):
    return {"ok": True}


@app.get("/info")
def info(_: None = Depends(auth)):
    return {
        "public_key": wg("show", IFACE, "public-key").strip(),
        "listen_port": int(wg("show", IFACE, "listen-port").strip()),
        "subnet": str(SUBNET),
    }


@app.get("/peers")
def peers(_: None = Depends(auth)):
    out = []
    # dump: first line is the interface, then one line per peer
    for line in wg("show", IFACE, "dump").splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 8:
            continue
        # f[2] (client endpoint IP) and f[1] (psk) are deliberately not exposed
        out.append({"public_key": f[0], "last_handshake": int(f[4]), "rx": int(f[5]), "tx": int(f[6])})
    return {"peers": out}


@app.post("/peers")
def add_peer(peer: PeerIn, _: None = Depends(auth)):
    with lock:
        _set_peer(peer.public_key, peer.psk, peer.address)
        state = _load_state()
        # WireGuard moves an allowed-ip to the newest peer; mirror that in the state file
        state = {k: v for k, v in state.items() if v["address"] != peer.address}
        state[peer.public_key] = {"psk": peer.psk, "address": peer.address}
        _save_state(state)
    log.info("peer added %s… %s", peer.public_key[:8], peer.address)
    return {"ok": True}


@app.post("/peers/remove")
def remove_peer(peer: PeerKey, _: None = Depends(auth)):
    with lock:
        wg("set", IFACE, "peer", peer.public_key, "remove")
        state = _load_state()
        if state.pop(peer.public_key, None) is not None:
            _save_state(state)
    log.info("peer removed %s…", peer.public_key[:8])
    return {"ok": True}
