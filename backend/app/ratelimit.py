"""Minimal in-memory sliding-window rate limiter, keyed by client IP.

Suitable for a single backend process. Run behind a reverse proxy with TRUST_PROXY=true
so the real client IP is taken from X-Forwarded-For.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import settings

WINDOW_SECONDS = 60


class RateLimiter:
    def __init__(self, limit: int, window: int = WINDOW_SECONDS):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = int(self.window - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please wait a moment and try again.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)
            # Drop idle keys so the table does not grow without bound.
            if len(self._hits) > 10_000:
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    del self._hits[k]


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


info_limiter = RateLimiter(settings.rate_limit_info)
download_limiter = RateLimiter(settings.rate_limit_download)
