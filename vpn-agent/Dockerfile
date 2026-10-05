# Alternative to install.sh: WireGuard node + agent in one container.
# Needs: --cap-add NET_ADMIN, --network host (production), host kernel with WireGuard (Linux 5.6+).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends wireguard-tools iproute2 iptables procps \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/nova-agent
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py entrypoint.sh ./
ENV WG_INTERFACE=wg0 WG_PORT=51820 WG_SUBNET=10.8.0.0/24 AGENT_BIND=127.0.0.1 AGENT_PORT=8787 \
    STATE_FILE=/data/peers.json
VOLUME /data
ENTRYPOINT ["sh", "/opt/nova-agent/entrypoint.sh"]
