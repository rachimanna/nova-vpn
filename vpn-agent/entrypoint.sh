#!/bin/sh
set -eu
umask 077
mkdir -p /data
[ -f /data/server.key ] || wg genkey > /data/server.key

SERVER_IP=$(echo "$WG_SUBNET" | awk -F'[./]' '{printf "%s.%s.%s.%d/%s", $1,$2,$3,$4+1,$5}')
ip link del "$WG_INTERFACE" 2>/dev/null || true
ip link add "$WG_INTERFACE" type wireguard
wg set "$WG_INTERFACE" listen-port "$WG_PORT" private-key /data/server.key
ip addr add "$SERVER_IP" dev "$WG_INTERFACE"
ip link set "$WG_INTERFACE" up

WAN_IF=$(ip -4 route show default | awk '{print $5; exit}')
if [ -n "$WAN_IF" ]; then
  iptables -t nat -C POSTROUTING -s "$WG_SUBNET" -o "$WAN_IF" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s "$WG_SUBNET" -o "$WAN_IF" -j MASQUERADE
  iptables -C FORWARD -i "$WG_INTERFACE" -j ACCEPT 2>/dev/null || iptables -A FORWARD -i "$WG_INTERFACE" -j ACCEPT
  iptables -C FORWARD -o "$WG_INTERFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -o "$WG_INTERFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
  # no fragmented TCP through the tunnel: clamp MSS to the path MTU
  iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null \
    || iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
fi
echo "WireGuard $WG_INTERFACE up: $SERVER_IP, port $WG_PORT, public key $(wg show "$WG_INTERFACE" public-key)"
exec uvicorn agent:app --host "$AGENT_BIND" --port "$AGENT_PORT" --no-access-log
