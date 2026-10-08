#!/usr/bin/env bash
# NOVA VPN node installer. Ubuntu 22.04/24.04 or Debian 12, run as root.
#
#   VLESS (Happ, v2RayTun, Hiddify…) — recommended:
#     sudo DOMAIN=vpn.example.com bash install.sh vless
#       Xray (VLESS over WebSocket) + Caddy with a free Let's Encrypt certificate on 443.
#       PANEL=1 (default): this is also the main server, Caddy serves the Mini App/API from 127.0.0.1:8000.
#       PANEL=0: extra node only; the backend reaches the agent at https://DOMAIN/nova-agent
#
#   WireGuard:
#     sudo bash install.sh wireguard
#       AGENT_BIND=127.0.0.1 (default) — backend on the same server.
set -euo pipefail

MODE=${1:-vless}
AGENT_PORT=${AGENT_PORT:-8787}
AGENT_BIND=${AGENT_BIND:-127.0.0.1}
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh $MODE"; exit 1; }
[[ $MODE == vless || $MODE == wireguard ]] || { echo "Usage: install.sh vless|wireguard"; exit 1; }

apt_install() { DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" >/dev/null; }

echo "==> Installing base packages"
apt-get update -qq
apt_install python3-venv python3-pip curl ca-certificates gnupg

echo "==> Tuning the network stack for low latency (BBR, fq, TCP Fast Open)"
cat > /etc/sysctl.d/98-nova-latency.conf <<'SYSCTL'
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_slow_start_after_idle=0
net.ipv4.tcp_notsent_lowat=16384
net.ipv4.tcp_mtu_probing=1
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.ipv4.udp_rmem_min=16384
net.ipv4.udp_wmem_min=16384
SYSCTL
modprobe tcp_bbr 2>/dev/null || true
sysctl -q --system || true

PUBLIC_IP=$(curl -4 -s --max-time 5 https://api.ipify.org || echo "<PUBLIC_IP>")

# ---------------------------------------------------------------- WireGuard
install_wireguard() {
  WG_IF=${WG_IF:-wg0}
  WG_PORT=${WG_PORT:-51820}
  WG_SUBNET=${WG_SUBNET:-10.8.0.0/24}
  apt_install wireguard wireguard-tools iptables
  echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-nova-vpn.conf
  sysctl -q --system
  local wan server_ip
  wan=$(ip -4 route show default | awk '{print $5; exit}')
  server_ip=$(echo "$WG_SUBNET" | awk -F'[./]' '{printf "%s.%s.%s.%d/%s", $1,$2,$3,$4+1,$5}')
  if [[ ! -f /etc/wireguard/$WG_IF.conf ]]; then
    echo "==> Creating /etc/wireguard/$WG_IF.conf (WAN: $wan)"
    umask 077
    cat > /etc/wireguard/$WG_IF.conf <<CONF
[Interface]
Address = $server_ip
ListenPort = $WG_PORT
PrivateKey = $(wg genkey)
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -s $WG_SUBNET -o $wan -j MASQUERADE; iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -D POSTROUTING -s $WG_SUBNET -o $wan -j MASQUERADE; iptables -t mangle -D FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
CONF
  fi
  systemctl enable --now "wg-quick@$WG_IF" >/dev/null
  if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow "$WG_PORT/udp" >/dev/null; fi
  AGENT_ENV="NODE_PROTOCOL=wireguard
WG_INTERFACE=$WG_IF
WG_SUBNET=$WG_SUBNET"
  AFTER_UNIT="wg-quick@$WG_IF.service"
  HOST_HINT=$PUBLIC_IP
  AGENT_URL="http://127.0.0.1:$AGENT_PORT"
}

# ---------------------------------------------------------------- VLESS
install_vless() {
  [[ -n ${DOMAIN:-} ]] || { echo "Set DOMAIN: its A record must point to $PUBLIC_IP"; exit 1; }
  PANEL=${PANEL:-1}
  local ws_path
  ws_path=$(grep -s '^WS_PATH=' /etc/nova-agent.env | cut -d= -f2 || true)
  ws_path=${ws_path:-/nv-$(head -c 9 /dev/urandom | od -An -tx1 | tr -d ' \n')}

  echo "==> Installing Xray (official XTLS installer)"
  bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install >/dev/null
  sed "s|__WS_PATH__|$ws_path|" "$SRC_DIR/xray-config.json" > /usr/local/etc/xray/config.json
  systemctl enable xray >/dev/null
  systemctl restart xray

  echo "==> Installing Caddy (free TLS certificate for $DOMAIN)"
  if ! command -v caddy >/dev/null; then
    apt_install debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt_install caddy
  fi
  local fallback='respond "OK" 200'
  [[ $PANEL == 1 ]] && fallback='reverse_proxy 127.0.0.1:8000'
  cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
	encode zstd gzip
	header -Server

	# VLESS over WebSocket -> Xray
	@vless path $ws_path
	reverse_proxy @vless 127.0.0.1:10000

	# node agent for a backend on another server (token protected)
	handle_path /nova-agent/* {
		reverse_proxy 127.0.0.1:$AGENT_PORT
	}

	# Mini App + API (PANEL=1) or a neutral page
	handle {
		$fallback
	}
}
CADDY
  systemctl enable caddy >/dev/null
  systemctl reload caddy || systemctl restart caddy
  if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; fi

  AGENT_ENV="NODE_PROTOCOL=vless
NODE_DOMAIN=$DOMAIN
WS_PATH=$ws_path
XRAY_BIN=/usr/local/bin/xray"
  AFTER_UNIT="xray.service"
  HOST_HINT=$DOMAIN
  if [[ $PANEL == 1 ]]; then AGENT_URL="http://127.0.0.1:$AGENT_PORT"; else AGENT_URL="https://$DOMAIN/nova-agent"; fi
}

install_$MODE

echo "==> Installing nova-agent"
mkdir -p /opt/nova-agent /var/lib/nova-agent
chmod 700 /var/lib/nova-agent
cp "$SRC_DIR/agent.py" "$SRC_DIR/requirements.txt" /opt/nova-agent/
python3 -m venv /opt/nova-agent/.venv
/opt/nova-agent/.venv/bin/pip install -q -r /opt/nova-agent/requirements.txt

TOKEN=$(grep -s '^AGENT_TOKEN=' /etc/nova-agent.env | cut -d= -f2 || true)
TOKEN=${TOKEN:-$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)}
umask 077
cat > /etc/nova-agent.env <<ENV
AGENT_TOKEN=$TOKEN
AGENT_BIND=$AGENT_BIND
AGENT_PORT=$AGENT_PORT
STATE_FILE=/var/lib/nova-agent/peers.json
$AGENT_ENV
ENV
sed "s|__AFTER__|$AFTER_UNIT|g" "$SRC_DIR/nova-agent.service" > /etc/systemd/system/nova-agent.service
systemctl daemon-reload
systemctl enable nova-agent >/dev/null
systemctl restart nova-agent
sleep 2
systemctl is-active --quiet nova-agent || { echo "!! nova-agent failed: journalctl -u nova-agent -n 50"; exit 1; }

cat <<DONE

============================================================
 Node is ready ($MODE).
 Clients connect to: $HOST_HINT
 Register it in the backend (from the backend/ directory or via the admin panel):

   python -m app.cli add-server --code nl-ams-1 --name Netherlands --country NL \\
     --city Amsterdam --host $HOST_HINT \\
     --agent-url $AGENT_URL --agent-token $TOKEN

 The token is stored in /etc/nova-agent.env. Keep it secret.
============================================================
DONE
