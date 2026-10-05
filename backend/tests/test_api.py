import json
import time

from app.security.crypto import sign_token
from app.security.telegram import sign_init_data
from app.tasks import poll_once

DEV = {"X-Dev-User": "1001"}


def tma(user_id: int) -> dict:
    init = sign_init_data(
        {"user": json.dumps({"id": user_id, "first_name": "T", "username": f"u{user_id}"}),
         "auth_date": str(int(time.time()))},
        "123456:TEST-TOKEN",
    )
    return {"Authorization": f"tma {init}"}


async def test_auth_required(client):
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me", headers={"Authorization": "tma user=1&hash=00"})).status_code == 401
    r = await client.get("/api/me", headers=tma(555))
    assert r.status_code == 200 and r.json()["user"]["username"] == "u555"


async def test_device_lifecycle(client):
    me = (await client.get("/api/me", headers=DEV)).json()
    assert me["vpn"]["state"] == "none" and me["user"]["device_limit"] == 3

    servers = (await client.get("/api/servers", headers=DEV)).json()
    assert len(servers) == 5 and servers[0]["flag"] == "🇩🇪"

    r = await client.post("/api/devices", headers=DEV, json={"server_id": servers[0]["id"], "name": "iPhone", "platform": "ios"})
    assert r.status_code == 201, r.text
    device = r.json()
    assert device["address"] == "10.8.0.2/32"
    assert "private" not in json.dumps(device).lower()

    cfg = (await client.get(f"/api/devices/{device['id']}/config", headers=DEV)).json()
    assert "[Interface]" in cfg["config"] and "PresharedKey" in cfg["config"]
    assert cfg["filename"].endswith(".conf")

    file = await client.get(cfg["download_path"])
    assert file.status_code == 200 and file.text == cfg["config"]

    # someone else cannot read it
    assert (await client.get(f"/api/devices/{device['id']}/config", headers={"X-Dev-User": "2002"})).status_code == 404

    regen = (await client.post(f"/api/devices/{device['id']}/regenerate", headers=DEV, json={})).json()
    assert regen["address"] == device["address"]
    new_cfg = (await client.get(f"/api/devices/{device['id']}/config", headers=DEV)).json()
    assert new_cfg["config"] != cfg["config"]
    assert (await client.get(cfg["download_path"])).status_code == 404  # old link dies with old keys

    moved = (await client.post(f"/api/devices/{device['id']}/regenerate", headers=DEV, json={"server_id": servers[1]["id"]})).json()
    assert moved["server"]["code"] == "nl-ams-1" and moved["address"] == "10.8.1.2/32"

    assert (await client.delete(f"/api/devices/{device['id']}", headers=DEV)).status_code == 200
    assert (await client.get(f"/api/devices/{device['id']}/config", headers=DEV)).status_code == 409


async def test_device_limit_and_poller(client):
    h = {"X-Dev-User": "3003"}
    for i in range(3):
        assert (await client.post("/api/devices", headers=h, json={"server_id": 3, "name": f"d{i}"})).status_code == 201
    r = await client.post("/api/devices", headers=h, json={"server_id": 3, "name": "d4"})
    assert r.status_code == 409 and "лимит" in r.json()["detail"].lower()

    for _ in range(3):
        await poll_once()
    me = (await client.get("/api/me", headers=h)).json()
    assert me["user"]["traffic_used"] > 0
    stats = (await client.get("/api/stats?range=24h", headers=h)).json()
    assert len(stats["series"]) == 24 and sum(b["download"] for b in stats["series"]) > 0


async def test_admin(client):
    assert (await client.get("/api/admin/overview")).status_code == 401
    assert (await client.post("/api/admin/login", json={"password": "wrong"})).status_code == 401
    token = (await client.post("/api/admin/login", json={"password": "admin-pass"})).json()["token"]
    A = {"Authorization": f"Bearer {token}"}

    ov = (await client.get("/api/admin/overview", headers=A)).json()
    assert ov["stats"]["total_users"] >= 2 and len(ov["servers"]) == 5

    users = (await client.get("/api/admin/users?q=u555", headers=A)).json()
    assert users["total"] == 1
    uid = users["items"][0]["id"]

    banned = (await client.post(f"/api/admin/users/{uid}/ban", headers=A)).json()
    assert banned["user"]["status"] == "banned"
    r = await client.post("/api/devices", headers=tma(555), json={"server_id": 1})
    assert r.status_code == 403
    await client.post(f"/api/admin/users/{uid}/unban", headers=A)

    patched = (await client.patch(f"/api/admin/users/{uid}", headers=A,
                                  json={"device_limit": 1, "traffic_limit_gb": 0, "extend_days": 30})).json()
    assert patched["user"]["device_limit"] == 1 and patched["user"]["traffic_limit"] == 0

    created = (await client.post(f"/api/admin/users/{uid}/devices", headers=A, json={"server_id": 2})).json()
    dev_id = created["devices"][0]["id"]
    assert (await client.delete(f"/api/admin/devices/{dev_id}", headers=A)).status_code == 200

    # bot-issued one-time link for Telegram admins
    link = sign_token("admin_link", {"tg": 42}, 60)
    assert (await client.post("/api/admin/exchange", json={"token": link})).status_code == 200
    bad = sign_token("admin_link", {"tg": 43}, 60)
    assert (await client.post("/api/admin/exchange", json={"token": bad})).status_code == 403
