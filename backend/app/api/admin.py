"""Admin panel API. Every route except login requires a signed admin session token."""

import hmac
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_admin
from app.config import get_settings
from app.db import get_session
from app.models import Device, Server, User
from app.security.crypto import TokenError, encrypt, sign_token, verify_token
from app.services import devices as device_service
from app.services import stats as stats_service
from app.services.servers import create_server, list_servers, server_view
from app.services.users import GB
from app.views import device_view, user_view

log = logging.getLogger("nova.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])
SESSION_TTL = 12 * 3600


class Login(BaseModel):
    password: str = Field(max_length=256)


class Exchange(BaseModel):
    token: str = Field(max_length=1024)


class UserPatch(BaseModel):
    device_limit: int | None = Field(default=None, ge=0, le=50)
    traffic_limit_gb: float | None = Field(default=None, ge=0, le=100_000)  # 0 = unlimited
    extend_days: int | None = Field(default=None, ge=-3650, le=3650)
    reset_traffic: bool = False


class AdminDeviceCreate(BaseModel):
    server_id: int
    name: str = Field(default="Admin config", max_length=48)
    platform: str = "other"


class ServerCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9-]{2,32}$")
    name: str = Field(max_length=64)
    country: str = Field(pattern=r"^[A-Za-z]{2}$")
    city: str | None = Field(default=None, max_length=64)
    host: str = Field(max_length=255)
    driver: Literal["agent", "mock"] = "agent"
    agent_url: str | None = Field(default=None, max_length=255)
    agent_token: str | None = Field(default=None, max_length=256)
    subnet: str = "10.8.0.0/24"
    dns: str = "1.1.1.1, 1.0.0.1"
    max_peers: int = Field(default=250, ge=1, le=65000)


class ServerPatch(BaseModel):
    is_active: bool | None = None
    max_peers: int | None = Field(default=None, ge=1, le=65000)
    name: str | None = Field(default=None, max_length=64)
    host: str | None = Field(default=None, max_length=255)
    agent_token: str | None = Field(default=None, max_length=256)


def _session_token(subject: str) -> dict:
    return {"token": sign_token("admin", {"sub": subject}, SESSION_TTL), "expires_in": SESSION_TTL}


@router.post("/login")
async def login(body: Login, request: Request):
    expected = get_settings().admin_password
    if not expected:
        raise HTTPException(403, "Вход по паролю отключён (ADMIN_PASSWORD не задан)")
    if not hmac.compare_digest(body.password.encode(), expected.encode()):
        log.warning("failed admin login from %s", request.client.host if request.client else "?")
        raise HTTPException(401, "Неверный пароль")
    return _session_token("password")


@router.post("/exchange")
async def exchange(body: Exchange):
    """One-time link sent by the bot (/admin) to Telegram admins -> admin session."""
    try:
        data = verify_token(body.token, "admin_link")
    except TokenError as e:
        raise HTTPException(401, "Ссылка устарела, запросите /admin в боте") from e
    if data.get("tg") not in get_settings().admin_ids:
        raise HTTPException(403, "Нет доступа")
    return _session_token(f"tg:{data['tg']}")


@router.get("/overview", dependencies=[Depends(require_admin)])
async def overview(session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    return {
        "stats": await stats_service.overview(session, settings.online_threshold_seconds),
        "servers": [server_view(s, n) | {"configs": n, "max_peers": s.max_peers, "peers_online": s.peers_online}
                    for s, n in await list_servers(session, include_inactive=True)],
        "traffic": await stats_service.traffic_series(session, None, 24, 24),
    }


@router.get("/users", dependencies=[Depends(require_admin)])
async def users(
    q: str = "",
    status: Literal["all", "active", "banned", "expired"] = "all",
    page: int = 1,
    session: AsyncSession = Depends(get_session),
):
    per_page = 25
    now = datetime.now(UTC)
    query = select(User).options(selectinload(User.devices))
    if q := q.strip().lstrip("@"):
        like = f"%{q.lower()}%"
        query = query.where(
            or_(func.lower(User.username).like(like), func.lower(User.first_name).like(like), cast(User.tg_id, String).like(like))
        )
    if status == "banned":
        query = query.where(User.is_banned.is_(True))
    elif status == "expired":
        query = query.where(User.expires_at <= now)
    elif status == "active":
        query = query.where(User.is_banned.is_(False), User.expires_at > now)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(User.id.desc()).offset((max(page, 1) - 1) * per_page).limit(per_page))
    return {"total": total, "page": page, "per_page": per_page, "items": [user_view(u, now) for u in rows]}


async def _load_user(session: AsyncSession, user_id: int) -> User:
    user = await session.scalar(select(User).where(User.id == user_id).options(selectinload(User.devices)))
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return user


async def _user_detail(session: AsyncSession, user: User) -> dict:
    return {
        "user": user_view(user),
        "devices": [device_view(d) for d in user.devices],
        "traffic": await stats_service.traffic_series(session, user.id, 24 * 7, 28),
    }


@router.get("/users/{user_id}", dependencies=[Depends(require_admin)])
async def user_detail(user_id: int, session: AsyncSession = Depends(get_session)):
    return await _user_detail(session, await _load_user(session, user_id))


@router.post("/users/{user_id}/ban")
async def ban(user_id: int, admin=Depends(require_admin), session: AsyncSession = Depends(get_session)):
    user = await _load_user(session, user_id)
    user.is_banned = True
    await session.commit()
    # Peers are removed right away; the poller would also catch it on the next run
    for device in device_service.active_devices(user):
        await device_service.remove_peer_quietly(device.server, device.public_key)
    log.info("%s banned user %s", admin["sub"], user_id)
    return await _user_detail(session, user)


@router.post("/users/{user_id}/unban")
async def unban(user_id: int, admin=Depends(require_admin), session: AsyncSession = Depends(get_session)):
    user = await _load_user(session, user_id)
    user.is_banned = False
    await session.commit()
    log.info("%s unbanned user %s", admin["sub"], user_id)
    return await _user_detail(session, user)


@router.patch("/users/{user_id}")
async def patch_user(user_id: int, body: UserPatch, admin=Depends(require_admin), session: AsyncSession = Depends(get_session)):
    user = await _load_user(session, user_id)
    if body.device_limit is not None:
        user.device_limit = body.device_limit
    if body.traffic_limit_gb is not None:
        user.traffic_limit = int(body.traffic_limit_gb * GB)
    if body.extend_days:
        base = max(user.expires_at, datetime.now(UTC)) if body.extend_days > 0 else user.expires_at
        user.expires_at = base + timedelta(days=body.extend_days)
    if body.reset_traffic:
        user.traffic_used = 0
    await session.commit()
    log.info("%s updated user %s: %s", admin["sub"], user_id, body.model_dump(exclude_defaults=True))
    return await _user_detail(session, user)


@router.post("/users/{user_id}/devices", status_code=201)
async def admin_create_device(
    user_id: int, body: AdminDeviceCreate, admin=Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    user = await _load_user(session, user_id)
    try:
        await device_service.create_device(
            session, user, server_id=body.server_id, name=body.name, platform=body.platform, enforce_limits=False
        )
    except device_service.DeviceError as e:
        raise HTTPException(e.status, e.message) from e
    log.info("%s created config for user %s", admin["sub"], user_id)
    return await _user_detail(session, user)


@router.delete("/devices/{device_id}")
async def admin_revoke(device_id: int, admin=Depends(require_admin), session: AsyncSession = Depends(get_session)):
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "Устройство не найдено")
    await device_service.revoke_device(session, device)
    log.info("%s revoked device %s", admin["sub"], device_id)
    return {"ok": True}


@router.get("/servers", dependencies=[Depends(require_admin)])
async def servers(session: AsyncSession = Depends(get_session)):
    return [
        server_view(s, n)
        | {"configs": n, "max_peers": s.max_peers, "peers_online": s.peers_online, "host": s.host, "port": s.port,
           "driver": s.driver, "is_active": s.is_active, "last_seen_at": s.last_seen_at}
        for s, n in await list_servers(session, include_inactive=True)
    ]


@router.post("/servers", status_code=201)
async def add_server(body: ServerCreate, admin=Depends(require_admin), session: AsyncSession = Depends(get_session)):
    try:
        server = await create_server(session, **body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    log.info("%s added server %s", admin["sub"], server.code)
    return server_view(server, 0)


@router.patch("/servers/{server_id}")
async def patch_server(server_id: int, body: ServerPatch, admin=Depends(require_admin), session: AsyncSession = Depends(get_session)):
    server = await session.get(Server, server_id)
    if server is None:
        raise HTTPException(404, "Сервер не найден")
    data = body.model_dump(exclude_none=True)
    if token := data.pop("agent_token", None):
        server.agent_token_enc = encrypt(token)
    for key, value in data.items():
        setattr(server, key, value)
    await session.commit()
    log.info("%s updated server %s: %s", admin["sub"], server.code, list(data))
    return {"ok": True}
