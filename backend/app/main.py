import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import admin, user
from app.config import get_settings
from app.db import init_db
from app.security.crypto import decrypt, encrypt
from app.security.ratelimit import RateLimitMiddleware
from app.tasks import poller_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nova")
settings = get_settings()


def _check_config() -> None:
    if settings.dev_mode:
        log.warning("DEV_MODE is ON: X-Dev-User auth is accepted. Never enable it in production.")
        return
    missing = [k for k in ("bot_token", "secret_key", "encryption_key") if not getattr(settings, k)]
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(m.upper() for m in missing)}")
    decrypt(encrypt("self-test"))  # fails fast on a malformed ENCRYPTION_KEY


@asynccontextmanager
async def lifespan(_: FastAPI):
    _check_config()
    await init_db()
    poller = asyncio.create_task(poller_loop())
    yield
    poller.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller


app = FastAPI(
    title="NOVA VPN API",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.dev_mode else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.dev_mode else None,
)
app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_minute)
if settings.cors_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)


app.include_router(user.router)
app.include_router(admin.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


# Serve the built Mini App from the same origin (no CORS, one HTTPS certificate).
dist = (Path(__file__).resolve().parent.parent / settings.frontend_dist).resolve()
if dist.is_dir():

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(file, headers={"Cache-Control": cache})
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
