#!/usr/bin/env bash
# Real end-to-end test on one machine with Docker (needs a kernel with WireGuard).
#
#   node container: wg0 + nova-agent            <- backend services register it, create a device
#   └─ netns "client" (veth 192.168.77.2): imports the generated config with wg-quick,
#      completes a WireGuard handshake and pings through the tunnel.
#   Then the poller must see the handshake/traffic and revoke must cut the tunnel.
#
# The client lives in a network namespace instead of a second container so the test also works
# where Docker blocks container-to-container traffic.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
TOKEN=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)
WORK=$(mktemp -d)
NODE=nova-e2e-node
CLIENT_NS="ip netns exec client"

remove_containers() { docker rm -f $NODE >/dev/null 2>&1 || true; }
[ -n "${KEEP:-}" ] || trap 'remove_containers; rm -rf "$WORK"' EXIT
remove_containers

echo "==> building images"
docker build -q -t nova-agent "$ROOT/vpn-agent" >/dev/null
printf 'FROM nova-agent\nRUN apt-get update -qq && apt-get install -y -qq iputils-ping >/dev/null\n' \
  | docker build -q -t nova-e2e - >/dev/null

echo "==> starting node"
docker run -d --name $NODE --privileged -p 127.0.0.1:18787:8787 -v "$WORK:/work" \
  -e AGENT_TOKEN="$TOKEN" -e AGENT_BIND=0.0.0.0 nova-e2e >/dev/null
for _ in $(seq 40); do curl -sf -H "Authorization: Bearer $TOKEN" http://127.0.0.1:18787/health >/dev/null && break; sleep 0.5; done
docker exec $NODE sh -c '
  ip netns add client
  ip link add veth0 type veth peer name veth1
  ip link set veth1 netns client
  ip addr add 192.168.77.1/24 dev veth0 && ip link set veth0 up
  ip netns exec client ip addr add 192.168.77.2/24 dev veth1
  ip netns exec client ip link set veth1 up
  ip netns exec client ip link set lo up
  ip netns exec client ip route add default via 192.168.77.1'
echo "    node agent healthy, client namespace ready"

export DATABASE_URL="sqlite+aiosqlite:///$WORK/e2e.db" DEV_MODE=true SECRET_KEY=e2e ENCRYPTION_KEY= POLL_INTERVAL=5
cd "$ROOT/backend"

echo "==> backend: register server, create user + device"
"$PY" - "$TOKEN" "$WORK" <<'PY'
import asyncio, sys
from app.db import SessionLocal, init_db
from app.security.telegram import TelegramUser
from app.services.servers import create_server
from app.services.users import get_or_create_user
from app.services.devices import create_device, render_config

token, work = sys.argv[1:]
async def main():
    await init_db()
    async with SessionLocal() as s:
        server = await create_server(s, code="e2e-1", name="E2E", country="DE", city=None, host="192.168.77.1",
                                     driver="agent", agent_url="http://127.0.0.1:18787", agent_token=token)
        user = await get_or_create_user(s, TelegramUser(id=777, username="e2e"))
        device = await create_device(s, user, server_id=server.id, name="client", platform="linux")
        text, _ = render_config(device)
        # no resolvconf in the namespace: the DNS line does not matter for the tunnel test
        open(f"{work}/nova.conf", "w").write("\n".join(l for l in text.splitlines() if not l.startswith("DNS")) + "\n")
        print(f"    server key fetched from node, device {device.address} created, peer pushed")
asyncio.run(main())
PY

echo "==> client: import config and connect"
docker exec $NODE sh -c "mkdir -p /etc/wireguard && cp /work/nova.conf /etc/wireguard/nova.conf && chmod 600 /etc/wireguard/nova.conf"
docker exec $NODE $CLIENT_NS wg-quick up nova >/dev/null 2>&1
docker exec $NODE $CLIENT_NS ping -c 3 -W 2 10.8.0.1 | sed -n 's/^/    /;/packets/p'
docker exec $NODE $CLIENT_NS ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1 \
  && echo "    internet through tunnel: OK (NAT works)" \
  || echo "    internet through tunnel: not available in this sandbox (tunnel itself works)"

echo "==> backend: poller sees the session"
"$PY" - <<'PY'
import asyncio
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Device, User
from app.services.devices import is_online, revoke_device
from app.tasks import poll_once

async def main():
    await poll_once()
    async with SessionLocal() as s:
        d = await s.scalar(select(Device))
        u = await s.get(User, d.user_id)
        print(f"    online={is_online(d)} download={d.download_bytes}B upload={d.upload_bytes}B user_traffic={u.traffic_used}B")
        assert is_online(d) and u.traffic_used > 0, "poller did not register the session"
        await revoke_device(s, d)
        print("    device revoked")
asyncio.run(main())
PY

if docker exec $NODE $CLIENT_NS ping -c 2 -W 2 10.8.0.1 >/dev/null 2>&1; then
  echo "FAIL: tunnel still works after revoke"; exit 1
fi
echo "    tunnel is closed after revoke"
echo "E2E PASSED"
