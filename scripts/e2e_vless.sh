#!/usr/bin/env bash
# Real end-to-end test of the VLESS path on one machine (no Docker, no root):
#   Xray server (VLESS over WebSocket + API) <- nova-agent (NODE_PROTOCOL=vless) <- backend services
#   backend issues a device -> subscription -> share link -> Xray client (socks) -> HTTPS request through it
#   then the poller must see the traffic and revoke must cut access.
# TLS is off here (NODE_TLS=false): in production Caddy terminates TLS in front of Xray.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
WORK=$(mktemp -d)
TOKEN=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)
WS_PATH="/nv-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; rm -rf "$WORK"; }
trap cleanup EXIT

XRAY=$(command -v xray || true)
if [ -z "$XRAY" ]; then
  echo "==> downloading Xray"
  curl -sL -o "$WORK/xray.zip" https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip
  "$PY" -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); [z.extract(f, sys.argv[2]) for f in ('xray', 'geoip.dat', 'geosite.dat')]" "$WORK/xray.zip" "$WORK"
  chmod +x "$WORK/xray"; XRAY="$WORK/xray"
fi

echo "==> starting Xray server"
sed "s|__WS_PATH__|$WS_PATH|" "$ROOT/vpn-agent/xray-config.json" | sed 's|"loglevel": "warning"|"loglevel": "error"|' > "$WORK/server.json"
"$XRAY" run -c "$WORK/server.json" > "$WORK/xray.log" 2>&1 & PIDS+=($!)
sleep 1

echo "==> starting agent (vless)"
(cd "$ROOT/vpn-agent" && AGENT_TOKEN="$TOKEN" NODE_PROTOCOL=vless NODE_DOMAIN=127.0.0.1 WS_PATH="$WS_PATH" \
  NODE_TLS=false XRAY_BIN="$XRAY" STATE_FILE="$WORK/peers.json" \
  exec "$ROOT/backend/.venv/bin/uvicorn" agent:app --host 127.0.0.1 --port 18788 --log-level warning > "$WORK/agent.log" 2>&1) & PIDS+=($!)
for _ in $(seq 30); do curl -sf -H "Authorization: Bearer $TOKEN" http://127.0.0.1:18788/health >/dev/null && break; sleep 0.3; done

export DATABASE_URL="sqlite+aiosqlite:///$WORK/e2e.db" DEV_MODE=true SECRET_KEY=e2e ENCRYPTION_KEY= POLL_INTERVAL=5 WEBAPP_URL=
cd "$ROOT/backend"

echo "==> backend: register node, create device, fetch subscription"
"$PY" - "$TOKEN" "$WORK" <<'PY'
import asyncio, base64, json, sys
from urllib.parse import parse_qs, unquote, urlparse
from httpx import ASGITransport, AsyncClient
from app.db import init_db, SessionLocal
from app.main import app
from app.services.servers import create_server

token, work = sys.argv[1:]

async def main():
    await init_db()
    async with SessionLocal() as s:
        server = await create_server(s, code="e2e-vl", name="E2E", country="NL", city=None, host="127.0.0.1",
                                     driver="agent", agent_url="http://127.0.0.1:18788", agent_token=token)
        assert server.protocol == "vless", server.protocol
    h = {"X-Dev-User": "777"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        dev = (await c.post("/api/devices", headers=h, json={"server_id": server.id, "name": "Happ"})).json()
        cfg = (await c.get(f"/api/devices/{dev['id']}/config", headers=h)).json()
        sub = await c.get(cfg["subscription_path"])
        link = base64.b64decode(sub.text).decode().strip()
        print(f"    node protocol: {server.protocol}, subscription: {sub.status_code}, userinfo: {sub.headers['subscription-userinfo'][:40]}…")
    u = urlparse(link)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    client = {
        "log": {"loglevel": "error"},
        "inbounds": [{"listen": "127.0.0.1", "port": 18808, "protocol": "socks"}],
        "outbounds": [{"protocol": "vless",
                       "settings": {"vnext": [{"address": u.hostname, "port": u.port,
                                               "users": [{"id": u.username, "encryption": "none"}]}]},
                       "streamSettings": {"network": q["type"], "security": q["security"],
                                          "wsSettings": {"path": unquote(q["path"])}}}],
    }
    json.dump(client, open(f"{work}/client.json", "w"))
    json.dump({"device": dev["id"]}, open(f"{work}/device.json", "w"))
    print(f"    client built from the share link ({q['type']}, path {unquote(q['path'])[:8]}…)")

asyncio.run(main())
PY

echo "==> client: request through the tunnel"
"$XRAY" run -c "$WORK/client.json" > "$WORK/client.log" 2>&1 & PIDS+=($!)
sleep 1
for i in 1 2 3; do curl -s -m 15 -x socks5h://127.0.0.1:18808 -o /dev/null https://www.cloudflare.com/ -w "    https via VLESS: %{http_code}\n"; done

echo "==> backend: poller sees traffic, then revoke"
"$PY" - "$WORK" <<'PY'
import asyncio, json, sys
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Device, User
from app.services.devices import is_online, revoke_device
from app.tasks import poll_once

async def main():
    await poll_once()
    async with SessionLocal() as s:
        d = await s.get(Device, json.load(open(f"{sys.argv[1]}/device.json"))["device"])
        u = await s.get(User, d.user_id)
        print(f"    online={is_online(d)} download={d.download_bytes}B upload={d.upload_bytes}B user_traffic={u.traffic_used}B")
        assert is_online(d) and d.download_bytes > 0, "poller did not register traffic"
        await revoke_device(s, d)
        print("    device revoked")
asyncio.run(main())
PY

code=$(curl -s -m 10 -x socks5h://127.0.0.1:18808 -o /dev/null https://www.cloudflare.com/ -w "%{http_code}" || true)
if [ "$code" = "200" ]; then echo "FAIL: access still works after revoke"; exit 1; fi
echo "    access is closed after revoke"
echo "E2E VLESS PASSED"
