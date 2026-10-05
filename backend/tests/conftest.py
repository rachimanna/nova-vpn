import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{_tmp}/test.db",
    BOT_TOKEN="123456:TEST-TOKEN",
    SECRET_KEY="test-secret",
    ENCRYPTION_KEY="",
    DEV_MODE="true",
    ADMIN_PASSWORD="admin-pass",
    ADMIN_TELEGRAM_IDS="42",
    POLL_INTERVAL="3600",
    FRONTEND_DIST="/nonexistent",
    RATE_LIMIT_PER_MINUTE="10000",
    WEBAPP_URL="",  # tests must not depend on a developer .env
    SUPPORT_URL="",
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.cli import seed_demo  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session")
async def client():
    async with app.router.lifespan_context(app):
        await seed_demo()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.security.ratelimit import limiter

    limiter._hits.clear()
