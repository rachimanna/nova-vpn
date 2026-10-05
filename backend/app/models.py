from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, TypeDecorator, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class TZDateTime(TypeDecorator):
    """SQLite drops tzinfo; always store UTC and hand back aware datetimes."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str | None] = mapped_column(String(8))
    photo_url: Mapped[str | None] = mapped_column(String(512))

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    device_limit: Mapped[int] = mapped_column(Integer)
    traffic_limit: Mapped[int] = mapped_column(BigInteger)  # bytes, 0 = unlimited
    traffic_used: Mapped[int] = mapped_column(BigInteger, default=0)
    notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    expiry_notified_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    devices: Mapped[list["Device"]] = relationship(back_populates="user", order_by="Device.id")


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # e.g. "de-fra-1"
    name: Mapped[str] = mapped_column(String(64))  # "Germany"
    country: Mapped[str] = mapped_column(String(2))  # ISO-3166 alpha-2, flag derived from it
    city: Mapped[str | None] = mapped_column(String(64))

    protocol: Mapped[str] = mapped_column(String(16), default="wireguard")  # wireguard | vless
    driver: Mapped[str] = mapped_column(String(16), default="agent")  # agent | mock
    # Non-secret client parameters reported by the node, JSON (vless: transport, path, sni, security)
    params: Mapped[str] = mapped_column(Text, default="{}")
    agent_url: Mapped[str | None] = mapped_column(String(255))
    agent_token_enc: Mapped[str | None] = mapped_column(Text)

    host: Mapped[str] = mapped_column(String(255))  # public endpoint for clients
    port: Mapped[int] = mapped_column(Integer, default=51820)
    public_key: Mapped[str] = mapped_column(String(64), default="")  # WireGuard only
    subnet: Mapped[str] = mapped_column(String(43), default="10.8.0.0/24")  # WireGuard only
    dns: Mapped[str] = mapped_column(String(128), default="1.1.1.1, 1.0.0.1")
    max_peers: Mapped[int] = mapped_column(Integer, default=250)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    ping_ms: Mapped[int | None] = mapped_column(Integer)
    peers_online: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class Device(Base):
    """One device == one client config == one peer on a server."""

    __tablename__ = "devices"
    __table_args__ = (
        # one IP per server among live configs; revoked rows keep history
        Index(
            "uq_devices_active_address",
            "server_id",
            "address",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(48))
    platform: Mapped[str] = mapped_column(String(16), default="other")  # ios|android|windows|macos|linux|other
    protocol: Mapped[str] = mapped_column(String(16), default="wireguard")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active | revoked

    # WireGuard: public key / private key / psk / tunnel IP.
    # VLESS: user label (Xray "email") / uuid / uuid / label (keeps the per-server unique index happy).
    public_key: Mapped[str] = mapped_column(String(64), unique=True)
    private_key_enc: Mapped[str] = mapped_column(Text)
    psk_enc: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(String(43))
    # Secret part of the subscription URL (Happ, v2RayTun, …); rotates with the credentials
    sub_token: Mapped[str | None] = mapped_column(String(48), unique=True)

    # Client perspective, accumulated across node counter resets
    download_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    upload_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    # Last raw WireGuard counters seen on the node (server perspective)
    raw_rx: Mapped[int] = mapped_column(BigInteger, default=0)
    raw_tx: Mapped[int] = mapped_column(BigInteger, default=0)
    last_handshake_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    session_started_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    user: Mapped[User] = relationship(back_populates="devices")
    server: Mapped[Server] = relationship(lazy="joined")


class TrafficSample(Base):
    """Per-device traffic delta over one poll interval, client perspective."""

    __tablename__ = "traffic_samples"
    __table_args__ = (Index("ix_samples_user_ts", "user_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    download: Mapped[int] = mapped_column(BigInteger, default=0)
    upload: Mapped[int] = mapped_column(BigInteger, default=0)
