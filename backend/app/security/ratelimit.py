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
        self._seen: dict[str, float] = {}

    def allow(self, key: str, limit: int, window: float = 60.0, *, max_keys: int = 50_000) -> bool:
        now = time.monotonic()
        # A rejected caller does not append a hit, but must stay "recent" or eviction frees them.
        self._seen[key] = now
        self._evict(now, window, max_keys)
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def _evict(self, now: float, window: float, max_keys: int) -> None:
        """Drop idle keys. Never wipe the table: that would also forget whoever is over the limit."""
        if len(self._hits) <= max_keys:
            return
        stale = [k for k, q in self._hits.items() if not q or now - q[-1] > window]
        for key in stale:
            del self._hits[key]
            self._seen.pop(key, None)
        overflow = len(self._hits) - max_keys
        if overflow <= 0:
            return
        # Oldest attempts first. allow() marks the caller seen before evicting, so a key that is
        # over its limit stays in the newest group and is not freed.
        ranked = sorted(self._hits, key=lambda k: self._seen.get(k, 0.0))
        for key in ranked[:overflow]:
            del self._hits[key]
            self._seen.pop(key, None)


limiter = SlidingWindow()

# Stricter buckets for sensitive endpoints: (exact path, method, limit per minute).
# Exact, so POST /api/devices/{id}/regenerate is not counted as creating a device.
STRICT = [
    ("/api/admin/login", "POST", 5),
    ("/api/devices", "POST", 10),
]


def strict_limit(path: str, method: str) -> tuple[str, int] | None:
    for prefix, verb, limit in STRICT:
        if method == verb and (path == prefix or path == prefix + "/"):
            return prefix, limit
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int) -> None:
        super().__init__(app)
        self.per_minute = per_minute

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"

        if hit := strict_limit(path, request.method):
            prefix, limit = hit
            if not limiter.allow(f"{ip}:{prefix}", limit):
                return _too_many()

        if not limiter.allow(ip, self.per_minute):
            return _too_many()
        return await call_next(request)


def _too_many() -> JSONResponse:
    return JSONResponse({"detail": "Слишком много запросов, попробуйте через минуту"}, status_code=429)
