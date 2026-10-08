"""VLESS (Xray) primitives: credentials and share links understood by Happ, v2RayTun, Hiddify, v2rayNG…"""

import json
import secrets
import uuid
from urllib.parse import quote, urlencode


def new_label() -> str:
    """Non-secret per-device id, used as the Xray user "email" and in stats."""
    return f"n{secrets.token_hex(8)}"


def new_uuid() -> str:
    return str(uuid.uuid4())


def parse_params(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def render_link(*, user_id: str, host: str, port: int, params: dict, name: str) -> str:
    security = params.get("security", "tls")
    query = {"encryption": "none", "type": params.get("transport", "ws"), "security": security}
    if query["type"] == "ws":
        path = params.get("path", "/")
        # WebSocket early data: the first request rides in the handshake, saving one round trip
        # per new connection. Xray accepts it on the server side without extra config.
        query["path"] = path if "ed=" in path else f"{path}?ed=2048"
        query["host"] = params.get("sni") or host
    if security == "tls":
        query["sni"] = params.get("sni") or host
        query["fp"] = params.get("fp", "chrome")
        query["alpn"] = "http/1.1"  # WebSocket needs HTTP/1.1 through the TLS proxy
    address = f"[{host}]" if ":" in host else host
    return f"vless://{user_id}@{address}:{port}?{urlencode(query, quote_via=quote)}#{quote(name)}"
