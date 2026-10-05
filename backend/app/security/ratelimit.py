"""Small in-memory sliding-window rate limiter.

Good enough for a single backend process. With several replicas move it to Redis.
"""

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if len(self._hits) > 50_000:  # crude memory guard
            self._hits.clear()
        return True


limiter = SlidingWindow()

# Stricter buckets for sensitive endpoints: (path prefix, method, limit per minute)
STRICT = [
    ("/api/admin/login", "POST", 5),
    ("/api/devices", "POST", 10),
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int) -> None:
        super().__init__(app)
        self.per_minute = per_minute

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"

        for prefix, method, limit in STRICT:
            if request.method == method and path.startswith(prefix):
                if not limiter.allow(f"{ip}:{prefix}", limit):
                    return _too_many()

        if not limiter.allow(ip, self.per_minute):
            return _too_many()
        return await call_next(request)


def _too_many() -> JSONResponse:
    return JSONResponse({"detail": "Слишком много запросов, попробуйте через минуту"}, status_code=429)
