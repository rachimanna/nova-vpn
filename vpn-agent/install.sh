#!/usr/bin/env bash
# NOVA VPN node installer: WireGuard + NAT + nova-agent.
# Tested target: Ubuntu 22.04/24.04, Debian 12. Run as root:
#   sudo bash install.sh                       # agent on 127.0.0.1 (backend on the same server)
#   sudo AGENT_BIND=0.0.0.0 bash install.sh    # remote backend; put TLS (Caddy) in front!
set -euo pipefail

WG_IF=${WG_IF:-wg0}
WG_PORT=${WG_PORT:-51820}
WG_SUBNET=${WG_SUBNET:-10.8.0.0/24}
AGENT_BIND=${AGENT_BIND:-127.0.0.1}
AGENT_PORT=${AGENT_PORT:-8787}
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh"; exit 1; }

echo "==> Installing packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard wireguard-tools iptables python3-venv python3-pip curl >/dev/null

echo "==> Enabling IP forwarding"
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-nova-vpn.conf
sysctl -q --system

WAN_IF=$(ip -4 route show default | awk '{print $5; exit}')
SERVER_IP=$(echo "$WG_SUBNET" | awk -F'[./]' '{printf "%s.%s.%s.%d/%s", $1,$2,$3,$4+1,$5}')

if [[ ! -f /etc/wireguard/$WG_IF.conf ]]; then
  echo "==> Creating /etc/wireguard/$WG_IF.conf (WAN interface: $WAN_IF)"
  umask 077
  PRIV=$(wg genkey)
  cat > /etc/wireguard/$WG_IF.conf <<CONF
[Interface]
Address = $SERVER_IP
ListenPort = $WG_PORT
PrivateKey = $PRIV
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -s $WG_SUBNET -o $WAN_IF -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -D POSTROUTING -s $WG_SUBNET -o $WAN_IF -j MASQUERADE
CONF
else
  echo "==> /etc/wireguard/$WG_IF.conf exists, keeping it"
fi
systemctl enable --now "wg-quick@$WG_IF" >/dev/null

if command -v ufw >/dev/null && ufw status | grep -q active; then
  ufw allow "$WG_PORT/udp" >/dev/null
  echo "==> ufw: opened $WG_PORT/udp"
fi

echo "==> Installing nova-agent"
mkdir -p /opt/nova-agent /var/lib/nova-agent
chmod 700 /var/lib/nova-agent
cp "$SRC_DIR/agent.py" "$SRC_DIR/requirements.txt" /opt/nova-agent/
python3 -m venv /opt/nova-agent/.venv
/opt/nova-agent/.venv/bin/pip install -q -r /opt/nova-agent/requirements.txt

if [[ ! -f /etc/nova-agent.env ]]; then
  TOKEN=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)
  umask 077
  cat > /etc/nova-agent.env <<ENV
AGENT_TOKEN=$TOKEN
WG_INTERFACE=$WG_IF
WG_SUBNET=$WG_SUBNET
AGENT_BIND=$AGENT_BIND
AGENT_PORT=$AGENT_PORT
STATE_FILE=/var/lib/nova-agent/peers.json
ENV
fi
cp "$SRC_DIR/nova-agent.service" /etc/systemd/system/nova-agent.service
systemctl daemon-reload
systemctl enable --now nova-agent >/dev/null
systemctl restart nova-agent

PUBLIC_IP=$(curl -4 -s --max-time 5 https://api.ipify.org || echo "<PUBLIC_IP>")
TOKEN=$(grep AGENT_TOKEN /etc/nova-agent.env | cut -d= -f2)
sleep 2
systemctl is-active --quiet nova-agent && echo "==> nova-agent is running" || { echo "!! nova-agent failed: journalctl -u nova-agent"; exit 1; }

cat <<DONE

============================================================
 Node is ready.
 WireGuard: $PUBLIC_IP:$WG_PORT/udp   subnet $WG_SUBNET
 Agent:     http://$AGENT_BIND:$AGENT_PORT

 Register it in the backend (from the backend/ directory):

   python -m app.cli add-server --code de-fra-1 --name Germany --country DE \\
     --city Frankfurt --host $PUBLIC_IP --subnet $WG_SUBNET \\
     --agent-url http://127.0.0.1:$AGENT_PORT --agent-token $TOKEN

 Keep the token secret. It is stored in /etc/nova-agent.env
============================================================
DONE
