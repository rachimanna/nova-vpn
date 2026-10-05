"""Endpoints used by the Telegram Mini App."""

import base64
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import current_user
from app.config import get_settings
from app.db import get_session
from app.models import Device, Server, User
from app.security.crypto import TokenError, sign_token, verify_token
from app.services import devices as device_service
from app.services import stats as stats_service
from app.services.servers import list_servers, server_view
from app.services.users import ACCESS_ERRORS, Access, access_state
from app.vpn.protocols import get_protocol
from app.views import device_view, user_view, vpn_view

router = APIRouter(prefix="/api", tags=["mini-app"])

NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


class DeviceCreate(BaseModel):
    server_id: int
    name: str = Field(default="", max_length=48)
    platform: str = Field(default="other", max_length=16)


class DeviceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=48)


class Regenerate(BaseModel):
    server_id: int | None = None


class Settings(BaseModel):
    notifications: bool


def _fail(e: device_service.DeviceError) -> HTTPException:
    return HTTPException(e.status, e.message)


def _own_device(user: User, device_id: int) -> Device:
    device = next((d for d in user.devices if d.id == device_id), None)
    if device is None:
        raise HTTPException(404, "Устройство не найдено")
    return device


async def _has_mock(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(Server.id).where(Server.driver == "mock").limit(1)))


@router.get("/me")
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    now = datetime.now(UTC)
    settings = get_settings()
    return {
        "user": user_view(user, now),
        "vpn": vpn_view(user, now)
        | {"speed": await stats_service.last_rate(session, user.id, settings.poll_interval)},
        "devices": [device_view(d, now) for d in user.devices if d.status == "active"],
        "demo": settings.dev_mode or await _has_mock(session),
    }


@router.patch("/me")
async def update_me(body: Settings, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    user.notifications = body.notifications
    await session.commit()
    return {"ok": True}


@router.get("/servers")
async def servers(_: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [server_view(s, n) for s, n in await list_servers(session)]


@router.get("/stats")
async def stats(
    range: Literal["24h", "7d"] = "24h",
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    hours, buckets = (24, 24) if range == "24h" else (168, 28)
    return {"range": range, "series": await stats_service.traffic_series(session, user.id, hours, buckets)}


@router.post("/devices", status_code=201)
async def create_device(
    body: DeviceCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    try:
        device = await device_service.create_device(
            session, user, server_id=body.server_id, name=body.name, platform=body.platform
        )
    except device_service.DeviceError as e:
        raise _fail(e) from e
    return device_view(device)


@router.patch("/devices/{device_id}")
async def rename_device(
    device_id: int, body: DeviceUpdate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    device = _own_device(user, device_id)
    device.name = body.name.strip()
    await session.commit()
    return device_view(device)


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await device_service.revoke_device(session, _own_device(user, device_id))
    return {"ok": True}


@router.post("/devices/{device_id}/regenerate")
async def regenerate(
    device_id: int, body: Regenerate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    try:
        device = await device_service.regenerate_device(session, _own_device(user, device_id), body.server_id)
    except device_service.DeviceError as e:
        raise _fail(e) from e
    return device_view(device)


@router.get("/devices/{device_id}/config")
async def device_config(device_id: int, user: User = Depends(current_user)):
    device = _own_device(user, device_id)
    try:
        text, filename = device_service.render_config(device)
    except device_service.DeviceError as e:
        raise _fail(e) from e
    # Short-lived link for Telegram.WebApp.downloadFile, which cannot send auth headers.
    token = sign_token("dl", {"d": device.id, "u": user.id, "k": device.public_key[:8]}, ttl=300)
    proto = get_protocol(device.protocol)
    return JSONResponse(
        {
            "protocol": device.protocol,
            "config": text,
            "filename": filename,
            "download_path": f"/api/download/{token}",
            "subscription_path": f"/api/sub/{device.sub_token}" if proto.subscription and device.sub_token else None,
        },
        headers=NO_STORE,
    )


def _b64(text: str) -> str:
    return "base64:" + base64.b64encode(text.encode()).decode()


@router.get("/sub/{token}")
async def subscription(token: str, session: AsyncSession = Depends(get_session)):
    """Subscription for Happ, v2RayTun, Hiddify, v2rayNG… The secret is the token itself.

    Body: base64 list of share links. Headers: name, traffic and expiry shown inside the app.
    """
    if not 16 <= len(token) <= 48:
        raise HTTPException(404, "Not Found")
    device = await session.scalar(
        select(Device)
        .where(Device.sub_token == token, Device.status == "active")
        .options(selectinload(Device.user).selectinload(User.devices))
    )
    if device is None or not get_protocol(device.protocol).subscription:
        raise HTTPException(404, "Not Found")
    user = device.user
    state = access_state(user)
    links = [] if state is not Access.ACTIVE else [device_service.render_config(device)[0]]
    used_up = sum(d.upload_bytes for d in user.devices)
    used_down = sum(d.download_bytes for d in user.devices)
    headers = {
        **NO_STORE,
        "profile-title": _b64("NOVA VPN"),
        "profile-update-interval": "1",
        "subscription-userinfo": (
            f"upload={used_up}; download={used_down}; total={user.traffic_limit}; "
            f"expire={int(user.expires_at.timestamp())}"
        ),
    }
    if state is not Access.ACTIVE:
        headers["announce"] = _b64(ACCESS_ERRORS[state] + ". Откройте NOVA VPN в Telegram.")
    if url := get_settings().support_url:
        headers["support-url"] = url
    body = base64.b64encode("\n".join(links).encode()).decode()
    return Response(body, media_type="text/plain; charset=utf-8", headers=headers)


@router.get("/download/{token}")
async def download(token: str, session: AsyncSession = Depends(get_session)):
    try:
        data = verify_token(token, "dl")
    except TokenError as e:
        raise HTTPException(404, "Ссылка устарела") from e
    device = await session.get(Device, data["d"])
    # the key prefix binds the link to the current keys, so regenerate invalidates old links
    if device is None or device.user_id != data["u"] or not device.public_key.startswith(data["k"]):
        raise HTTPException(404, "Ссылка устарела")
    try:
        text, filename = device_service.render_config(device)
    except device_service.DeviceError as e:
        raise _fail(e) from e
    return Response(
        text,
        media_type="application/octet-stream",
        headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{filename}"'},
    )
